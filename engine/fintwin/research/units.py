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
    """Family pass: one event per family and cutoff. Where several members of a family have the event at the same
    `when` (or at all, when None: a single cutoff), the largest (log_rev) keeps it and the others' labels become NaN (they leave that test, neither event
    nor survivor). Returns the frame and the number of labels removed per column."""
    if not family_pass() or df.empty or "cluster" not in df:
        return df, {}
    df = df.copy()
    size = pd.to_numeric(df["log_rev"], errors="coerce") if "log_rev" in df else pd.Series(0.0, index=df.index)
    removed = {}
    for c in cols:
        if c not in df:
            continue
        y = pd.to_numeric(df[c], errors="coerce")
        hit = df[y == 1].assign(_size=size[y == 1])
        drop = []
        for _, g in hit.groupby(["cluster", when] if when else ["cluster"]):
            if len(g) > 1:
                drop += g.sort_values("_size", ascending=False).index[1:].tolist()
        df.loc[drop, c] = np.nan
        removed[c] = len(drop)
    return df, removed
