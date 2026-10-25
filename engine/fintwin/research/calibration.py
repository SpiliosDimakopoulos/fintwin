"""Calibration of the twin's predictive distributions, unconditionally and where it matters (reviewer point 9).

Online conformal rescaling: the interval for a forecast made at origin O is widened by the 90% quantile of past
normalized errors, using only forecasts whose target quarter had been *reported* by O (quarter end + 90 days,
`REPORT_LAG`). The first version used every forecast from earlier origins, which can include quarters reported
after O.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

REPORT_LAG = pd.Timedelta(days=90)


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
    return d


def conformal(d: pd.DataFrame) -> pd.DataFrame:
    d = d.copy()
    d["c90"] = np.nan
    for o in sorted(d["origin_ts"].unique()):
        past = d[d["target_ts"] + REPORT_LAG <= o]
        if len(past) >= 40:
            d.loc[d["origin_ts"] == o, "c90"] = float(np.quantile(past["s90"], 0.9))
    d["conf90"] = d["s90"] <= d["c90"]
    return d[d["c90"].notna()]


def section(fc: pd.DataFrame, panel: pd.DataFrame) -> dict:
    if fc.empty or "q" not in fc:
        return {}
    fc = fc[fc["q"].notna()]
    feats = panel[["ticker", "year", "log_rev", "nd_ebitda", "rev_vol", "industry"]].drop_duplicates(["ticker", "year"])
    out: dict = {}
    for var, g in fc.groupby("var"):
        d = conformal(_norm(g)).merge(feats, on=["ticker", "year"], how="left")
        d["stress"] = d["target_ts"].between("2020-03-01", "2021-03-31")
        d["below_q05"] = d["y"] < d["q05"]
        res: dict = {
            "n": int(len(d)),
            "raw90": float(d["hit90"].mean()),
            "conformal90": float(d["conf90"].mean()),
            "mean_pit": float(d["pit_twin"].mean()),
            "below_q05": float((d["y"] < d["q05"]).mean()),
            "above_q95": float((d["y"] > d["q95"]).mean()),
            "bias_median": float(((d["y"] - d["q50"]) / d["scale"]).median()),
        }
        groups = {
            "year": d["year"],
            "horizon": d["h"],
            "stress_2020": d["stress"].map({True: "2020Q2-2021Q1 targets", False: "other targets"}),
            "size": pd.qcut(d["log_rev"].rank(method="first"), 3, labels=["small", "mid", "large"]),
            "leverage": pd.qcut(d["nd_ebitda"].rank(method="first"), 3, labels=["low", "mid", "high"]),
            "volatility": pd.qcut(d["rev_vol"].rank(method="first"), 3, labels=["low", "mid", "high"]),
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
                cov_type="cluster", cov_kwds={"groups": pd.factorize(d.loc[ok, "ticker"])[0]}
            )
            res["width_regression"] = {k: {"coef": float(m.params[k]), "t": float(m.tvalues[k])} for k in X}
            # and do the realized errors scale the same way?
            e = np.log((d["y"] - d["q50"]).abs().clip(lower=1e-9) / d["scale"].clip(lower=1e-9))
            m2 = sm.OLS(e[ok], sm.add_constant((X[ok] - X[ok].mean()) / X[ok].std())).fit(
                cov_type="cluster", cov_kwds={"groups": pd.factorize(d.loc[ok, "ticker"])[0]}
            )
            res["error_regression"] = {k: {"coef": float(m2.params[k]), "t": float(m2.tvalues[k])} for k in X}
        out[var] = res
    return out
