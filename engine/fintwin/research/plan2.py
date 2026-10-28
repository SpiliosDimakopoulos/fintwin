"""Second-round tests (docs/REVISION_PLAN_2.md). Every decision rule used here was committed before the run.

1.1  revised specification: the fixed-cost prior chosen walk-forward from a grid, globally and by industry
1.2  where the over-reaction comes from: response of cash, EBITDA and capex to revenue, twin versus reality
1.3  cash forecasts: random walk + lambda * (twin - random walk), lambda from earlier origins
3    calibration: adaptive conformal inference and group-conditional scaling, learned on past errors only
4.2  timing of liquidity events (concordance), 4.3 event thresholds, 4.4 other downturns (2015-16, 2022),
4.5  mechanism of the free-cash-flow gain, 4.6 two-way (firm x year) bootstrap and Holm adjustment, 4.7 small firms
H1, H3 formal verdicts.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import stats as S
from . import transmission as T

PRIORS = {
    "baseline": 0.35,
    "fixed_prior_low": 0.20,
    "fixed_prior_high": 0.50,
    "prior_share_05": 0.05,
    "prior_share_10": 0.10,
    "prior_share_15": 0.15,
    "prior_share_25": 0.25,
    "prior_share_30": 0.30,
    "prior_share_45": 0.45,
    "prior_none": None,
}


# ---------------------------------------------------------------- frame of everything this module needs
def frame(panel: pd.DataFrame) -> pd.DataFrame:
    recs = []
    for r in panel.itertuples():
        st = r.st if isinstance(r.st, dict) else {}
        if not st.get("real_cfo"):
            continue
        rev = np.asarray(st["rev"], float)
        m = st.get("m", {})
        rec: dict = {
            "ticker": r.ticker,
            "year": r.year,
            "industry": getattr(r, "industry", ""),
            "rev_change": float(rev.sum() / 2 - 100),
            "log_rev": getattr(r, "log_rev", np.nan),
            "y_bk8": getattr(r, "y_bk8", np.nan),
            "y_burn8": getattr(r, "y_burn8", np.nan),
            "h_base": getattr(r, "h_base", np.nan),
            "health_t0": getattr(r, "health_t0", np.nan),
        }
        for k, key in (
            ("real_cfo", "real_cfo"),
            ("twin_cfo", "twin_cfo"),
            ("real_fcf", "real_fcf"),
            ("twin_fcf", "twin_fcf"),
            ("real_ebitda", "real_ebitda"),
            ("twin_ebitda", "twin_ebitda"),
            ("real_capex", "real_capex"),
            ("twin_capex", "twin_capex"),
            ("ols_cfo", "ols_cfo"),
            ("ols_fcf", "ols_fcf"),
            ("dyn_cfo", "dyn_cfo"),
        ):
            v = st.get(key)
            rec[k] = float(np.sum(np.asarray(v, float))) if v is not None else np.nan
        for var in ("cfo", "fcf"):
            mv = m.get(f"{var}16")
            rec[f"N3_{var}"] = float(mv) * rev.sum() if mv is not None else np.nan
        rec["N3_capex"] = rec["N3_cfo"] - rec["N3_fcf"]
        rec["N5_capex"] = rec["ols_cfo"] - rec["ols_fcf"]
        for name, v in (st.get("sens") or {}).items():
            rec[f"S_{name}_cfo"] = float(np.sum(np.asarray(v["cfo"], float)))
            rec[f"S_{name}_health"] = v.get("health")
        rec["S_baseline_cfo"], rec["S_baseline_health"] = rec["twin_cfo"], rec["h_base"]
        rc = st.get("realized_cont") or {}
        for k, v in rc.items():
            rec[f"rc_{k}"] = np.nan if v is None else float(v)
        probs = st.get("probs") or {}
        for abl in ("full", "no_loops"):
            pb = probs.get(abl) or {}
            for ev, curve in (pb.get("timing") or {}).items():
                if curve:
                    rec[f"tm_{abl}_{ev}"] = float(curve[-1])
                    rec[f"tmx_{abl}_{ev}"] = float(np.sum(1 - np.asarray(curve)))  # expected event-free quarters
            for ev, g in (pb.get("grid") or {}).items():
                for x, val in g.items():
                    rec[f"gr_{abl}_{ev}_{x}"] = val
        stt = st.get("static") or {}
        rec["st_cash_min"] = stt.get("cash_min")
        rec["st_fin_need"] = stt.get("fin_need")
        recs.append(rec)
    df = pd.DataFrame(recs)
    for c in df.columns:
        if c not in ("ticker", "industry"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def _mae(x: np.ndarray, y: np.ndarray) -> float:
    m = np.isfinite(x) & np.isfinite(y)
    return float(np.median(np.abs(x[m] - y[m]))) if m.any() else np.nan


# ---------------------------------------------------------------- 1.1 revised specification
def revised_spec(df: pd.DataFrame, firms: np.ndarray, b: int) -> dict:
    """For each test year choose the prior with the lowest median error on earlier years (globally, and within each
    industry with at least 300 earlier firm-years); evaluate on the test year only."""
    real = df["real_cfo"].to_numpy(float)
    names = [n for n in PRIORS if f"S_{n}_cfo" in df]
    yrs, ind = df["year"].to_numpy(), df["industry"].to_numpy()
    out: dict = {"grid_median_ae": {n: _mae(df[f"S_{n}_cfo"].to_numpy(float), real) for n in names}}
    for scope in ("global", "industry"):
        pred = np.full(len(df), np.nan)
        health = np.full(len(df), np.nan)
        chosen: dict = {}
        for y in sorted(set(yrs)):
            past = yrs <= y - 3
            if past.sum() < 500:
                continue
            groups = [None] if scope == "global" else sorted(set(ind[yrs == y]))
            for g in groups:
                pg = past & ((ind == g) if g is not None else True)
                if pg.sum() < 300:
                    pg = past
                err = {n: _mae(df[f"S_{n}_cfo"].to_numpy(float)[pg], real[pg]) for n in names}
                best = min(err, key=lambda k: err[k])
                te = (yrs == y) & ((ind == g) if g is not None else True)
                pred[te] = df[f"S_{best}_cfo"].to_numpy(float)[te]
                health[te] = df[f"S_{best}_health"].to_numpy(float)[te]
                chosen[f"{int(y)}{'' if g is None else ':' + str(g)}"] = best
        test = np.isfinite(pred) & np.isfinite(real)
        base = df["twin_cfo"].to_numpy(float)

        def med(u, t):
            return float(np.median(np.abs(u - t)))

        d = S.boot(lambda u, v, t: med(u, t) - med(v, t), [pred[test], base[test], real[test]], firms[test], b=b)
        bk = df["y_bk8"].to_numpy(float)
        auc_new = S.auc(-health[test], bk[test])
        auc_old = S.auc(-df["h_base"].to_numpy(float)[test], bk[test])
        out[scope] = {
            "n": int(test.sum()),
            "median_ae_revised": med(pred[test], real[test]),
            "median_ae_baseline": med(base[test], real[test]),
            "diff": {"diff": float(np.mean(d)), "ci": S.ci(d), "p": S.p_two_sided(d)},
            "auc_bk_revised": auc_new,
            "auc_bk_baseline": auc_old,
            "chosen": chosen,
        }
        out[scope]["accepted"] = bool(out[scope]["diff"]["ci"][1] < 0 and (auc_old - auc_new) <= 0.01)
    return out


# ---------------------------------------------------------------- 1.2 over-reaction
def overreaction(df: pd.DataFrame) -> dict:
    """Slope of each 8-quarter total (pp of trailing revenue) on the revenue change, twin and reality (OLS, winsorized)."""
    out: dict = {}
    x = df["rev_change"].to_numpy(float)
    for var in ("cfo", "ebitda", "capex"):
        res: dict = {}
        for who in ("real", "twin"):
            y = df[f"{who}_{var}"].to_numpy(float)
            m = np.isfinite(x) & np.isfinite(y)
            if m.sum() < 50:
                raise ValueError(f"{who}_{var}: not enough observations")
            lo, hi = np.nanpercentile(y[m], [1, 99])
            xl, xh = np.nanpercentile(x[m], [1, 99])
            slope = np.polyfit(np.clip(x[m], xl, xh), np.clip(y[m], lo, hi), 1)[0]
            res[who] = float(slope)
        res["ratio"] = res["twin"] / res["real"] if res["real"] else None
        out[var] = res
    return out


# ---------------------------------------------------------------- 1.3 cash forecasts
def cash_hybrid(fc: pd.DataFrame) -> dict:
    from ..backtest.scoring import crps_gaussian

    g = fc[(fc["var"] == "cash_like") & fc["rw_mu"].notna() & fc["q"].notna()].copy()
    if g.empty:
        return {}
    g["q50"] = [q[2] for q in g["q"]]
    g["origin_ts"] = pd.to_datetime(g["origin"])
    lam_grid = np.round(np.arange(0, 1.01, 0.05), 2)
    pred, lams = np.full(len(g), np.nan), {}
    y, rw, tw, sc = (g[c].to_numpy(float) for c in ("y", "rw_mu", "q50", "scale"))
    oy = g["origin_ts"].dt.year.to_numpy()
    for yr in sorted(set(oy)):
        past = oy < yr - 1  # forecasts whose four quarters were all reported before this origin
        if past.sum() < 200:
            continue
        err = [np.mean(np.abs(rw[past] + lam * (tw[past] - rw[past]) - y[past]) / sc[past]) for lam in lam_grid]
        lam = float(lam_grid[int(np.argmin(err))])
        lams[int(yr)] = lam
        te = oy == yr
        pred[te] = rw[te] + lam * (tw[te] - rw[te])
    sd = g["rw_sd"].to_numpy(float)
    m = (
        np.isfinite(pred)
        & np.isfinite(sd)
        & (sd > 0)
        & np.isfinite(g["crps_rw"].to_numpy(float))
        & np.isfinite(g["crps_twin"].to_numpy(float))
        & np.isfinite(sc)
        & (sc > 0)
    )
    crps_h = np.array([crps_gaussian(a, s_, t) for a, s_, t in zip(pred[m], sd[m], y[m], strict=True)])
    crps_rw = g["crps_rw"].to_numpy(float)[m]
    crps_tw = g["crps_twin"].to_numpy(float)[m]
    firms = g["ticker"].to_numpy()[m]
    s_ = sc[m]
    d = S.boot(lambda a, b_: 1 - np.mean(a) / np.mean(b_), [crps_h / s_, crps_rw / s_], firms, b=300)
    out = {
        "n": int(m.sum()),
        "lambda": lams,
        "skill_hybrid_vs_rw": float(1 - np.mean(crps_h / s_) / np.mean(crps_rw / s_)),
        "skill_hybrid_ci": S.ci(d),
        "skill_twin_vs_rw": float(1 - np.mean(crps_tw / s_) / np.mean(crps_rw / s_)),
        "accepted": bool(S.ci(d)[1] >= 0 and (1 - np.mean(crps_h / s_) / np.mean(crps_rw / s_)) >= 0),
    }
    out |= density_combos(g, oy)
    return out


TAUS = np.array([0.05, 0.25, 0.5, 0.75, 0.95])  # the twin's stored quantiles (experiments.py)


def _quantile_grid(q: np.ndarray, m: int = 50) -> np.ndarray:
    """(n x m) quantiles at tau_j = (j - 0.5) / m from the five stored quantiles: piecewise linear in the normal score
    of tau, extrapolated with the outer segments' slopes, so the tails stay continuous and monotone."""
    from scipy.stats import norm

    z_k, z = norm.ppf(TAUS), norm.ppf((np.arange(m) + 0.5) / m)
    q = np.sort(q, axis=1)
    j = np.clip(np.searchsorted(z_k, z) - 1, 0, len(z_k) - 2)
    slope = (q[:, j + 1] - q[:, j]) / (z_k[j + 1] - z_k[j])
    return q[:, j] + slope * (z - z_k[j])


def _crps_sorted(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """CRPS of equally weighted sorted samples (rows of x) at y: E|X - y| - 0.5 E|X - X'|."""
    m = x.shape[1]
    i = np.arange(1, m + 1)
    return np.mean(np.abs(x - y[:, None]), axis=1) - (x * (2 * i - m - 1)).sum(axis=1) / (m * m)


def density_combos(g: pd.DataFrame, oy: np.ndarray, m: int = 50, b: int = 300) -> dict:
    """E11: density combinations of the random walk (Gaussian) and the twin, with lambda chosen on mean scaled CRPS
    of forecasts already reported (the same rule as the location hybrid, which shifts the mean only).

    linear_pool: F = (1 - lambda) F_rw + lambda F_twin. quantile_avg: Q = (1 - lambda) Q_rw + lambda Q_twin
    (Vincentization). Both densities are discretized at m quantiles; the twin's from its five stored quantiles, so
    its CRPS here is an approximation of the sample CRPS (both are reported). Skill is against the discretized RW."""
    from scipy.stats import norm

    y, rw, sd, sc = (g[c].to_numpy(float) for c in ("y", "rw_mu", "rw_sd", "scale"))
    Q = np.array(g["q"].tolist(), float)
    ok = np.isfinite(y) & np.isfinite(rw) & np.isfinite(sd) & (sd > 0) & np.isfinite(sc) & (sc > 0)
    ok &= np.isfinite(Q).all(axis=1)
    y, rw, sd, sc, Q, oy_ = y[ok], rw[ok], sd[ok], sc[ok], Q[ok], oy[ok]
    firms = g["ticker"].to_numpy()[ok]
    if len(y) < 50:
        return {}
    z = norm.ppf((np.arange(m) + 0.5) / m)
    xr = rw[:, None] + sd[:, None] * z[None, :]
    xt = _quantile_grid(Q, m)
    grid = np.round(np.arange(0, 1.01, 0.05), 2)
    # linear pool, closed form: CRPS = (1-l) A_r + l A_t - 0.5 [(1-l)^2 D_rr + l^2 D_tt + 2 l (1-l) D_rt]
    A_r, A_t = np.mean(np.abs(xr - y[:, None]), 1), np.mean(np.abs(xt - y[:, None]), 1)
    D_rr = 2 * (A_r - _crps_sorted(xr, y))
    D_tt = 2 * (A_t - _crps_sorted(xt, y))
    D_rt = np.concatenate(
        [np.abs(xr[s, :, None] - xt[s, None, :]).mean(axis=(1, 2)) for s in np.array_split(np.arange(len(y)), 50)]
    )

    def pool(lam):
        return (1 - lam) * A_r + lam * A_t - 0.5 * ((1 - lam) ** 2 * D_rr + lam**2 * D_tt + 2 * lam * (1 - lam) * D_rt)

    def qavg(lam):
        return _crps_sorted((1 - lam) * xr + lam * xt, y)

    crps_r = _crps_sorted(xr, y) / sc
    out: dict = {"twin_crps_discretized_vs_sample": None}
    if "crps_twin" in g:
        ct = g["crps_twin"].to_numpy(float)[ok]
        out["twin_crps_discretized_vs_sample"] = float(np.nanmean(_crps_sorted(xt, y)) / np.nanmean(ct))
    for name, fn in (("linear_pool", pool), ("quantile_avg", qavg)):
        C = np.column_stack([fn(lam) / sc for lam in grid])  # n x lambdas, scaled CRPS
        pred, lams = np.full(len(y), np.nan), {}
        for yr in sorted(set(oy_)):
            past = oy_ < yr - 1  # forecasts whose four quarters were all reported before this origin
            if past.sum() < 200:
                continue
            j = int(np.argmin(C[past].mean(axis=0)))
            lams[int(yr)] = float(grid[j])
            pred[oy_ == yr] = C[oy_ == yr, j]
        te = np.isfinite(pred)
        if not te.any():
            out[name] = {"n": 0}
            continue
        skill = float(1 - pred[te].mean() / crps_r[te].mean())
        d = S.boot(
            lambda a, c: 1 - np.mean(a) / np.mean(c),
            [pred[te], crps_r[te]],
            firms[te],
            b=b,
            seed=S.SEEDS["cash_pool"][0],
        )
        out[name] = {
            "n": int(te.sum()),
            "lambda": lams,
            "skill_vs_rw": skill,
            "skill_ci": S.ci(d),
            "skill_twin_alone_vs_rw": float(1 - C[te, -1].mean() / crps_r[te].mean()),
            "accepted": bool(S.ci(d)[1] >= 0 and skill >= 0),  # the location hybrid's rule (REVISION_PLAN_2 1.3)
            "ci_excludes_zero": bool(S.ci(d)[0] > 0),
        }
    return out


# ---------------------------------------------------------------- 3 calibration
def calibration(fc: pd.DataFrame, panel: pd.DataFrame) -> dict:
    """Adaptive conformal inference (Gibbs and Candes 2021) on normalized errors in the order targets were reported,
    and group-conditional rescaling with factors learned only from already-reported errors."""
    from .calibration import REPORT_LAG, _norm

    feats = panel[["ticker", "year", "log_rev", "rev_vol"]].drop_duplicates(["ticker", "year"])
    out: dict = {}
    for var, g in fc[fc["q"].notna()].groupby("var"):
        d = _norm(g).merge(feats, on=["ticker", "year"], how="left")
        d["size_t"] = pd.qcut(d["log_rev"].rank(method="first"), 3, labels=False)
        d["vol_t"] = pd.qcut(d["rev_vol"].rank(method="first"), 3, labels=False)
        d["stress"] = d["target_ts"].between("2020-03-01", "2021-03-31")
        d["seen"] = d["target_ts"] + REPORT_LAG
        d = d.sort_values("origin_ts").reset_index(drop=True)
        res: dict = {}
        # (a) group-conditional split conformal: factor per (size tercile, volatility tercile) from reported errors
        c90 = np.full(len(d), np.nan)
        for o in sorted(d["origin_ts"].unique()):
            past = d[d["seen"] <= o]
            cur = d["origin_ts"] == o
            if len(past) < 200:
                continue
            for (st_, vt), idx in d[cur].groupby(["size_t", "vol_t"]).groups.items():
                pg = past[(past["size_t"] == st_) & (past["vol_t"] == vt)]
                pool = pg if len(pg) >= 100 else past
                c90[idx] = float(np.quantile(pool["s90"], 0.9))
        d["cond_hit"] = d["s90"] <= c90
        # (b) adaptive conformal: alpha_t updated after each reported error (gamma = 0.005), quantile of past scores
        # forecasts are issued in yearly batches, so alpha is updated once per batch of newly reported errors with
        # their average miscoverage (Gibbs and Candes 2021, eq. 2, with the batch error rate), gamma = 0.05
        alpha, gamma, hits, widths = 0.10, 0.05, np.full(len(d), np.nan), np.full(len(d), np.nan)
        seen_ts = d["seen"].to_numpy()
        used = np.zeros(len(d), bool)
        for o in sorted(d["origin_ts"].unique()):
            new = (~used) & (seen_ts <= o)
            judged = new & np.isfinite(widths)
            if judged.any():
                alpha = float(np.clip(alpha + gamma * (0.10 - (1 - hits[judged].astype(float)).mean()), 0.001, 0.5))
            used |= new
            cur = np.flatnonzero((d["origin_ts"] == o).to_numpy())
            if used.sum() < 200:
                continue
            q = float(np.quantile(d.loc[used, "s90"].to_numpy(), 1 - alpha))
            widths[cur] = q
            hits[cur] = d.loc[cur, "s90"].to_numpy() <= q
        d["aci_hit"] = hits
        d["aci_w"] = widths
        ev = d[np.isfinite(c90) & np.isfinite(hits)]
        res["n"] = int(len(ev))
        res["coverage"] = {k: float(ev[f"{k}_hit"].astype(float).mean()) for k in ("cond", "aci")}
        groups = {
            "year": ev["year"],
            "size": ev["size_t"],
            "volatility": ev["vol_t"],
            "stress": ev["stress"].map({True: "2020Q2-2021Q1", False: "other"}),
        }
        res["by"] = {}
        for name, gr in groups.items():
            t = ev.groupby(gr, observed=True)[["cond_hit", "aci_hit"]].agg(lambda s: float(s.astype(float).mean()))
            res["by"][name] = {str(k): {c: float(v) for c, v in r.items()} for k, r in t.iterrows()}
        cells = [v for grp in res["by"].values() for v in grp.values()]
        res["accepted"] = {m: bool(all(0.85 <= c[f"{m}_hit"] <= 0.95 for c in cells)) for m in ("cond", "aci")}
        res["width_vs_plain"] = float(np.nanmedian(ev["aci_w"]) / np.nanmedian(c90[ev.index]))
        out[var] = res
    return out


# ---------------------------------------------------------------- 4.2 timing, 4.3 thresholds
def harrell_c(risk: np.ndarray, time: np.ndarray, event: np.ndarray) -> float:
    """Concordance of a risk score with time to event (higher risk, earlier event); ties in risk count one half."""
    m = np.isfinite(risk) & np.isfinite(time)
    r, t, e = risk[m], time[m], event[m].astype(bool)
    num = den = 0.0
    # event times are quarters (few distinct values): for each, compare its events with the sorted risks of every
    # firm-year still event-free afterwards, O(n log n) instead of O(n^2)
    for tv in np.unique(t[e]):
        later = np.sort(r[t > tv])
        if not len(later):
            continue
        ri = r[e & (t == tv)]
        below = np.searchsorted(later, ri, "left")
        ties = np.searchsorted(later, ri, "right") - below
        den += len(later) * len(ri)
        num += below.sum() + 0.5 * ties.sum()
    return float(num / den) if den else np.nan


def timing(df: pd.DataFrame, firms: np.ndarray, b: int) -> dict:
    out: dict = {}
    for ev, static in (("cash_half", "st_cash_min"), ("debt_raise", "st_fin_need")):
        tcol = f"rc_t_{ev}"
        if tcol not in df or f"tm_full_{ev}" not in df:
            continue
        t_ev = df[tcol].to_numpy(float)
        event = np.isfinite(t_ev)
        time = np.where(event, t_ev, 9.0)  # censored after eight quarters
        risks = {
            "twin": df[f"tm_full_{ev}"].to_numpy(float),
            "no_loops": df.get(f"tm_no_loops_{ev}", pd.Series(np.nan, index=df.index)).to_numpy(float),
            "static": (-1 if static == "st_cash_min" else 1) * df[static].to_numpy(float),
        }
        res: dict = {k: harrell_c(v, time, event) for k, v in risks.items()}
        # SW-12: the paired difference on the firm-years where both risks exist, point estimate and bootstrap alike
        # (revision 2 compared C-indices of different samples and bootstrapped a random 6000-row subsample)
        both = np.isfinite(risks["twin"]) & np.isfinite(risks["no_loops"])
        cols = [risks["twin"][both], risks["no_loops"][both], time[both], event[both].astype(float)]

        def diff(a, c_, t_, e_):
            return harrell_c(a, t_, e_) - harrell_c(c_, t_, e_)

        d = S.boot(diff, cols, firms[both], b=b) if both.sum() > 1 else np.array([np.nan])
        est = float(diff(*cols)) if both.sum() > 1 else np.nan
        res["twin_minus_no_loops"] = {
            "diff": float(np.nanmean(d)),
            "ci": S.ci(d),
            "est": est,
            "p_centered": S.p_centered(est, d),
            "n": int(both.sum()),
        }
        res["events"] = int(event.sum())
        out[ev] = res
    return out


def thresholds(df: pd.DataFrame) -> dict:
    rc = {
        "cash": ("rc_cash_min_ratio", lambda v, x: v < x),
        "debt": ("rc_debt_raise_ratio", lambda v, x: v > x),
        "div": ("rc_div_ratio", lambda v, x: v < 1 - x),
        "capex": ("rc_capex_ratio", lambda v, x: v < 1 - x),
    }
    out: dict = {}
    for ev, (col, rule) in rc.items():
        if col not in df:
            continue
        out[ev] = {}
        for c in [c for c in df if c.startswith(f"gr_full_{ev}_")]:
            x = float(c.rsplit("_", 1)[1])
            v = df[col].to_numpy(float)
            y = np.where(np.isfinite(v), rule(v, x).astype(float), np.nan)
            m = np.isfinite(y)
            out[ev][str(x)] = {
                "rate": float(np.nanmean(y)),
                "auc_twin": S.auc(df[c].to_numpy(float)[m], y[m]),
                "auc_no_loops": S.auc(df[c.replace("full", "no_loops")].to_numpy(float)[m], y[m])
                if c.replace("full", "no_loops") in df
                else None,
            }
    return out


# ---------------------------------------------------------------- 4.4 other downturns
def episodes(panel: pd.DataFrame, b: int) -> dict:
    """The 2020 exposure design applied to the 2015-16 commodity bust and the 2022 rate shock: each firm gets the
    leave-one-out median realized revenue shock of its industry, the twin is read at that depth."""
    from .distress import _sic2, exposure_regression

    out: dict = {}
    for year in (2015, 2020, 2022):
        p = panel[(panel["year"] == year)].reset_index(drop=True)
        grid = sorted(c for c in p if c.startswith("dg_"))
        if not grid or "y_rev_drop8" not in p:
            continue
        p = p[p["y_rev_drop8"].notna()].reset_index(drop=True)
        drop = p["y_rev_drop8"].astype(float)
        sic2 = _sic2(p["cik"])
        by_sic = drop.groupby(sic2).transform(T.loo_median).reindex(p.index)
        n_sic = drop.groupby(sic2).transform("count").reindex(p.index).fillna(0)
        by_ff = drop.groupby(p["industry"]).transform(T.loo_median)
        depth = np.clip(-np.where(n_sic >= 6, by_sic, by_ff) / 100, 0, 0.8)
        cluster = np.where(n_sic >= 6, "sic" + sic2.astype(str), "ff" + p["industry"].astype(str))
        xs = np.array([float(c[3:]) for c in grid])
        H = p[grid].to_numpy(float)
        h = np.array(
            [
                np.interp(dd, xs, hh) if np.isfinite(dd) and np.isfinite(hh).all() else np.nan
                for dd, hh in zip(depth, H, strict=True)
            ]
        )
        res: dict = {
            "n": int(len(p)),
            "median_depth": float(np.nanmedian(depth)),
            "share_with_decline": float(np.mean(drop < 0)),
        }
        cum = "y_cum8" in p and p["y_cum8"].notna().any()
        for o, src in (
            ("y_burn8", "y_cum8" if cum else "y_burn8"),
            ("y_abn_burn8", "y_abn_cum8" if cum else "y_abn_burn8"),
        ):
            sev = -p[src].to_numpy(float)
            fcf = -p["fcf_margin"].to_numpy(float)
            reg = exposure_regression(sev, depth, -h, fcf, -p["health_t0"].to_numpy(float), cluster)
            res[o] = {
                "outcome": src,
                "rho_twin_at_exposure": S.rho(-h, sev),
                "rho_exposure": S.rho(depth, sev),
                "t": {k: v["t"] for k, v in reg["pre_specified"].items()},
                "t_robust": {k: v["t"] for k, v in reg["robust"].items()},
                "n": reg["n"],
                "n_clusters": reg["n_clusters"],
            }
        out[str(year)] = res
    gen = [out[y]["y_abn_burn8"]["t"]["twin"] > 2 for y in ("2015", "2022") if y in out]
    out["generalizes"] = bool(len(gen) == 2 and all(gen))  # the pre-specified rule
    rob = [out[y]["y_abn_burn8"]["t_robust"]["twin"] > 2 for y in ("2015", "2022") if y in out]
    out["generalizes_robust"] = bool(len(rob) == 2 and all(rob))
    return out


# ---------------------------------------------------------------- 4.5 FCF mechanism
def _combo(
    b_: np.ndarray, adj: np.ndarray, real: np.ndarray, yrs: np.ndarray, lo: float | None, hi: float | None
) -> np.ndarray:
    """Walk-forward combination base + lambda * (adjuster - base), lambda chosen on earlier years.

    `lo`, `hi`: winsorization limits of the training loss; None takes each year's limits from its training years
    only (E6, transmission.train_bounds)."""
    pr = np.full(len(b_), np.nan)
    bnd = T.train_bounds(real, yrs, "train") if lo is None else None
    for y in sorted(set(yrs)):
        tr = (yrs <= y - 3) & np.isfinite(b_) & np.isfinite(adj) & np.isfinite(real)
        if tr.sum() < 200:
            continue
        if bnd is not None:
            lo, hi = bnd[int(y)]
        err = [
            np.mean(np.abs(np.clip(b_[tr] + lam * (adj[tr] - b_[tr]), lo, hi) - np.clip(real[tr], lo, hi)))
            for lam in T.LAMBDAS
        ]
        lam = float(T.LAMBDAS[int(np.argmin(err))])
        te = yrs == y
        pr[te] = b_[te] + lam * (adj[te] - b_[te])
    return pr


def fcf_mechanism(df: pd.DataFrame) -> dict:
    """Out-of-sample gain of N3 + lambda(twin - N3) over N3 + lambda(regression - N3), for capex and operating cash
    flow separately; the share of the free-cash-flow gain that comes from capex."""
    out: dict = {}
    for var, base, null in (
        ("cfo", "N3_cfo", "ols_cfo"),
        ("capex", "N3_capex", "N5_capex"),
        ("fcf", "N3_fcf", "ols_fcf"),
    ):
        real = df[f"real_{var}"].to_numpy(float)
        b_, tw, nl = df[base].to_numpy(float), df[f"twin_{var}"].to_numpy(float), df[null].to_numpy(float)
        yrs = df["year"].to_numpy()
        lo, hi = np.nanpercentile(real, [1, 99])

        pt, pn = _combo(b_, tw, real, yrs, lo, hi), _combo(b_, nl, real, yrs, lo, hi)
        m = np.isfinite(pt) & np.isfinite(pn) & np.isfinite(real)
        e_t = np.mean(np.abs(np.clip(pt[m], lo, hi) - np.clip(real[m], lo, hi)))
        e_n = np.mean(np.abs(np.clip(pn[m], lo, hi) - np.clip(real[m], lo, hi)))
        out[var] = {"mae_twin_combo": float(e_t), "mae_null_combo": float(e_n), "gain": float(e_n - e_t)}
        # E6: limits from training years only, for the weight and for the evaluation of each test year
        bnd = T.train_bounds(real, yrs, "train")
        LO = np.array([bnd.get(int(y), (np.nan, np.nan))[0] for y in yrs])
        HI = np.array([bnd.get(int(y), (np.nan, np.nan))[1] for y in yrs])
        pt, pn = _combo(b_, tw, real, yrs, None, None), _combo(b_, nl, real, yrs, None, None)
        m = np.isfinite(pt) & np.isfinite(pn) & np.isfinite(real) & np.isfinite(LO)
        e_t = np.mean(np.abs(np.clip(pt[m], LO[m], HI[m]) - np.clip(real[m], LO[m], HI[m])))
        e_n = np.mean(np.abs(np.clip(pn[m], LO[m], HI[m]) - np.clip(real[m], LO[m], HI[m])))
        out[var]["train_bounds"] = {
            "mae_twin_combo": float(e_t),
            "mae_null_combo": float(e_n),
            "gain": float(e_n - e_t),
            "mae_twin_combo_unwinsorized": float(np.mean(np.abs(pt[m] - real[m]))),
            "mae_null_combo_unwinsorized": float(np.mean(np.abs(pn[m] - real[m]))),
            "n": int(m.sum()),
        }
    for key, src in (("", lambda v: out[v]["gain"]), ("_train_bounds", lambda v: out[v]["train_bounds"]["gain"])):
        g_fcf = src("fcf")
        share = float(src("capex") / g_fcf) if g_fcf else None
        out[f"capex_share_of_fcf_gain{key}"] = share
        out[f"capex_hypothesis_holds{key}"] = bool(share is not None and share > 0.5)
    return out


# ---------------------------------------------------------------- 4.6 two-way bootstrap, Holm
def boot_two_way(
    stat, cols: list[np.ndarray], firms: np.ndarray, years: np.ndarray, b: int = 300, seed: int | None = None
) -> np.ndarray:
    """Pigeonhole bootstrap: resample firms and years independently and keep the firm-years in both draws."""
    rng = np.random.default_rng(S.SEEDS["boot_two_way"][0] if seed is None else seed)
    fu, yu = pd.unique(firms), pd.unique(years)
    fi = {f: np.flatnonzero(firms == f) for f in fu}
    out = np.empty(b)
    for k in range(b):
        fs = rng.choice(fu, len(fu))
        ys = rng.choice(yu, len(yu))
        ycount = pd.Series(ys).value_counts()
        idx = np.concatenate([fi[f] for f in fs])
        mult = ycount.reindex(years[idx]).fillna(0).to_numpy(int)
        idx = np.repeat(idx, mult)
        out[k] = stat(*(c[idx] for c in cols))
    return out


def holm(pvals: dict[str, float]) -> dict[str, float]:
    items = sorted((p, k) for k, p in pvals.items() if p is not None and np.isfinite(p))
    m, out, running = len(items), {}, 0.0
    for i, (p, k) in enumerate(items):
        running = max(running, min(1.0, (m - i) * p))
        out[k] = running
    return out


def robustness_stats(tdf: pd.DataFrame, b: int) -> dict:
    """Key transmission statistics with firm x year clustering."""
    firms, years = tdf["ticker"].to_numpy(), tdf["year"].to_numpy()
    real, t1, n3 = (tdf[c].to_numpy(float) for c in ("real_cfo", "T1_cfo", "N3_cfo"))
    d = boot_two_way(S.rho, [t1 - n3, real - n3], firms, years, b)
    return {"incr_twin_vs_16q": S.rho(t1 - n3, real - n3), "ci_two_way": S.ci(d)}


# ---------------------------------------------------------------- 4.7 small firms
def small_firms(panel_all: pd.DataFrame, b: int) -> dict:
    lr = panel_all["log_rev"].astype(float)
    small = panel_all[(lr >= np.log(10e6)) & (lr < np.log(50e6))].reset_index(drop=True)
    if len(small) < 300:
        return {"n": int(len(small))}
    tr = T.section(small, b, panel=False)
    bk = small["y_bk8"].to_numpy(float)
    return {
        "n": int(len(small)),
        "n_firms": int(small["ticker"].nunique()),
        "incr_twin_vs_16q": tr.get("cfo", {}).get("incremental", {}).get("N3", {}).get("T1", {}).get("rho"),
        "median_ae": {k: tr.get("cfo", {}).get("levels", {}).get(k, {}).get("median_ae") for k in ("N3", "T1")},
        "auc_bk_twin": S.auc(-small["h_base"].to_numpy(float), bk),
        "auc_bk_formula": S.auc(-small["health_t0"].to_numpy(float), bk),
        "bk_events": int(np.nansum(bk)),
    }


# ---------------------------------------------------------------- verdicts
def verdicts(res: dict) -> dict:
    out: dict = {}
    bp = res.get("bankruptcy_panel", {}).get("all", {}).get("predictors", {})
    tf = (bp.get("formula") or {}).get("twin_minus") or {}
    out["H1_accepted"] = bool(tf and tf["ci"][0] > 0)
    dec = res.get("transmission", {}).get("panel", {}).get("decisions", {})
    wins = sum(1 for e in dec.values() if (e.get("twin_minus", {}).get("no_loops", {}).get("ci") or [0])[0] > 0)
    tim = res.get("plan2", {}).get("timing", {})
    c_ok = any((v.get("twin_minus_no_loops", {}).get("ci") or [0])[0] > 0 for v in tim.values())
    out["H3_auc_wins"] = wins
    out["H3_accepted"] = bool(wins >= 2 and c_ok)
    return out


# firm-level examples quoted in the paper: (label, CIK, cutoff year)
EXAMPLES = [
    ("amazon_2020", 1018724, 2020),
    ("ge_2016", 40545, 2016),
    ("ford_2020", 37996, 2020),
    ("gm_2020", 1467858, 2020),
]


def examples(panel: pd.DataFrame) -> dict:
    """The cases the paper describes, and how often a large departure from the 16-quarter margin has the right sign."""
    df = frame(panel)
    df["cik"] = panel.set_index("ticker")["cik"].groupby(level=0).first().reindex(df["ticker"]).to_numpy()
    dep, miss = df["twin_cfo"] - df["N3_cfo"], df["real_cfo"] - df["N3_cfo"]
    big = (dep.abs() > 8) & (np.exp(df["log_rev"]) > 2e9)
    out: dict = {
        "large_departures": int(big.sum()),
        "share_right_sign": float((np.sign(dep[big]) == np.sign(miss[big])).mean()) if big.any() else None,
    }
    for label, cik, year in EXAMPLES:
        row = df[(df["cik"] == cik) & (df["year"] == year)]
        if len(row):
            r = row.iloc[0]
            out[label] = {
                "rev_change": float(r["rev_change"]),
                "rule": float(r["N3_cfo"]),
                "twin": float(r["twin_cfo"]),
                "real": float(r["real_cfo"]),
            }
    return out


def census_check() -> dict:
    """How many of the first version's 35 Chapter 11 filers of 2020 the 8-K census finds, and repeat filings."""
    u = pd.read_csv(S.DATA / "universe_edgar.csv", dtype={"bankruptcy_8k": str})
    b = pd.read_csv(S.DATA / "bankruptcies_2020.csv")
    dates = dict(zip(u["cik"].astype(int), u["bankruptcy_8k"], strict=True))
    found = [
        isinstance(dates.get(int(c)), str) and any(x.startswith("2020") for x in dates[int(c)].split(";"))
        for c in b["cik"]
    ]
    n = u["bankruptcy_8k"].dropna().str.split(";").map(len)
    return {
        "legacy": int(len(b)),
        "found": int(sum(found)),
        "share_repeat": float((n > 1).mean()),
        "missing": b.loc[[not f for f in found], "name"].tolist(),
    }


def attrition(panel: pd.DataFrame) -> dict:
    """The transmission test needs eight reported quarters after the cutoff, so it conditions on survival. How many
    firm-years drop out, how many of the later bankruptcies, and do the main errors change when the surviving
    firm-years are reweighted by the inverse probability of survival (a logit on the cutoff's characteristics)?"""
    import statsmodels.api as sm

    has = np.array([bool((st or {}).get("real_cfo")) if isinstance(st, dict) else False for st in panel["st"]])
    bk = panel["y_bk8"].to_numpy(float)
    out: dict = {
        "firm_years": int(len(panel)),
        "with_outcome": int(has.sum()),
        "share_with_outcome": float(has.mean()),
        "share_with_outcome_bankrupt": float(has[bk == 1].mean()) if (bk == 1).any() else None,
        "share_with_outcome_not_bankrupt": float(has[bk == 0].mean()),
    }
    feats = ["fcf_margin", "log_rev", "health_t0", "z2", "nd_ebitda", "rev_vol"]
    X = pd.DataFrame({c: S.pct(panel[c].to_numpy(float)) if c in panel else np.nan for c in feats}).fillna(0.5)
    X = pd.concat([X, pd.get_dummies(panel["year"], prefix="y", drop_first=True, dtype=float)], axis=1)
    fit = sm.Logit(has.astype(float), sm.add_constant(X)).fit(disp=False)
    ps = np.clip(np.asarray(fit.predict(sm.add_constant(X))), 0.05, 1.0)
    df = frame(panel[has].reset_index(drop=True))
    w = 1 / ps[has][: len(df)] if len(df) == has.sum() else None
    if w is not None:

        def wmed(x, ww):
            m = np.isfinite(x)
            o = np.argsort(x[m])
            c = np.cumsum(ww[m][o])
            return float(x[m][o][np.searchsorted(c, c[-1] / 2)])

        for k in ("twin_cfo", "N3_cfo"):
            e = np.abs(df[k].to_numpy(float) - df["real_cfo"].to_numpy(float))
            out[f"median_ae_{k}"] = float(np.nanmedian(e))
            out[f"median_ae_{k}_ipw"] = wmed(e, w)
    return out


def _safe(fn, *args) -> dict:
    """Run one analysis; a failure (e.g. outcomes missing in an older run) is recorded instead of stopping the rest."""
    try:
        return fn(*args)
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


def section(panel_all: pd.DataFrame, panel: pd.DataFrame, fc: pd.DataFrame, b: int) -> dict:
    df = frame(panel)
    firms = df["ticker"].to_numpy() if len(df) else np.array([])
    out: dict = {
        "revised_spec": _safe(revised_spec, df, firms, b),
        "overreaction": _safe(overreaction, df),
        "cash_hybrid": _safe(cash_hybrid, fc),
        "calibration": _safe(calibration, fc, panel),
        "timing": _safe(timing, df, firms, max(b // 5, 50)),
        "thresholds": _safe(thresholds, df),
        "episodes": _safe(episodes, panel, b),
        "fcf_mechanism": _safe(fcf_mechanism, df),
        "small_firms": _safe(small_firms, panel_all, b),
        "examples": _safe(examples, panel),
        "census": _safe(census_check),
        "attrition": _safe(attrition, panel),
    }
    out["two_way"] = _safe(lambda: robustness_stats(T.add_shrunk(T.frame(panel)), b))
    return out
