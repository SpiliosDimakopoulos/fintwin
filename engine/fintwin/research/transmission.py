"""The transmission test: given the revenue that actually happened, does the twin know where cash goes?

The first version of this test correlated (twin - margin rule) with (realized - margin rule), with a four-quarter
margin as the rule. Referees pointed out that any predictor smoother than the rule passes that test, because margins
mean-revert and the twin's costs come from a 16-quarter regression. This module therefore compares the twin with a
ladder of simple rules that see the same realized revenue, quarter by quarter:

    N1  trailing 4-quarter cash-flow margin x revenue (the old rule)
    N2  trailing 8-quarter margin                      N3  trailing 16-quarter margin
    N4  4-quarter margin shrunk toward the industry median (weight chosen on earlier years only)
    N5  per-company regression cash = a + b * revenue (operating leverage, no simulation)
    N6  N5 plus the change in revenue (working-capital timing)
    T0  the twin without feedback loops                T1  the twin

and reports, for each: errors in levels, the incremental correlation against *each* rule (not only the weakest),
an encompassing regression, an out-of-sample hybrid (rule + lambda * (twin - rule), lambda from earlier years), and
the same by firm characteristics. Outcomes are cumulative operating or free cash flow over eight quarters, as a
percentage of trailing revenue. The same runs give liquidity decisions (cash halves, new borrowing, dividend and
capex cuts) for the twin, its loop ablations and a static runway rule with the same inputs.
"""

from __future__ import annotations

import warnings
from typing import Any

import numpy as np
import pandas as pd

from . import stats as S
from .units import unit

MODELS = ["N1", "N2", "N3", "N4", "N5", "N6", "T0", "T1"]
LABELS = {
    "N1": "Margin, 4 quarters",
    "N2": "Margin, 8 quarters",
    "N3": "Margin, 16 quarters",
    "N4": "Margin shrunk to industry",
    "N5": "Cash-revenue regression",
    "N6": "Regression + revenue change",
    "T0": "Twin without loops",
    "T1": "Twin",
}
NULLS = ["N1", "N2", "N3", "N4", "N5", "N6"]
EVENTS = ("cash_half", "debt_raise", "div_cut", "capex_cut")
ABL = ("full", "no_r1", "no_r2", "no_b1", "no_b2", "no_loops")
# the static runway rule's measure for each event, with its risk orientation
STATIC = {
    "cash_half": ("cash_min", -1),
    "debt_raise": ("fin_need", 1),
    "div_cut": ("div_pressure", 1),
    "capex_cut": ("rev4", -1),
}
LAMBDAS = np.round(np.arange(0.0, 1.51, 0.05), 2)
LAG = 3  # a cutoff year's eight-quarter outcomes are known three cutoffs later (the Y-3 rule)
MIN_TRAIN = 200  # earlier firm-years needed to choose a combination weight
# out-of-sample combinations base + lambda * (adjuster - base)
COMBOS = {
    "N1+T1": ("N1", "T1"),
    "N3+T1": ("N3", "T1"),
    "N4+T1": ("N4", "T1"),
    "N6+T1": ("N6", "T1"),
    "N1+N3": ("N1", "N3"),
    "N1+N6": ("N1", "N6"),
    "N3+N6": ("N3", "N6"),
    # combination-puzzle controls: any second, noisier estimate given a small weight
    "N3+N1": ("N3", "N1"),
    "N3+N2": ("N3", "N2"),
    "N3+N5": ("N3", "N5"),
    "N3+T0": ("N3", "T0"),
}
FORECASTERS = [*MODELS, *COMBOS]
# the pre-specified family (REVISION_PLAN_3 2.1): {twin, twin+16q, 16q+4q, regression+16q} x {OCF, FCF} x {median,
# mean absolute error}, each against the 16-quarter margin: 16 comparisons
FAMILY = ("T1", "N3+T1", "N3+N1", "N3+N5")
FAMILY_BENCH = "N3"
# combination gains reported with DM (firm x year) and the year-block bootstrap
GAINS = (
    ("N3+T1", "N3"),
    ("N3+T1", "N3+N1"),
    ("N3+T1", "N3+N2"),
    ("N3+T1", "N3+N5"),
    ("N3+T1", "N3+N6"),
    ("N3+T1", "N3+T0"),
    ("T1", "N3"),
)


# ---------------------------------------------------------------- frame
def point(st: dict, key: str) -> float:
    """The specification's 8-quarter point forecast of a structural output (`twin_cfo`, `noloops_fcf`, ...).

    `<key>_point` when the shard stores it (the median of path totals in v3, the sum of per-quarter medians in
    v2-pre); else `<key>_tot` when the shard says E1 is on; else the revision-2 sum of the per-quarter medians."""
    if st.get(f"{key}_point") is not None:
        return float(st[f"{key}_point"])
    if st.get("e1") and st.get(f"{key}_tot") is not None:
        return float(st[f"{key}_tot"])
    v = st.get(key)
    return float(np.sum(np.asarray(v, float))) if v is not None else np.nan


def sens_point(path: dict, var: str, e1: bool) -> float:
    """The same for a sensitivity variant (`cfo_tot` under E1, else the summed per-quarter medians)."""
    if e1 and path.get(f"{var}_tot") is not None:
        return float(path[f"{var}_tot"])
    return float(np.sum(np.asarray(path[var], float)))


def frame(rows: pd.DataFrame) -> pd.DataFrame:
    """One row per firm-cutoff with 8-quarter totals (and worst cumulative values) of every model, % of revenue."""
    recs = []
    for r in rows.itertuples():
        st = r.st if isinstance(r.st, dict) else {}
        if not st.get("real_cfo"):
            continue
        rev = np.asarray(st["rev"], float)
        m = st.get("m", {})
        rec = {
            "ticker": r.ticker,
            "cluster": getattr(r, "cluster", r.ticker),
            "year": getattr(r, "year", 2020),
            "industry": getattr(r, "industry", ""),
            "rev_change": float(rev.sum() / (len(rev) / 4) - 100),
        }
        for var in ("cfo", "fcf"):
            paths = {
                "real": st[f"real_{var}"],
                "N1": _mpath(m.get(f"{var}4"), rev),
                "N2": _mpath(m.get(f"{var}8"), rev),
                "N3": _mpath(m.get(f"{var}16"), rev),
                "N5": st.get(f"ols_{var}"),
                "N6": st.get(f"dyn_{var}"),
                "T0": st.get(f"noloops_{var}"),
                "T1": st.get(f"twin_{var}"),
            }
            for k, path in paths.items():
                x = np.asarray(path if path is not None else [np.nan] * len(rev), float)
                rec[f"{k}_{var}"] = float(x.sum())
                rec[f"{k}_{var}_w"] = float(np.min(np.cumsum(x)))
            # the twin's totals are the specification's point forecast; the v2 sum of medians is kept beside it
            rec[f"T1sm_{var}"] = rec[f"T1_{var}"]
            if st.get(f"twin_{var}") is not None:
                rec[f"T1_{var}"] = point(st, f"twin_{var}")
            if st.get(f"noloops_{var}") is not None:
                rec[f"T0_{var}"] = point(st, f"noloops_{var}")
            rec[f"m4_{var}"] = m.get(f"{var}4")
            rec["revsum"] = float(rev.sum())
        for k, path in (st.get("sens") or {}).items():
            rec[f"S_{k}_cfo"] = sens_point(path, "cfo", bool(st.get("e1")))
            rec[f"S_{k}_health"] = path.get("health")
            for e in EVENTS:
                rec[f"S_{k}_pb_{e}"] = (path.get("probs") or {}).get(e)
        for e in EVENTS:
            v = (st.get("events") or {}).get(e)
            rec[f"ev_{e}"] = np.nan if v is None else float(v)
            for a in ABL:
                rec[f"pb_{a}_{e}"] = ((st.get("probs") or {}).get(a) or {}).get(e)
        for k, v in (st.get("static") or {}).items():
            rec[f"st_{k}"] = v
        for c in (
            "nd_ebitda",
            "fixed_share",
            "due_cash",
            "health_t0",
            "fcf_margin",
            "z2",
            "log_rev",
            "h_base",
            "y_bk8",
            "y_burn8",
        ):
            rec[c] = getattr(r, c, np.nan)
        recs.append(rec)
    df = pd.DataFrame(recs)
    for c in df.columns:
        if c not in ("ticker", "cluster", "industry"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def loo_median(x: pd.Series) -> pd.Series:
    """Median of the other members of the group (NaN for singletons and missing values)."""
    v = x.to_numpy(float)
    ok = np.flatnonzero(np.isfinite(v))
    out = np.full(len(v), np.nan)
    n = len(ok)
    if n < 2:
        return pd.Series(out, index=x.index)
    order = ok[np.argsort(v[ok])]
    srt = v[order]
    for k, i in enumerate(order):
        rest = np.delete(srt, k)
        out[i] = 0.5 * (rest[(n - 2) // 2] + rest[(n - 1) // 2])
    return pd.Series(out, index=x.index)


def _mpath(m, rev: np.ndarray) -> np.ndarray:
    return np.full(len(rev), np.nan) if m is None else float(m) * rev


def add_shrunk(df: pd.DataFrame) -> pd.DataFrame:
    """N4: the 4-quarter margin shrunk toward the leave-one-out industry median of the same cutoff year.

    The weight on the company's own margin is chosen, for each year, to minimize the median absolute error on
    earlier years only (0.5 for the first year), so N4 never uses information from the year it predicts.
    """
    df = df.copy()
    for var in ("cfo", "fcf"):
        m = df[f"m4_{var}"]
        loo = df.groupby(["year", "industry"])[f"m4_{var}"].transform(loo_median)
        weights = np.round(np.arange(0.0, 1.01, 0.1), 1)
        pred = {w: (w * m + (1 - w) * loo) * df["revsum"] for w in weights}
        out = pd.Series(np.nan, index=df.index)
        chosen = {}
        for y in sorted(df["year"].unique()):
            past = df["year"] <= y - 3  # outcomes of later cutoffs were not yet reported
            if past.sum() >= 100:
                err = {w: np.nanmedian(np.abs(pred[w][past] - df.loc[past, f"real_{var}"])) for w in weights}
                w = min(err, key=lambda k: err[k])
            else:
                w = 0.5
            chosen[int(y)] = float(w)
            out[df["year"] == y] = pred[w][df["year"] == y]
        df[f"N4_{var}"] = out
        df.attrs[f"N4_weights_{var}"] = chosen
    return df


# ---------------------------------------------------------------- statistics
def _wins(x: np.ndarray, lo: float, hi: float) -> np.ndarray:
    return np.clip(x, lo, hi)


def levels(df: pd.DataFrame, var: str) -> dict:
    real = df[f"real_{var}"].to_numpy(float)
    lo, hi = np.nanpercentile(real, [1, 99])
    out = {}
    base = df[f"N1_{var}"].to_numpy(float)
    for k in MODELS:
        x = df[f"{k}_{var}"].to_numpy(float)
        ok = np.isfinite(x) & np.isfinite(real)
        e = np.abs(x - real)
        out[k] = {
            "label": LABELS[k],
            "n": int(ok.sum()),
            "median_ae": float(np.nanmedian(e[ok])),
            "mae_w": float(np.nanmean(np.abs(_wins(x, lo, hi) - _wins(real, lo, hi))[ok])),
            "mae": float(np.nanmean(e[ok])),  # unwinsorized
            "rho": S.rho(x, real),
            "share_closer_than_N1": float(np.nanmean((e < np.abs(base - real))[ok & np.isfinite(base)])),
        }
    if f"T1sm_{var}" in df:  # the twin as the sum of per-quarter medians (the v2-pre estimator), for comparison
        x = df[f"T1sm_{var}"].to_numpy(float)
        ok = np.isfinite(x) & np.isfinite(real)
        if ok.any():
            out["T1_sum_of_medians"] = {
                "n": int(ok.sum()),
                "median_ae": float(np.median(np.abs(x - real)[ok])),
                "mae": float(np.mean(np.abs(x - real)[ok])),
                "rho": S.rho(x, real),
            }
    return out


def incremental(df: pd.DataFrame, var: str, firms: np.ndarray, b: int) -> dict:
    """rho(model - base, realized - base) for every model and base: the old statistic, against every null."""
    real = df[f"real_{var}"].to_numpy(float)
    out: dict = {}
    key_cells = {
        ("T1", "N1"),
        ("N2", "N1"),
        ("N3", "N1"),
        ("N4", "N1"),
        ("N5", "N1"),
        ("N6", "N1"),
        ("T1", "N3"),
        ("T1", "N4"),
        ("T1", "N6"),
        ("T0", "N6"),
    }
    for base in ["N1", "N3", "N4", "N6"]:
        bx = df[f"{base}_{var}"].to_numpy(float)
        row = {}
        for k in MODELS:
            if k == base:
                continue
            x = df[f"{k}_{var}"].to_numpy(float)
            e: dict = {"rho": S.rho(x - bx, real - bx)}
            if (k, base) in key_cells:
                e["ci"] = S.ci(S.boot(S.rho, [x - bx, real - bx], firms, b=b))
            row[k] = e
        out[base] = row
    return out


def encompassing(df: pd.DataFrame, var: str) -> dict:
    """OLS of (realized - N1) on each model's departure from N1, with year effects and firm-clustered errors.

    If the twin's coefficient survives the smoother rules (N3, N4) and the timing rule (N6), its departures from the
    four-quarter rule carry information they do not.
    """
    import statsmodels.api as sm

    cols = ["T1", "N3", "N4", "N6"]
    d = df[
        [
            f"real_{var}",
            *[f"{k}_{var}" for k in ["N1", *cols]],
            "year",
            "ticker",
            *(["cluster"] if "cluster" in df else []),
        ]
    ].dropna()
    real = d[f"real_{var}"]
    lo, hi = np.nanpercentile(real, [1, 99])
    y = _wins(real, lo, hi) - _wins(d[f"N1_{var}"], lo, hi)
    X = pd.DataFrame({k: _wins(d[f"{k}_{var}"], lo, hi) - _wins(d[f"N1_{var}"], lo, hi) for k in cols})
    X = pd.concat([X, pd.get_dummies(d["year"], prefix="y", drop_first=True, dtype=float)], axis=1)
    out = {}
    for name, use in (("all", cols), ("twin_only", ["T1"]), ("nulls_only", ["N3", "N4", "N6"])):
        Xs = sm.add_constant(X[[*use, *[c for c in X if c.startswith("y_")]]])
        m = sm.OLS(y.to_numpy(float), Xs).fit(cov_type="cluster", cov_kwds={"groups": pd.factorize(unit(d))[0]})
        out[name] = {
            "coef": {k: float(m.params[k]) for k in use},
            "t": {k: float(m.tvalues[k]) for k in use},
            "p": {k: float(m.pvalues[k]) for k in use},
            "r2": float(m.rsquared),
            "n": int(m.nobs),
        }
    # the same with standard errors clustered by firm and by cutoff year (common shocks within a year)
    two_way = np.column_stack([pd.factorize(unit(d))[0], pd.factorize(d["year"])[0]])
    Xs = sm.add_constant(X[[*cols, *[c for c in X if c.startswith("y_")]]])
    m = sm.OLS(y.to_numpy(float), Xs).fit(cov_type="cluster", cov_kwds={"groups": two_way})
    out["all_two_way"] = {"t": {k: float(m.tvalues[k]) for k in cols}, "p": {k: float(m.pvalues[k]) for k in cols}}
    # Harvey, Leybourne and Newbold (1998): does forecast A encompass forecast B? d = e_A (e_A - e_B), mean > 0 rejects
    real_w = np.asarray(_wins(real, lo, hi), float)
    hln: dict = {}
    for a_, b_ in (("N3", "T1"), ("T1", "N3"), ("N6", "T1"), ("T1", "N6")):
        e_a = real_w - np.asarray(_wins(d[f"{a_}_{var}"], lo, hi), float)
        e_b = real_w - np.asarray(_wins(d[f"{b_}_{var}"], lo, hi), float)
        dd = e_a * (e_a - e_b)
        mm = sm.OLS(dd, np.ones(len(dd))).fit(cov_type="cluster", cov_kwds={"groups": two_way})
        hln[f"{a_}_encompasses_{b_}"] = {
            "t": float(mm.tvalues[0]),
            "p_one_sided": float(mm.pvalues[0] / 2) if mm.params[0] > 0 else float(1 - mm.pvalues[0] / 2),
        }
    out["hln"] = hln
    # unconstrained form (Fair and Shiller 1990): realized on every forecast in levels, so that noise in the four-quarter
    # rule cannot load on the other forecasts through a coefficient restricted to 1 - sum(b)
    lv = pd.DataFrame({k: _wins(d[f"{k}_{var}"], lo, hi) for k in ["N1", *cols]})
    lv = pd.concat([lv, X[[c for c in X if c.startswith("y_")]]], axis=1)
    for name, use in (("levels", ["N1", *cols]), ("levels_nulls_only", ["N1", "N3", "N4", "N6"])):
        Xs = sm.add_constant(lv[[*use, *[c for c in lv if c.startswith("y_")]]])
        m = sm.OLS(np.asarray(_wins(real, lo, hi), float), Xs).fit(
            cov_type="cluster", cov_kwds={"groups": pd.factorize(unit(d))[0]}
        )
        m2 = sm.OLS(np.asarray(_wins(real, lo, hi), float), Xs).fit(cov_type="cluster", cov_kwds={"groups": two_way})
        out[name] = {
            "coef": {k: float(m.params[k]) for k in use},
            "t": {k: float(m.tvalues[k]) for k in use},
            "p": {k: float(m.pvalues[k]) for k in use},
            "r2": float(m.rsquared),
            "n": int(m.nobs),
            "t_two_way": {k: float(m2.tvalues[k]) for k in use},
        }
    out |= _encompassing_v3(d, var, X, lo, hi, cols)
    return out


def _one_sided(t: float, df: int) -> float:
    from scipy.stats import t as t_dist

    return float(t_dist.sf(t, df))


def _encompassing_v3(d: pd.DataFrame, var: str, X: pd.DataFrame, lo: float, hi: float, cols: list[str]) -> dict:
    """The two-way clustered tests with t(G-1) critical values and a PSD check, beside the firm-only ones.
    Also encompassing and DM under absolute loss, the loss lambda is chosen on, and a LAD (median) regression."""
    firms, years = unit(d).to_numpy(), d["year"].to_numpy()
    real = d[f"real_{var}"].to_numpy(float)
    yfe = [c for c in X if c.startswith("y_")]
    out: dict = {}
    Xs = np.column_stack([np.ones(len(X)), X[[*cols, *yfe]].to_numpy(float)])
    yv = (_wins(real, lo, hi) - _wins(d[f"N1_{var}"].to_numpy(float), lo, hi)).astype(float)
    tw = S.cluster_ols(yv, Xs, [firms, years])
    fo = S.cluster_ols(yv, Xs, [firms])
    out["all_two_way_tG1"] = {
        "coef": {k: float(tw["params"][1 + i]) for i, k in enumerate(cols)},
        "t": {k: float(tw["t"][1 + i]) for i, k in enumerate(cols)},
        "p": {k: float(tw["p"][1 + i]) for i, k in enumerate(cols)},
        "p_firm": {k: float(fo["p"][1 + i]) for i, k in enumerate(cols)},
        "G": tw["G"],
        "t_crit": tw["t_crit"],
        "psd": tw["psd"],
    }
    rw = _wins(real, lo, hi)
    hln, absl, dm = {}, {}, {}
    for a_, b_ in (("N3", "T1"), ("T1", "N3"), ("N6", "T1"), ("T1", "N6")):
        e_a = rw - _wins(d[f"{a_}_{var}"].to_numpy(float), lo, hi)
        e_b = rw - _wins(d[f"{b_}_{var}"].to_numpy(float), lo, hi)
        r = S.two_way_mean(e_a * (e_a - e_b), firms, years)
        hln[f"{a_}_encompasses_{b_}"] = {"t": r["t"], "p_one_sided": _one_sided(r["t"], r["G"] - 1), "psd": r["psd"]}
        # absolute loss: d/dlambda E|e_a - lambda (e_a - e_b)| at 0 is -E[sign(e_a)(e_a - e_b)], so a positive mean
        # of sign(e_a)(e_a - e_b) means moving toward b lowers the MAE: a does not encompass b
        ra, rb = real - d[f"{a_}_{var}"].to_numpy(float), real - d[f"{b_}_{var}"].to_numpy(float)
        r = S.two_way_mean(np.sign(ra) * (ra - rb), firms, years)
        absl[f"{a_}_encompasses_{b_}"] = {
            "mean": r["mean"],
            "t": r["t"],
            "p_one_sided": _one_sided(r["t"], r["G"] - 1),
            "psd": r["psd"],
        }
    for a_, b_ in (("T1", "N3"), ("T1", "N6"), ("T1", "N1"), ("N6", "N3")):
        ea = np.abs(real - d[f"{a_}_{var}"].to_numpy(float))
        eb = np.abs(real - d[f"{b_}_{var}"].to_numpy(float))
        dm[f"{a_}_vs_{b_}"] = S.two_way_mean(ea - eb, firms, years)  # negative mean = a better
    out["hln_tG1"], out["abs_loss_encompassing"], out["dm_abs"] = hln, absl, dm
    out["lad_levels"] = _lad(d, var, ["N1", *cols], yfe, X)
    return out


def _lad(d: pd.DataFrame, var: str, use: list[str], yfe: list[str], X: pd.DataFrame, b: int | None = None) -> dict:
    """Median (LAD) regression of the realized outcome on every forecast in levels (Fair-Shiller form under absolute
    loss), unwinsorized; standard errors from a firm bootstrap of `b` resamples."""
    import statsmodels.api as sm

    b = S.B_LAD if b is None else b
    y = d[f"real_{var}"].to_numpy(float)
    A = np.column_stack([np.ones(len(d)), d[[f"{k}_{var}" for k in use]].to_numpy(float), X[yfe].to_numpy(float)])
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            beta = np.asarray(sm.QuantReg(y, A).fit(q=0.5, max_iter=2000).params)[1 : 1 + len(use)]
            groups = S._clusters(unit(d).to_numpy())
            g = S.rng("lad")
            bs = np.full((b, len(use)), np.nan)
            for k in range(b):
                idx = np.concatenate([groups[i] for i in g.integers(0, len(groups), len(groups))])
                bs[k] = np.asarray(sm.QuantReg(y[idx], A[idx]).fit(q=0.5, max_iter=2000).params)[1 : 1 + len(use)]
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}
    se = np.nanstd(bs, axis=0, ddof=1)
    return {
        "coef": dict(zip(use, beta.tolist(), strict=True)),
        "se_firm_boot": dict(zip(use, se.tolist(), strict=True)),
        "t": dict(zip(use, (beta / se).tolist(), strict=True)),
        "B": b,
        "n": int(len(y)),
    }


def train_bounds(real: np.ndarray, yrs: np.ndarray, mode: str = "train") -> dict[int, tuple[float, float]]:
    """Winsorization limits (1st and 99th percentiles of the realized outcome) for each cutoff year.

    "train": from the years whose outcomes were known at that cutoff (<= Y-3) only; "full": the revision-2 limits
    from every year, test years included."""
    real = np.asarray(real, float)
    years = sorted({int(y) for y in yrs})
    if mode == "full":
        lo, hi = np.nanpercentile(real, [1, 99])
        return {y: (float(lo), float(hi)) for y in years}
    out = {}
    for y in years:
        m = (yrs <= y - LAG) & np.isfinite(real)
        if m.sum() >= 20:
            lo, hi = np.percentile(real[m], [1, 99])
            out[y] = (float(lo), float(hi))
    return out


def hybrid(df: pd.DataFrame, var: str, firms: np.ndarray, b: int, bounds: str = "full") -> dict:
    """Out-of-sample combinations base + lambda * (adjuster - base), lambda chosen on earlier cutoff years.

    Evaluated on years with at least 200 earlier observations; the null hybrid (N1 adjusted by N6) is the control.
    `bounds="full"` is the revision-2 computation (winsorization limits from every year, test years included);
    `bounds="train"` takes each test year's limits from its training years only and adds unwinsorized errors.
    """
    real = df[f"real_{var}"].to_numpy(float)
    yrs = df["year"].to_numpy()
    bnd = train_bounds(real, yrs, bounds)
    preds: dict[str, np.ndarray] = {}
    lambdas: dict[str, dict[int, float]] = {}
    for name, (base, adj) in COMBOS.items():
        bx, ax = df[f"{base}_{var}"].to_numpy(float), df[f"{adj}_{var}"].to_numpy(float)
        p = np.full(len(df), np.nan)
        lambdas[name] = {}
        for y in sorted(set(yrs)):
            tr = (yrs <= y - LAG) & np.isfinite(bx) & np.isfinite(ax) & np.isfinite(real)
            if tr.sum() < MIN_TRAIN or int(y) not in bnd:
                continue
            lo, hi = bnd[int(y)]
            err = [
                np.nanmean(np.abs(_wins(bx[tr] + lam * (ax[tr] - bx[tr]), lo, hi) - _wins(real[tr], lo, hi)))
                for lam in LAMBDAS
            ]
            lam = float(LAMBDAS[int(np.argmin(err))])
            lambdas[name][int(y)] = lam
            te = yrs == y
            p[te] = bx[te] + lam * (ax[te] - bx[te])
        preds[name] = p
    test = np.isfinite(preds["N1+T1"]) & np.isfinite(real)
    for k in MODELS:
        preds[k] = df[f"{k}_{var}"].to_numpy(float)
    test &= np.all([np.isfinite(v) for v in preds.values()], axis=0)
    LO = np.array([bnd.get(int(y), (np.nan, np.nan))[0] for y in yrs])
    HI = np.array([bnd.get(int(y), (np.nan, np.nan))[1] for y in yrs])

    def mae(x, t, lo, hi):
        return float(np.mean(np.abs(_wins(x, lo, hi) - _wins(t, lo, hi))))

    out: dict = {"n": int(test.sum()), "lambda": lambdas, "mae_w": {}, "median_ae": {}}
    if bounds != "full":
        out["bounds"], out["mae"] = bounds, {}
    for k, v in preds.items():
        out["mae_w"][k] = mae(v[test], real[test], LO[test], HI[test])
        out["median_ae"][k] = float(np.median(np.abs(v[test] - real[test])))
        if bounds != "full":
            out["mae"][k] = float(np.mean(np.abs(v[test] - real[test])))
    f = firms[test]
    for a, c in (
        ("N1+T1", "N1"),
        ("N3+T1", "N3"),
        ("N3+T1", "N3+N6"),
        ("N3+T1", "N3+N1"),
        ("N3+T1", "N3+N2"),
        ("N3+T1", "N3+N5"),
        ("N3+T1", "N3+T0"),
        ("N4+T1", "N4"),
        ("N6+T1", "N6"),
        ("N1+T1", "N1+N6"),
        ("T1", "N1"),
        ("T1", "N3"),
        ("T1", "N6"),
    ):
        cols = [preds[a][test], preds[c][test], real[test], LO[test], HI[test]]
        d = S.boot(lambda u, v, t, lo, hi: mae(u, t, lo, hi) - mae(v, t, lo, hi), cols, f, b=b)
        est = mae(cols[0], *cols[2:]) - mae(*cols[1:])
        out[f"{a}_vs_{c}"] = {
            "diff": float(np.mean(d)),
            "ci": S.ci(d),
            "p": S.p_two_sided(d),
            "est": est,
            "p_centered": S.p_centered(est, d),
        }
    return out


# ---------------------------------------------------------------- resampling engine for the comparison family
# Every loss is a sum over firm x year cells, so a bootstrap resample is a vector of firm counts w (multinomial over
# firms) and of cutoff-year counts v (multinomial over years); a firm-year's weight is w_f * v_t. The combination
# weight lambda is re-chosen in every resample from the reweighted training years by one matrix product
# W (B x F) @ S (F x years*lambdas) per test year, instead of a Python loop over resamples.
def _draws(n_f: int, n_t: int, b: int, scheme: str, g: np.random.Generator):
    W = g.multinomial(n_f, np.full(n_f, 1 / n_f), size=b).astype(float) if scheme in ("firm", "firm_year") else None
    V = g.multinomial(n_t, np.full(n_t, 1 / n_t), size=b).astype(float) if scheme in ("year", "firm_year") else None
    return W, V


def _wsum(W: np.ndarray | None, M: np.ndarray, b: int) -> np.ndarray:
    """(b x ...) firm-weighted sums of the cell array M (F x ...); unit firm weights when W is None."""
    if W is None:
        return np.broadcast_to(M.sum(axis=0), (b, *M.shape[1:]))
    return (W @ M.reshape(M.shape[0], -1)).reshape(b, *M.shape[1:])


def _ysum(A: np.ndarray, V: np.ndarray | None, ny: int) -> np.ndarray:
    """Sum over the first `ny` year columns of A (b x years x ...), weighted by the year counts V."""
    A = A[:, :ny]
    if V is not None:
        A = A * V[:, :ny].reshape(V.shape[0], ny, *([1] * (A.ndim - 2)))
    return A.sum(axis=1)


def wmedian(e: np.ndarray, w: np.ndarray, o: np.ndarray | None = None) -> np.ndarray:
    """Weighted medians of the values e (n) under each row of weights w (b x n); equals np.median for unit weights.
    `o`, if given, is an argsort of e."""
    o = np.argsort(e, kind="stable") if o is None else o
    # resample weights are integer counts, exact in float32 far beyond any cumulative total here
    es, c = e[o], np.cumsum(np.atleast_2d(w)[:, o], axis=1, dtype=np.float32)
    half = c[:, -1] / 2
    out = np.full(len(c), np.nan)
    for r in np.flatnonzero(half > 0):
        lo, hi = np.searchsorted(c[r], half[r], "left"), np.searchsorted(c[r], half[r], "right")
        out[r] = 0.5 * (es[lo] + es[min(hi, len(es) - 1)])
    return out


class _Losses:
    """One outcome variable: the common test sample of the forecasters `names`, winsorization limits per test year,
    and cell sums (firm x year) of training and test losses for every lambda of every combination."""

    def __init__(self, df: pd.DataFrame, var: str, names: list[str], bounds: str, fcode, tcode, years: list[int]):
        self.names, self.F, self.T = names, int(fcode.max()) + 1, len(years)
        real = df[f"real_{var}"].to_numpy(float)
        yrs = df["year"].to_numpy()
        X = {k: df[f"{k}_{var}"].to_numpy(float) for k in MODELS}
        combos = [k for k in names if k in COMBOS]
        bnd = train_bounds(real, yrs, bounds)

        def trained(y, b_, a_):
            return (yrs <= y - LAG) & np.isfinite(X[b_]) & np.isfinite(X[a_]) & np.isfinite(real)

        test_years = [y for y in years if y in bnd and all(trained(y, *COMBOS[c]).sum() >= MIN_TRAIN for c in combos)]
        need = {m for k in names for m in (COMBOS[k] if k in COMBOS else (k,))}
        test = np.isin(yrs, test_years) & np.isfinite(real) & np.all([np.isfinite(X[m]) for m in need], axis=0)
        order = np.flatnonzero(test)
        order = order[np.argsort(yrs[order], kind="stable")]  # test rows grouped by year
        self.idx, self.test_years = order, [y for y in test_years if (yrs[order] == y).any()]
        self.fc, self.tc, self.yt = fcode[order], tcode[order], yrs[order]
        r = real[order]
        lo = np.array([bnd[int(y)][0] for y in self.yt])
        hi = np.array([bnd[int(y)][1] for y in self.yt])
        cell = self.fc * self.T + self.tc
        self.N = np.bincount(cell, minlength=self.F * self.T).reshape(self.F, self.T).astype(float)
        # plain forecasters: winsorized-error cell sums, per-row winsorized and raw absolute errors
        self.plain: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
        for k in names:
            if k not in COMBOS:
                x = X[k][order]
                ew = np.abs(np.clip(x, lo, hi) - np.clip(r, lo, hi))
                C = np.bincount(cell, weights=ew, minlength=self.F * self.T).reshape(self.F, self.T)
                self.plain[k] = (C, ew, np.abs(x - r))
        tpos = {y: i for i, y in enumerate(years)}
        nl = len(LAMBDAS)
        self.combo: dict[str, list[dict]] = {}
        for k in combos:
            bx, ax = X[COMBOS[k][0]], X[COMBOS[k][1]]
            per_year = []
            for y in self.test_years:
                lo_y, hi_y = bnd[y]
                tr = trained(y, *COMBOS[k])
                ntr = max(tpos[t] for t in years if t <= y - LAG) + 1  # training years are a prefix of `years`
                p = bx[tr][:, None] + LAMBDAS[None, :] * (ax[tr] - bx[tr])[:, None]
                L = np.abs(np.clip(p, lo_y, hi_y) - np.clip(real[tr], lo_y, hi_y)[:, None])
                c_tr = fcode[tr] * ntr + tcode[tr]
                S_ = np.stack([np.bincount(c_tr, weights=L[:, j], minlength=self.F * ntr) for j in range(nl)], 1)
                rows = np.flatnonzero(self.yt == y)
                bt, at = bx[order][rows], ax[order][rows]
                pt = bt[:, None] + LAMBDAS[None, :] * (at - bt)[:, None]
                Lt = np.abs(np.clip(pt, lo_y, hi_y) - np.clip(r[rows], lo_y, hi_y)[:, None])
                Ct = np.stack([np.bincount(self.fc[rows], weights=Lt[:, j], minlength=self.F) for j in range(nl)], 1)
                per_year.append(
                    {
                        "t": tpos[y],
                        "ntr": ntr,
                        "S": S_.reshape(self.F, ntr, nl),
                        "Ntr": np.bincount(c_tr, minlength=self.F * ntr).reshape(self.F, ntr).astype(float),
                        "Ct": Ct,
                        "Lt": Lt,
                        "E": np.abs(pt - r[rows][:, None]),
                        "Eo": np.argsort(np.abs(pt - r[rows][:, None]), axis=0, kind="stable") + rows[0],
                    }
                )
            self.combo[k] = per_year
        self.lam_point = {k: self.lambdas(k, None, None, 1)[0] for k in combos} if len(order) else {}

    def lambdas(self, k: str, W, V, b: int) -> np.ndarray:
        """(b x test years) index of the lambda chosen on the reweighted training years; a resample that leaves a
        test year no training weight keeps the point lambda."""
        out = np.empty((b, len(self.combo[k])), int)
        for j, c in enumerate(self.combo[k]):
            out[:, j] = np.argmin(_ysum(_wsum(W, c["S"], b), V, c["ntr"]), axis=1)
            if (W is not None or V is not None) and k in getattr(self, "lam_point", {}):
                dead = _ysum(_wsum(W, c["Ntr"], b), V, c["ntr"]) <= 0
                out[dead, j] = self.lam_point[k][j]
        return out

    def losses(self, W, V, b: int) -> tuple[np.ndarray, np.ndarray]:
        """(b x K) mean winsorized and median raw absolute errors of every forecaster under the weights."""
        K = len(self.names)
        mean, med = np.full((b, K), np.nan), np.full((b, K), np.nan)
        if not len(self.idx):
            return mean, med
        den = _ysum(_wsum(W, self.N, b), V, self.T)
        wf = np.ones((b, self.F), np.float32) if W is None else W.astype(np.float32)
        wt = np.ones((b, self.T), np.float32) if V is None else V.astype(np.float32)
        omega = wf[:, self.fc] * wt[:, self.tc]  # b x n weights of the test rows
        with np.errstate(invalid="ignore", divide="ignore"):
            for i, k in enumerate(self.names):
                if k in self.plain:
                    C, _, e = self.plain[k]
                    mean[:, i] = _ysum(_wsum(W, C, b), V, self.T) / den
                    med[:, i] = wmedian(e, omega)
                    continue
                lam = self.lambdas(k, W, V, b)
                num = np.zeros(b)
                for j, c in enumerate(self.combo[k]):
                    s = _wsum(W, c["Ct"], b)[np.arange(b), lam[:, j]]
                    num += s * (V[:, c["t"]] if V is not None else 1.0)
                mean[:, i] = num / den
                pats, inv = np.unique(lam, axis=0, return_inverse=True)
                inv = np.asarray(inv).reshape(-1)
                for p_i, pat in enumerate(pats):  # resamples that chose the same lambdas share one sort
                    cs = self.combo[k]
                    e = np.concatenate([c["E"][:, pat[j]] for j, c in enumerate(cs)])
                    # each year's errors are pre-sorted, so the stable sort (timsort) only merges a few runs
                    run = np.concatenate([c["Eo"][:, pat[j]] for j, c in enumerate(cs)])
                    o = run[np.argsort(e[run], kind="stable")]
                    sel = np.flatnonzero(inv == p_i)
                    med[sel, i] = wmedian(e, omega[sel], o)
        return mean, med

    def rows(self, k: str) -> tuple[np.ndarray, np.ndarray]:
        """Per test row at the point lambdas: winsorized and raw absolute error."""
        if k in self.plain:
            return self.plain[k][1], self.plain[k][2]
        lp, cs = self.lam_point[k], self.combo[k]
        return (
            np.concatenate([c["Lt"][:, lp[j]] for j, c in enumerate(cs)]),
            np.concatenate([c["E"][:, lp[j]] for j, c in enumerate(cs)]),
        )


def boot_losses(
    df: pd.DataFrame,
    names: list[str],
    b: int,
    scheme: str = "firm_year",
    seed: int | None = None,
    bounds: str = "train",
    variables: tuple[str, ...] = ("cfo", "fcf"),
    chunk: int = 500,
) -> dict:
    """Point and bootstrap losses (mean winsorized, median raw absolute error) of the forecasters `names` for each
    variable, on their common test sample, with every combination weight re-chosen inside each resample.

    `scheme`: "firm" (resample firms), "year" (resample cutoff years, the year-block bootstrap) or "firm_year" (both,
    the pigeonhole bootstrap). The variables share the same resamples, so a family across them is coherent."""
    years = sorted({int(y) for y in df["year"]})
    fcode = pd.factorize(unit(df))[0]
    tcode = np.searchsorted(years, df["year"].to_numpy().astype(int))
    data = {v: _Losses(df, v, names, bounds, fcode, tcode, years) for v in variables}
    g = np.random.default_rng(S.SEEDS["family"][0] if seed is None else seed)
    out: dict = {}
    for v, d in data.items():
        pm, pd_ = d.losses(None, None, 1)
        out[v] = {
            "names": names,
            "n": int(len(d.idx)),
            "test_years": d.test_years,
            "point_mean": pm[0],
            "point_median": pd_[0],
            "boot_mean": np.empty((b, len(names))),
            "boot_median": np.empty((b, len(names))),
            "lambda": {
                k: {y: float(LAMBDAS[li]) for y, li in zip(d.test_years, lp, strict=True)}
                for k, lp in d.lam_point.items()
            },
            "_data": d,
        }
    for start in range(0, b, chunk):
        bc = min(chunk, b - start)
        W, V = _draws(int(fcode.max()) + 1, len(years), bc, scheme, g)
        for v, d in data.items():
            mn, md = d.losses(W, V, bc)
            out[v]["boot_mean"][start : start + bc] = mn
            out[v]["boot_median"][start : start + bc] = md
    return out


def _gain(L: np.ndarray, a: int, c: int) -> np.ndarray:
    """Relative gain of forecaster a over c: 1 - loss_a / loss_c (positive = a better)."""
    with np.errstate(invalid="ignore", divide="ignore"):
        return 1 - L[..., a] / L[..., c]


def inference(df: pd.DataFrame, b: int, seed_family: int | None = None, seed_year: int | None = None) -> dict:
    """The pre-specified inference of REVISION_PLAN_3 2.1.

    family: the 16 comparisons {twin, twin+16q, 16q+4q, regression+16q} x {OCF, FCF} x {median, mean absolute error}
        against the 16-quarter margin; Romano-Wolf stepdown (studentized, two-sided) over the firm x year bootstrap,
        with Holm on the same raw p-values for continuity.
    spa: Hansen's SPA with the 16-quarter margin as benchmark, over the family's models and over every forecaster.
    mcs: model confidence set (alpha = 0.10) over every forecaster.
    gains: combination gains with lambda re-chosen in each year-block resample, firm x year DM tests (absolute and
        squared loss), year-by-year gains and the count of positive years.
    Mean errors are winsorized at limits from training years only; median errors are unwinsorized.
    """
    from .plan2 import holm

    fy = boot_losses(df, FORECASTERS, b, "firm_year", S.SEEDS["family"][0] if seed_family is None else seed_family)
    out: dict = {"B": int(b), "scheme_family": "firm_year", "bounds": "train", "family": {}, "spa": {}, "mcs": {}}
    idx = {k: i for i, k in enumerate(FORECASTERS)}
    ib = idx[FAMILY_BENCH]
    names: list[str] = []
    theta: Any = []
    star: Any = []
    for var in ("cfo", "fcf"):
        r = fy[var]
        out[f"n_{var}"], out[f"test_years_{var}"], out[f"lambda_{var}"] = r["n"], r["test_years"], r["lambda"]
        for loss in ("median", "mean"):
            P, Bs = r[f"point_{loss}"], r[f"boot_{loss}"]
            for k in FAMILY:
                names.append(f"{var}_{loss}_{k}_vs_{FAMILY_BENCH}")
                theta.append(P[idx[k]] - P[ib])
                star.append(Bs[:, idx[k]] - Bs[:, ib])
            # SPA: d = loss(benchmark) - loss(model)
            for scope, models in (("family", FAMILY), ("all", [k for k in FORECASTERS if k != FAMILY_BENCH])):
                ii = [idx[k] for k in models]
                sp = S.spa(P[ib] - P[ii], Bs[:, [ib]] - Bs[:, ii], r["n"])
                out["spa"][f"{var}_{loss}_{scope}"] = {
                    "models": list(models),
                    "t": dict(zip(models, sp["t"].tolist(), strict=True)),
                    **{k: sp[k] for k in ("stat", "p_consistent", "p_lower", "p_upper", "B")},
                }
            mc = S.mcs(P, Bs, FORECASTERS, alpha=0.10)
            out["mcs"][f"{var}_{loss}"] = mc | {"loss": dict(zip(FORECASTERS, P.tolist(), strict=True))}
    theta, star = np.array(theta), np.column_stack(star)
    rw = S.stepm(theta, star, side="two-sided")
    hp = holm({n: float(p) for n, p in zip(names, rw["p_raw"], strict=True)})
    for j, n in enumerate(names):
        out["family"][n] = {
            "diff": float(theta[j]),  # loss(model) - loss(16q margin): negative = model better
            "se": float(rw["se"][j]),
            "t": float(rw["t"][j]),
            "ci": S.ci(star[:, j]),
            "p": float(rw["p_raw"][j]),
            "p_romano_wolf": float(rw["p_adj"][j]),
            "p_holm": hp.get(n),
            "reject_05": bool(rw["p_adj"][j] <= 0.05),
            "reject_10": bool(rw["p_adj"][j] <= 0.10),
        }
    out["gains"] = _gains(df, b, fy, S.SEEDS["year_block"][0] if seed_year is None else seed_year)
    return out


def _gains(df: pd.DataFrame, b: int, fy: dict, seed: int) -> dict:
    """Combination gains with lambda re-estimated in every year-block resample, DM with firm x year clustering,
    year-by-year gains."""
    names = sorted({k for pair in GAINS for k in pair}, key=FORECASTERS.index)
    yb = boot_losses(df, names, b, "year", seed)
    idx = {k: i for i, k in enumerate(names)}
    out: dict = {}
    for var in ("cfo", "fcf"):
        r = yb[var]
        d: _Losses = r["_data"]
        firms, years = unit(df).to_numpy()[d.idx], d.yt
        res: dict = {"n": r["n"], "test_years": r["test_years"]}
        if not d.test_years:  # too little history for any combination weight (small dry runs)
            out[var] = res
            continue
        for a, c in GAINS:
            ia, ic = idx[a], idx[c]
            ew_a, e_a = d.rows(a)
            ew_c, e_c = d.rows(c)
            g = float(_gain(r["point_mean"], ia, ic))
            gs = _gain(r["boot_mean"], ia, ic)
            dg = float(r["point_mean"][ic] - r["point_mean"][ia])
            dgs = r["boot_mean"][:, ic] - r["boot_mean"][:, ia]
            per_year = {}
            for y in d.test_years:
                m = years == y
                la, lc = float(np.mean(ew_a[m])), float(np.mean(ew_c[m]))
                per_year[int(y)] = {"n": int(m.sum()), "gain": float(1 - la / lc) if lc else None}
            pos = sum(1 for v in per_year.values() if v["gain"] is not None and v["gain"] > 0)
            res[f"{a}_vs_{c}"] = {
                "gain_pct": g,  # 1 - MAE_a / MAE_c, winsorized at training-year limits
                "gain_pct_ci_year_block": S.ci(gs),
                "mae_diff": dg,  # MAE_c - MAE_a
                "p_year_block": S.p_centered(dg, dgs),
                "p_year_block_positive": float((1 + np.sum(dgs - dg >= dg)) / (np.isfinite(dgs).sum() + 1)),
                "dm_abs": S.two_way_mean(ew_c - ew_a, firms, years),
                "dm_abs_raw": S.two_way_mean(e_c - e_a, firms, years),
                "dm_sq": S.two_way_mean(ew_c**2 - ew_a**2, firms, years),
                "by_year": per_year,
                "positive_years": pos,
                "n_years": len(per_year),
            }
        # the same gains under the firm x year bootstrap of the family, for comparison
        fr = fy[var]
        fidx = {k: i for i, k in enumerate(fr["names"])}
        res["firm_year_ci"] = {f"{a}_vs_{c}": S.ci(_gain(fr["boot_mean"], fidx[a], fidx[c])) for a, c in GAINS}
        out[var] = res
    return out


def by_year(df: pd.DataFrame, var: str) -> dict:
    out = {}
    for y, g in df.groupby("year"):
        real = g[f"real_{var}"].to_numpy(float)
        cell: dict[str, float] = {"n": int(len(g))}
        for k, base in (("T1", "N1"), ("N3", "N1"), ("N4", "N1"), ("N6", "N1"), ("T1", "N6"), ("T1", "N4")):
            x, bx = g[f"{k}_{var}"].to_numpy(float), g[f"{base}_{var}"].to_numpy(float)
            cell[f"{k}|{base}"] = S.rho(x - bx, real - bx)
        for k in ("N1", "N6", "T1"):
            cell[f"mae_{k}"] = float(np.nanmedian(np.abs(g[f"{k}_{var}"] - g[f"real_{var}"])))
        out[int(y)] = cell
    return out


def heterogeneity(df: pd.DataFrame, var: str) -> dict:
    """The incremental correlation and errors in levels by firm characteristics (terciles) and revenue shock."""
    real = df[f"real_{var}"].to_numpy(float)
    groups: dict[str, pd.Series] = {}
    for c, label in (("nd_ebitda", "leverage"), ("fixed_share", "fixed_costs"), ("due_cash", "maturities")):
        x = df[c].astype(float)
        groups[label] = pd.qcut(x.rank(method="first"), 3, labels=["low", "mid", "high"])
    groups["revenue_shock"] = pd.cut(
        df["rev_change"], [-np.inf, -10, 0, 10, np.inf], labels=["fell >10%", "fell 0-10%", "rose 0-10%", "rose >10%"]
    )
    out: dict = {}
    for name, gr in groups.items():
        cells = {}
        for lev in gr.cat.categories:
            m = (gr == lev).to_numpy()
            r = real[m]
            cell: dict[str, float] = {"n": int(m.sum())}
            for k, base in (("T1", "N1"), ("T1", "N6"), ("N3", "N1"), ("N6", "N1")):
                x, bx = df[f"{k}_{var}"].to_numpy(float)[m], df[f"{base}_{var}"].to_numpy(float)[m]
                cell[f"{k}|{base}"] = S.rho(x - bx, r - bx)
            for k in ("N1", "N6", "T1"):
                cell[f"mae_{k}"] = float(np.nanmedian(np.abs(df[f"{k}_{var}"].to_numpy(float)[m] - r)))
            cells[str(lev)] = cell
        out[name] = cells
    return out


def decisions(df: pd.DataFrame, firms: np.ndarray, b: int) -> dict:
    """AUC of the twin's event probabilities (and of each loop ablation) against a static runway rule with the
    same inputs, an opening-balance-sheet score and the FCF margin, plus out-of-sample combined logits."""
    out: dict = {}
    for e in EVENTS:
        y = df[f"ev_{e}"].to_numpy(float)
        m = np.isfinite(y)
        if m.sum() < 200 or np.nansum(y) < 20:
            continue
        col, sign = STATIC[e]
        preds = {
            "twin": df[f"pb_full_{e}"].to_numpy(float),
            "static": sign * df[f"st_{col}"].to_numpy(float),
            "formula": -df["health_t0"].to_numpy(float),
            "fcf_margin": -df["fcf_margin"].to_numpy(float),
        }
        for a in ABL[1:]:
            preds[a] = df[f"pb_{a}_{e}"].to_numpy(float)
        res: dict = {"n": int(m.sum()), "events": int(np.nansum(y)), "base_rate": float(np.nanmean(y)), "auc": {}}
        for k, x in preds.items():
            sel = m & np.isfinite(x)
            res["auc"][k] = S.auc(x[sel], y[sel])
        res["auc_ci_twin"] = S.ci(S.boot(S.auc, [preds["twin"][m], y[m]], firms[m], b=b))
        res["twin_minus"] = {
            k: S.paired(S.auc, preds["twin"], preds[k], y, firms, b)
            for k in ("static", "formula", "fcf_margin", *ABL[1:])
        }
        res["oos"] = _oos_events(df, preds, y, firms, b)
        out[e] = res
    return out


def _oos_events(df: pd.DataFrame, preds: dict, y: np.ndarray, firms: np.ndarray, b: int) -> dict:
    """Walk-forward logits: static rule + score + FCF margin, with and without the twin (train on years <= Y-3)."""
    import statsmodels.api as sm

    yrs = df["year"].to_numpy()
    # percentile ranks within each cutoff year: the cross-section an analyst would have seen on that day
    X = pd.DataFrame({k: _pct_by(preds[k], yrs) for k in ("static", "formula", "fcf_margin", "twin")}).fillna(0.5)
    P: dict[str, list[np.ndarray]] = {"rule_score": [], "rule_score_twin": []}
    ys, fs = [], []
    for yr in sorted(set(yrs)):
        tr, te = (yrs <= yr - 3) & np.isfinite(y), (yrs == yr) & np.isfinite(y)
        if tr.sum() < 300 or te.sum() < 30 or y[tr].sum() < 10:
            continue
        for key, cols in (
            ("rule_score", ["static", "formula", "fcf_margin"]),
            ("rule_score_twin", ["static", "formula", "fcf_margin", "twin"]),
        ):
            use = [c for c in cols if X.loc[tr, c].std() > 0]
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                fit = sm.GLM(
                    y[tr], sm.add_constant(X.loc[tr, use], has_constant="add"), family=sm.families.Binomial()
                ).fit_regularized(alpha=0.001, L1_wt=0.0)
            P[key].append(np.asarray(fit.predict(sm.add_constant(X.loc[te, use], has_constant="add"))))
        ys.append(y[te])
        fs.append(firms[te])
    if not ys:
        return {}
    yy, ff = np.concatenate(ys), np.concatenate(fs)
    P2 = {k: np.concatenate(v) for k, v in P.items()}
    return {
        "n": int(len(yy)),
        "auc": {k: S.auc(v, yy) for k, v in P2.items()},
        "delta_twin": S.paired(S.auc, P2["rule_score_twin"], P2["rule_score"], yy, ff, b),
    }


def _pct_by(x: np.ndarray, groups: np.ndarray) -> np.ndarray:
    out = np.full(len(x), np.nan)
    for g in set(groups):
        m = groups == g
        out[m] = S.pct(x[m])
    return out


def sensitivity(df: pd.DataFrame, firms: np.ndarray, b: int) -> dict:
    """Each judgement call varied in turn: transmission (incremental rho against N1 and N6, errors in levels) and
    the baseline verdict (AUC for bankruptcy and for severe cash burn over eight quarters)."""
    names = sorted({c.split("_", 1)[1].rsplit("_cfo", 1)[0] for c in df if c.startswith("S_") and c.endswith("_cfo")})
    real = df["real_cfo"].to_numpy(float)
    bk = df["y_bk8"].to_numpy(float)
    burn = (df["y_burn8"].to_numpy(float) < -10).astype(float)
    burn[~np.isfinite(df["y_burn8"].to_numpy(float))] = np.nan
    out: dict = {}

    def row(x: np.ndarray, h: np.ndarray) -> dict:
        r: dict = {"median_ae": float(np.nanmedian(np.abs(x - real)))}
        for base in ("N1", "N6"):
            bx = df[f"{base}_cfo"].to_numpy(float)
            r[f"incr_{base}"] = S.rho(x - bx, real - bx)
        r["auc_bk"] = S.auc(-h, bk)
        r["auc_burn"] = S.auc(-h, burn)
        return r

    out["baseline"] = row(df["T1_cfo"].to_numpy(float), df["h_base"].to_numpy(float))
    for n in names:
        out[n] = row(df[f"S_{n}_cfo"].to_numpy(float), df[f"S_{n}_health"].to_numpy(float))
    return out


def section(rows: pd.DataFrame, b: int, panel: bool = True, b_family: int | None = None) -> dict:
    """`b_family`: bootstrap size of the pre-specified comparison family (default stats.B_FAMILY); panel only."""
    df = add_shrunk(frame(rows))
    if df.empty:
        return {}
    firms = unit(df).to_numpy()
    out: dict = {
        "n": int(len(df)),
        "n_firms": int(df["ticker"].nunique()),
        "n4_weights": {v: df.attrs.get(f"N4_weights_{v}") for v in ("cfo", "fcf")},
    }
    for var in ("cfo", "fcf"):
        e: dict = {"levels": levels(df, var), "incremental": incremental(df, var, firms, b)}
        e["worst_cumulative"] = {
            k: S.rho(
                df[f"{k}_{var}_w"].to_numpy(float) - df[f"N1_{var}_w"].to_numpy(float),
                df[f"real_{var}_w"].to_numpy(float) - df[f"N1_{var}_w"].to_numpy(float),
            )
            for k in MODELS[1:]
            if k != "N4"  # the shrunk margin is built from totals only
        }
        down = (df["rev_change"] < -10).to_numpy()
        e["revenue_down_10pct"] = (
            {
                "n": int(down.sum()),
                "levels": levels(df[down].reset_index(drop=True), var),
                "incremental": incremental(df[down].reset_index(drop=True), var, firms[down], max(b // 2, 50)),
            }
            if down.sum() >= 30
            else {"n": int(down.sum())}
        )
        if panel:
            e["encompassing"] = encompassing(df, var)
            e["hybrid"] = hybrid(df, var, firms, b)  # revision 2: winsorization limits from all years
            e["hybrid_train"] = hybrid(df, var, firms, b, bounds="train")
            e["by_year"] = by_year(df, var)
            e["heterogeneity"] = heterogeneity(df, var)
        out[var] = e
    if panel:
        out["inference"] = inference(df, S.B_FAMILY if b_family is None else int(b_family))
        out["decisions"] = decisions(df, firms, b)
        out["sensitivity"] = sensitivity(df, firms, b)
        inc = out["cfo"]["incremental"]
        best_null = max(("N3", "N4", "N6"), key=lambda k: inc["N1"][k]["rho"])
        twin_vs_best = inc[best_null]["T1"]
        out["verdict"] = {
            # the decision rule written down before the run (docs/REVISION_PLAN.md, 2.6)
            "twin_vs_N1": inc["N1"]["T1"]["rho"],
            "best_null": best_null,
            "best_null_vs_N1": inc["N1"][best_null]["rho"],
            "null_share_of_twin": inc["N1"][best_null]["rho"] / inc["N1"]["T1"]["rho"]
            if inc["N1"]["T1"]["rho"]
            else None,
            "twin_vs_best_null": twin_vs_best["rho"],
            "twin_vs_best_null_ci": twin_vs_best.get("ci"),
            "encompassing_p_twin": out["cfo"]["encompassing"]["all"]["p"]["T1"],
            # the same coefficient with firm x year clustering and t(G-1) critical values
            "encompassing_p_twin_two_way_tG1": out["cfo"]["encompassing"]["all_two_way_tG1"]["p"]["T1"],
        }
        v = out["verdict"]
        v["twin_vs_each_null_ci_low"] = {k: (inc[k]["T1"].get("ci") or [np.nan])[0] for k in ("N3", "N4", "N6")}
        v["transmission_claim_survives"] = bool(
            all(np.isfinite(x) and x > 0 for x in v["twin_vs_each_null_ci_low"].values())
            and v["encompassing_p_twin"] < 0.05
        )
    return out
