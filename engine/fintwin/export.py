"""Build the dashboard's static data: one JSON per company, an index, backtests and parity goldens.

uv run python -m fintwin.export                 # showcase + universe
uv run python -m fintwin.export AAPL MSFT       # specific tickers only (index is merged)
"""

from __future__ import annotations

import json
import math
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .backtest.batch import UNIVERSE_XL
from .backtest.walk_forward import CUTOFFS, UNIVERSE, cross_section, forecast_backtest
from .data.edgar import filing_url
from .data.facts import load_company
from .data.fred import macro_quarterly
from .data.quality import quality_report
from .model.ratings import ICR_LOWER, RATINGS, SPREADS, rating_rank
from .model.sd_model import simulate
from .scenarios.presets import DEFAULT_LEVERS, KNOBS, PRESETS, build_scenario
from .scenarios.reverse_stress import reverse_stress
from .sensitivity.sobol import sobol
from .sensitivity.tornado import tornado
from .stochastic.calibrate import calibrate
from .stochastic.mc import run, summarize
from .stochastic.shocks import draw_shocks
from .universe import classify

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "web" / "public" / "data"
GOLDEN = ROOT / "web" / "src" / "engine" / "__golden__"
SHOWCASE = ["AAPL", "TSLA", "CCL", "BA", "INTC", "NFLX"]
SOBOL_SET = set(SHOWCASE) | set(UNIVERSE)  # the original 30-name universe gets global sensitivity
HORIZON = 12

SECTORS = {
    "AAPL": "Technology",
    "MSFT": "Technology",
    "GOOGL": "Technology",
    "INTC": "Semiconductors",
    "AMZN": "Retail & cloud",
    "NFLX": "Media",
    "DIS": "Media",
    "TSLA": "Automotive",
    "BA": "Aerospace",
    "CAT": "Industrials",
    "CCL": "Cruise",
    "RCL": "Cruise",
    "NCLH": "Cruise",
    "DAL": "Airlines",
    "UAL": "Airlines",
    "AAL": "Airlines",
    "MAR": "Lodging",
    "HLT": "Lodging",
    "MGM": "Casinos",
    "LVS": "Casinos",
    "EXPE": "Travel",
    "M": "Department stores",
    "KSS": "Department stores",
    "WMT": "Retail",
    "NKE": "Apparel",
    "SBUX": "Restaurants",
    "KO": "Beverages",
    "PG": "Household products",
    "JNJ": "Healthcare",
    "CVX": "Energy",
    "META": "Technology",
    "NVDA": "Semiconductors",
    "AVGO": "Semiconductors",
    "AMD": "Semiconductors",
    "QCOM": "Semiconductors",
    "TXN": "Semiconductors",
    "ORCL": "Software",
    "ADBE": "Software",
    "CRM": "Software",
    "INTU": "Software",
    "CSCO": "Technology",
    "IBM": "Technology",
    "ACN": "IT services",
    "CMCSA": "Media & cable",
    "CHTR": "Media & cable",
    "T": "Telecom",
    "VZ": "Telecom",
    "TMUS": "Telecom",
    "COST": "Retail",
    "HD": "Retail",
    "LOW": "Retail",
    "TGT": "Retail",
    "MCD": "Restaurants",
    "PEP": "Beverages",
    "CL": "Household products",
    "MDLZ": "Food",
    "KHC": "Food",
    "PM": "Tobacco",
    "MO": "Tobacco",
    "PFE": "Pharma",
    "MRK": "Pharma",
    "ABBV": "Pharma",
    "LLY": "Pharma",
    "BMY": "Pharma",
    "AMGN": "Biotech",
    "GILD": "Biotech",
    "UNH": "Health insurance",
    "CVS": "Healthcare services",
    "MDT": "Medical devices",
    "ABT": "Medical devices",
    "TMO": "Life sciences tools",
    "DHR": "Life sciences tools",
    "LMT": "Defense",
    "RTX": "Aerospace & defense",
    "GD": "Defense",
    "DE": "Industrials",
    "HON": "Industrials",
    "MMM": "Industrials",
    "GE": "Industrials",
    "EMR": "Industrials",
    "UPS": "Logistics",
    "FDX": "Logistics",
    "UNP": "Railroads",
    "COP": "Energy",
    "NEE": "Utilities",
    "DUK": "Utilities",
    "SO": "Utilities",
    "LIN": "Chemicals",
    "DOW": "Chemicals",
    "BKNG": "Travel",
    "LUV": "Airlines",
    "WYNN": "Casinos",
    "ABNB": "Travel",
    "UBER": "Mobility",
}


def _clean(o, sig: int = 10):
    """JSON-safe: numpy -> python, NaN/inf -> None, floats rounded to `sig` significant digits."""
    if isinstance(o, dict):
        return {str(k): _clean(v, sig) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v, sig) for v in o]
    if isinstance(o, np.ndarray):
        return _clean(o.tolist(), sig)
    if isinstance(o, (np.floating, float)):
        x = float(o)
        return None if not math.isfinite(x) else (x if sig >= 17 else float(f"{x:.{sig}g}"))
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return o


def _write(path: Path, obj, sig: int = 10) -> None:
    """Write a JSON-safe object to ``path``, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_clean(obj, sig), separators=(",", ":")), encoding="utf-8")


def history_block(c, n: int = 28) -> dict:
    """Build recent quarterly history series and SEC filing provenance for a company."""
    q = c.quarters.tail(n)
    ebitda = q["operating_income"] + q["da"]

    def ttm(s: pd.Series) -> pd.Series:
        return s.rolling(4).sum()

    full = c.quarters
    ebit_ttm = ttm(full["operating_income"]).tail(n)
    int_ttm = ttm(full["interest_expense"]).tail(n)
    icr = ebit_ttm / int_ttm.where(int_ttm > 0)
    ebitda_ttm = ttm(full["operating_income"] + full["da"]).tail(n)
    cash_like = q["cash"] + q["short_investments"]
    nd_ebitda = (q["total_debt"] - cash_like) / ebitda_ttm.where(ebitda_ttm > 0)
    series = {
        "revenue": q["revenue"],
        "ebitda": ebitda,
        "net_income": q["net_income"],
        "cfo": q["cfo"],
        "capex": q["capex"],
        "fcf": q["cfo"] - q["capex"],
        "cash": cash_like,
        "debt": q["total_debt"],
        "equity": q["equity"],
        "icr": icr,
        "nd_ebitda": nd_ebitda,
        "rating": pd.Series(np.where(icr.notna(), rating_rank(icr.fillna(0).values), np.nan), index=q.index),
    }
    prov = {}
    for field in ["revenue", "cash", "total_debt", "operating_income", "cfo"]:
        accns = c.provenance.get(field, {})
        prov[field] = [
            filing_url(c.cik, accns[d.date().isoformat()]) if d.date().isoformat() in accns else None for d in q.index
        ]
    return {
        "dates": [d.date().isoformat() for d in q.index],
        "series": {k: v.tolist() for k, v in series.items()},
        "provenance": prov,
    }


def company_block(ticker: str, macro: pd.DataFrame, n_paths: int = 5000, with_sobol: bool = False) -> dict:
    """Build one company's dashboard payload using macro data and Monte Carlo paths."""
    c = load_company(ticker)
    p = calibrate(c, macro, HORIZON)
    eps = draw_shocks(p, n_paths, HORIZON, seed=7)
    presets = {}
    for key, preset in PRESETS.items():
        sm = summarize(run(p, preset["knobs"], eps=eps))
        presets[key] = {
            k: sm[k]
            for k in (
                "health_score",
                "health_p10",
                "p_breach",
                "p_icr_below_1_5",
                "p_downgrade_below_ig",
                "median_quarters_to_breach",
                "rating_dist",
                "components",
                "health_mean",
            )
        }
        if key == "base":
            presets[key]["bands"] = sm["bands"]
            presets[key]["p_breach_by_q"] = sm["p_breach_by_q"]
    return {
        "ticker": c.ticker,
        "name": c.name,
        "cik": c.cik,
        "sector": classify(c.ticker)[1] or SECTORS.get(c.ticker, ""),
        "gics": classify(c.ticker)[0],
        "edgar_url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={c.cik}&type=10-",
        "quality": quality_report(c),
        "params": p,
        "history": history_block(c),
        "presets": presets,
        "reverse_stress": reverse_stress(p),
        "tornado": tornado(p),
        **({"sobol": sobol(p)} if with_sobol else {}),
    }


def golden_cases(macro: pd.DataFrame) -> None:
    """Small reference runs that the TypeScript engine must reproduce."""
    cases = [
        ("CCL", "pandemic", {}),
        ("AAPL", "rates_200", {}),
        ("BA", "credit_crunch", {"issue_equity": True}),
        ("NFLX", "supply_chain", {"cut_costs": False, "draw_revolver": False}),
        ("INTC", "base", {}),
        ("TSLA", "recession", {"recessions": False}),
    ]
    for ticker, preset, lev in cases:
        p = calibrate(load_company(ticker), macro, HORIZON)
        eps = draw_shocks(p, 64, HORIZON, seed=3)
        knobs = PRESETS[preset]["knobs"]
        levers = {**DEFAULT_LEVERS, **lev}
        out = simulate(p, build_scenario(knobs, HORIZON), eps, levers)
        _write(
            GOLDEN / f"{ticker}_{preset}.json",
            {
                "params": p,
                "knobs": knobs,
                "levers": levers,
                "eps": eps,
                "expected": {
                    k: out[k]
                    for k in (
                        "revenue",
                        "cash",
                        "debt",
                        "revolver",
                        "interest",
                        "icr",
                        "health",
                        "zscore",
                        "breach",
                        "equity",
                        "debt_issued",
                        "recession",
                    )
                },
            },
            sig=17,
        )


def meta_block() -> dict:
    """Return dashboard metadata for ratings, scenario presets, knobs, and levers."""
    return {
        "generated": date.today().isoformat(),
        "horizon": HORIZON,
        "ratings": {
            "labels": RATINGS,
            "icr_lower": [None if not np.isfinite(x) else x for x in ICR_LOWER],
            "spreads": SPREADS.tolist(),
        },
        "knobs": {k: {"default": d, "desc": desc} for k, (d, desc) in KNOBS.items()},
        "presets": {k: {"label": v["label"], "desc": v["desc"], "knobs": v["knobs"]} for k, v in PRESETS.items()},
        "levers": DEFAULT_LEVERS,
    }


def build(tickers: list[str], with_backtests: bool = True) -> None:
    """Generate company JSON, index metadata, and optionally backtests under ``web/public``."""
    macro = macro_quarterly()
    OUT.mkdir(parents=True, exist_ok=True)
    index_path = OUT / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {"companies": {}}
    failed: list[str] = []
    for t in tickers:
        t0 = time.time()
        try:
            block = company_block(t, macro, with_sobol=t in SOBOL_SET)
        except Exception as e:
            print(f"  {t}: FAILED {type(e).__name__}: {e}")
            failed.append(t)
            continue
        _write(OUT / "companies" / f"{t}.json", block)
        index["companies"][t] = {
            "name": block["name"],
            "sector": block["sector"],
            "showcase": t in SHOWCASE,
            "last_quarter": block["params"]["last_quarter"],
            "matrix": {
                k: {"health": v["health_score"], "p_breach": v["p_breach"]} for k, v in block["presets"].items()
            },
        }
        print(f"  {t}: health {block['presets']['base']['health_score']:.0f} ({time.time() - t0:.1f}s)")
    index["meta"] = meta_block()
    _write(index_path, index)
    if not GOLDEN.exists() or len(tickers) > 1:
        golden_cases(macro)

    if with_backtests:
        build_backtests()
    if failed:
        raise SystemExit(f"failed: {failed}")


def build_backtests() -> None:
    """Run forecast and cross-sectional backtests and write their JSON output under ``web/public``."""
    if True:
        bt: dict[str, Any] = {"cutoffs": CUTOFFS, "forecast": {}, "aggregate": {}}
        for t in SHOWCASE:
            for ck in CUTOFFS:
                bt["forecast"][f"{t}:{ck}"] = forecast_backtest(t, ck)
        rows = [
            (r["ticker"], ck, var, s)
            for r in bt["forecast"].values()
            for ck in [r["cutoff"]]
            for var, s in r["scores"].items()
        ]
        df = pd.DataFrame(
            [
                {"var": v, "cov50": s["coverage50"], "cov90": s["coverage90"], "skill": s["crps_skill"], "n": s["n"]}
                for _, _, v, s in rows
            ]
        )
        bt["aggregate"] = {
            v: {
                "coverage50": float(np.average(g["cov50"], weights=g["n"])),
                "coverage90": float(np.average(g["cov90"], weights=g["n"])),
                "median_crps_skill": float(g["skill"].median()),
                "share_beating_baseline": float((g["skill"] > 0).mean()),
                "cases": len(g),
            }
            for v, g in df.groupby("var")
        }
        bt["cross_section"] = cross_section()
        _write(OUT / "backtest.json", bt)
        print("  backtests written")


if __name__ == "__main__":
    args = [a.upper() for a in sys.argv[1:]]
    if args == ["GOLDEN"]:
        golden_cases(macro_quarterly())
    elif args == ["BACKTEST"]:
        build_backtests()
    elif args:
        build(args, with_backtests=False)
    else:
        build(list(dict.fromkeys(SHOWCASE + UNIVERSE + UNIVERSE_XL)))
