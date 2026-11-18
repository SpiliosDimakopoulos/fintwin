"""REVISION_PLAN_5 P1: walk-forward pooled priors for the calibration's structural parameters.

The table is built from the panel rows of a first pass that records `pool_inputs` (v4b): for test year Y, the prior of
industry j is the median of the firm estimates of j at cutoffs <= Y-3, with s.d. = IQR / 1.349; industries with fewer
than MIN_INDUSTRY firm-years use the all-firm prior. `FINTWIN_POOL` points the calibration at the table.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

LAG = 3
MIN_INDUSTRY = 30


def _prior(x: np.ndarray) -> dict | None:
    x = x[np.isfinite(x)]
    if len(x) < 2:
        return None
    q1, q3 = np.percentile(x, [25, 75])
    return {"m": float(np.median(x)), "s": float((q3 - q1) / 1.349), "n": int(len(x))}


def pool_table(rows: list[dict], years: list[int] | None = None) -> dict:
    """rows: dicts with origin (cutoff date string), industry, pool_inputs {param: [value, se]}."""
    recs = [r for r in rows if r.get("pool_inputs")]
    yr = np.array([int(str(r["origin"])[:4]) for r in recs])
    ind = np.array([r.get("industry") or "_all" for r in recs])
    params = sorted({k for r in recs for k in r["pool_inputs"]})
    def num(x) -> float:
        return float(x) if x is not None else np.nan  # `_clean` writes NaN as null

    vals = {k: np.array([num((r["pool_inputs"].get(k) or [None])[0]) for r in recs]) for k in params}
    out: dict = {"rule": f"Y-{LAG}", "min_industry": MIN_INDUSTRY, "n_rows": len(recs), "prior": {}}
    for y in sorted(set(years or yr.tolist())):
        past = yr <= y - LAG
        if not past.any():
            continue
        by: dict = {}
        for k in params:
            allp = _prior(vals[k][past])
            if allp is None:
                continue
            by.setdefault("_all", {})[k] = allp
            for j in set(ind[past].tolist()):
                m = past & (ind == j)
                pj = _prior(vals[k][m]) if m.sum() >= MIN_INDUSTRY else None
                by.setdefault(j, {})[k] = pj or allp
        out["prior"][str(y)] = by
    return out


def prior_for(table: dict, asof: str, industry: str) -> dict:
    """The pooled prior {param: {m, s}} for a cutoff and industry ({} before the first year with history)."""
    by = (table.get("prior") or {}).get(str(asof)[:4]) or {}
    return dict(by.get(industry) or by.get("_all") or {})


def write(table: dict, path: Path) -> None:
    path.write_text(json.dumps(table, indent=1, sort_keys=True), encoding="utf-8")
