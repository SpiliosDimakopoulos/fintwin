"""Non-accounting rivals of the twin (a reader, 12-11-2026 reply), exploratory and declared after the
pre-specification (docs/review_2026-10/RERUN5_PLAN.md, WP6).

At each cutoff, from the firm's own EDGAR filing record with filing date <= cutoff only:
- age: years since its first filing of any form (left-censored at the start of EDGAR, ~1993-1996);
- amendments: 10-K/A and 10-Q/A filed in the three years before the cutoff;
- non-reliance: an 8-K with Item 4.02 (previously issued statements should no longer be relied upon), three years;
- late filing: an NT 10-K or NT 10-Q in the two years before the cutoff.
And the industry's bankruptcy base rate: the share of firm-years of its SIC-2 industry with a petition within eight
quarters, from cutoffs at least three years earlier (their outcome windows had closed and been filed), shrunk to the
overall rate of the same years (beta prior with PRIOR_N pseudo firm-years).

Rivals, out of sample by test year exactly as the panel's logits (train on cutoffs <= Y-3): the non-accounting set
alone, the accounting benchmarks plus it, and both with the twin; AUC differences with the firm bootstrap; Holm
within this family only, apart from every confirmatory test.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import stats as S

PRIOR_N = 50.0  # pseudo firm-years of the overall rate in the industry base rate
NONACC = ["age", "amend_3y", "nonreliance_3y", "late_2y", "ind_base_rate"]


def filing_features(filings: pd.DataFrame, origin: str) -> dict:
    """The four filing-record features at `origin`, from filings dated on or before it."""
    o = pd.Timestamp(origin)
    f = filings[pd.to_datetime(filings["filingDate"]) <= o]
    if f.empty:
        return {"age": np.nan, "amend_3y": np.nan, "nonreliance_3y": np.nan, "late_2y": np.nan}
    d = pd.to_datetime(f["filingDate"])
    y3, y2 = d > o - pd.DateOffset(years=3), d > o - pd.DateOffset(years=2)
    items = f["items"].fillna("").astype(str) if "items" in f else pd.Series("", index=f.index)
    return {
        "age": float((o - d.min()).days / 365.25),
        "amend_3y": float((y3 & f["form"].isin(["10-K/A", "10-Q/A", "10-K405/A", "10-KT/A"])).sum()),
        "nonreliance_3y": float(
            (y3 & f["form"].isin(["8-K", "8-K/A"]) & items.str.contains(r"(?<![\d.])4\.02(?!\d)")).any()
        ),
        "late_2y": float(
            (y2 & f["form"].isin(["NT 10-K", "NT 10-Q", "NT 10-K/A", "NT 10-Q/A", "NTN 10K", "NTN 10Q"])).any()
        ),
    }


def add_filing_features(p: pd.DataFrame) -> pd.DataFrame:
    """The panel with the filing-record features of each firm-year (snapshot submissions; NaN if unavailable)."""
    from ..data.edgar_universe import submissions

    cols = {k: np.full(len(p), np.nan) for k in ("age", "amend_3y", "nonreliance_3y", "late_2y")}
    origin = p["origin"].astype(str) if "origin" in p else p["year"].astype(int).astype(str) + "-02-15"
    for cik, idx in p.groupby("cik").indices.items():
        try:
            f = submissions(int(cik))["filings"][["filingDate", "form", "items"]]
        except Exception:  # noqa: BLE001 - no record: the features stay missing (the logit flags them)
            continue
        for i in idx:
            for k, v in filing_features(f, origin.iloc[i]).items():
                cols[k][i] = v
    return p.assign(**cols)


def industry_base_rate(years: np.ndarray, groups: np.ndarray, y: np.ndarray, lag: int = 3) -> np.ndarray:
    """For each firm-year of year Y: (events + PRIOR_N * overall) / (n + PRIOR_N) over its industry's firm-years of
    years <= Y - lag; the overall rate from the same years. NaN where no earlier year exists."""
    years, groups, y = np.asarray(years), np.asarray(groups, object), np.asarray(y, float)
    out = np.full(len(y), np.nan)
    for yr in np.unique(years):
        past = (years <= yr - lag) & np.isfinite(y)
        if not past.any():
            continue
        overall = float(y[past].mean())
        here = years == yr
        for g in pd.unique(groups[here]):
            m = past & (groups == g)
            out[here & (groups == g)] = (y[m].sum() + PRIOR_N * overall) / (m.sum() + PRIOR_N)
    return out


def section(p: pd.DataFrame, b: int = S.B_PANEL) -> dict:
    """Exploratory: do non-accounting rivals rank bankruptcies as well as the twin, and does the twin add to them?"""
    from .distress import _sic2

    y = S._col(p, "y_bk8").to_numpy(float)
    m = np.isfinite(y)
    if m.sum() < 300 or np.nansum(y) < 10:
        return {"skipped": "too few firm-years or events"}
    p = add_filing_features(p.reset_index(drop=True))
    sic = _sic2(p["cik"]).to_numpy()
    groups = np.where(np.isfinite(sic), sic, -1).astype(int).astype(str)
    p["ind_base_rate"] = industry_base_rate(p["year"].to_numpy(), groups, y)
    bench = list(S.BENCH)
    models = {
        "nonacc": NONACC,
        "benchmarks": bench,
        "benchmarks_nonacc": [*bench, *NONACC],
        "benchmarks_nonacc_twin": [*bench, *NONACC, "twin"],
        "twin_only": ["twin"],
    }
    preds: dict[str, list] = {k: [] for k in models}
    ys, fs, test_years = [], [], []
    for yr in sorted(p["year"].unique()):
        tr = (p["year"] <= yr - 3).to_numpy() & m
        te = (p["year"] == yr).to_numpy() & m
        if tr.sum() < 300 or te.sum() < 30 or np.nansum(y[tr]) < 10:
            continue
        for k, cols in models.items():
            preds[k].append(S._fit_predict(p[tr], p[te], y[tr], cols))
        ys.append(y[te])
        fs.append(p["ticker"].to_numpy()[te])
        test_years.append(int(yr))
    if not ys:
        return {"skipped": "no test year with enough training data"}
    yy, ff = np.concatenate(ys), np.concatenate(fs)
    P = {k: np.concatenate(v) for k, v in preds.items()}
    out: dict = {
        "status": "exploratory, declared after the pre-specification (RERUN5_PLAN WP6); not part of any confirmatory test",
        "features": {"nonacc": NONACC, "prior_n": PRIOR_N},
        "coverage": {k: float(np.isfinite(p[k].to_numpy(float)).mean()) for k in NONACC},
        "test_years": test_years,
        "n_test": int(len(yy)),
        "events": int(yy.sum()),
        "auc": {k: S.auc(v, yy) for k, v in P.items()},
        "comparisons": {
            "twin_vs_nonacc": S.paired(S.auc, P["twin_only"], P["nonacc"], yy, ff, b),
            "nonacc_beyond_benchmarks": S.paired(S.auc, P["benchmarks_nonacc"], P["benchmarks"], yy, ff, b),
            "twin_beyond_benchmarks_nonacc": S.paired(
                S.auc, P["benchmarks_nonacc_twin"], P["benchmarks_nonacc"], yy, ff, b
            ),
        },
    }
    ps = {k: v.get("p") for k, v in out["comparisons"].items() if isinstance(v, dict) and v.get("p") is not None}
    out["holm"] = _holm(ps)
    return out


def _holm(p: dict[str, float]) -> dict[str, float]:
    order = sorted(p, key=p.get)
    adj, run = {}, 0.0
    for i, k in enumerate(order):
        run = max(run, min(1.0, (len(order) - i) * p[k]))
        adj[k] = run
    return adj
