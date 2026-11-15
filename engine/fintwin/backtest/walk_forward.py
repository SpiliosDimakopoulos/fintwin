"""Out-of-sample backtests with point-in-time data.

1. Forecast backtest - calibrate on filings available at a cutoff date, forecast unconditionally,
   score against what was actually reported afterwards (coverage, PIT, CRPS vs naive baselines).
2. Structural backtest - feed the realized revenue path into the model and check whether its
   mechanics reproduce the realized cash burn. This separates "could not foresee the shock" from
   "misunderstood how the company reacts to it".
3. Cross-sectional test - did the pre-COVID twin rank companies' vulnerability correctly?
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from ..data.facts import load_company
from ..data.fred import macro_quarterly
from ..model.sd_model import simulate
from ..scenarios.presets import DEFAULT_LEVERS, PRESETS, build_scenario
from ..stochastic.calibrate import calibrate
from ..stochastic.mc import run, summarize
from ..stochastic.shocks import draw_shocks
from .batch import _calendar, data_legacy, usable_prefix, window_ok
from .scoring import crps_gaussian, crps_samples, interval_hit, pit

CUTOFFS: dict[str, dict[str, str]] = {
    "pre_covid": {"date": "2020-02-20", "label": "Pre-COVID (data filed by 20 Feb 2020)", "stress": "pandemic"},
    "pre_hikes": {"date": "2022-01-31", "label": "Pre-rate-hikes (data filed by 31 Jan 2022)", "stress": "stagflation"},
}
BANDS = [5, 25, 50, 75, 95]


def _realized(full: pd.DataFrame, after: pd.Timestamp, horizon: int) -> pd.DataFrame:
    r = full[full.index > after + pd.Timedelta(days=20)].head(horizon).copy()
    if not data_legacy():  # keep the longest gap-free run of quarters, never a window across a hole
        r = r.iloc[: usable_prefix(r, after)]  # the run `following` accepts, found in one pass
    r["cash_like"] = r["cash"] + r["short_investments"]
    r["ebitda"] = r["operating_income"] + r["da"]
    r["fcf"] = r["cfo"] - r["capex"]
    return r


def _baseline(hist: pd.DataFrame, var: str, h: int) -> tuple[float, float]:
    """Naive benchmarks: seasonal random walk for revenue, plain random walk for balances."""
    legacy = data_legacy()  # otherwise changes on the calendar series (gap rows blank), not across a hole
    if var == "revenue":
        s = hist["revenue"].dropna()
        same_season = s.iloc[-4 + ((h - 1) % 4)]
        r = s if legacy else _calendar(hist, hist["revenue"])
        yoy = np.log(r / r.shift(4)).dropna().tail(20)
        sd = float(yoy.std()) * np.sqrt(int(np.ceil(h / 4)))
        return float(same_season), float(same_season * sd)
    col = {"cash_like": None, "total_debt": "total_debt"}[var]
    s = (hist["cash"] + hist["short_investments"]) if col is None else hist[col]
    if legacy:
        s = s.dropna()
        sd = float(s.diff().tail(20).std()) * np.sqrt(h)
        return float(s.iloc[-1]), sd
    s = _calendar(hist, s)
    return float(s.dropna().iloc[-1]), float(s.diff().dropna().tail(20).std()) * np.sqrt(h)


def forecast_backtest(ticker: str, cutoff_key: str, horizon: int = 8, n_paths: int = 4000) -> dict:
    cut = CUTOFFS[cutoff_key]
    hist = load_company(ticker, asof=cut["date"])
    macro = macro_quarterly(cut["date"])
    p = calibrate(hist, macro, horizon)
    eps = draw_shocks(p, n_paths, horizon, seed=101)
    base = run(p, eps=eps)
    stress = run(p, PRESETS[cut["stress"]]["knobs"], eps=eps)

    full = load_company(ticker).quarters
    real = _realized(full, hist.quarters.index[-1], horizon)
    H = len(real)

    model_vars = {
        "revenue": base["revenue"],
        "cash_like": base["cash"],
        "total_debt": base["debt"] + base["revolver"],
    }
    stress_vars = {
        "revenue": stress["revenue"],
        "cash_like": stress["cash"],
        "total_debt": stress["debt"] + stress["revolver"],
    }
    scores, series = {}, {}
    for var, sims in model_vars.items():
        y = real[var].values
        rows = []
        for h in range(H):
            if not np.isfinite(y[h]):
                continue
            mu_b, sd_b = _baseline(hist.quarters, var, h + 1)
            if not (np.isfinite(mu_b) and np.isfinite(sd_b)):
                continue  # a NaN baseline would drop out of the crps_baseline mean but not out of the crps mean
            rows.append(
                {
                    "h": h + 1,
                    "y": float(y[h]),
                    "hit50": interval_hit(sims[:, h], y[h], 50),
                    "hit90": interval_hit(sims[:, h], y[h], 90),
                    "pit": pit(sims[:, h], y[h]),
                    "crps": crps_samples(sims[:, h], y[h]),
                    "crps_baseline": crps_gaussian(mu_b, sd_b, y[h]),
                    "stress_hit90": interval_hit(stress_vars[var][:, h], y[h], 90),
                }
            )
        if rows:
            df = pd.DataFrame(rows)
            scores[var] = {
                "n": len(df),
                "coverage50": float(df["hit50"].mean()),
                "coverage90": float(df["hit90"].mean()),
                "stress_coverage90": float(df["stress_hit90"].mean()),
                "crps": float(df["crps"].mean()),
                "crps_baseline": float(df["crps_baseline"].mean()),
                "crps_skill": float(1 - df["crps"].mean() / max(df["crps_baseline"].mean(), 1e-9)),
                "pit": df["pit"].round(3).tolist(),
            }
        hq = hist.quarters
        hist_vals = {
            "revenue": hq["revenue"],
            "cash_like": hq["cash"] + hq["short_investments"],
            "total_debt": hq["total_debt"],
        }[var].tail(12)
        series[var] = {
            "history": {
                "dates": [d.date().isoformat() for d in hist_vals.index],
                "values": hist_vals.round(0).tolist(),
            },
            "realized": {
                "dates": [d.date().isoformat() for d in real.index],
                "values": [None if not np.isfinite(v) else round(float(v)) for v in real[var].values],
            },
            "base_bands": np.percentile(sims, BANDS, axis=0).round(0).tolist(),
            "stress_bands": np.percentile(stress_vars[var], BANDS, axis=0).round(0).tolist(),
        }

    structural = structural_backtest(p, real, eps)
    return {
        "ticker": ticker,
        "cutoff": cut["date"],
        "cutoff_label": cut["label"],
        "stress": cut["stress"],
        "last_quarter_known": hist.quarters.index[-1].date().isoformat(),
        "horizon": H,
        "scores": scores,
        "series": series,
        "structural": structural,
        "pre_shock": {"base": _headline(summarize(base)), "stress": _headline(summarize(stress))},
    }


def _headline(sm: dict) -> dict:
    return {k: sm[k] for k in ("health_score", "p_breach", "p_icr_below_1_5", "p_downgrade_below_ig")}


def structural_backtest(p: dict, real: pd.DataFrame, eps: np.ndarray) -> dict:
    """Feed realized revenue; compare simulated vs actual cumulative free cash flow."""
    T = p["horizon"]
    override = np.full(T, np.nan)
    H = min(len(real), T)
    override[:H] = real["revenue"].values[:H]
    scn = build_scenario({}, T)
    scn["revenue_override"] = override
    out = simulate(p, scn, eps, DEFAULT_LEVERS)
    actual = real["fcf"].values[:H]
    ok = np.isfinite(actual)
    if not data_legacy() and not ok.all():  # cumulate only up to the first missing quarter, never through it
        H = int(np.argmin(ok))
        actual, ok = actual[:H], ok[:H]
    if ok.sum() == 0:
        return {}
    sim_cum = np.cumsum(out["fcf"][:, :H], axis=1)
    act_cum = np.cumsum(np.where(ok, actual, 0.0))
    med = np.median(sim_cum, axis=0)
    return {
        "dates": [d.date().isoformat() for d in real.index[:H]],
        "actual_cum_fcf": act_cum.round(0).tolist(),
        "model_cum_fcf_bands": np.percentile(sim_cum, BANDS, axis=0).round(0).tolist(),
        "final_error_pct": float((med[-1] - act_cum[-1]) / max(abs(act_cum[-1]), 1e-9) * 100),
        "corr": float(np.corrcoef(np.diff(np.r_[0, med]), np.diff(np.r_[0, act_cum]))[0, 1]) if H > 2 else None,
    }


UNIVERSE = [
    "AAPL",
    "MSFT",
    "GOOGL",
    "AMZN",
    "NFLX",
    "TSLA",
    "INTC",
    "BA",
    "CCL",
    "RCL",
    "NCLH",
    "DAL",
    "UAL",
    "AAL",
    "MAR",
    "HLT",
    "M",
    "KSS",
    "CVX",
    "DIS",
    "NKE",
    "SBUX",
    "WMT",
    "KO",
    "PG",
    "JNJ",
    "CAT",
    "MGM",
    "LVS",
    "EXPE",
]


def cross_section(tickers: list[str] = UNIVERSE, n_paths: int = 2000) -> dict:
    """Pre-COVID twin vulnerability vs realized 2020-21 liquidity stress, across a universe.

    The universe is hand-picked (with hindsight about which sectors 2020 hit), so the rank correlation is an
    illustration, not the census result."""
    cutoff = CUTOFFS["pre_covid"]["date"]
    macro = macro_quarterly(cutoff)
    rows, failed = [], {}
    for t in tickers:
        try:
            hist = load_company(t, asof=cutoff)
            # cheap data checks before calibration and simulation (no earlier 16-quarter screen here, so the
            # four-quarter one is needed for the trailing revenue)
            if not window_ok(hist.quarters, 4):
                failed[t] = "no four consecutive quarters before the cutoff"
                continue
            full = load_company(t).quarters
            win = full[(full.index > pd.Timestamp("2020-01-15")) & (full.index <= pd.Timestamp("2021-07-15"))]
            fcf = win["cfo"] - win["capex"]
            if not data_legacy() and not np.isfinite(fcf.to_numpy(float)).all():
                failed[t] = "missing cash-flow quarter in 2020-21"  # unknown, not zero burn
                continue
            p = calibrate(hist, macro, 8)
            eps = draw_shocks(p, n_paths, 8, seed=7)
            sm_base = summarize(run(p, eps=eps))
            sm_stress = summarize(run(p, PRESETS["pandemic"]["knobs"], eps=eps))
            fcf = fcf.fillna(0).cumsum()
            pre_liq = p["cash0"]
            rev_ttm = float(hist.quarters["revenue"].tail(4).sum())
            debt_raise = float(win["total_debt"].max() - p["debt0"])
            rows.append(
                {
                    "ticker": t,
                    "name": hist.name,
                    "health_base": sm_base["health_score"],
                    "health_stress": sm_stress["health_score"],
                    "p_breach_stress": sm_stress["p_breach"],
                    "realized_burn_ratio": float(max(-fcf.min(), 0.0) / max(pre_liq, 1e-9)) if len(fcf) else None,
                    "realized_debt_raise_pct_rev": debt_raise / rev_ttm * 100,
                    "realized_min_cum_fcf_pct_rev": float(fcf.min() / rev_ttm * 100) if len(fcf) else None,
                }
            )
        except Exception as e:  # keep the study going; report what failed and why
            failed[t] = f"{type(e).__name__}: {e}"
    if not rows:
        raise RuntimeError(f"cross_section: no ticker produced a row; failures: {failed}")
    df = pd.DataFrame(rows)
    stats: dict[str, dict[str, Any]] = {}
    for x in ["health_stress", "p_breach_stress"]:
        for y in ["realized_min_cum_fcf_pct_rev", "realized_debt_raise_pct_rev"]:
            d = df[[x, y]].dropna()
            if len(d) < 3:  # Spearman is undefined below three pairs
                stats[f"{x}__{y}"] = {"spearman": None, "p_value": None, "n": len(d)}
                continue
            rho, pval = spearmanr(d[x], d[y])
            stats[f"{x}__{y}"] = {"spearman": float(rho), "p_value": float(pval), "n": len(d)}
    return {"cutoff": cutoff, "rows": rows, "stats": stats, "failed": failed}
