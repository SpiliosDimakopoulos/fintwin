"""Simulation runs of REVISION_PLAN_4 (P4-1 unconditional forecasts, P4-8 real-time recession regime at 2021).

This module is outside the plan-3 shard code (nothing in the shard modules imports it), so the plan-3 stamps and
results are unchanged. It reuses the plan-3 calibration exactly: v3 with the walk-forward selection table of the
full run (FINTWIN_SPEC=v3, FINTWIN_SELECTION=<that table>), the panel's baseline draws (1,500 paths, seed 5, 12
quarters) and the transmission run's draws for the 2021 rerun. Each row stores the baseline health score, which
must equal the plan-3 panel's `base.health` of the same firm-year: the check that the reproduction is exact.

Usage (server only): python -m fintwin.research.plan4_run <i> <n> [--limit N]
Writes .cache/research/p4/<ticker>.json.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

from ..data.facts import load_company
from ..model.sd_model import simulate
from ..scenarios.presets import DEFAULT_LEVERS, PRESETS, build_scenario
from ..stochastic.mc import summarize
from ..stochastic.shocks import draw_shocks
from .experiments import (
    PANEL_ORIGINS,
    QLEVELS,
    _finite,
    _run,
    _ttm,
    calibrate,
    macro_quarterly,
    realtime_recession,
    spec_record,
    structural,
    usable,
)

N_PATHS, SEED, HORIZON, N_Q = 1500, 5, 12, 8  # the panel's baseline run (plan 4, "Data and runs")
PLAN_LEVELS = tuple(range(0, 101, 5))  # 21 quantiles 0, 0.05, ..., 1 (plan 4, P4-1)
RT_ORIGIN = "2021-02-15"  # P4-8


def _q(x: np.ndarray, levels) -> list[float]:
    return [round(float(v), 4) for v in np.percentile(x, levels)]


def unconditional(p: dict, rev_ttm: float) -> dict:
    """Baseline scenario, the simulator's own revenue: 8-quarter path totals in % of trailing revenue."""
    eps = draw_shocks(p, N_PATHS, HORIZON, seed=SEED)
    sim = _finite(simulate(p, build_scenario({}, HORIZON), eps, dict(DEFAULT_LEVERS)))
    out: dict = {"health": float(summarize(sim)["health_score"])}
    for v in ("revenue", "cfo", "fcf"):
        tot = sim[v][:, :N_Q].sum(1) / rev_ttm * 100
        out[v] = {"median": round(float(np.median(tot)), 4), "q": _q(tot, PLAN_LEVELS), "q_p3": _q(tot, QLEVELS)}
    return out


def _structural_core(st: dict) -> dict:
    """The parts of a transmission result that P4-8 compares (keeps the shard small)."""
    if not st:
        return {}
    return {k: st.get(k) for k in ("twin_cfo_tot", "twin_fcf_tot", "twin_cfo_point", "dens")}


def firm(ticker: str) -> dict:
    full = load_company(ticker)
    res: dict = {"ticker": ticker, "spec": spec_record(), "rows": [], "errors": {}}
    for origin in PANEL_ORIGINS:
        try:
            hist = load_company(ticker, asof=origin)
            if not usable(hist, origin):
                continue
            p = calibrate(hist, macro_quarterly(origin), HORIZON)
            raw = {**p, "sector_tol": 1.0}
            rev_ttm = _ttm(hist.quarters, "revenue")
            if not np.isfinite(rev_ttm) or rev_ttm <= 0:
                continue
            row: dict = {"origin": origin, "rev_ttm": rev_ttm, "u": unconditional(raw, rev_ttm)}
            if origin == RT_ORIGIN:
                rt = realtime_recession(origin)
                raw_rt = {**raw, "rec_state0": 1.0 if rt else 0.0}
                row["rt"] = {
                    "rec_state0": p.get("rec_state0"),
                    "rec_realtime": rt,
                    "base": _structural_core(structural(hist, raw, full.quarters, macro_quarterly(origin))),
                    "realtime": _structural_core(structural(hist, raw_rt, full.quarters, macro_quarterly(origin))),
                    "short8_rec": _run(raw, PRESETS["recession"]["knobs"], {}, N_PATHS, HORIZON, SEED).get("short8"),
                    "short8_rec_rt": _run(raw_rt, PRESETS["recession"]["knobs"], {}, N_PATHS, HORIZON, SEED).get(
                        "short8"
                    ),
                }
            res["rows"].append(row)
        except Exception as e:  # recorded, never silent
            res["errors"][origin] = f"{type(e).__name__}: {e}"
    return res


def main(argv: list[str]) -> None:
    from ..clean import _clean
    from .__main__ import dry_tickers, research_tickers

    i, n = int(argv[0]), int(argv[1])
    limit = int(argv[argv.index("--limit") + 1]) if "--limit" in argv else None
    keys = dry_tickers(limit) if limit is not None else research_tickers()
    out_dir = Path(".cache/research") / ("p4" if limit is None else f"p4_s{limit}")
    out_dir.mkdir(parents=True, exist_ok=True)
    for k, t in enumerate(keys):
        if k % n != i or (out_dir / f"{t}.json").exists():
            continue
        t0 = time.time()
        try:
            res = firm(t)
        except Exception as e:
            res = {"ticker": t, "rows": [], "errors": {"company": f"{type(e).__name__}: {e}"}}
        (out_dir / f"{t}.json").write_text(json.dumps(_clean(res)), encoding="utf-8")
        print(f"  {t}: {len(res['rows'])} rows, {len(res['errors'])} errors ({time.time() - t0:.0f}s)", flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
