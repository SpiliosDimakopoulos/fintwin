"""The confirmatory test v3 against v2-pre (docs/REVISION_PLAN_3.md, "Νέο επιβεβαιωτικό τεστ"; criterion of §2.1).

Statistic: median|e(v3)| - median|e(v2-pre)| of the twin's 8-quarter CFO error (% of revenue), on the intersection of
the firm-years that have an error in both specifications, every year; a continuity line on 2018-2024. Reported beside
it: the firm-years each side loses, whether the losses differ by more than 1 percentage point, and each spec's median
on its own set. Decision: t(G-1) interval on the yearly differences of the medians; success if its 95% upper bound is
below 0. Alongside: a year-block bootstrap (B = 2,000) of the pooled statistic and a Diebold-Mariano test of the mean
difference with firm x year clustering. One uncorrected test, outside the family of 16.

Each specification's `stats` run writes its firm-year errors (`cfo_errors_frame`) after the stamp check, and this
module only compares those files, so it never reads shards of another stamp.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import t as student_t

from . import stats as S

B_YEAR_BLOCK = 2000
CONTINUITY = (2018, 2024)


def cfo_errors_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Firm-year absolute CFO errors of the twin from a `transmission.frame` (one row per firm-cutoff)."""
    if df.empty or "T1_cfo" not in df:
        return pd.DataFrame(columns=["ticker", "year", "abs_e"])
    e = (df["T1_cfo"].astype(float) - df["real_cfo"].astype(float)).abs()
    out = pd.DataFrame({"ticker": df["ticker"].astype(str), "year": df["year"].astype(int), "abs_e": e})
    return out[np.isfinite(out["abs_e"])].drop_duplicates(["ticker", "year"]).reset_index(drop=True)


def _t_interval(d: np.ndarray, level: float = 0.95) -> dict:
    d = d[np.isfinite(d)]
    g = len(d)
    if g < 2:
        return {"G": g, "mean": float(d.mean()) if g else None, "ci": [None, None]}
    m, se = float(d.mean()), float(d.std(ddof=1) / np.sqrt(g))
    q = float(student_t.ppf(0.5 + level / 2, g - 1))
    return {"G": g, "mean": m, "se": se, "ci": [m - q * se, m + q * se]}


def _pooled(c: pd.DataFrame) -> float:
    return float(np.median(c["abs_e_a"]) - np.median(c["abs_e_b"]))


def _year_block(c: pd.DataFrame, b: int, seed: int) -> dict:
    g = np.random.default_rng(seed)
    years = np.array(sorted(c["year"].unique()))
    rows = {y: np.flatnonzero(c["year"].to_numpy() == y) for y in years}
    a, bb = c["abs_e_a"].to_numpy(float), c["abs_e_b"].to_numpy(float)
    out = np.empty(b)
    for k in range(b):
        idx = np.concatenate([rows[y] for y in g.choice(years, len(years))])
        out[k] = np.median(a[idx]) - np.median(bb[idx])
    return {"blocks": int(len(years)), "b": b, "ci": S.ci(out)}


def compare(
    a: pd.DataFrame, b: pd.DataFrame, names: tuple[str, str] = ("v3", "v2-pre"), boot: int = B_YEAR_BLOCK
) -> dict:
    """`a`, `b`: `cfo_errors_frame` of the two specifications (a is the candidate, b the reference)."""
    ka = set(zip(a["ticker"], a["year"], strict=True))
    kb = set(zip(b["ticker"], b["year"], strict=True))
    c = a.merge(b, on=["ticker", "year"], suffixes=("_a", "_b"))
    lost_a, lost_b = len(kb - ka), len(ka - kb)  # firm-years with an error in one spec only
    union = len(ka | kb)
    out: dict = {
        "specs": {"candidate": names[0], "reference": names[1]},
        "n_common": int(len(c)),
        "n_own": {names[0]: len(ka), names[1]: len(kb)},
        "lost": {names[0]: lost_a, names[1]: lost_b},
        "lost_share": {names[0]: lost_a / union if union else None, names[1]: lost_b / union if union else None},
        "median_own": {
            names[0]: float(a["abs_e"].median()) if len(a) else None,
            names[1]: float(b["abs_e"].median()) if len(b) else None,
        },
    }
    out["losses_differ_gt_1pp"] = bool(union and abs(lost_a - lost_b) / union > 0.01)
    if len(c) < 30:
        out["skipped"] = "fewer than 30 common firm-years"
        return out
    yearly = c.groupby("year").apply(lambda g: float(np.median(g["abs_e_a"]) - np.median(g["abs_e_b"])))
    out["statistic"] = _pooled(c)
    out["yearly"] = {int(y): v for y, v in yearly.items()}
    out["years_negative"] = int((yearly < 0).sum())
    lo, hi = CONTINUITY
    cc = c[c["year"].between(lo, hi)]
    out["continuity"] = {"years": [lo, hi], "n": int(len(cc)), "statistic": _pooled(cc) if len(cc) else None}
    out["decision"] = _t_interval(yearly.to_numpy(float))
    up = out["decision"]["ci"][1]
    out["success"] = bool(up is not None and up < 0)
    out["year_block"] = _year_block(c, boot, S.SEEDS["cross_spec"][0])
    out["dm"] = S.two_way_mean(
        (c["abs_e_a"] - c["abs_e_b"]).to_numpy(float), c["ticker"].to_numpy(), c["year"].to_numpy()
    )
    return out
