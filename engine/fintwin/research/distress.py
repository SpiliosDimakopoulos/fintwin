"""Bankruptcy tests on the census, the hard task among already-weak firms, and fragility versus exposure in 2020.

The first version of the paper compared 27 prominent Chapter 11 filers of 2020 with today's S&P 500, a task that
size alone nearly solves and in which the survivors are known to have survived. Here the event is any Item 1.03
8-K, the population is every non-financial XBRL filer alive at the cutoff, and a second test asks the question
practitioners care about: among firms that already look weak, which ones fail?
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import stats as S
from .units import cluster_of, unit

DATA = S.DATA
EPS_LOG = 1e-4  # probabilities are clipped to [EPS_LOG, 1 - EPS_LOG] for the log score: 500-2000 paths give exact 0s


def _risk(df: pd.DataFrame, health: str, pb: str | None) -> pd.DataFrame:
    R = S.risk_frame(df, health, pb)
    if "h_base" in df and health != "h_base":
        R["twin_base"] = -df["h_base"].astype(float)
    return R


def _weak(df: pd.DataFrame, by: str | None) -> np.ndarray:
    """Already weak at the cutoff: bottom quintile of Altman's Z'' (within the cutoff year) or negative FCF margin."""
    z = df["z2"].astype(float)
    q = z.groupby(df[by]).transform(lambda s: s.quantile(0.2)) if by else z.quantile(0.2)
    return ((z <= q) | (df["fcf_margin"].astype(float) < 0)).to_numpy()


def auc_table(df: pd.DataFrame, y: np.ndarray, R: pd.DataFrame, firms: np.ndarray | None, b: int) -> dict:
    out: dict = {"n": int(np.isfinite(y).sum()), "events": int(np.nansum(y)), "predictors": {}}
    twin = R["twin"].to_numpy(float)
    for k in R.columns:
        x = R[k].to_numpy(float)
        m = np.isfinite(x) & np.isfinite(y)
        if m.sum() < 30 or y[m].sum() < 3:
            continue
        out["predictors"][k] = {
            "label": S.LABELS.get(k, k),
            "auc": S.auc(x[m], y[m]),
            "auc_ci": S.ci(S.boot(S.auc, [x[m], y[m]], None if firms is None else firms[m], b=b)),
            "n_events": int(y[m].sum()),
            "twin_minus": None if k == "twin" else S.paired(S.auc, twin, x, y, firms, b),
        }
    return out


def bankruptcy_2020(xs: pd.DataFrame, b: int) -> dict:
    """Chapter 11 / 7 petitions from 20 February 2020 to the end of 2021, every firm alive on the cutoff."""
    df = xs[np.isfinite(xs["bk_2020"].astype(float))].reset_index(drop=True)
    y = df["bk_2020"].to_numpy(float)
    R = _risk(df, "h_pandemic", "pb_pandemic")
    out = {"all": auc_table(df, y, R, None, b)}
    weak = _weak(df, None)
    out["weak"] = auc_table(df[weak].reset_index(drop=True), y[weak], R[weak].reset_index(drop=True), None, b)
    out["firms"] = df.loc[y == 1, ["ticker", "name", "sector", "h_pandemic", "h_base", "z2", "log_rev"]].to_dict(
        "records"
    )
    return out


def bankruptcy_panel(p: pd.DataFrame, b: int) -> dict:
    """Bankruptcy within eight quarters, every cutoff 2014-2024, all firms and the already-weak ones."""
    df = p[np.isfinite(p["y_bk8"].astype(float))].reset_index(drop=True)
    y = df["y_bk8"].to_numpy(float)
    firms = unit(df).to_numpy()
    R = _risk(df, "h_base", "pb_base")
    R["twin_rec"] = -df["h_rec"].astype(float)
    out: dict = {"all": auc_table(df, y, R, firms, b)}
    weak = _weak(df, "year")
    out["weak"] = auc_table(df[weak].reset_index(drop=True), y[weak], R[weak].reset_index(drop=True), firms[weak], b)
    out["weak"]["share_of_events"] = float(y[weak].sum() / max(y.sum(), 1))
    out["distinct_firms"] = int(df.loc[y == 1, "ticker"].nunique())
    y4 = df["y_bk4"].to_numpy(float) if "y_bk4" in df else np.full(len(df), np.nan)
    out["four_quarters"] = auc_table(df, y4, R, firms, b) if np.nansum(y4) >= 20 else {}
    out["by_year"] = {
        int(yr): {"n": int((df["year"] == yr).sum()), "events": int(y[(df["year"] == yr).to_numpy()].sum())}
        for yr in sorted(df["year"].unique())
    }
    return out


# ---------------------------------------------------------------- 2020: fragility versus exposure
def exposure_regression(sev, depth, twin, fcf, formula, cluster) -> dict:
    """Rank regression of burn severity on the industry shock, the twin at that shock and the FCF margin.

    `pre_specified`: the specification of the plan (HC3). `robust`: standard errors clustered by the industry that
    defines the shock (the regressor is constant within it), and the twin's own formula without simulation added, so
    that the twin's coefficient is what the simulation adds to balance-sheet weakness at the same shock.
    """
    import statsmodels.api as sm

    d = pd.DataFrame(
        {
            "y": S.pct(sev),
            "exp": S.pct(depth),
            "twin": S.pct(twin),
            "fcf": S.pct(fcf),
            "formula": S.pct(formula),
            "g": cluster,
        }
    ).dropna()
    out: dict = {"n": int(len(d))}
    m = sm.OLS(d["y"], sm.add_constant(d[["exp", "twin", "fcf"]])).fit(cov_type="HC3")
    out["pre_specified"] = {k: {"coef": float(m.params[k]), "t": float(m.tvalues[k])} for k in ("exp", "twin", "fcf")}
    m2 = sm.OLS(d["y"], sm.add_constant(d[["exp", "twin", "fcf", "formula"]])).fit(
        cov_type="cluster", cov_kwds={"groups": pd.factorize(d["g"])[0]}
    )
    out["robust"] = {
        k: {"coef": float(m2.params[k]), "t": float(m2.tvalues[k])} for k in ("exp", "twin", "fcf", "formula")
    }
    out["n_clusters"] = int(d["g"].nunique())
    return out


def _sic2(ciks: pd.Series) -> pd.Series:
    if not (DATA / "universe_edgar.csv").exists():
        return pd.Series(np.nan, index=ciks.index)
    u = pd.read_csv(DATA / "universe_edgar.csv", usecols=["cik", "sic"])
    m = {int(c): float(s) for c, s in zip(u["cik"], u["sic"], strict=True) if pd.notna(s)}
    return ciks.map(lambda c: m[int(c)] // 100 if pd.notna(c) and int(c) in m else np.nan)


def exposure(xs: pd.DataFrame, b: int) -> dict:
    """Give each company its industry's realized 2020 revenue shock (leave-one-out median of peers' worst
    year-on-year revenue change, 2-digit SIC with at least five peers, else the Fama-French industry) and read the
    twin's stress score at that depth from the precomputed grid. If the twin's mechanics are right, knowing the
    exposure should let it rank who burned cash; comparing it with the exposure alone shows what fragility adds.
    """
    from .transmission import loo_median

    df = xs[xs["real_rev_drop"].notna()].reset_index(drop=True)
    grid = sorted(c for c in df if c.startswith("grid_"))
    if not grid:
        return {}
    df["sic2"] = _sic2(df["cik"])
    drop = df["real_rev_drop"].astype(float)
    by_sic = drop.groupby(df["sic2"]).transform(loo_median).reindex(df.index)
    n_sic = drop.groupby(df["sic2"]).transform("count").reindex(df.index).fillna(0)
    by_ff = drop.groupby(df["sector"]).transform(loo_median)
    shock = np.where(n_sic >= 6, by_sic, by_ff)
    cluster = np.where(n_sic >= 6, "sic" + df["sic2"].astype(str), "ff" + df["sector"].astype(str))
    depth = np.clip(-shock / 100, 0.0, 0.8)
    xs_depth = np.array([float(c[5:]) for c in grid])
    H = df[grid].to_numpy(float)
    h_exp = np.array(
        [
            np.interp(d, xs_depth, h) if np.isfinite(d) and np.isfinite(h).all() else np.nan
            for d, h in zip(depth, H, strict=True)
        ]
    )
    out: dict = {"n": int(len(df)), "median_depth": float(np.nanmedian(depth))}
    outcomes = ("real_cum_fcf", "real_abn_cum_fcf") if "real_cum_fcf" in df else ("real_burn", "real_abn_burn")
    out["outcomes"] = list(outcomes)
    for outcome in outcomes:
        sev = -df[outcome].to_numpy(float)
        preds = {
            "twin_at_exposure": -h_exp,
            "exposure_only": depth,
            "twin_uniform": -df["h_pandemic"].to_numpy(float),
            "fcf_margin": -df["fcf_margin"].to_numpy(float),
        }
        res: dict = {}
        for k, x in preds.items():
            res[k] = {"rho": S.rho(x, sev), "ci": S.ci(S.boot(S.rho, [x, sev], b=b))}
        res["twin_at_exposure_minus_exposure"] = S.paired(S.rho, preds["twin_at_exposure"], depth, sev, None, b)
        res["twin_at_exposure_minus_fcf"] = S.paired(
            S.rho, preds["twin_at_exposure"], preds["fcf_margin"], sev, None, b
        )
        # what fragility adds to exposure, controlling for the exposure (and, robustly, for the formula)
        reg = exposure_regression(sev, depth, -h_exp, preds["fcf_margin"], -df["health_t0"].to_numpy(float), cluster)
        res["regression"] = {**reg["pre_specified"], "n": reg["n"]}
        res["regression_robust"] = reg["robust"]
        key = "real_burn" if outcome in ("real_burn", "real_cum_fcf") else "real_abn_burn"
        out[key] = res
    return out


# ---------------------------------------------------------------- probability scores (E8)
def _ok(p: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    p, y = np.asarray(p, float), np.asarray(y, float)
    m = np.isfinite(p) & np.isfinite(y)
    return np.clip(p[m], 0.0, 1.0), y[m]


def brier(p: np.ndarray, y: np.ndarray) -> float:
    p, y = _ok(p, y)
    return float(np.mean((p - y) ** 2)) if len(y) else np.nan


def log_score(p: np.ndarray, y: np.ndarray) -> float:
    """Mean negative log likelihood (lower is better)."""
    p, y = _ok(p, y)
    if not len(y):
        return np.nan
    p = np.clip(p, EPS_LOG, 1 - EPS_LOG)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def murphy(p: np.ndarray, y: np.ndarray, bins: int = 10) -> dict:
    """Murphy (1973) decomposition of the Brier score on equal-width bins, Brier = REL - RES + UNC + within, where
    `within` is the within-bin variance term that the binned decomposition leaves over; plus the reliability curve."""
    p, y = _ok(p, y)
    n = len(y)
    if not n:
        return {}
    k = np.minimum((p * bins).astype(int), bins - 1)
    ybar = float(y.mean())
    rel = res = 0.0
    curve = []
    for b in range(bins):
        m = k == b
        if not m.any():
            continue
        pb, yb, nb = float(p[m].mean()), float(y[m].mean()), int(m.sum())
        rel += nb * (pb - yb) ** 2 / n
        res += nb * (yb - ybar) ** 2 / n
        curve.append({"bin": b, "lo": b / bins, "hi": (b + 1) / bins, "n": nb, "p_mean": pb, "y_mean": yb})
    unc = ybar * (1 - ybar)
    bs = float(np.mean((p - y) ** 2))
    return {"brier": bs, "reliability": rel, "resolution": res, "uncertainty": unc, "within": bs - (rel - res + unc),
            "curve": curve}  # fmt: skip


def prob_scores(p: np.ndarray, y: np.ndarray, bins: int = 10) -> dict:
    pp, yy = _ok(p, y)
    return {
        "n": int(len(yy)),
        "events": int(yy.sum()),
        "base_rate": float(yy.mean()) if len(yy) else None,
        "mean_p": float(pp.mean()) if len(yy) else None,
        "brier": brier(p, y),
        "log": log_score(p, y),
        "murphy": murphy(p, y, bins),
    }


def _bss(p: np.ndarray, q: np.ndarray, y: np.ndarray) -> float:
    """Brier skill of p against the reference q, on rows where both are defined."""
    m = np.isfinite(p) & np.isfinite(q) & np.isfinite(y)
    bq = brier(q[m], y[m])
    return float(1 - brier(p[m], y[m]) / bq) if bq and np.isfinite(bq) else np.nan


MIN_BLOCKS = 5  # fewest resampling blocks for a year-block percentile interval to mean anything


def block_ci(stat, cols: list[np.ndarray], blocks: np.ndarray, b: int, seed: int = 15) -> dict:
    """Percentile CI of `stat` resampling whole blocks (cutoff years, or firms) with replacement; own RNG."""
    rng = np.random.default_rng(seed)
    blocks = np.asarray(blocks)
    groups = [np.flatnonzero(blocks == g) for g in pd.unique(blocks)]
    if len(groups) < 2:
        return {"ci": [None, None], "blocks": len(groups)}
    draws = np.empty(b)
    for i in range(b):
        idx = np.concatenate([groups[g] for g in rng.integers(0, len(groups), len(groups))])
        draws[i] = stat(*(c[idx] for c in cols))
    draws = draws[np.isfinite(draws)]
    if not len(draws):
        return {"ci": [None, None], "blocks": len(groups)}
    return {"ci": [float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5))], "blocks": len(groups)}


# ---------------------------------------------------------------- benchmarks trained on earlier years
def fit_logit(X: np.ndarray, y: np.ndarray, ridge: float = 1e-3, iters: int = 100) -> dict:
    """Logistic regression by Newton steps with a small ridge (stable under separation, no extra dependency).
    Regressors are standardized with the training moments, which are returned with the coefficients."""
    X, y = np.asarray(X, float), np.asarray(y, float)
    mu, sd = X.mean(0), X.std(0)
    sd = np.where(sd > 0, sd, 1.0)
    Z = np.column_stack([np.ones(len(X)), (X - mu) / sd])
    beta = np.zeros(Z.shape[1])
    beta[0] = np.log(max(y.mean(), 1e-6) / max(1 - y.mean(), 1e-6))
    pen = np.full(Z.shape[1], ridge)
    pen[0] = 0.0
    for _ in range(iters):
        pr = 1 / (1 + np.exp(-np.clip(Z @ beta, -35, 35)))
        g = Z.T @ (y - pr) - pen * beta
        H = (Z * (pr * (1 - pr))[:, None]).T @ Z + np.diag(pen) + 1e-9 * np.eye(len(beta))
        step = np.linalg.solve(H, g)
        beta = beta + step
        if np.max(np.abs(step)) < 1e-8:
            break
    return {"beta": beta, "mu": mu, "sd": sd}


def predict_logit(m: dict, X: np.ndarray) -> np.ndarray:
    Z = np.column_stack([np.ones(len(X)), (np.asarray(X, float) - m["mu"]) / m["sd"]])
    return 1 / (1 + np.exp(-np.clip(Z @ m["beta"], -35, 35)))


LOGIT_COLS = ("cash_rev", "debt_assets", "fcf_margin")  # liquidity, leverage, burn at the cutoff (pre-specified)
Z_COLS = ("z2",)
MIN_TRAIN, MIN_TRAIN_EVENTS = 300, 10


def known_by(df: pd.DataFrame, cutoff: pd.Timestamp, k: int) -> np.ndarray:
    """Firm-years whose k-quarter label was observable at `cutoff`: the event window has closed and the last outcome
    quarter has been filed (actual filing date, D10; quarter window + 90 days where unknown)."""
    origin = pd.to_datetime(df["origin"])
    days = pd.Timedelta(days=365 * k // 4)
    col = "outcome_filed" if k == 8 else "outcome_filed4"
    fallback = origin + days + pd.Timedelta(days=90)
    filed = pd.to_datetime(df[col], errors="coerce").fillna(fallback) if col in df else fallback
    return ((origin + days <= cutoff) & (filed <= cutoff)).to_numpy()


def benchmark_probs(df: pd.DataFrame, y: np.ndarray, k: int, cols: tuple[str, ...], years: list[int]) -> np.ndarray:
    """Out-of-sample probabilities for each test year from a logit on firm-years known by that year's cutoff.
    Regressors are winsorized at the training 1st/99th percentiles (no test-year information in the bounds)."""
    X = df[list(cols)].astype(float).to_numpy()
    out = np.full(len(df), np.nan)
    yr = df["year"].to_numpy()
    for t in years:
        cut = pd.Timestamp(f"{t}-02-15")
        tr = known_by(df, cut, k) & np.isfinite(y) & np.isfinite(X).all(1)
        te = (yr == t) & np.isfinite(X).all(1)
        if tr.sum() < MIN_TRAIN or y[tr].sum() < MIN_TRAIN_EVENTS or not te.any():
            continue
        lo, hi = np.percentile(X[tr], 1, axis=0), np.percentile(X[tr], 99, axis=0)
        m = fit_logit(np.clip(X[tr], lo, hi), y[tr])
        out[te] = predict_logit(m, np.clip(X[te], lo, hi))
    return out


# ---------------------------------------------------------------- credit events (M9) and liquidity shortfall (E12)
CREDIT_ITEMS = ("1.03", "2.04", "3.01")


def event_label(dates: list[str], origin: str, days: int) -> float:
    """1 if an event follows the cutoff within `days`; NaN if one occurred in the two years before it (the firm is
    already in, or just out of, a credit event); else 0. Same convention as `stats.bk_event`."""
    o = pd.Timestamp(origin)
    ts = [pd.Timestamp(d) for d in dates]
    if any(o - pd.Timedelta(days=730) < d <= o for d in ts):
        return np.nan
    return float(any(o < d <= o + pd.Timedelta(days=days) for d in ts))


def credit_labels(events: dict | None, origin: str) -> dict:
    """Labels within 4 and 8 quarters: any credit item (`ce`), and each item alone (1.03 `bk`, 2.04 `acc`,
    3.01 `delist`). All NaN if the firm's filings could not be read."""
    out: dict = {}
    names = {"1.03": "bk", "2.04": "acc", "3.01": "delist"}
    for k, days in ((4, 365), (8, 730)):
        if events is None:
            out |= {f"ce{k}": np.nan, **{f"{v}{k}": np.nan for v in names.values()}}
            continue
        allv = sorted({d for it in CREDIT_ITEMS for d in events.get(it, [])})
        out[f"ce{k}"] = event_label(allv, origin, days)
        for it, v in names.items():
            out[f"{v}{k}"] = event_label(events.get(it, []), origin, days)
    return out


# Realized shortfall (pre-specified here, before any rev-3 run): within k quarters, a credit event, or the cash-like
# balance fell below a quarter of its opening value while total debt rose by more than 5% of trailing revenue (the
# firm ran its liquidity down and had to borrow). The model's event, cash + undrawn < 0, cannot be observed directly.
SHORT_CASH, SHORT_DEBT = 0.25, 0.05
SHOCK_YEARS = (2015, 2020, 2022)


def shortfall_label(ce: float, cash_min: float | None, raise_: float | None) -> float:
    if ce == 1:
        return 1.0
    if not np.isfinite(ce) or cash_min is None or raise_ is None:
        return np.nan
    return float(cash_min < SHORT_CASH and raise_ > SHORT_DEBT)


def liquidity_frame(cache: Path, min_log_rev: float = S.MIN_LOG_REV) -> pd.DataFrame:
    """One row per firm-year from the shards' `liquidity`, `outcome`, `features` and `credit_events` blocks."""
    rows = []
    # D8 as in `stats.main`: a firm-year whose cutoff falls inside a running Chapter 11 case is neither a survivor
    # nor a new filer (12-11-2026 review, S3: B2 / B3 used to keep them)
    bkd, raw = S.bankruptcy_dates(), S.bankruptcy_filings()
    excluded = 0
    for f in sorted(Path(cache).glob("*.json")):
        r = json.loads(f.read_text(encoding="utf-8"))
        ind = (r.get("covid") or {}).get("sector")
        dates = bkd.get(r.get("cik"), []) if r.get("cik") is not None else []
        spans = S._spans(dates, raw.get(r.get("cik"))) if dates else []
        for pr in r.get("panel", []):
            in_case = bool(spans) and not S._data_legacy() and S.in_bankruptcy(spans, pr["origin"])
            liq, oc, ft = pr.get("liquidity") or {}, pr.get("outcome") or {}, pr.get("features") or {}
            if not liq:
                continue
            if in_case:  # counted only if the row would otherwise enter the tests (size screen below)
                lr = ft.get("log_rev")
                excluded += int(lr is not None and float(lr) >= min_log_rev)
                continue
            row = {
                "ticker": r["ticker"],
                "cluster": cluster_of(r["ticker"], r.get("cik")),
                "cik": r.get("cik"),
                "origin": pr["origin"],
                "year": int(pr["origin"][:4]),
                "industry": ind,
                "h_base": (pr.get("base") or {}).get("health"),
                "pb_base": (pr.get("base") or {}).get("p_breach"),
                **{c: ft.get(c) for c in (*LOGIT_COLS, *Z_COLS, "log_rev")},
                **{c: oc.get(c) for c in ("rev_drop8", "outcome_filed", "outcome_filed4")},
                **credit_labels(r.get("credit_events"), pr["origin"]),
            }
            for i, k in enumerate((4, 8)):
                row[f"rec{k}"] = (liq.get("recession") or [None, None])[i]
                row[f"base{k}"] = (liq.get("base") or [None, None])[i]
                for d, v in (liq.get("grid") or {}).items():
                    row[f"lg{k}_{d}"] = v[i]
                row[f"y_short{k}"] = shortfall_label(
                    row[f"ce{k}"], oc.get(f"cash_min_ratio{k}"), oc.get(f"debt_raise{k}")
                )
            rows.append(row)
    df = pd.DataFrame(rows)
    df.attrs["in_bankruptcy_excluded"] = excluded
    if df.empty:
        return df
    if df["industry"].isna().any():
        df["industry"] = [
            i if isinstance(i, str) and i else S._industry(t) for i, t in zip(df["industry"], df["ticker"], strict=True)
        ]
    df = df[df["log_rev"].astype(float) >= min_log_rev].reset_index(drop=True)
    num = [c for c in df if c not in ("ticker", "cluster", "origin", "industry", "outcome_filed", "outcome_filed4")]
    df[num] = df[num].apply(pd.to_numeric, errors="coerce")
    df.attrs["in_bankruptcy_excluded"] = excluded
    return df


def realized_shock_probs(df: pd.DataFrame, k: int) -> np.ndarray:
    """P(shortfall within k) at each firm's industry shock of its cutoff year: the leave-one-out median of peers'
    worst year-on-year revenue change over the eight quarters (2-digit SIC with 6+ firms, else the FF industry),
    read off the shock-depth grid. The same decomposition as `exposure`, for every cutoff year."""
    from .transmission import loo_median

    grid = sorted((c for c in df if c.startswith(f"lg{k}_")), key=lambda c: float(c.split("_")[1]))
    if not grid:
        return np.full(len(df), np.nan)
    xs = np.array([float(c.split("_")[1]) for c in grid])
    sic2 = _sic2(df["cik"]) if "cik" in df else pd.Series(np.nan, index=df.index)
    drop = df["rev_drop8"].astype(float)
    key = sic2.fillna(-1.0)  # groupby drops NaN keys; firms without a SIC code use the industry below
    by_sic = drop.groupby([df["year"], key]).transform(loo_median)
    n_sic = drop.groupby([df["year"], key]).transform("count").fillna(0)
    by_ind = drop.groupby([df["year"], df["industry"].fillna("")]).transform(loo_median)
    shock = np.where(((n_sic >= 6) & sic2.notna()).to_numpy(), by_sic.to_numpy(), by_ind.to_numpy())
    depth = np.clip(-shock / 100, 0.0, 0.8)
    G = df[grid].to_numpy(float)
    return np.array(
        [
            np.interp(d, xs, g) if np.isfinite(d) and np.isfinite(g).all() else np.nan
            for d, g in zip(depth, G, strict=True)
        ]
    )


def _versus(df: pd.DataFrame, p: np.ndarray, y: np.ndarray, k: int, years: list[int], b: int) -> dict:
    """The twin's probabilities against the logit and Altman Z'' benchmarks on the test years."""
    logit = benchmark_probs(df, y, k, LOGIT_COLS, years)
    z2 = benchmark_probs(df, y, k, Z_COLS, years)
    yr = df["year"].to_numpy()
    test = np.isin(yr, years) & np.isfinite(p) & np.isfinite(y) & np.isfinite(logit) & np.isfinite(z2)
    out: dict = {"years": [int(t) for t in years if (test & (yr == t)).any()], "n": int(test.sum())}
    if test.sum() < 30:
        return out
    P, L, Z, Y = p[test], logit[test], z2[test], y[test]
    out["twin"] = prob_scores(P, Y)
    out["logit"] = prob_scores(L, Y)
    out["altman_z2"] = prob_scores(Z, Y)
    for name, ref in (("logit", L), ("altman_z2", Z)):
        out[f"bss_vs_{name}"] = {
            "bss": _bss(P, ref, Y),
            "year_block": block_ci(_bss, [P, ref, Y], yr[test], b),
            "firm_block": block_ci(_bss, [P, ref, Y], unit(df).to_numpy()[test], b),
        }
    out["by_year"] = {
        int(t): {
            "n": int((yr[test] == t).sum()),
            "events": int(Y[yr[test] == t].sum()),
            "brier_twin": brier(P[yr[test] == t], Y[yr[test] == t]),
            "brier_logit": brier(L[yr[test] == t], Y[yr[test] == t]),
            "brier_z2": brier(Z[yr[test] == t], Y[yr[test] == t]),
        }
        for t in sorted(set(yr[test].tolist()))
    }
    # success rule of REVISION_PLAN_3 §2.2 B2: Brier skill > 0 against the logit, year-block CI excluding 0. With
    # fewer than MIN_BLOCKS cutoff years the percentile "CI" is the min / max of the yearly skills (12-11-2026 review,
    # S2), so no verdict is given
    yb = out["bss_vs_logit"]["year_block"]
    lo = yb["ci"][0]
    if yb["blocks"] < MIN_BLOCKS:
        out["success"] = None
        out["success_undefined"] = f"year-block CI from {yb['blocks']} cutoff years (< {MIN_BLOCKS})"
    else:
        out["success"] = bool(out["bss_vs_logit"]["bss"] > 0 and lo is not None and lo > 0)
    return out


def liquidity_section(df: pd.DataFrame, b: int = 2000) -> dict:
    """E12: P(cash + undrawn revolver < 0 within 4 and 8 quarters) against realized shortfalls, under each firm's
    realized industry shock (cutoffs Feb 2015, 2020, 2022) and under the Recession preset (every cutoff with a
    trainable benchmark), scored by Brier, log score and the Murphy decomposition (E8)."""
    if df.empty:
        return {}
    out: dict = {
        "in_bankruptcy_excluded": int(df.attrs.get("in_bankruptcy_excluded", 0)),  # D8 (S3)
        "definition": {
            "forecast": "share of paths with cash + undrawn revolver < 0 in some quarter within k",
            "realized": f"credit event (8-K 1.03/2.04/3.01) within k quarters, or cash-like < {SHORT_CASH:.0%} of "
            f"opening with total debt up > {SHORT_DEBT:.0%} of trailing revenue",
            "benchmarks": {"logit": list(LOGIT_COLS), "altman_z2": list(Z_COLS)},
            "training": "firm-years whose label was observable at the test cutoff (actual filing dates)",
        },
    }
    all_years = sorted(set(df["year"].astype(int).tolist()))
    for label, ycol in (("shortfall", "y_short"), ("credit_event", "ce")):
        res: dict = {}
        for k in (4, 8):
            y = df[f"{ycol}{k}"].to_numpy(float)
            res[str(k)] = {
                "realized_shock": _versus(df, realized_shock_probs(df, k), y, k, list(SHOCK_YEARS), b),
                "recession": _versus(df, df[f"rec{k}"].to_numpy(float), y, k, all_years, b),
            }
        out[label] = res
    # The single B2 test (§2.2), named before any rerun-5 result (12-11-2026, S2): the B2 label (shortfall), 8
    # quarters (the panel's outcome horizon), and the Recession version, the only one whose year-block CI has enough
    # cutoff years; the other seven cells are descriptive.
    cell = out.get("shortfall", {}).get("8", {}).get("recession", {})
    lv = cell.get("bss_vs_logit") or {}
    out["primary"] = {
        "cell": "shortfall / 8 / recession",
        "success": cell.get("success"),
        "blocks": lv.get("year_block", {}).get("blocks"),
        # the percentile year-block CI is a little narrow with 5-8 blocks (round 2): the firm-block CI beside it
        "year_block_ci": lv.get("year_block", {}).get("ci"),
        "firm_block_ci": lv.get("firm_block", {}).get("ci"),
    }
    return out


def credit_section(df: pd.DataFrame, b: int = 2000) -> dict:
    """M9 / B3 (secondary): AUC of the twin's baseline verdict for the broad credit-event label and each item."""
    if df.empty:
        return {}
    firms = unit(df).to_numpy()
    preds = {"twin": -df["h_base"].to_numpy(float), "pb_base": df["pb_base"].to_numpy(float),
             "altman_z2": -df["z2"].to_numpy(float), "recession8": df["rec8"].to_numpy(float)}  # fmt: skip
    out: dict = {}
    for lab in ("ce8", "bk8", "acc8", "delist8", "ce4"):
        y = df[lab].to_numpy(float)
        res: dict = {"n": int(np.isfinite(y).sum()), "events": int(np.nansum(y))}
        for k, x in preds.items():
            m = np.isfinite(x) & np.isfinite(y)
            if m.sum() < 30 or y[m].sum() < 3:
                continue
            res[k] = {"auc": S.auc(x[m], y[m]), "ci": block_ci(S.auc, [x[m], y[m]], firms[m], b)["ci"]}
        out[lab] = res
    return out


def event_scores(panel: pd.DataFrame) -> dict:
    """E8 for the structural liquidity decisions: the twin's event probabilities (realized revenue fed in) scored by
    Brier, log score and Murphy decomposition against what happened, with the climatology of earlier years as the
    reference forecast (base rate of cutoffs <= Y-3)."""
    from .experiments import EVENTS

    out: dict = {}
    yrs = panel["year"].to_numpy() if "year" in panel else np.zeros(len(panel))
    for e in EVENTS:
        p = np.array([((st or {}).get("probs") or {}).get("full", {}).get(e) for st in panel["st"]], dtype=float)
        y = np.array([((st or {}).get("events") or {}).get(e) for st in panel["st"]], dtype=float)
        clim = np.full(len(p), np.nan)
        for t in sorted(set(yrs.tolist())):
            past = (yrs <= t - 3) & np.isfinite(y)
            if past.sum() >= 100:
                clim[yrs == t] = y[past].mean()
        sc = prob_scores(p, y)
        m = np.isfinite(clim)
        sc["bss_vs_climatology"] = _bss(p[m], clim[m], y[m]) if m.any() else None
        out[e] = sc
    return out
