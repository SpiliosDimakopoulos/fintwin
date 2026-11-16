"""Statistics of REVISION_PLAN_4 (P4-1 ... P4-9) on the plan-3 shards and the P4 simulation shards.

Runs under the analysis code of the plan-3 run (commit 77f3b7f) on a server with the frozen snapshot:
    FINTWIN_FROZEN=1 FINTWIN_SPEC=v3 python -m fintwin.research.plan4 <cache root> <out.json>
<cache root> holds research/{v3-wf,v3,v2-pre,v2-rev,p4}. Every test of the plan is computed and written, whatever
its result.
"""

from __future__ import annotations

import itertools
import json
import os
import sys
from multiprocessing import Pool
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats as sps

from . import distress as D
from . import plan2 as P2
from . import stats as S
from . import transmission as T
from .experiments import QLEVELS
from .units import unit

TEST_YEARS = list(range(2017, 2025))
LAG = 3
B = 2000
B_WILD = 9999
W_GRID = np.round(np.arange(0.0, 1.0001, 0.05), 2)
PLAN_LEVELS = np.arange(0, 101, 5) / 100.0
P3_LEVELS = np.asarray(QLEVELS, float) / 100.0
MIN_TR, MIN_TR_ML, MIN_ENC = 200, 500, 30  # fewest training firm-years for a rival / for ML1
SEED = {"p41": 41, "p42": 42, "p43": 43, "p44": 44, "p45": 45, "p46": 46, "p47": 47, "p49": 49}


# ---------------------------------------------------------------- helpers
def crps_q(q: np.ndarray, levels: np.ndarray, y: np.ndarray) -> np.ndarray:
    """CRPS by the quantile approximation (addendum 1, item 5): (2/K) sum_k pinball_tau_k(y - q_k), per row."""
    q, y = np.asarray(q, float), np.asarray(y, float)[:, None]
    u = y - q
    return 2.0 * np.mean(np.where(u >= 0, levels * u, (levels - 1) * u), axis=1)


def pit_q(q: np.ndarray, levels: np.ndarray, y: np.ndarray) -> np.ndarray:
    out = np.empty(len(y))
    for i, (qi, yi) in enumerate(zip(q, y, strict=True)):
        qs = np.maximum.accumulate(np.asarray(qi, float))
        out[i] = np.interp(yi, qs, levels, left=0.0, right=1.0)
    return out


def coverage90(q: np.ndarray, levels: np.ndarray, y: np.ndarray) -> float:
    lo, hi = int(np.argmin(np.abs(levels - 0.05))), int(np.argmin(np.abs(levels - 0.95)))
    return float(np.mean((y >= q[:, lo]) & (y <= q[:, hi])))


def pit_hist(p: np.ndarray) -> list[float]:
    h, _ = np.histogram(np.clip(p, 0, 1 - 1e-12), bins=10, range=(0, 1))
    return (h / max(len(p), 1)).round(4).tolist()


def tG1(diffs: np.ndarray) -> dict:
    d = np.asarray(diffs, float)
    d = d[np.isfinite(d)]
    g = len(d)
    if g < 3:
        return {"G": g}
    se = d.std(ddof=1) / np.sqrt(g)
    c = sps.t.ppf(0.975, g - 1)
    return {
        "G": g,
        "mean": float(d.mean()),
        "se": float(se),
        "ci": [float(d.mean() - c * se), float(d.mean() + c * se)],
        "years_negative": int((d < 0).sum()),
    }


def sign_test(diffs: np.ndarray) -> float:
    d = np.asarray(diffs, float)
    d = d[np.isfinite(d) & (d != 0)]
    k, n = int((d < 0).sum()), len(d)
    return float(min(1.0, 2 * sps.binom.sf(max(k, n - k) - 1, n, 0.5))) if n else np.nan


def randomization_p(diffs: np.ndarray) -> float:
    """Exact sign-flip test of mean(diffs) = 0 over years (2^G), two-sided."""
    d = np.asarray(diffs, float)
    d = d[np.isfinite(d)]
    obs = abs(d.mean())
    flips = np.array(list(itertools.product((-1.0, 1.0), repeat=len(d))))
    return float(np.mean(np.abs((flips * d).mean(1)) >= obs - 1e-12))


WEBB = np.array([-np.sqrt(1.5), -1.0, -np.sqrt(0.5), np.sqrt(0.5), 1.0, np.sqrt(1.5)])


def wild_year_mean(x: np.ndarray, years: np.ndarray, b: int = B_WILD, seed: int = 44) -> float:
    """Wild-cluster bootstrap by year (Webb weights, null imposed) of H0: mean(x) = 0; two-sided p of the t-stat."""
    x, years = np.asarray(x, float), np.asarray(years)
    m = np.isfinite(x)
    x, years = x[m], years[m]
    ys = np.unique(years)
    if len(ys) < 3:
        return np.nan
    idx = np.searchsorted(ys, years)

    def tstat(v):
        s = np.bincount(idx, weights=v - v.mean(), minlength=len(ys))
        se = np.sqrt(np.sum(s**2)) / len(v)
        return v.mean() / se if se > 0 else np.nan

    t0 = tstat(x)
    r = x - x.mean()  # null imposed: residuals around the null mean 0 are x - 0, recentred
    g = np.random.default_rng(seed)
    W = WEBB[g.integers(0, 6, (b, len(ys)))]
    tb = np.array([tstat(r * W[i, idx]) for i in range(b)])
    tb = tb[np.isfinite(tb)]
    return float(np.mean(np.abs(tb) >= abs(t0)))


def wild_year_coef(y: np.ndarray, X: np.ndarray, j: int, years: np.ndarray, b: int = B_WILD, seed: int = 44) -> dict:
    """Wild-cluster (restricted, Webb) bootstrap by year for H0: beta_j = 0 in OLS y = X beta."""
    m = np.isfinite(y) & np.isfinite(X).all(1)
    y, X, years = y[m], X[m], np.asarray(years)[m]
    ys = np.unique(years)
    idx = np.searchsorted(ys, years)

    def fit_t(yv):
        beta, *_ = np.linalg.lstsq(X, yv, rcond=None)
        e = yv - X @ beta
        XtXi = np.linalg.pinv(X.T @ X)
        sc = np.zeros((len(ys), X.shape[1]))
        np.add.at(sc, idx, X * e[:, None])
        V = XtXi @ (sc.T @ sc) @ XtXi
        return beta[j], beta[j] / np.sqrt(V[j, j]) if V[j, j] > 0 else np.nan

    b0, t0 = fit_t(y)
    Xr = np.delete(X, j, axis=1)
    br, *_ = np.linalg.lstsq(Xr, y, rcond=None)
    fr, er = Xr @ br, y - Xr @ br
    g = np.random.default_rng(seed)
    W = WEBB[g.integers(0, 6, (b, len(ys)))]
    tb = np.array([fit_t(fr + er * W[i, idx])[1] for i in range(b)])
    tb = tb[np.isfinite(tb)]
    return {
        "coef": float(b0),
        "t_year_cluster": float(t0),
        "p_wild": float(np.mean(np.abs(tb) >= abs(t0))),
        "G": len(ys),
    }


def median_ae_by_year(e_a: np.ndarray, e_b: np.ndarray, years: np.ndarray) -> dict[int, float]:
    out = {}
    for y in sorted(set(int(v) for v in years)):
        m = years == y
        out[y] = float(np.median(np.abs(e_a[m])) - np.median(np.abs(e_b[m])))
    return out


def pointwise_test(f_a: np.ndarray, f_b: np.ndarray, real: np.ndarray, years: np.ndarray, firms: np.ndarray) -> dict:
    """P4-1 test A / P4-2 rule: t(G-1) over yearly differences of median AE, DM two-way, wild, sign, randomization."""
    m = np.isfinite(f_a) & np.isfinite(f_b) & np.isfinite(real)
    ea, eb, yr, fi = (f_a - real)[m], (f_b - real)[m], years[m], firms[m]
    yearly = median_ae_by_year(ea, eb, yr)
    d = np.array(list(yearly.values()))
    dec = tG1(d)
    dm = S.two_way_mean(np.abs(ea) - np.abs(eb), fi, yr)
    return {
        "n": int(m.sum()),
        "median_a": float(np.median(np.abs(ea))),
        "median_b": float(np.median(np.abs(eb))),
        "statistic": float(np.median(np.abs(ea)) - np.median(np.abs(eb))),
        "yearly": yearly,
        "decision": dec,
        "success": bool(dec.get("ci", [0, 0])[1] < 0) if "ci" in dec else None,
        "dm_abs": dm,
        "wild_p_yearly": wild_year_mean(d, np.arange(len(d))) if len(d) >= 3 else None,
        "wild_p_dm": wild_year_mean(np.abs(ea) - np.abs(eb), yr),
        "sign_p": sign_test(d),
        "randomization_p": randomization_p(d),
        "mean_a": float(np.mean(np.abs(ea))),
        "mean_b": float(np.mean(np.abs(eb))),
    }


def combine(base: np.ndarray, adj: np.ndarray, real: np.ndarray, years: np.ndarray) -> dict:
    """base + w (adj - base), w chosen each test year on years <= Y-3 by winsorized MAE (training bounds)."""
    pred = np.full(len(base), np.nan)
    ws: dict[int, float] = {}
    for y in TEST_YEARS:
        tr = (years <= y - LAG) & np.isfinite(base) & np.isfinite(adj) & np.isfinite(real)
        te = (years == y) & np.isfinite(base) & np.isfinite(adj)
        if tr.sum() < MIN_TR or not te.any():
            continue
        lo, hi = np.percentile(real[tr], [1, 99])
        L = [
            np.mean(np.abs(np.clip(base[tr] + w * (adj[tr] - base[tr]), lo, hi) - np.clip(real[tr], lo, hi)))
            for w in W_GRID
        ]
        w = float(W_GRID[int(np.argmin(L))])
        ws[y] = w
        pred[te] = base[te] + w * (adj[te] - base[te])
    m = np.isfinite(pred) & np.isfinite(real) & np.isfinite(base)
    out: dict = {"w": ws, "n": int(m.sum())}
    if m.sum() < 30:
        return out
    yr = years[m]
    lo_hi = {y: np.percentile(real[(years <= y - LAG) & np.isfinite(real)], [1, 99]) for y in set(yr.tolist())}
    lo = np.array([lo_hi[y][0] for y in yr])
    hi = np.array([lo_hi[y][1] for y in yr])
    r, pc, pb = real[m], pred[m], base[m]
    mw_c = np.mean(np.abs(np.clip(pc, lo, hi) - np.clip(r, lo, hi)))
    mw_b = np.mean(np.abs(np.clip(pb, lo, hi) - np.clip(r, lo, hi)))
    out |= {
        "gain_winsorized_mae": float(1 - mw_c / mw_b),
        "gain_median_ae": float(1 - np.median(np.abs(pc - r)) / np.median(np.abs(pb - r))),
        "gain_raw_mae": float(1 - np.mean(np.abs(pc - r)) / np.mean(np.abs(pb - r))),
    }
    out["_pred"] = pred
    return out


# ---------------------------------------------------------------- loading
def load_spec(root: Path, spec: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The plan-3 panel of one spec (size screen) and its transmission frame (with N4), as in stats.main."""
    _, panel_all, _, _ = S.load(root / "research" / spec)
    panel = S.size_screen(panel_all)
    if "in_bankruptcy" in panel:
        panel = panel[~panel["in_bankruptcy"].astype(bool)].reset_index(drop=True)
    return panel, T.add_shrunk(T.frame(panel))


def load_p4(root: Path) -> pd.DataFrame:
    recs = []
    for f in sorted((root / "research" / "p4").glob("*.json")):
        r = json.loads(f.read_text(encoding="utf-8"))
        for row in r.get("rows", []):
            u = row["u"]
            rec = {
                "ticker": r["ticker"],
                "year": int(row["origin"][:4]),
                "u_health": u["health"],
                "T1u_cfo": u["cfo"]["median"],
                "u_rev_med": u["revenue"]["median"],
                "u_q": u["cfo"]["q"],
                "rev_ttm": row["rev_ttm"],
            }
            if "rt" in row:
                rec["rt"] = row["rt"]
            recs.append(rec)
    return pd.DataFrame(recs)


def _hist_one(args):
    from ..data.facts import load_company

    ticker, years = args
    out = []
    for y in years:
        try:
            q = load_company(ticker, asof=f"{y}-02-15").quarters
            rev, cfo = q["revenue"].tail(16).astype(float), q["cfo"].tail(16).astype(float)
            mean16 = float(rev.mean()) if rev.notna().sum() >= 12 else np.nan
            marg = (cfo / rev).replace([np.inf, -np.inf], np.nan).dropna()
            out.append((ticker, y, mean16, float(marg.std(ddof=1)) if len(marg) >= 8 else np.nan))
        except Exception:
            out.append((ticker, y, np.nan, np.nan))
    return out


def history_features(df: pd.DataFrame) -> pd.DataFrame:
    """16-quarter mean quarterly revenue and the s.d. of the quarterly CFO margin at each cutoff (P4-5, P4-6)."""
    jobs = [(t, sorted(set(g["year"].astype(int)))) for t, g in df.groupby("ticker")]
    with Pool(int(os.environ.get("P4_PROCS", os.cpu_count() or 1))) as pool:
        res = [r for part in pool.imap_unordered(_hist_one, jobs, chunksize=8) for r in part]
    return pd.DataFrame(res, columns=["ticker", "year", "rev_mean16", "marg_sd16"])


# ---------------------------------------------------------------- the tests
def p41(df: pd.DataFrame, u: pd.DataFrame) -> dict:
    d = df.merge(u, on=["ticker", "year"], how="inner")
    # all cutoffs stay in: <= Y-3 trains the rivals and weights, 2017-2024 is tested (addendum 2)
    d = d.reset_index(drop=True)
    real = d["real_cfo"].to_numpy(float)
    revsum = d["revsum"].to_numpy(float)
    m16 = d["N3_cfo"].to_numpy(float) / revsum
    m4 = d["N1_cfo"].to_numpy(float) / revsum
    F = {
        "T1u": d["T1u_cfo"].to_numpy(float),
        "R1u": m16 * 200.0,
        "R2u": m16 * d["u_rev_med"].to_numpy(float),
        "R3u": m4 * 200.0,
    }
    years, firms = d["year"].to_numpy(int), unit(d).to_numpy()
    tm = np.isin(years, TEST_YEARS)
    out: dict = {"n": int(tm.sum()), "levels": {}}
    for k, f in F.items():
        e = f - real
        ok = np.isfinite(e) & tm
        out["levels"][k] = {
            "n": int(ok.sum()),
            "median_ae": float(np.median(np.abs(e[ok]))),
            "mean_ae": float(np.mean(np.abs(e[ok]))),
        }
    out["test_A"] = pointwise_test(F["T1u"][tm], F["R1u"][tm], real[tm], years[tm], firms[tm])
    # density, test B: T1u's 21 plan quantiles against R1u + the empirical residuals of R1u on cutoffs <= Y-3
    q_t = np.vstack(d["u_q"].to_numpy())
    resid = real - F["R1u"]
    crps_t, crps_r, pit_t, pit_r, cov_t, cov_r, rows = [], [], [], [], [], [], []
    for y in TEST_YEARS:
        tr = (years <= y - LAG) & np.isfinite(resid)
        te = np.flatnonzero((years == y) & np.isfinite(real) & np.isfinite(F["R1u"]) & np.isfinite(q_t).all(1))
        if tr.sum() < MIN_TR or not len(te):
            continue
        rq = np.percentile(resid[tr], PLAN_LEVELS * 100)
        qr = F["R1u"][te, None] + rq[None, :]
        crps_t.append(crps_q(q_t[te], PLAN_LEVELS, real[te]))
        crps_r.append(crps_q(qr, PLAN_LEVELS, real[te]))
        pit_t.append(pit_q(q_t[te], PLAN_LEVELS, real[te]))
        pit_r.append(pit_q(qr, PLAN_LEVELS, real[te]))
        cov_t.append((real[te] >= q_t[te, 1]) & (real[te] <= q_t[te, 19]))
        cov_r.append((real[te] >= qr[:, 1]) & (real[te] <= qr[:, 19]))
        rows.append(te)
    if rows:
        idx = np.concatenate(rows)
        ct, cr = np.concatenate(crps_t), np.concatenate(crps_r)
        dm = S.two_way_mean(ct - cr, firms[idx], years[idx])
        p_one = float(sps.t.cdf(dm["t"], dm["G"] - 1)) if "t" in dm else None  # H1: simulator lower
        out["test_B"] = {
            "n": int(len(idx)),
            "crps_twin": float(ct.mean()),
            "crps_rival": float(cr.mean()),
            "dm": dm,
            "p_one_sided": p_one,
            "success": bool(dm.get("mean", 0) < 0 and p_one is not None and p_one < 0.05),
            "pit_twin": pit_hist(np.concatenate(pit_t)),
            "pit_rival": pit_hist(np.concatenate(pit_r)),
            "coverage90_twin": float(np.concatenate(cov_t).mean()),
            "coverage90_rival": float(np.concatenate(cov_r).mean()),
            "years_twin_better": int(sum(a.mean() < b.mean() for a, b in zip(crps_t, crps_r, strict=True))),
            "years": len(rows),
        }
    c = combine(F["R1u"], F["T1u"], real, years)
    c.pop("_pred", None)
    out["combination"] = c
    return out


ML_FEATS = [
    "m4",
    "m8",
    "m16",
    "revrel",
    "N1x",
    "N2x",
    "N3x",
    "fcf_margin",
    "capex_rev",
    "cash_rev",
    "debt_assets",
    "rev_vol",
    "fixed_share",
    "log_rev",
]


def ml1_design(d: pd.DataFrame) -> pd.DataFrame:
    revsum = d["revsum"].astype(float)
    X = pd.DataFrame(
        {
            "m4": d["N1_cfo"] / revsum,
            "m8": d["N2_cfo"] / revsum,
            "m16": d["N3_cfo"] / revsum,
            "revrel": revsum / 100.0,
            "N1x": d["N1_cfo"],
            "N2x": d["N2_cfo"],
            "N3x": d["N3_cfo"],
            **{
                c: d[c].astype(float)
                for c in ("fcf_margin", "capex_rev", "cash_rev", "debt_assets", "rev_vol", "fixed_share", "log_rev")
            },
        }
    )
    return X


def ml1(df: pd.DataFrame, panel: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Walk-forward pooled LAD (and 21 quantile regressions) of real_cfo; trained on cutoffs <= Y-3."""
    import statsmodels.api as sm

    extra = panel[["ticker", "year", "capex_rev", "cash_rev", "debt_assets", "rev_vol"]].drop_duplicates(
        ["ticker", "year"]
    )
    d = df.merge(extra, on=["ticker", "year"], how="left", suffixes=("", "_p"))
    X = ml1_design(d)
    inds = pd.get_dummies(d["industry"].fillna("Other").astype(str), prefix="ind", drop_first=True, dtype=float)
    y = d["real_cfo"].to_numpy(float)
    years = d["year"].to_numpy(int)
    point = np.full(len(d), np.nan)
    qs = np.full((len(d), len(P3_LEVELS)), np.nan)
    for t in TEST_YEARS:
        tr = (years <= t - LAG) & np.isfinite(y) & X.notna().all(1).to_numpy()
        te = (years == t) & X.notna().all(1).to_numpy()
        if tr.sum() < MIN_TR_ML or not te.any():
            continue
        lo, hi = X[tr].quantile(0.01), X[tr].quantile(0.99)
        Z = pd.concat([X.clip(lo, hi, axis=1), inds], axis=1)
        keep = Z.columns[(Z[tr].std() > 0).to_numpy()]
        Z = sm.add_constant(Z[keep], has_constant="add")
        ylo, yhi = np.percentile(y[tr], [1, 99])
        ytr = np.clip(y[tr], ylo, yhi)
        res = sm.QuantReg(ytr, Z[tr].to_numpy(float)).fit(q=0.5, max_iter=5000)
        point[te] = Z[te].to_numpy(float) @ res.params
        for j, tau in enumerate(P3_LEVELS):
            rj = sm.QuantReg(ytr, Z[tr].to_numpy(float)).fit(q=float(tau), max_iter=5000)
            qs[te, j] = Z[te].to_numpy(float) @ rj.params
    qs = np.sort(qs, axis=1)  # rearrangement
    return point, qs


def p42(df: pd.DataFrame, panel: pd.DataFrame) -> tuple[dict, np.ndarray]:
    point, qs = ml1(df, panel)
    d = df.copy()
    d["ML1_cfo"] = point
    real = d["real_cfo"].to_numpy(float)
    years, firms = d["year"].to_numpy(int), unit(d).to_numpy()
    sel = np.isin(years, TEST_YEARS)
    out: dict = {
        "test": pointwise_test(point[sel], d["N3_cfo"].to_numpy(float)[sel], real[sel], years[sel], firms[sel])
    }
    out["vs_T1"] = pointwise_test(point[sel], d["T1_cfo"].to_numpy(float)[sel], real[sel], years[sel], firms[sel])
    # levels on the common test firm-years
    m = sel & np.isfinite(point) & d[[f"{k}_cfo" for k in T.MODELS]].notna().all(1).to_numpy() & np.isfinite(real)
    out["levels"] = {
        k: {
            "median_ae": float(np.median(np.abs(d[f"{k}_cfo"].to_numpy(float)[m] - real[m]))),
            "mean_ae": float(np.mean(np.abs(d[f"{k}_cfo"].to_numpy(float)[m] - real[m]))),
        }
        for k in [*T.MODELS, "ML1"]
    }
    out["levels_n"] = int(m.sum())
    # encompassing in levels: real on T1, N3, ML1 (winsorized at full-sample 1/99 as the plan-3 levels regression)
    if m.sum() < MIN_ENC:
        return out, point
    lo, hi = np.nanpercentile(real[m], [1, 99])
    Y = np.clip(real[m], lo, hi)
    Xe = np.column_stack(
        [np.ones(m.sum())] + [np.clip(d[f"{k}_cfo"].to_numpy(float)[m], lo, hi) for k in ("T1", "N3", "ML1")]
    )
    tw = S.cluster_ols(Y, Xe, [firms[m], years[m]])
    out["encompassing_levels"] = {
        "names": ["const", "T1", "N3", "ML1"],
        "params": np.asarray(tw["params"]).tolist(),
        "t": np.asarray(tw["t"]).tolist(),
        "t_crit": tw.get("t_crit"),
        "psd": tw.get("psd"),
    }
    c = combine(d["N3_cfo"].to_numpy(float), point, real, years)
    c.pop("_pred", None)
    out["combination_N3_ML1"] = c
    # density: ML1 quantiles against the empirical N3-residual rival (<= Y-3), same quantile CRPS
    resid = real - d["N3_cfo"].to_numpy(float)
    q_t1 = (
        np.vstack(
            [
                np.asarray(x, float) if isinstance(x, list | np.ndarray) else np.full(len(P3_LEVELS), np.nan)
                for x in d["dens_q"]
            ]
        )
        if "dens_q" in d
        else None
    )
    cr_ml, cr_emp, cr_t1, idx_all = [], [], [], []
    for y in TEST_YEARS:
        tr = (years <= y - LAG) & np.isfinite(resid)
        te = np.flatnonzero((years == y) & np.isfinite(qs).all(1) & np.isfinite(real) & np.isfinite(resid))
        if q_t1 is not None:
            te = te[np.isfinite(q_t1[te]).all(1)]
        if tr.sum() < MIN_TR or not len(te):
            continue
        rq = np.percentile(resid[tr], P3_LEVELS * 100)
        cr_ml.append(crps_q(qs[te], P3_LEVELS, real[te]))
        cr_emp.append(crps_q(d["N3_cfo"].to_numpy(float)[te, None] + rq[None, :], P3_LEVELS, real[te]))
        if q_t1 is not None:
            cr_t1.append(crps_q(q_t1[te], P3_LEVELS, real[te]))
        idx_all.append(te)
    if idx_all:
        idx = np.concatenate(idx_all)
        a, b_ = np.concatenate(cr_ml), np.concatenate(cr_emp)
        out["density"] = {
            "n": int(len(idx)),
            "crps_ml1": float(a.mean()),
            "crps_empirical": float(b_.mean()),
            "dm_ml1_vs_empirical": S.two_way_mean(a - b_, firms[idx], years[idx]),
            "coverage90_ml1": coverage90(qs[idx], P3_LEVELS, real[idx]),
            "pit_ml1": pit_hist(pit_q(qs[idx], P3_LEVELS, real[idx])),
        }
        if cr_t1:
            c1 = np.concatenate(cr_t1)
            out["density"] |= {
                "crps_twin": float(c1.mean()),
                "dm_twin_vs_ml1": S.two_way_mean(c1 - a, firms[idx], years[idx]),
            }
    return out, point


def p43(df: pd.DataFrame, ml1_point: np.ndarray | None) -> dict:
    """Raw mean-loss MCS over the 19 plan-3 forecasters (and with ML1 as a 20th), firm x year bootstrap."""
    orig_bounds = T.train_bounds

    def raw_bounds(real, yrs, mode="train"):
        if mode == "raw":
            b = orig_bounds(real, yrs, "train")
            return {y: (-np.inf, np.inf) for y in b}
        return orig_bounds(real, yrs, mode)

    T.train_bounds = raw_bounds
    out: dict = {}
    try:
        fy = T.boot_losses(df, T.FORECASTERS, B, "firm_year", SEED["p43"], bounds="raw", variables=("cfo",))
        r = fy["cfo"]
        out["raw_mean_19"] = S.mcs(r["point_mean"], r["boot_mean"], T.FORECASTERS, alpha=0.10) | {
            "loss": dict(zip(T.FORECASTERS, np.asarray(r["point_mean"]).tolist(), strict=True)),
            "n": r["n"],
        }
        if ml1_point is not None:
            d = df.copy()
            d["ML1_cfo"] = ml1_point
            d["ML1_fcf"] = np.nan
            T.MODELS.append("ML1")
            try:
                names = [*T.FORECASTERS, "ML1"]
                for bounds in ("train", "raw"):
                    f2 = T.boot_losses(d, names, B, "firm_year", SEED["p43"], bounds=bounds, variables=("cfo",))
                    r2 = f2["cfo"]
                    for loss in ("mean", "median"):
                        out[f"with_ml1_{bounds}_{loss}"] = S.mcs(
                            r2[f"point_{loss}"], r2[f"boot_{loss}"], names, alpha=0.10
                        ) | {
                            "loss": dict(zip(names, np.asarray(r2[f"point_{loss}"]).tolist(), strict=True)),
                            "n": r2["n"],
                        }
            finally:
                T.MODELS.remove("ML1")
    finally:
        T.train_bounds = orig_bounds
    return out


def p44(df: pd.DataFrame, s1_yearly: dict | None, comb_rows: tuple | None) -> dict:
    out: dict = {}
    if s1_yearly:
        d = np.array([s1_yearly[k] for k in sorted(s1_yearly)], float)
        out["S1"] = {
            "wild_p": wild_year_mean(d, np.arange(len(d))),
            "randomization_p": randomization_p(d),
            "sign_p": sign_test(d),
            "G": int(len(d)),
        }
    # T1's encompassing coefficient (levels regression of real on the forecasts, plan-3 levels winsorization)
    real = df["real_cfo"].to_numpy(float)
    m = np.isfinite(real) & df[[f"{k}_cfo" for k in ("T1", "N3", "N4", "N6")]].notna().all(1).to_numpy()
    lo, hi = np.nanpercentile(real[m], [1, 99])
    X = np.column_stack(
        [np.ones(m.sum())] + [np.clip(df[f"{k}_cfo"].to_numpy(float)[m], lo, hi) for k in ("T1", "N3", "N4", "N6")]
    )
    out["encompassing_T1"] = wild_year_coef(np.clip(real[m], lo, hi), X, 1, df["year"].to_numpy()[m])
    if comb_rows is not None:
        diff, yrs = comb_rows
        out["gain_N3T1_vs_N3"] = {"wild_p": wild_year_mean(diff, yrs), "n": int(np.isfinite(diff).sum())}
    return out


def p45(df: pd.DataFrame, hist: pd.DataFrame) -> dict:
    real = df["real_cfo"].to_numpy(float)
    e3 = np.abs(df["N3_cfo"].to_numpy(float) - real)
    firms, years = unit(df).to_numpy(), df["year"].to_numpy(int)
    common = np.isfinite(real) & df[[f"{k}_cfo" for k in T.MODELS]].notna().all(1).to_numpy()
    out: dict = {"relative": {}}
    keep = common & (e3 >= 0.01)
    out["dropped_small_N3_error"] = int((common & (e3 < 0.01)).sum())
    g = np.random.default_rng(SEED["p45"])
    fcode = pd.factorize(firms[keep])[0]
    ycode = pd.factorize(years[keep])[0]
    nf, ny = fcode.max() + 1, ycode.max() + 1
    for k in [x for x in T.MODELS if x != "N3"]:
        ek = np.abs(df[f"{k}_cfo"].to_numpy(float) - real)[keep]
        lr = np.log(np.maximum(ek, 1e-6) / e3[keep])
        draws: list[float] = []
        for _ in range(B):
            wf = np.bincount(g.integers(0, nf, nf), minlength=nf)
            wy = np.bincount(g.integers(0, ny, ny), minlength=ny)
            w = wf[fcode] * wy[ycode]
            draws.append(np.sum(w * lr) / w.sum() if w.sum() else np.nan)
        star = np.asarray(draws)
        out["relative"][k] = {
            "gmrae": float(np.exp(lr.mean())),
            "gmrae_ci": np.exp(np.nanpercentile(star, [2.5, 97.5])).tolist(),
            "median_rae": float(np.median(np.exp(lr))),
            "share_beats_N3": float(np.mean(ek < e3[keep])),
        }
    d = df.merge(hist, on=["ticker", "year"], how="left")
    near0 = (d["rev_ttm_pct"] < 25.0).to_numpy() if "rev_ttm_pct" in d else np.zeros(len(d), bool)
    out["near_zero_excluded"] = int((near0 & common).sum())
    ok = common & ~near0
    out["without_near_zero"] = {
        k: {
            "median_ae": float(np.median(np.abs(df[f"{k}_cfo"].to_numpy(float)[ok] - real[ok]))),
            "mean_ae": float(np.mean(np.abs(df[f"{k}_cfo"].to_numpy(float)[ok] - real[ok]))),
        }
        for k in T.MODELS
    }
    out["without_near_zero_n"] = int(ok.sum())
    return out


def p46(df: pd.DataFrame, panel: pd.DataFrame, hist: pd.DataFrame, others: dict[str, pd.DataFrame]) -> dict:
    """Heteroskedastic (H) and quantile-regression (Q) rivals to T1's conditional density."""
    import statsmodels.api as sm

    q_t1 = df["dens_q"]
    real = df["real_cfo"].to_numpy(float)
    n3 = df["N3_cfo"].to_numpy(float)
    resid = real - n3
    d = df.merge(hist, on=["ticker", "year"], how="left")
    s = d["marg_sd16"].to_numpy(float) * np.sqrt(8)
    years, firms = df["year"].to_numpy(int), unit(df).to_numpy()
    Qt = np.vstack(
        [np.asarray(x, float) if isinstance(x, list | np.ndarray) else np.full(len(P3_LEVELS), np.nan) for x in q_t1]
    )
    res: dict[str, list] = {"T1": [], "H": [], "Q": [], "idx": []}
    for y in TEST_YEARS:
        tr = (years <= y - LAG) & np.isfinite(resid) & np.isfinite(s)
        if tr.sum() < MIN_TR:
            continue
        floor = np.percentile(s[tr], 5)
        s_f = np.maximum(s, floor)
        te = np.flatnonzero(
            (years == y) & np.isfinite(real) & np.isfinite(n3) & np.isfinite(s) & np.isfinite(Qt).all(1)
        )
        if not len(te):
            continue
        z = resid[tr] / s_f[tr]
        zq = np.percentile(z, P3_LEVELS * 100)
        qH = n3[te, None] + s_f[te, None] * zq[None, :]
        Xtr = sm.add_constant(
            np.column_stack(
                [
                    d["log_rev"].to_numpy(float)[tr],
                    d["rev_vol"].to_numpy(float)[tr] if "rev_vol" in d else np.zeros(tr.sum()),
                    s_f[tr],
                ]
            )
        )
        Xte = sm.add_constant(
            np.column_stack(
                [
                    d["log_rev"].to_numpy(float)[te],
                    d["rev_vol"].to_numpy(float)[te] if "rev_vol" in d else np.zeros(len(te)),
                    s_f[te],
                ]
            ),
            has_constant="add",
        )
        okx = np.isfinite(Xtr).all(1)
        qQ = np.column_stack(
            [
                n3[te] + Xte @ sm.QuantReg(resid[tr][okx], Xtr[okx]).fit(q=float(t), max_iter=5000).params
                for t in P3_LEVELS
            ]
        )
        qQ = np.sort(qQ, axis=1)
        good = np.isfinite(qQ).all(1) & np.isfinite(qH).all(1)
        te, qH, qQ = te[good], qH[good], qQ[good]
        res["T1"].append(crps_q(Qt[te], P3_LEVELS, real[te]))
        res["H"].append(crps_q(qH, P3_LEVELS, real[te]))
        res["Q"].append(crps_q(qQ, P3_LEVELS, real[te]))
        res["idx"].append((te, qH, qQ))
    out: dict = {}
    if res["idx"]:
        idx = np.concatenate([t[0] for t in res["idx"]])
        cT, cH, cQ = (np.concatenate(res[k]) for k in ("T1", "H", "Q"))
        qH_all = np.vstack([t[1] for t in res["idx"]])
        qQ_all = np.vstack([t[2] for t in res["idx"]])
        out = {
            "n": int(len(idx)),
            "crps": {"T1": float(cT.mean()), "H": float(cH.mean()), "Q": float(cQ.mean())},
            "dm_T1_vs_H": S.two_way_mean(cT - cH, firms[idx], years[idx]),
            "dm_T1_vs_Q": S.two_way_mean(cT - cQ, firms[idx], years[idx]),
            "coverage90": {
                "T1": coverage90(Qt[idx], P3_LEVELS, real[idx]),
                "H": coverage90(qH_all, P3_LEVELS, real[idx]),
                "Q": coverage90(qQ_all, P3_LEVELS, real[idx]),
            },
            "pit": {
                "T1": pit_hist(pit_q(Qt[idx], P3_LEVELS, real[idx])),
                "H": pit_hist(pit_q(qH_all, P3_LEVELS, real[idx])),
                "Q": pit_hist(pit_q(qQ_all, P3_LEVELS, real[idx])),
            },
        }
        keys = df.iloc[idx][["ticker", "year"]]
        for spec, odf in others.items():
            o = keys.merge(odf[["ticker", "year", "real_cfo", "dens_q"]], on=["ticker", "year"], how="inner")
            Qo = np.vstack(
                [
                    np.asarray(x, float) if isinstance(x, list | np.ndarray) else np.full(len(P3_LEVELS), np.nan)
                    for x in o["dens_q"]
                ]
            )
            ok = np.isfinite(Qo).all(1) & np.isfinite(o["real_cfo"].to_numpy(float))
            ro = o["real_cfo"].to_numpy(float)[ok]
            out[f"spec_{spec}"] = {
                "n": int(ok.sum()),
                "coverage90": coverage90(Qo[ok], P3_LEVELS, ro),
                "pit": pit_hist(pit_q(Qo[ok], P3_LEVELS, ro)),
                "crps": float(crps_q(Qo[ok], P3_LEVELS, ro).mean()),
            }
    return out


def isotonic(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Pool-adjacent-violators fit of y on x; returns the sorted x knots and fitted values."""
    o = np.argsort(x, kind="stable")
    xs, ys = x[o], y[o].astype(float)
    vals, wts, lefts = [], [], []
    for i, v in enumerate(ys):
        vals.append(v)
        wts.append(1.0)
        lefts.append(i)
        while len(vals) > 1 and vals[-2] > vals[-1]:
            w = wts[-2] + wts[-1]
            v2 = (vals[-2] * wts[-2] + vals[-1] * wts[-1]) / w
            vals[-2:], wts[-2:], lefts[-2:] = [v2], [w], [lefts[-2]]
    fit = np.empty(len(ys))
    bounds = [*lefts[1:], len(ys)]
    for v, a, b_ in zip(vals, lefts, bounds, strict=True):
        fit[a:b_] = v
    return xs, fit


def p47(root: Path) -> dict:
    liq = D.liquidity_frame(root / "research" / "v3-wf")
    # outcome pieces of the cash criterion, from the shards (liquidity_frame keeps only the labels)
    extra = []
    for f in sorted((root / "research" / "v3-wf").glob("*.json")):
        r = json.loads(f.read_text(encoding="utf-8"))
        for pr in r.get("panel", []):
            oc = pr.get("outcome") or {}
            extra.append(
                {
                    "ticker": r["ticker"],
                    "origin": pr["origin"],
                    "cash_min_ratio8": oc.get("cash_min_ratio8"),
                    "debt_raise8": oc.get("debt_raise8"),
                }
            )
    liq = liq.merge(pd.DataFrame(extra), on=["ticker", "origin"], how="left")
    bk, acc = liq["bk8"].to_numpy(float), liq["acc8"].to_numpy(float)
    ev = np.where(np.isfinite(bk) & np.isfinite(acc), np.maximum(bk, acc), np.nan)
    L2 = np.array(
        [D.shortfall_label(e, c, r) for e, c, r in zip(ev, liq["cash_min_ratio8"], liq["debt_raise8"], strict=True)],
        float,
    )
    labels = {"L1": liq["y_short8"].to_numpy(float), "L2": L2}
    years_all = sorted(set(liq["year"].astype(int)))
    yr = liq["year"].to_numpy(int)
    firms = unit(liq).to_numpy()
    out: dict = {"n_frame": int(len(liq))}
    for lab, y in labels.items():
        for cell, col in (("recession", "rec8"), ("baseline", "base8")):
            p = liq[col].to_numpy(float)
            logit = D.benchmark_probs(liq, y, 8, D.LOGIT_COLS, years_all)
            recal = np.full(len(liq), np.nan)
            for t in years_all:
                tr = D.known_by(liq, pd.Timestamp(f"{t}-02-15"), 8) & np.isfinite(y) & np.isfinite(p)
                te = (yr == t) & np.isfinite(p)
                if tr.sum() < D.MIN_TRAIN or y[tr].sum() < D.MIN_TRAIN_EVENTS or not te.any():
                    continue
                xs, fit = isotonic(p[tr], y[tr])
                recal[te] = np.interp(p[te], xs, fit)
            test = np.isfinite(recal) & np.isfinite(logit) & np.isfinite(y) & np.isfinite(p)
            if test.sum() < 30:
                out[f"{lab}_{cell}"] = {"n": int(test.sum())}
                continue
            P, R, L, Y = p[test], recal[test], logit[test], y[test]
            res: dict[str, Any] = {
                "n": int(test.sum()),
                "events": int(Y.sum()),
                "years": sorted(set(yr[test].tolist())),
                "raw": D.prob_scores(P, Y),
                "recalibrated": D.prob_scores(R, Y),
                "logit": D.prob_scores(L, Y),
                "bss_raw_vs_logit": D._bss(P, L, Y),
                "bss_recal_vs_logit": D._bss(R, L, Y),
                "recal_year_block": D.block_ci(D._bss, [R, L, Y], yr[test], B, seed=SEED["p47"]),
                "recal_firm_block": D.block_ci(D._bss, [R, L, Y], firms[test], B, seed=SEED["p47"]),
            }
            lo = res["recal_firm_block"]["ci"][0]
            res["success"] = bool(res["bss_recal_vs_logit"] > 0 and lo is not None and lo > 0)
            out[f"{lab}_{cell}"] = res
    out["confirmatory"] = {"cell": "L2_recession", "success": out.get("L2_recession", {}).get("success")}
    return out


def p48(u: pd.DataFrame, df: pd.DataFrame) -> dict:
    rows = u[u["rt"].notna()] if "rt" in u else u.iloc[:0]
    recs = []
    for r in rows.itertuples():
        rt = r.rt
        b, t = rt.get("base") or {}, rt.get("realtime") or {}
        recs.append(
            {
                "ticker": r.ticker,
                "differs": (rt.get("rec_state0") or 0.0) != (1.0 if rt.get("rec_realtime") else 0.0),
                "b_cfo": b.get("twin_cfo_tot"),
                "t_cfo": t.get("twin_cfo_tot"),
                "b_crps": ((b.get("dens") or {}).get("cfo") or {}).get("crps"),
                "t_crps": ((t.get("dens") or {}).get("cfo") or {}).get("crps"),
                "s8": rt.get("short8_rec"),
                "s8_rt": rt.get("short8_rec_rt"),
            }
        )
    d = pd.DataFrame(recs)
    if d.empty:
        return {"n": 0}
    real = df[df["year"] == 2021][["ticker", "real_cfo", "T1_cfo"]]
    d = d.merge(real, on="ticker", how="inner")
    for c in ("b_cfo", "t_cfo", "b_crps", "t_crps", "s8", "s8_rt", "real_cfo", "T1_cfo"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    ok = d[["b_cfo", "t_cfo", "real_cfo"]].notna().all(1)
    e_b, e_t = (d["b_cfo"] - d["real_cfo"]).abs()[ok], (d["t_cfo"] - d["real_cfo"]).abs()[ok]
    return {
        "n": int(ok.sum()),
        "share_regime_differs": float(d["differs"].mean()),
        "reproduces_plan3_point": float(np.mean(np.isclose(d["b_cfo"][ok], d["T1_cfo"][ok], atol=1e-3))),
        "median_ae": {"plan3": float(e_b.median()), "realtime": float(e_t.median())},
        "mean_ae": {"plan3": float(e_b.mean()), "realtime": float(e_t.mean())},
        "mean_crps": {"plan3": float(d["b_crps"].mean()), "realtime": float(d["t_crps"].mean())},
        "mean_short8_rec": {"plan3": float(d["s8"].mean()), "realtime": float(d["s8_rt"].mean())},
    }


def p49(frames: dict[str, pd.DataFrame]) -> dict:
    out = {}
    for spec, panel in frames.items():
        df = P2.frame(panel)
        firms, years = unit(df).to_numpy(), df["year"].to_numpy(int)
        point = P2.overreaction(df)["cfo"]["ratio"]
        g = np.random.default_rng(SEED["p49"])
        res = {"ratio": point}
        for scheme, groups in (("firm", firms), ("year", years)):
            ug = pd.unique(groups)
            pos = {k: np.flatnonzero(groups == k) for k in ug}
            draws = []
            for _ in range(B):
                pick = g.integers(0, len(ug), len(ug))
                idx = np.concatenate([pos[ug[i]] for i in pick])
                try:
                    draws.append(P2.overreaction(df.iloc[idx].reset_index(drop=True))["cfo"]["ratio"])
                except ValueError:
                    continue
            res[f"ci_{scheme}"] = np.nanpercentile(np.asarray(draws, float), [2.5, 97.5]).tolist()
        out[spec] = res
    return out


# ---------------------------------------------------------------- addendum 3: statistics the plan lists, missing in the first run
def p4_extras(root: Path, df: pd.DataFrame, u: pd.DataFrame) -> dict:
    out: dict = {}
    # P4-1 on the common firm-years of all four unconditional forecasts, and the simulator against R2u
    d = df.merge(u, on=["ticker", "year"], how="inner").reset_index(drop=True)
    real = d["real_cfo"].to_numpy(float)
    revsum = d["revsum"].to_numpy(float)
    m16, m4 = d["N3_cfo"].to_numpy(float) / revsum, d["N1_cfo"].to_numpy(float) / revsum
    F = {
        "T1u": d["T1u_cfo"].to_numpy(float),
        "R1u": m16 * 200.0,
        "R2u": m16 * d["u_rev_med"].to_numpy(float),
        "R3u": m4 * 200.0,
    }
    yrs, firms = d["year"].to_numpy(int), unit(d).to_numpy()
    tm = np.isin(yrs, TEST_YEARS) & np.isfinite(real) & np.all([np.isfinite(f) for f in F.values()], axis=0)
    out["p41_common"] = {
        "n": int(tm.sum()),
        **{
            k: {
                "median_ae": float(np.median(np.abs(f[tm] - real[tm]))),
                "mean_ae": float(np.mean(np.abs(f[tm] - real[tm]))),
            }
            for k, f in F.items()
        },
    }
    out["p41_T1u_vs_R2u"] = pointwise_test(F["T1u"][tm], F["R2u"][tm], real[tm], yrs[tm], firms[tm])
    out["p41_R2u_vs_R1u"] = pointwise_test(F["R2u"][tm], F["R1u"][tm], real[tm], yrs[tm], firms[tm])
    # P4-4 (ii): randomization over years for T1's encompassing coefficient (per-year coefficients) and the gain
    r = df["real_cfo"].to_numpy(float)
    y_all = df["year"].to_numpy(int)
    cols = ("T1", "N3", "N4", "N6")
    ok = np.isfinite(r) & df[[f"{k}_cfo" for k in cols]].notna().all(1).to_numpy()
    lo, hi = np.nanpercentile(r[ok], [1, 99])
    coefs = []
    for y in sorted(set(y_all[ok].tolist())):
        mm = ok & (y_all == y)
        X = np.column_stack([np.ones(mm.sum())] + [np.clip(df[f"{k}_cfo"].to_numpy(float)[mm], lo, hi) for k in cols])
        beta, *_ = np.linalg.lstsq(X, np.clip(r[mm], lo, hi), rcond=None)
        coefs.append(float(beta[1]))
    out["p44_encompassing_by_year"] = {
        "coefs": coefs,
        "randomization_p": randomization_p(np.array(coefs)),
        "positive": int(np.sum(np.array(coefs) > 0)),
        "G": len(coefs),
    }
    c = combine(df["N3_cfo"].to_numpy(float), df["T1_cfo"].to_numpy(float), r, y_all)
    if "_pred" in c:
        n3 = df["N3_cfo"].to_numpy(float)
        lo_y = {
            y: np.percentile(r[(y_all <= y - LAG) & np.isfinite(r)], [1, 99])
            for y in TEST_YEARS
            if ((y_all <= y - LAG) & np.isfinite(r)).sum() >= 20
        }
        per = []
        for y in sorted(lo_y):
            mm = (y_all == y) & np.isfinite(c["_pred"]) & np.isfinite(r) & np.isfinite(n3)
            if not mm.any():
                continue
            a_, b_ = lo_y[y]
            e_c = np.abs(np.clip(c["_pred"][mm], a_, b_) - np.clip(r[mm], a_, b_))
            e_b = np.abs(np.clip(n3[mm], a_, b_) - np.clip(r[mm], a_, b_))
            per.append(float(e_c.mean() - e_b.mean()))
        out["p44_gain_by_year"] = {
            "diffs": per,
            "randomization_p": randomization_p(np.array(per)),
            "negative": int(np.sum(np.array(per) < 0)),
            "G": len(per),
        }
    # P4-8: cutoffs whose plan-3 opening regime equals the real-time one (look-ahead zero by construction)
    cnt: dict[int, list[int]] = {}
    for f in sorted((root / "research" / "v3-wf").glob("*.json")):
        rr = json.loads(f.read_text(encoding="utf-8"))
        for pr in rr.get("panel", []):
            rt, st0 = pr.get("rec_realtime"), pr.get("rec_state0")
            if rt is None or st0 is None:
                continue
            y = int(pr["origin"][:4])
            cnt.setdefault(y, [0, 0])
            cnt[y][0] += 1
            cnt[y][1] += int(float(st0) != (1.0 if rt else 0.0))
    out["p48_by_year"] = {str(y): {"n": v[0], "differs": v[1]} for y, v in sorted(cnt.items())}
    # P4-5: the simulator's mean error on the whole common frame, for the near-zero comparison
    common = np.isfinite(r) & df[[f"{k}_cfo" for k in T.MODELS]].notna().all(1).to_numpy()
    out["p45_common_mean"] = {
        "n": int(common.sum()),
        "T1": float(np.mean(np.abs(df["T1_cfo"].to_numpy(float)[common] - r[common]))),
        "N3": float(np.mean(np.abs(df["N3_cfo"].to_numpy(float)[common] - r[common]))),
    }
    return out


# ---------------------------------------------------------------- main
def _dens_q(panel: pd.DataFrame, df: pd.DataFrame) -> pd.DataFrame:
    """Attach the conditional density quantiles (plan-3 levels) of T1 to the transmission frame."""
    q = [((st or {}).get("dens") or {}).get("cfo", {}).get("q") if isinstance(st, dict) else None for st in panel["st"]]
    k = panel[["ticker", "year"]].assign(dens_q=q).drop_duplicates(["ticker", "year"])
    return df.merge(k, on=["ticker", "year"], how="left")


def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items() if not str(k).startswith("_")}
    if isinstance(o, list | tuple):
        return [_clean(v) for v in o]
    if isinstance(o, np.generic):
        return o.item()
    if isinstance(o, float) and not np.isfinite(o):
        return None
    return o


def main(argv: list[str]) -> None:
    root, out_path = Path(argv[0]), Path(argv[1])
    out: dict = {"plan": "REVISION_PLAN_4.md (+ addendum 1)", "B": B, "B_wild": B_WILD, "test_years": TEST_YEARS}

    def step(name, fn, *a):
        print(f"== {name}", flush=True)
        try:
            out[name] = fn(*a)
        except Exception as e:  # recorded, never silent
            import traceback

            out[name] = {"error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-2000:]}
        out_path.write_text(json.dumps(_clean(out), default=str), encoding="utf-8")

    panel, df = load_spec(root, "v3-wf")
    df = _dens_q(panel, df)
    u = load_p4(root)
    # reproduction check: the P4 baseline health equals the plan-3 panel's base health
    chk = panel[["ticker", "year", "h_base"]].merge(u[["ticker", "year", "u_health"]], on=["ticker", "year"])
    out["reproduction"] = {
        "n": int(len(chk)),
        "share_equal": float(np.mean(np.isclose(chk["h_base"], chk["u_health"], atol=1e-6))),
        "max_abs_diff": float(np.nanmax(np.abs(chk["h_base"] - chk["u_health"]))) if len(chk) else None,
    }
    hist = history_features(df)
    rt = df[["ticker", "year"]].copy()
    hist = hist.merge(rt, on=["ticker", "year"], how="right")
    if "rev_ttm" in u:
        hist = hist.merge(u[["ticker", "year", "rev_ttm"]], on=["ticker", "year"], how="left")
        hist["rev_ttm_pct"] = hist["rev_ttm"] / (4 * hist["rev_mean16"]) * 100
    pv = panel[["ticker", "year", "rev_vol"]].drop_duplicates(["ticker", "year"])
    hist = hist.merge(pv, on=["ticker", "year"], how="left")
    step("P4-1", p41, df, u)
    ml_holder: dict = {}

    def run42():
        r, pt = p42(df, panel)
        ml_holder["pt"] = pt
        return r

    step("P4-2", run42)
    step("P4-3", p43, df, ml_holder.get("pt"))
    # inputs for P4-4 from the plan-3 replication file and the combination rows
    s1 = None
    cs = root / "research" / "_results" / "cross_spec_v3-wf_vs_v2-pre.json"
    if cs.exists():
        s1 = json.loads(cs.read_text(encoding="utf-8")).get("yearly")
    real, yrs = df["real_cfo"].to_numpy(float), df["year"].to_numpy(int)
    c = combine(df["N3_cfo"].to_numpy(float), df["T1_cfo"].to_numpy(float), real, yrs)
    comb = None
    if "_pred" in c:
        lo = np.array(
            [
                np.percentile(real[(yrs <= y - LAG) & np.isfinite(real)], 1) if (yrs <= y - LAG).any() else np.nan
                for y in yrs
            ]
        )
        hi = np.array(
            [
                np.percentile(real[(yrs <= y - LAG) & np.isfinite(real)], 99) if (yrs <= y - LAG).any() else np.nan
                for y in yrs
            ]
        )
        n3 = df["N3_cfo"].to_numpy(float)
        diff = np.abs(np.clip(c["_pred"], lo, hi) - np.clip(real, lo, hi)) - np.abs(
            np.clip(n3, lo, hi) - np.clip(real, lo, hi)
        )
        comb = (diff, yrs)
    step("P4-4", p44, df, s1, comb)
    step("P4-5", p45, df, hist)
    others = {}
    for spec in ("v2-pre", "v2-rev"):
        try:
            pnl, odf = load_spec(root, spec)
            others[spec] = _dens_q(pnl, odf)
        except Exception as e:
            out[f"load_{spec}"] = f"{type(e).__name__}: {e}"
    step("P4-6", p46, df, panel, hist, others)
    step("P4-7", p47, root)
    step("P4-8", p48, u, df)
    frames = {"v3-wf": panel}
    for spec in ("v3", "v2-pre"):
        try:
            frames[spec] = load_spec(root, spec)[0]
        except Exception as e:
            out[f"load_{spec}_p49"] = f"{type(e).__name__}: {e}"
    step("P4-9", p49, frames)
    print("done", flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
