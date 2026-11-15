"""Calibration of the twin's predictive distributions, unconditionally and where it matters (reviewer point 9).

Online conformal rescaling: the interval for a forecast made at origin O is widened by the 90% quantile of past
normalized errors, using only forecasts whose target quarter had been *reported* by O: its actual first filing date,
or quarter end + 90 days (`REPORT_LAG`) where that date is unknown. The first version used every forecast from
earlier origins, which can include quarters reported after O.

Also here: PIT histograms, interval scores and conditional-coverage tests, an asymmetric conformal interval
(the symmetric one cannot correct skew), the density test of the 8-quarter totals against Gaussian and empirical
residual densities around the 16-quarter margin, and DM tests by horizon.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..backtest.batch import dm_stat, seen_by
from ..backtest.scoring import crps_gaussian, crps_samples
from .units import unit

REPORT_LAG = pd.Timedelta(days=90)
ALPHA = 0.10


def _norm(fc: pd.DataFrame) -> pd.DataFrame:
    q = np.array(fc["q"].tolist(), float)
    d = fc.copy()
    d["q05"], d["q25"], d["q50"], d["q75"], d["q95"] = q.T
    d["half90"] = ((d["q95"] - d["q05"]) / 2).clip(lower=1e-9)
    d["s90"] = (d["y"] - d["q50"]).abs() / d["half90"]
    d["hit90"] = (d["y"] >= d["q05"]) & (d["y"] <= d["q95"])
    d["origin_ts"] = pd.to_datetime(d["origin"])
    d["target_ts"] = pd.to_datetime(d["target"])
    d["year"] = d["origin_ts"].dt.year
    # one-sided scores for the asymmetric interval: distance below / above the median in units of that side's width
    d["s_lo"] = (d["q50"] - d["y"]) / (d["q50"] - d["q05"]).clip(lower=1e-9)
    d["s_hi"] = (d["y"] - d["q50"]) / (d["q95"] - d["q50"]).clip(lower=1e-9)
    d["is90"] = interval_score(d["q05"].to_numpy(), d["q95"].to_numpy(), d["y"].to_numpy(), ALPHA)
    return d


def interval_score(lo: np.ndarray, hi: np.ndarray, y: np.ndarray, alpha: float = ALPHA) -> np.ndarray:
    """Gneiting and Raftery (2007) interval score of a central (1 - alpha) interval (lower is better)."""
    lo, hi, y = (np.asarray(v, float) for v in (lo, hi, y))
    return (hi - lo) + 2 / alpha * np.maximum(lo - y, 0) + 2 / alpha * np.maximum(y - hi, 0)


def conformal(d: pd.DataFrame) -> pd.DataFrame:
    d = d.copy()
    d["c90"] = d["c_lo"] = d["c_hi"] = np.nan
    filed = d["filed"] if "filed" in d else None
    for o in sorted(d["origin_ts"].unique()):
        past = d[seen_by(d["target_ts"], filed, pd.Timestamp(o), REPORT_LAG.days).to_numpy()]
        past = past[
            np.isfinite(past[["s90", "s_lo", "s_hi"]].to_numpy(float)).all(axis=1)
        ]  # one NaN poisons a quantile
        if len(past) >= 40:
            here = d["origin_ts"] == o
            d.loc[here, "c90"] = float(np.quantile(past["s90"], 0.9))
            # asymmetric: each tail gets its own factor at 1 - alpha/2, so a skewed error distribution is matched
            d.loc[here, "c_lo"] = float(np.quantile(past["s_lo"], 1 - ALPHA / 2))
            d.loc[here, "c_hi"] = float(np.quantile(past["s_hi"], 1 - ALPHA / 2))
    d["conf90"] = d["s90"] <= d["c90"]
    d["conf90_asym"] = (d["s_lo"] <= d["c_lo"]) & (d["s_hi"] <= d["c_hi"])
    lo = d["q50"] - d["c_lo"] * (d["q50"] - d["q05"])
    hi = d["q50"] + d["c_hi"] * (d["q95"] - d["q50"])
    d["is90_asym"] = interval_score(lo.to_numpy(), hi.to_numpy(), d["y"].to_numpy(), ALPHA)
    half = d["c90"] * d["half90"]
    d["is90_conf"] = interval_score((d["q50"] - half).to_numpy(), (d["q50"] + half).to_numpy(), d["y"].to_numpy())
    return d[d["c90"].notna()]


def christoffersen(hits: pd.Series, groups: pd.Series, order: pd.Series, level: float = 1 - ALPHA) -> dict:
    """Christoffersen (1998) tests of interval forecasts: unconditional coverage (LR_uc), independence of misses
    within each firm's sequence of targets (LR_ind; transitions pooled over firms) and conditional coverage
    (LR_cc = LR_uc + LR_ind, chi2 with 2 df)."""
    from scipy.stats import chi2

    miss = (~hits.astype(bool)).astype(int)
    d = pd.DataFrame({"m": miss.to_numpy(), "g": groups.to_numpy(), "o": order.to_numpy()}).sort_values(["g", "o"])
    n1 = int(d["m"].sum())
    n = len(d)
    if n < 20:
        return {}
    pi, p = n1 / n, 1 - level

    def ll(k: int, m: int, q: float) -> float:
        q = min(max(q, 1e-12), 1 - 1e-12)
        return (m - k) * np.log(1 - q) + k * np.log(q)

    lr_uc = -2 * (ll(n1, n, p) - ll(n1, n, pi))
    prev = d.groupby("g")["m"].shift(1)
    t = d[prev.notna()].assign(prev=prev[prev.notna()].astype(int))
    n00 = int(((t["prev"] == 0) & (t["m"] == 0)).sum())
    n01 = int(((t["prev"] == 0) & (t["m"] == 1)).sum())
    n10 = int(((t["prev"] == 1) & (t["m"] == 0)).sum())
    n11 = int(((t["prev"] == 1) & (t["m"] == 1)).sum())
    out = {"n": n, "miss_rate": pi, "lr_uc": float(lr_uc), "p_uc": float(chi2.sf(lr_uc, 1))}
    if n00 + n01 and n10 + n11:
        p01, p11 = n01 / (n00 + n01), n11 / (n10 + n11)
        p1 = (n01 + n11) / (n00 + n01 + n10 + n11)
        lr_ind = -2 * (ll(n01 + n11, n00 + n01 + n10 + n11, p1) - ll(n01, n00 + n01, p01) - ll(n11, n10 + n11, p11))
        out |= {
            "lr_ind": float(lr_ind),
            "p_ind": float(chi2.sf(lr_ind, 1)),
            "lr_cc": float(lr_uc + lr_ind),
            "p_cc": float(chi2.sf(lr_uc + lr_ind, 2)),
            "p_miss_after_miss": float(p11),
            "p_miss_after_hit": float(p01),
        }
    return out


def pit_hist(pit: np.ndarray, bins: int = 10) -> dict:
    """PIT histogram (shares per bin) and a chi-square test of uniformity."""
    from scipy.stats import chisquare

    pit = np.asarray(pit, float)
    pit = pit[np.isfinite(pit)]
    if not len(pit):
        return {}
    counts = np.histogram(pit, bins=bins, range=(0, 1))[0]
    return {
        "shares": (counts / len(pit)).round(4).tolist(),
        "n": int(len(pit)),
        "chi2_p": float(chisquare(counts).pvalue),
    }


def _tertiles(x: pd.Series, labels: list[str]) -> pd.Series:
    """Tertile labels by rank; all missing where fewer than 3 values are known (pd.qcut would raise)."""
    r = x.astype(float).rank(method="first")
    if r.notna().sum() < 3:
        return pd.Series(np.nan, index=x.index)
    return pd.qcut(r, 3, labels=labels)


def section(fc: pd.DataFrame, panel: pd.DataFrame) -> dict:
    if fc.empty or "q" not in fc:
        return {}
    fc = fc[fc["q"].map(lambda q: isinstance(q, (list, tuple)) and bool(np.isfinite(np.asarray(q, float)).all()))]
    feats = panel[["ticker", "year", "log_rev", "nd_ebitda", "rev_vol", "industry"]].drop_duplicates(["ticker", "year"])
    out: dict = {}
    for var, g in fc.groupby("var"):
        d = conformal(_norm(g)).merge(feats, on=["ticker", "year"], how="left")
        if len(d) < 30:  # no origin had 40 reported past forecasts: nothing to calibrate (qcut needs rows)
            out[var] = {"n": int(len(d)), "skipped": "fewer than 30 conformal forecasts"}
            continue
        d["stress"] = d["target_ts"].between("2020-03-01", "2021-03-31")
        d["below_q05"] = d["y"] < d["q05"]
        res: dict = {
            "n": int(len(d)),
            "raw90": float(d["hit90"].mean()),
            "conformal90": float(d["conf90"].mean()),
            "conformal90_asym": float(d["conf90_asym"].mean()),
            "mean_pit": float(d["pit_twin"].mean()),
            "below_q05": float((d["y"] < d["q05"]).mean()),
            "above_q95": float((d["y"] > d["q95"]).mean()),
            "bias_median": float(((d["y"] - d["q50"]) / d["scale"]).median()),
            # the whole PIT distribution, interval scores (scaled by trailing quarterly revenue) and the
            # conditional-coverage tests, before and after conformal rescaling
            "pit_hist": pit_hist(d["pit_twin"].to_numpy(float)),
            "interval_score90": {
                k: float((d[c] / d["scale"].clip(lower=1e-9)).mean())
                for k, c in (("raw", "is90"), ("conformal", "is90_conf"), ("conformal_asym", "is90_asym"))
            },
            "coverage_tests": {
                "raw": christoffersen(d["hit90"], d["ticker"], d["target_ts"]),
                "conformal": christoffersen(d["conf90"], d["ticker"], d["target_ts"]),
                "conformal_asym": christoffersen(d["conf90_asym"], d["ticker"], d["target_ts"]),
            },
        }
        if "pit_rw_emp" in d:
            res["pit_hist_rw_emp"] = pit_hist(d["pit_rw_emp"].to_numpy(float))
        groups = {
            "year": d["year"],
            "horizon": d["h"],
            "stress_2020": d["stress"].map({True: "2020Q2-2021Q1 targets", False: "other targets"}),
            "size": _tertiles(d["log_rev"], ["small", "mid", "large"]),
            "leverage": _tertiles(d["nd_ebitda"], ["low", "mid", "high"]),
            "volatility": _tertiles(d["rev_vol"], ["low", "mid", "high"]),
            "industry": d["industry"],
        }
        res["by"] = {}
        for name, gr in groups.items():
            t = d.groupby(gr, observed=True).agg(
                n=("hit90", "size"),
                raw90=("hit90", "mean"),
                conf90=("conf90", "mean"),
                below_q05=("below_q05", "mean"),
                pit=("pit_twin", "mean"),
            )
            res["by"][name] = {str(k): {c: float(v) for c, v in r.items()} for k, r in t.iterrows() if r["n"] >= 30}
        # do intervals widen where they should? log relative width on firm characteristics
        import statsmodels.api as sm

        w = np.log((d["q95"] - d["q05"]).clip(lower=1e-9) / d["scale"].clip(lower=1e-9))
        X = d[["log_rev", "nd_ebitda", "rev_vol"]].astype(float)
        X["nd_ebitda"] = X["nd_ebitda"].clip(-5, 20)
        ok = X.notna().all(axis=1) & np.isfinite(w)
        if ok.sum() > 100:
            m = sm.OLS(w[ok], sm.add_constant((X[ok] - X[ok].mean()) / X[ok].std())).fit(
                cov_type="cluster", cov_kwds={"groups": pd.factorize(unit(d).loc[ok])[0]}
            )
            res["width_regression"] = {k: {"coef": float(m.params[k]), "t": float(m.tvalues[k])} for k in X}
            # and do the realized errors scale the same way?
            e = np.log((d["y"] - d["q50"]).abs().clip(lower=1e-9) / d["scale"].clip(lower=1e-9))
            m2 = sm.OLS(e[ok], sm.add_constant((X[ok] - X[ok].mean()) / X[ok].std())).fit(
                cov_type="cluster", cov_kwds={"groups": pd.factorize(unit(d).loc[ok])[0]}
            )
            res["error_regression"] = {k: {"coef": float(m2.params[k]), "t": float(m2.tvalues[k])} for k in X}
        out[var] = res
    return out


# ---------------------------------------------------------------- DM by horizon
def dm_by_horizon(fc: pd.DataFrame, a: str = "crps_twin", refs: tuple[str, ...] = ("crps_rw", "crps_rw_emp")) -> dict:
    """Mean CRPS difference (a - ref) and a firm-clustered DM statistic per variable and horizon, not pooled."""
    out: dict = {}
    for (var, h), g in fc.groupby(["var", "h"]):
        r: dict = {}
        for ref in refs:
            if ref not in g:
                continue
            x, y = pd.to_numeric(g[a], errors="coerce"), pd.to_numeric(g[ref], errors="coerce")
            ok = (x.notna() & y.notna()).to_numpy()
            if ok.sum() < 10:
                continue
            r[ref] = {
                "skill": float(1 - x[ok].mean() / y[ok].mean()),
                **dm_stat((x - y).to_numpy()[ok], unit(g).to_numpy()[ok]),
            }
        out.setdefault(str(var), {})[int(h)] = r
    return out


# ---------------------------------------------------------------- density of the 8-quarter totals
DENSITY_LAG = 3  # training years <= Y-3, the walk-forward rule of revision 2 (all eight outcome quarters reported)
MIN_TRAIN = 300


def dm_two_way(d: np.ndarray, firms: np.ndarray, years: np.ndarray) -> dict:
    """DM test on loss differences with two-way (firm x year) cluster-robust variance (Cameron, Gelbach and Miller
    2011), t(G-1) critical values with G the smaller number of clusters; the variance falls back to the larger
    one-way term if the two-way sum is not positive."""
    from scipy import stats as _st

    d = np.asarray(d, float)
    m = np.isfinite(d)
    d, firms, years = d[m], np.asarray(firms)[m], np.asarray(years)[m]
    n = len(d)
    if n < 30:
        return {"n": int(n), "mean": float(d.mean()) if n else None, "t": None, "p": None}
    e = d - d.mean()

    def v(g: np.ndarray) -> tuple[float, int]:
        s = pd.Series(e).groupby(g).sum().to_numpy()
        G = len(s)
        return (G / (G - 1)) * float(np.sum(s**2)) / n**2, G

    vf, gf = v(firms)
    vy, gy = v(years)
    vfy, _ = v(np.char.add(firms.astype(str), np.char.add("|", years.astype(str))))
    var = vf + vy - vfy
    if not var > 0:
        var = max(vf, vy)
    G = min(gf, gy)
    t = float(d.mean() / np.sqrt(var))
    return {
        "n": int(n),
        "firms": int(gf),
        "years": int(gy),
        "mean": float(d.mean()),
        "t": t,
        "p": float(2 * _st.t.sf(abs(t), G - 1)),
        "p_less": float(_st.t.cdf(t, G - 1)),  # H1: the first forecast has the lower CRPS
    }


def density_frame(panel: pd.DataFrame) -> pd.DataFrame:
    """Per firm-year and variable: realized 8-quarter total, the 16-quarter-margin point (N3) on realized revenue, and
    the twin's stored density (all in % of trailing revenue)."""
    recs = []
    for r in panel.itertuples():
        st = r.st if isinstance(r.st, dict) else {}
        dens, m = st.get("dens") or {}, st.get("m") or {}
        if not dens or st.get("rev") is None:
            continue
        revsum = float(np.sum(st["rev"]))
        for var in ("cfo", "fcf"):
            dv, mv = dens.get(var), m.get(f"{var}16")
            if not dv or st.get(f"real_{var}") is None:
                continue
            recs.append(
                {
                    "ticker": r.ticker,
                    "cluster": getattr(r, "cluster", r.ticker),
                    "year": int(r.year),
                    "var": var,
                    "real": float(np.sum(st[f"real_{var}"])),
                    "n3": float(mv) * revsum if mv is not None else np.nan,
                    "crps_twin": dv["crps"],
                    "pit_twin": dv["pit"],
                    "q": dv["q"],
                }
            )
    return pd.DataFrame(recs)


def density_section(panel: pd.DataFrame) -> dict:
    """REVISION_PLAN_3 §2.2 B1: CRPS and PIT of the twin's 8-quarter OCF / FCF totals against a Gaussian and an
    empirical density of the residuals around the 16-quarter margin, both estimated on training years <= Y-3; DM on
    the CRPS differences with firm x year clustering. Success: twin CRPS below the benchmark's with p < 0.05."""
    from scipy.stats import norm

    from ..research.experiments import QLEVELS

    df = density_frame(panel)
    if df.empty:
        return {}
    out: dict = {"rule": f"benchmarks estimated on cutoffs <= Y-{DENSITY_LAG}"}
    i05, i95 = QLEVELS.index(5), QLEVELS.index(95)
    grid = np.linspace(0.0005, 0.9995, 1000)
    for var, g in df.groupby("var"):
        g = g.reset_index(drop=True)
        n = len(g)
        cg, ce, pg, pe = (np.full(n, np.nan) for _ in range(4))
        yrs = g["year"].to_numpy()
        real, n3 = g["real"].to_numpy(float), g["n3"].to_numpy(float)
        for t in sorted(set(yrs.tolist())):
            tr = (yrs <= t - DENSITY_LAG) & np.isfinite(real) & np.isfinite(n3)
            if tr.sum() < MIN_TRAIN:
                continue
            e = real[tr] - n3[tr]
            mu, sd = float(e.mean()), float(e.std(ddof=1))
            qs = np.quantile(e, grid)  # deterministic 1000-point summary of the training residuals
            for i in np.flatnonzero((yrs == t) & np.isfinite(n3) & np.isfinite(real)):
                cg[i] = crps_gaussian(n3[i] + mu, sd, real[i])
                pg[i] = float(norm.cdf((real[i] - n3[i] - mu) / sd))
                ce[i] = crps_samples(n3[i] + qs, real[i])
                pe[i] = float(np.mean(n3[i] + qs <= real[i]))
        tw = g["crps_twin"].to_numpy(float)
        ok = np.isfinite(cg) & np.isfinite(tw)
        q = np.array(g["q"].tolist(), float)
        res: dict = {
            "n": int(ok.sum()),
            "test_years": sorted({int(t) for t in yrs[ok]}),
            "crps": {"twin": float(tw[ok].mean()), "gaussian": float(cg[ok].mean()), "empirical": float(ce[ok].mean())},
            "pit": {
                "twin": pit_hist(g["pit_twin"].to_numpy(float)[ok]),
                "gaussian": pit_hist(pg[ok]),
                "empirical": pit_hist(pe[ok]),
            },
            "coverage90_twin": float(((real >= q[:, i05]) & (real <= q[:, i95]))[ok].mean()) if ok.any() else None,
        }
        for name, c in (("gaussian", cg), ("empirical", ce)):
            dm = dm_two_way(tw[ok] - c[ok], unit(g).to_numpy()[ok], yrs[ok])
            by_year = {
                int(t): float(np.mean(tw[ok & (yrs == t)] - c[ok & (yrs == t)])) for t in sorted(set(yrs[ok].tolist()))
            }
            res[f"vs_{name}"] = {
                "dm": dm,
                "by_year_mean_diff": by_year,
                "years_twin_better": int(sum(v < 0 for v in by_year.values())),
                "success": bool(dm.get("p_less") is not None and dm["mean"] < 0 and dm["p_less"] < 0.05),
            }
        out[str(var)] = res
    return out
