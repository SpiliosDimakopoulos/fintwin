"""The resampling unit of the statistics: the firm (ticker) by default, the corporate family in the robustness pass
(FINTWIN_FAMILIES = path of the CIK -> family JSON written by `python -m fintwin.research families`; WP6, a reader
Blanco). A leaf module, so every analysis module can use it without import cycles."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd


@lru_cache(maxsize=2)
def _families(path: str) -> dict[int, int]:
    return {int(k): int(v) for k, v in json.loads(Path(path).read_text(encoding="utf-8")).items()}


def family_pass() -> bool:
    return bool(os.environ.get("FINTWIN_FAMILIES"))


def cluster_of(ticker: str, cik) -> str:
    """The unit of one firm: its ticker, or in the family pass its family (the smallest CIK of the group)."""
    path = os.environ.get("FINTWIN_FAMILIES")
    if not path or cik is None or (isinstance(cik, float) and np.isnan(cik)):
        return str(ticker)
    fam = _families(path).get(int(cik))
    return f"F{fam:010d}" if fam is not None else str(ticker)


def unit(df: pd.DataFrame) -> pd.Series:
    """The resampling / clustering unit of each row."""
    return df["cluster"] if "cluster" in df else df["ticker"]


def dedupe_events(df: pd.DataFrame, cols: list[str], when: str | None) -> tuple[pd.DataFrame, dict]:
    """Family pass: one event per family and cutoff (`when`; None: one cutoff). In a family-cutoff where any member
    has an event in any of `cols`, one member stands for the family (the largest by log_rev among those with an
    event, ties by ticker) with the family's labels (the maximum over members per column), and every other member's
    labels become NaN: neither a second event nor a survivor
    of a group that failed (round 2: per-column choices could keep different members; siblings stayed survivors).
    Returns the frame and the number of labels set to NaN per column."""
    cols = [c for c in cols if c in df]
    if not family_pass() or df.empty or "cluster" not in df or not cols:
        return df, {}
    df = df.copy()
    ev = df[cols].apply(pd.to_numeric, errors="coerce").eq(1).any(axis=1)
    size = pd.to_numeric(df["log_rev"], errors="coerce") if "log_rev" in df else pd.Series(0.0, index=df.index)
    keys = ["cluster", when] if when else ["cluster"]
    drop: list = []
    for _, g in df.groupby(keys, sort=True):
        if len(g) < 2 or not ev[g.index].any():
            continue
        hit = g[ev[g.index]].assign(_s=size[g.index][ev[g.index]].fillna(-np.inf))
        keep = hit.sort_values(["_s", "ticker"], ascending=[False, True], kind="mergesort").index[0]
        # the kept row carries the family's labels: an event of any member in any column (round 3: the kept member's
        # 0 or NaN replaced a sibling's 1, a false survivor)
        fam = g[cols].apply(pd.to_numeric, errors="coerce").max(axis=0, skipna=True)
        df.loc[keep, cols] = fam.to_numpy()
        drop += [i for i in g.index if i != keep]
    removed = {c: int(df.loc[drop, c].notna().sum()) for c in cols}
    df.loc[drop, cols] = np.nan
    return df, removed
