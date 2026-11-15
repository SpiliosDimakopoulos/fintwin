"""Build the dashboard's static data: one JSON per company, an index, backtests and parity goldens.

uv run python -m fintwin.export                 # showcase + universe
uv run python -m fintwin.export AAPL MSFT       # specific tickers only (index is merged)
"""

from __future__ import annotations

import json
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .backtest.batch import UNIVERSE_XL
from .backtest.walk_forward import CUTOFFS, UNIVERSE, cross_section, forecast_backtest
from .clean import _clean  # noqa: F401  (moved; kept importable here)
from .data.edgar import filing_url, write_atomic
from .data.facts import contiguous_mask, load_company
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


def dumps(obj, sig: int = 10, **kw) -> str:
    """Strict JSON text: `_clean` first, then ``allow_nan=False`` so a stray NaN can never reach JSON.parse."""
    return json.dumps(_clean(obj, sig), allow_nan=False, **kw)


def _write(path: Path, obj, sig: int = 10) -> None:
    """Write a JSON-safe object to ``path``, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(path, dumps(obj, sig, separators=(",", ":")).encode("utf-8"))


def index_entry(block: dict) -> dict:
    """One company's entry in index.json; the single builder shared by export.build and pipeline.build_index."""
    return {
        "name": block["name"],
        "sector": block["sector"],
        "gics": block.get("gics", ""),
        "showcase": block["ticker"] in SHOWCASE,
        "last_quarter": block["params"]["last_quarter"],
        "matrix": {k: {"health": v["health_score"], "p_breach": v["p_breach"]} for k, v in block["presets"].items()},
        # baseline score components, so the weekly changes feed can say which one moved
        "components": block["presets"]["base"].get("components"),
    }


def history_block(c, n: int = 28) -> dict:
    """Build recent quarterly history series and SEC filing provenance for a company."""
    q = c.quarters.tail(n)
    ebitda = q["operating_income"] + q["da"]

    full = c.quarters
    ok4 = contiguous_mask(full, 4)

    def ttm(s: pd.Series) -> pd.Series:
        # NaN unless the 4 rows are 4 consecutive reported quarters (a gap row or a calendar hole spoils the sum)
        return s.rolling(4).sum().where(ok4)

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
    gics, sub_industry = classify(c.ticker)
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
        "sector": sub_industry,
        "gics": gics,
        "edgar_url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={c.cik}&type=10-",
        "quality": quality_report(c),
        "n_paths": n_paths,
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
            if t in index["companies"]:  # its old JSON stays; the index must not pass it off as fresh
                index["companies"][t]["stale"] = True
            continue
        _write(OUT / "companies" / f"{t}.json", block)
        index["companies"][t] = index_entry(block)
        print(f"  {t}: health {block['presets']['base']['health_score']:.0f} ({time.time() - t0:.1f}s)")
    index["meta"] = meta_block()
    _write(index_path, index)
    # the parity goldens are rewritten only by `export GOLDEN`: from here they would drift with each day's EDGAR data
    if with_backtests:
        build_backtests()
    if failed:
        raise SystemExit(f"failed: {failed}")


def build_backtests() -> None:
    """Run forecast and cross-sectional backtests and write their JSON output under ``web/public``."""
    bt: dict[str, Any] = {"cutoffs": CUTOFFS, "forecast": {}, "aggregate": {}}
    for t in SHOWCASE:
        for ck in CUTOFFS:
            bt["forecast"][f"{t}:{ck}"] = forecast_backtest(t, ck)
    df = pd.DataFrame(
        [
            {"var": v, "cov50": s["coverage50"], "cov90": s["coverage90"], "skill": s["crps_skill"], "n": s["n"]}
            for r in bt["forecast"].values()
            for v, s in r["scores"].items()
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
