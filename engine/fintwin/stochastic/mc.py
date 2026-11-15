"""Monte Carlo driver: shocks -> model -> distribution summaries."""

from __future__ import annotations

import numpy as np

from ..model.ratings import INVESTMENT_GRADE_MIN_RANK, RATINGS
from ..model.sd_model import simulate
from ..scenarios.presets import DEFAULT_LEVERS, build_scenario
from .shocks import draw_shocks

BANDS = [5, 25, 50, 75, 95]
BAND_VARS = ["revenue", "ebitda", "fcf", "cash", "liquidity", "debt", "icr", "nd_ebitda", "health", "zscore"]


def run(
    p: dict,
    knobs: dict | None = None,
    levers: dict | None = None,
    n_paths: int = 5000,
    seed: int = 7,
    eps: np.ndarray | None = None,
) -> dict:
    T = p["horizon"]
    scn = build_scenario(knobs or {}, T)
    lev = {**DEFAULT_LEVERS, **(levers or {})}
    if eps is None:
        eps = draw_shocks(p, n_paths, T, seed)
    return simulate_paths(p, scn, eps, lev)


def simulate_paths(p: dict, scn: dict, eps: np.ndarray, levers: dict) -> dict:
    """`simulate`, with parameter uncertainty when calibration attached `_param_draws` (MM-F9).

    Paths are split into contiguous blocks, one parameter vector each; the shocks are unchanged, so with the same eps
    the only difference from `simulate` is the parameters. Without draws this is exactly `simulate`.
    """
    draws = p.get("_param_draws")
    if not draws:
        return simulate(p, scn, eps, levers)
    blocks = np.array_split(np.arange(eps.shape[0]), min(len(draws), eps.shape[0]))
    outs = [simulate({**p, **draws[i]}, scn, eps[b], levers) for i, b in enumerate(blocks)]
    return {k: np.concatenate([o[k] for o in outs], axis=0) for k in outs[0]}


def summarize(out: dict) -> dict:
    T = out["cash"].shape[1]
    bands = {k: np.percentile(out[k], BANDS, axis=0).round(4).tolist() for k in BAND_VARS}
    breach_by_q = out["breach"].mean(0)
    final_rating = out["rating"][:, -1].astype(int)
    rating_dist = np.bincount(final_rating, minlength=len(RATINGS)) / len(final_rating)
    health_path_mean = out["health"].mean(1)
    min_liq = out["liquidity"].min(1)
    # quarter index of the first breach: 0 is the first simulated quarter (as runway and first_covenant_breach)
    first_breach = np.where(out["breach"].any(1), out["breach"].argmax(1), -1)
    return {
        "bands": bands,
        "p_breach_by_q": breach_by_q.round(4).tolist(),
        "p_breach": float(breach_by_q[-1]),
        "p_icr_below_1_5": float((out["icr"].min(1) < 1.5).mean()),
        "p_downgrade_below_ig": float((out["rating"][:, -1] < INVESTMENT_GRADE_MIN_RANK).mean()),
        "rating_dist": rating_dist.round(4).tolist(),
        "health_score": float(np.median(health_path_mean)),
        "health_p10": float(np.percentile(health_path_mean, 10)),
        "min_liquidity_bands": np.percentile(min_liq, BANDS).tolist(),
        "median_quarters_to_breach": float(np.median(first_breach[first_breach >= 0]))
        if (first_breach >= 0).any()
        else None,
        "equity_needed_median": float(np.median(out["issued"].sum(1))),
        # mean component scores (paths x quarters) for the health waterfall; health_mean is their weighted
        # sum, minus the cap applied to paths that ran out of cash
        "components": {k: float(out[f"h_{k}"].mean()) for k in ("liq", "cov", "lev", "solv")},
        "health_mean": float(out["health"].mean()),
        "horizon": T,
    }
