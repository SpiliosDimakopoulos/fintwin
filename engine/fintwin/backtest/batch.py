"""Large-sample validation, one company per process (memory-friendly), then pooled aggregation.

    uv run python -m fintwin.backtest.batch AAPL        # per-company: rolling-origin cases + COVID cross-section row
    uv run python -m fintwin.backtest.batch --aggregate # pool everything -> web/public/data/calibration.json

Rolling-origin design: for every company and every yearly cutoff (15 Feb 2013 ... 15 Feb 2025) the twin is
calibrated on point-in-time filings and forecasts the next 4 quarters. Online conformal calibration then
rescales interval widths using only forecasts made at *earlier* cutoffs, so the calibrated coverage is itself
out-of-sample.
"""

from __future__ import annotations

import json
import os
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from ..data.facts import load_company
from ..data.fred import macro_quarterly
from ..model.sd_model import simulate
from ..scenarios.presets import DEFAULT_LEVERS, PRESETS, build_scenario
from ..stochastic.calibrate import calibrate
from ..stochastic.mc import summarize
from ..stochastic.shocks import draw_shocks
from .scoring import crps_gaussian, crps_samples

CACHE = Path(__file__).resolve().parents[2] / ".cache" / "batch"
OUT = Path(__file__).resolve().parents[3] / "web" / "public" / "data" / "calibration.json"
ORIGINS = [f"{y}-02-15" for y in range(2013, 2026)]
H = 4
Q = [5, 25, 50, 75, 95]

# S&P 100-style large caps outside financials, plus the travel / leisure names most exposed to 2020.
UNIVERSE_XL = [
    "AAPL",
    "MSFT",
    "AMZN",
    "GOOGL",
    "META",
    "NVDA",
    "TSLA",
    "AVGO",
    "ORCL",
    "ADBE",
    "CRM",
    "CSCO",
    "INTC",
    "AMD",
    "QCOM",
    "TXN",
    "IBM",
    "ACN",
    "INTU",
    "NFLX",
    "DIS",
    "CMCSA",
    "T",
    "VZ",
    "TMUS",
    "CHTR",
    "WMT",
    "COST",
    "HD",
    "LOW",
    "TGT",
    "NKE",
    "SBUX",
    "MCD",
    "KO",
    "PEP",
    "PG",
    "CL",
    "MDLZ",
    "PM",
    "MO",
    "KHC",
    "JNJ",
    "PFE",
    "MRK",
    "ABBV",
    "LLY",
    "BMY",
    "AMGN",
    "GILD",
    "UNH",
    "CVS",
    "MDT",
    "ABT",
    "TMO",
    "DHR",
    "BA",
    "LMT",
    "RTX",
    "GD",
    "CAT",
    "DE",
    "HON",
    "MMM",
    "GE",
    "UPS",
    "FDX",
    "UNP",
    "EMR",
    "CVX",
    "COP",
    "NEE",
    "DUK",
    "SO",
    "LIN",
    "DOW",
    "BKNG",
    "CCL",
    "RCL",
    "NCLH",
    "DAL",
    "UAL",
    "AAL",
    "LUV",
    "MAR",
    "HLT",
    "M",
    "KSS",
    "MGM",
    "LVS",
    "WYNN",
    "EXPE",
    "ABNB",
    "UBER",
]


STEP_DAYS = (60, 125)  # one fiscal quarter apart, allowing for 52/53-week calendars and stub periods


def data_legacy() -> bool:
    """FINTWIN_DATA_LEGACY=1 restores the v2 data handling (zero-filled outcome gaps, positional alignment, 90-day
    reporting lag) for the one comparison run of REVISION_PLAN_3 §0.3."""
    return os.environ.get("FINTWIN_DATA_LEGACY", "0") == "1"


def contiguous_prefix(prev: pd.Timestamp, idx: pd.DatetimeIndex) -> int:
    """How many of the quarter ends in `idx` follow `prev` (and each other) one quarter apart, up to the first gap.

    Realized quarters are matched to forecast quarters by position, so a missing quarter would compare simulated
    quarter h with a later quarter (SW-4). Workstream A's full calendar turns such quarters into NaN rows; this check
    also holds for a spine that drops them."""
    n = 0
    for t in idx:
        if not STEP_DAYS[0] <= (t - prev).days <= STEP_DAYS[1]:
            break
        n += 1
        prev = t
    return n


def first_filed(cik: int) -> dict[str, pd.Series]:
    """Period end -> date the value was first filed, for revenue and cash, from the cached companyfacts (D10)."""
    from ..data.facts import DURATION, FORMS, INSTANT
    from ..data.facts import company_facts as _facts

    gaap = _facts(cik)["facts"].get("us-gaap", {})
    out: dict[str, pd.Series] = {}
    for field, tags in (("revenue", DURATION["revenue"]), ("cash", INSTANT["cash"])):
        frames = []
        for tag in tags:
            rows = gaap.get(tag, {}).get("units", {}).get("USD", [])
            if rows:
                d = pd.DataFrame(rows)
                frames.append(d.loc[d["form"].isin(FORMS), ["end", "filed"]])
        if frames:
            d = pd.concat(frames)
            out[field] = pd.to_datetime(d["filed"]).groupby(pd.to_datetime(d["end"])).min().sort_index()
    return out


def filed_for(filed: pd.Series | None, end: pd.Timestamp, tol_days: int = 12) -> str | None:
    """First filing date of the period ending nearest `end` (within the spine's alignment tolerance)."""
    if filed is None or filed.empty:
        return None
    gap = np.abs((filed.index - pd.Timestamp(end)).days)
    i = int(np.argmin(gap))
    return str(filed.iloc[i].date()) if gap[i] <= tol_days else None


def seen_by(target: pd.Series, filed: pd.Series | None, cutoff: pd.Timestamp, lag_days: int = 90) -> pd.Series:
    """Was each target quarter reported by `cutoff`? The actual first filing date when known (D10), otherwise the
    quarter end plus `lag_days` (the only rule before revision 3, and the rule under FINTWIN_DATA_LEGACY)."""
    fallback = pd.to_datetime(target) + pd.Timedelta(days=lag_days)
    if filed is None or data_legacy():
        return fallback <= cutoff
    when = pd.to_datetime(filed, errors="coerce").fillna(fallback)
    return when <= cutoff


def _realized(full: pd.DataFrame, after: pd.Timestamp) -> pd.DataFrame:
    r = full[full.index > after + pd.Timedelta(days=20)].head(H).copy()
    if not data_legacy():
        r = r.iloc[: contiguous_prefix(after, r.index)]
    r["cash_like"] = r["cash"] + r["short_investments"]
    return r


def _baseline(hist: pd.DataFrame, var: str, h: int) -> tuple[float, float]:
    if var == "revenue":
        s = hist["revenue"].dropna()
        same = s.iloc[-4 + ((h - 1) % 4)]
        yoy = np.log(s / s.shift(4)).dropna().tail(20)
        return float(same), float(same * yoy.std() * np.sqrt(int(np.ceil(h / 4))))
    s = (hist["cash"] + hist["short_investments"]).dropna()
    return float(s.iloc[-1]), float(s.diff().tail(20).std() * np.sqrt(h))


def rw_empirical(hist: pd.DataFrame, var: str, h: int) -> np.ndarray | None:
    """Random-walk density from empirical quantiles (E10), an alternative to the Gaussian `_baseline`: the seasonal
    random walk times the last 20 observed year-on-year growth factors for revenue; the last cash balance plus the
    last 20 observed h-quarter changes for cash."""
    if var == "revenue":
        s = hist["revenue"].dropna()
        if len(s) < 12:
            return None
        same = float(s.iloc[-4 + ((h - 1) % 4)])
        yoy = np.log(s / s.shift(4)).replace([np.inf, -np.inf], np.nan).dropna().tail(20).to_numpy(float)
        return same * np.exp(yoy * np.sqrt(int(np.ceil(h / 4)))) if len(yoy) >= 8 else None
    s = (hist["cash"] + hist["short_investments"].fillna(0)).dropna()
    d = s.diff(h).dropna().tail(20).to_numpy(float)
    return float(s.iloc[-1]) + d if len(d) >= 8 else None


def _vintage(hist, origin: str | None, macro) -> dict:
    """The twin as it stood at one point in time: horizon-12 parameters and its baseline verdict."""
    p12 = calibrate(hist, macro, 12)
    sm = summarize(simulate(p12, build_scenario({}, 12), draw_shocks(p12, 1500, 12, seed=5), DEFAULT_LEVERS))
    return {
        "asof": origin or "latest",
        "last_quarter": hist.quarters.index[-1].date().isoformat(),
        "health": sm["health_score"],
        "health_p10": sm["health_p10"],
        "p_breach": sm["p_breach"],
        "params": {k: v for k, v in p12.items() if k != "_sources"},
    }


def company_cases(ticker: str, n_paths: int = 2000) -> dict:
    full_data = load_company(ticker)
    full = full_data.quarters
    cases, skipped, vintages = [], {}, []
    try:
        filed = first_filed(int(full_data.cik))
    except Exception as e:  # conformal windows then use the fixed lag; the reason is kept
        filed = {}
        skipped["filed"] = f"{type(e).__name__}: {e}"
    for origin in ORIGINS:
        try:
            hist = load_company(ticker, asof=origin)
            if len(hist.quarters) < 16:
                skipped[origin] = "fewer than 16 quarters of history"
                continue
            vintages.append(_vintage(hist, origin, macro_quarterly(origin)))
            real = _realized(full, hist.quarters.index[-1])
            if len(real) < H:
                skipped[origin] = "not enough realized quarters yet"
                continue
            p = calibrate(hist, macro_quarterly(origin), H)
            eps = draw_shocks(p, n_paths, H, seed=11)
            sims = {
                flag: simulate(p, build_scenario({}, H), eps, {**DEFAULT_LEVERS, "recessions": flag})
                for flag in (True, False)
            }
            for var, key in (("revenue", "revenue"), ("cash_like", "cash")):
                for h in range(H):
                    y = float(real[var].iloc[h])
                    if not np.isfinite(y):
                        continue
                    mu_b, sd_b = _baseline(hist.quarters, var, h + 1)
                    emp = rw_empirical(hist.quarters, var, h + 1)
                    row = {
                        "origin": origin,
                        "var": var,
                        "h": h + 1,
                        "y": y,
                        "target": str(real.index[h].date()),
                        "filed": filed_for(filed.get("revenue" if var == "revenue" else "cash"), real.index[h]),
                        "crps_baseline": crps_gaussian(mu_b, sd_b, y),
                        "crps_baseline_emp": crps_samples(emp, y) if emp is not None else None,
                    }
                    for flag, out in sims.items():
                        x = out[key][:, h]
                        tag = "reg" if flag else "noreg"
                        row[f"q_{tag}"] = np.percentile(x, Q).tolist()
                        row[f"pit_{tag}"] = float(np.mean(x <= y))
                        row[f"crps_{tag}"] = crps_samples(x, y)
                    cases.append(row)
        except Exception as e:  # keep going: report why a cutoff could not be used
            skipped[origin] = f"{type(e).__name__}: {e}"
    try:
        vintages.append(_vintage(full_data, None, macro_quarterly()))
    except Exception as e:
        skipped["latest"] = f"{type(e).__name__}: {e}"
    cash_like = full["cash"] + full["short_investments"]
    timeline = {
        "ticker": ticker,
        "series": {
            "dates": [d.date().isoformat() for d in full.index],
            "revenue": full["revenue"].round(0).tolist(),
            "cash": cash_like.round(0).tolist(),
            "debt": full["total_debt"].round(0).tolist(),
        },
        "vintages": vintages,
    }
    from ..research.__main__ import stamp

    return {
        "ticker": ticker,
        "cases": cases,
        "covid": covid_row(ticker, full, skipped),
        "skipped": skipped,
        "timeline": timeline,
        "_stamp": stamp(),  # SW-2: `aggregate` reports how many companies come from another code/data version
    }


def covid_row(ticker: str, full: pd.DataFrame, why: dict | None = None) -> dict | None:
    """Pre-COVID twin under the demand-freeze scenario vs realized 2020-21 cash burn. When there is no row, the
    reason is written to `why["covid"]` (SW-3)."""
    why = why if why is not None else {}
    try:
        cutoff = "2020-02-20"
        hist = load_company(ticker, asof=cutoff)
        if len(hist.quarters) < 16:
            why["covid"] = "fewer than 16 quarters of history"
            return None
        p = calibrate(hist, macro_quarterly(cutoff), 8)
        eps = draw_shocks(p, 2000, 8, seed=7)
        st = summarize(simulate(p, build_scenario(PRESETS["pandemic"]["knobs"], 8), eps, DEFAULT_LEVERS))
        win = full[(full.index > pd.Timestamp("2020-01-15")) & (full.index <= pd.Timestamp("2021-07-15"))]
        fcf = win["cfo"] - win["capex"]
        if not data_legacy() and not np.isfinite(fcf.to_numpy(float)).all():
            why["covid"] = "missing cash-flow quarter in 2020-21"  # D4: not zero burn
            return None
        fcf = fcf.fillna(0).cumsum()
        rev_ttm = float(hist.quarters["revenue"].tail(4).sum())
        if not len(fcf):
            why["covid"] = "no reported quarter in 2020-21"
            return None
        return {
            "ticker": ticker,
            "name": hist.name,
            "health_stress": st["health_score"],
            "p_breach_stress": st["p_breach"],
            "realized_min_cum_fcf_pct_rev": float(fcf.min() / rev_ttm * 100),
            "realized_debt_raise_pct_rev": float((win["total_debt"].max() - p["debt0"]) / rev_ttm * 100),
        }
    except Exception as e:
        why["covid"] = f"{type(e).__name__}: {e}"
        return None


def _scores(df: pd.DataFrame, tag: str) -> pd.DataFrame:
    q = np.array(df[f"q_{tag}"].tolist())
    y = df["y"].values
    half90, half50 = (q[:, 4] - q[:, 0]) / 2, (q[:, 3] - q[:, 1]) / 2
    return pd.DataFrame(
        {
            "s90": np.abs(y - q[:, 2]) / np.maximum(half90, 1e-9),
            "s50": np.abs(y - q[:, 2]) / np.maximum(half50, 1e-9),
            "hit90": (y >= q[:, 0]) & (y <= q[:, 4]),
            "hit50": (y >= q[:, 1]) & (y <= q[:, 3]),
        },
        index=df.index,
    )


def aggregate() -> dict:
    files = sorted(CACHE.glob("*.json"))
    per = [json.loads(f.read_text(encoding="utf-8")) for f in files]
    df = pd.DataFrame([c | {"ticker": r["ticker"]} for r in per for c in r["cases"]])
    df["year"] = df["origin"].str[:4].astype(int)
    res: dict = {
        "n_companies": int(df["ticker"].nunique()),
        "n_forecasts": int(len(df)),
        "origins": ORIGINS,
        "horizon": H,
        "vars": {},
    }
    for var, g in df.groupby("var"):
        g = g.copy()
        sc = _scores(g, "reg")
        g = g.join(sc)
        # online conformal: the scale factor for origin 15 Feb Y uses only forecasts whose target quarter had been
        # reported by then (its actual first filing date, D10; quarter end + 90 days where unknown), so no error is
        # used before it was observable
        conf90, conf50, factors = [], [], {}
        target = pd.to_datetime(g["target"]) if "target" in g else pd.to_datetime(g["year"].astype(str) + "-01-01")
        filed = g["filed"] if "filed" in g else None
        for year, gy in g.groupby("year"):
            seen = seen_by(target, filed, pd.Timestamp(f"{year}-02-15"))
            past = g[(g["year"] < year) & seen]
            if len(past) < 40:
                continue
            c90, c50 = float(np.quantile(past["s90"], 0.9)), float(np.quantile(past["s50"], 0.5))
            factors[int(year)] = {"c90": c90, "c50": c50}
            conf90 += list(gy["s90"] <= c90)
            conf50 += list(gy["s50"] <= c50)
        eval_mask = g["year"].isin(list(factors))
        pit = np.histogram(g["pit_reg"], bins=10, range=(0, 1))[0] / len(g)
        by_year = {
            int(y): {
                "cov90": float(gy["hit90"].mean()),
                "n": int(len(gy)),
                "skill": float(1 - gy["crps_reg"].mean() / gy["crps_baseline"].mean()),
            }
            for y, gy in g.groupby("year")
        }
        res["vars"][var] = {
            "n": int(len(g)),
            "raw": {
                "coverage90": float(g.loc[eval_mask, "hit90"].mean()),
                "coverage50": float(g.loc[eval_mask, "hit50"].mean()),
            },
            "conformal": {"coverage90": float(np.mean(conf90)), "coverage50": float(np.mean(conf50))},
            "conformal_factors": factors,
            "crps_skill_vs_naive": float(1 - g["crps_reg"].mean() / g["crps_baseline"].mean()),
            "median_case_skill": float((1 - g["crps_reg"] / g["crps_baseline"]).median()),
            "share_cases_beating_naive": float((g["crps_reg"] < g["crps_baseline"]).mean()),
            "regime_ablation": {
                "crps_with": float(g["crps_reg"].mean()),
                "crps_without": float(g["crps_noreg"].mean()),
                "improvement_pct": float((1 - g["crps_reg"].mean() / g["crps_noreg"].mean()) * 100),
            },
            "pit_hist": pit.round(4).tolist(),
            "by_year": by_year,
            "by_horizon": {int(h): float(gh["hit90"].mean()) for h, gh in g.groupby("h")},
            # E10: skill and a firm-clustered DM statistic per horizon (not pooled), against both naive densities
            "skill_by_horizon": skill_by_horizon(g),
        }
    rows = [r["covid"] for r in per if r.get("covid")]
    xs = pd.DataFrame(rows)
    rho, pval = spearmanr(xs["health_stress"], xs["realized_min_cum_fcf_pct_rev"])
    rng = np.random.default_rng(0)
    boot = []
    for _ in range(2000):
        b = xs.sample(len(xs), replace=True, random_state=int(rng.integers(1_000_000_000)))
        boot.append(spearmanr(b["health_stress"], b["realized_min_cum_fcf_pct_rev"])[0])
    # decile view: realized burn of the twin's most vs least fragile fifth
    xs["quintile"] = pd.qcut(xs["health_stress"].rank(method="first"), 5, labels=False)
    quint = xs.groupby("quintile")["realized_min_cum_fcf_pct_rev"].median().round(1).tolist()
    severe = (xs["realized_min_cum_fcf_pct_rev"] < -10).groupby(xs["quintile"]).mean().round(3).tolist()
    res["cross_section"] = {
        "n": int(len(xs)),
        "spearman": float(rho),
        "p_value": float(pval),
        "ci95": [float(np.nanpercentile(boot, 2.5)), float(np.nanpercentile(boot, 97.5))],
        "quintile_median_burn": quint,
        "quintile_share_severe_burn": severe,
        "rows": rows,
    }
    res["skipped"] = {r["ticker"]: r["skipped"] for r in per if r["skipped"]}
    stamps = pd.Series([r.get("_stamp") or "none" for r in per]).value_counts()
    res["stamps"] = {"n_distinct": int(len(stamps)), "largest_share": float(stamps.iloc[0] / stamps.sum())}
    from ..export import _clean

    OUT.write_text(json.dumps(_clean(res), separators=(",", ":"), allow_nan=False), encoding="utf-8")
    return res


def dm_stat(d: np.ndarray, groups: np.ndarray) -> dict:
    """Diebold-Mariano statistic of mean loss differences `d`, with a cluster-robust variance over `groups` and
    t(G-1) p-values (few clusters)."""
    from scipy import stats as _st

    d, groups = np.asarray(d, float), np.asarray(groups)
    m = np.isfinite(d)
    d, groups = d[m], groups[m]
    n, G = len(d), len(set(groups.tolist()))
    if n < 10 or G < 3:
        return {"n": int(n), "mean": float(d.mean()) if n else None, "t": None, "p": None}
    e = d - d.mean()
    s = pd.Series(e).groupby(groups).sum().to_numpy()
    var = (G / (G - 1)) * float(np.sum(s**2)) / n**2
    t = float(d.mean() / np.sqrt(var)) if var > 0 else None
    return {
        "n": int(n),
        "clusters": int(G),
        "mean": float(d.mean()),
        "t": t,
        "p": float(2 * _st.t.sf(abs(t), G - 1)) if t is not None else None,
    }


def skill_by_horizon(g: pd.DataFrame) -> dict:
    out: dict = {}
    for h, gh in g.groupby("h"):
        r: dict = {"n": int(len(gh))}
        for base in ("crps_baseline", "crps_baseline_emp"):
            if base not in gh or gh[base].isna().all():
                continue
            b = gh[base].astype(float)
            ok = b.notna()
            r[base] = {
                "skill": float(1 - gh.loc[ok, "crps_reg"].mean() / b[ok].mean()),
                "dm": dm_stat((gh.loc[ok, "crps_reg"] - b[ok]).to_numpy(float), gh.loc[ok, "ticker"].to_numpy()),
            }
        out[int(h)] = r
    return out


if __name__ == "__main__":
    warnings.simplefilter("ignore")
    arg = sys.argv[1]
    if arg == "--aggregate":
        r = aggregate()
        print(json.dumps({k: v for k, v in r.items() if k not in ("vars", "cross_section", "skipped")}))
        for var, v in r["vars"].items():
            print(
                var,
                {
                    k: v[k]
                    for k in (
                        "n",
                        "raw",
                        "conformal",
                        "crps_skill_vs_naive",
                        "share_cases_beating_naive",
                        "regime_ablation",
                    )
                },
            )
        cs = r["cross_section"]
        print(
            "cross-section",
            {
                k: cs[k]
                for k in ("n", "spearman", "p_value", "ci95", "quintile_median_burn", "quintile_share_severe_burn")
            },
        )
    else:
        CACHE.mkdir(parents=True, exist_ok=True)
        t = arg.upper()
        res = company_cases(t)
        (CACHE / f"{t}.json").write_text(json.dumps(res), encoding="utf-8")
        print(f"{t}: {len(res['cases'])} cases, {len(res['skipped'])} skipped, covid={'yes' if res['covid'] else 'no'}")
