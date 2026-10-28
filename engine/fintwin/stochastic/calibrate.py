"""Calibrate model parameters from a company's own filing history (and FRED rates).

Every parameter records how it was obtained in `p["_sources"]`, so the dashboard can show
"estimated from 16 quarters of filings" versus "assumption" for each number.

Revision-3 fixes (docs/review_2026-10/model_mechanics.md, MM-F*; wave1 M2/M3) are each behind a switch in `spec`;
with every switch off the output is identical to revision 2 (tests/test_B1_parity.py).
"""

from __future__ import annotations

import warnings
import zlib

import numpy as np
import pandas as pd
from scipy import stats

from ..data.facts import CompanyData
from ..data.fred import recession_regime
from . import spec as S

DAYS_Q = 91.25
LONG_RUN_GROWTH_Q = 0.012  # ~5% nominal p.a., the anchor that trend growth is shrunk toward


def _clip(x, lo, hi, default):
    x = float(x) if x is not None and np.isfinite(x) else default
    return float(min(max(x, lo), hi))


# Revision-3 data layer: a balance can be NaN in the last row (not reported, after A's 2-quarter carry-forward).
# The model needs a starting stock, so take the last reported value up to STALE_ROWS rows back; beyond that, 0 for
# working-capital items and debt-like lines (what revision 2 assumed for every missing quarter), the last value ever
# reported for equity and assets, and NaN where the code already has a documented fallback. Each use is noted.
STALE_ROWS = 4
STOCK_ZERO = (
    "receivables",
    "inventory",
    "payables",
    "deferred_revenue",
    "total_debt",
    "short_borrowings",
    "commercial_paper",
    "short_investments",
)
STOCK_ANY = ("equity", "assets", "cash")
STOCK_FIELDS = (
    STOCK_ZERO + STOCK_ANY + ("ppe", "liabilities", "current_assets", "current_liabilities", "retained_earnings")
)


def _last_known(q: pd.DataFrame, fields: tuple[str, ...], limit: int) -> tuple[pd.Series, list[str]]:
    """Last row with each stock field replaced by its last finite value within `limit` rows (see STALE_ROWS)."""
    last = q.iloc[-1].copy()
    notes = []
    for k in fields:
        if k not in q or np.isfinite(float(last[k])):
            continue
        s = q[k].astype(float)
        recent = s.tail(limit + 1).dropna()
        if len(recent):
            last[k] = float(recent.iloc[-1])
            notes.append(f"{k} carried from {recent.index[-1].date()}")
        elif k in STOCK_ZERO:
            last[k] = 0.0
            notes.append(f"{k} not reported for {limit}+ quarters, assumed 0")
        elif k in STOCK_ANY and s.notna().any():
            last[k] = float(s.dropna().iloc[-1])
            notes.append(f"{k} stale, last reported {s.dropna().index[-1].date()}")
    return last, notes


def _seasonal(rev: pd.Series, seasons: pd.Series) -> np.ndarray:
    hist = rev.tail(32)
    ma = hist.rolling(4, center=True).mean()
    ratio = (hist / ma).groupby(seasons.loc[hist.index]).median()  # median: robust to crisis quarters
    s = np.array([ratio.get(i, 1.0) for i in range(4)], dtype=float)
    s = np.where(np.isfinite(s), s, 1.0)
    return s / s.mean()


# Prior share of operating costs that does not scale with revenue. The first version used 35%; selected walk-forward
# on the 2014-2024 research panel (each year from earlier years only), 5% was chosen in every year and lowered the
# twin's cash-flow error out of sample without hurting its bankruptcy ranking (docs/REVISION_PLAN_2.md, rule 1.1).
FIXED_SHARE_PRIOR = 0.05
SPECIFIED_FIXED_SHARE_PRIOR = 0.35  # the pre-specified value the paper's main results use
PRIOR_WEIGHT = 2.0


# MM-F1: prior s.d. of the fixed share (tau, in fixed-share units; the s.d. on v is tau * cost ratio). The default is
# the reviewer's suggestion; research selects tau walk-forward from TAU_GRID with `select_walk_forward`.
PRIOR_TAU = 0.15
TAU_GRID = (0.05, 0.10, 0.15, 0.25, 0.50, 1.0, float("inf"))
# MM-F3: partial adjustment of fixed costs toward f * deseasonalized revenue; lambda 0.2/q is a half-life of about
# 3 quarters (reviewer: 2-4 is plausible). Research selects it walk-forward from LAMBDA_GRID.
FIXED_ADJ_LAMBDA = 0.2
LAMBDA_GRID = (0.0, 0.1, 0.2, 0.3, 0.5)
MA_THRESHOLD = 0.05  # acquisitions over the last 8 quarters above 5% of revenue flag the firm as an acquirer
N_PARAM_DRAWS = 50  # MM-F9: parameter vectors per firm (one per block of paths)
# M2 assumption: share of debt at floating rates by sector when no XBRL tag reports it (GICS and Fama-French 12
# names). Rough midpoints: utilities and staples fund with fixed-rate bonds, real estate and leveraged cyclicals use
# more bank debt. Short-term borrowings and commercial paper always count as floating (a data-based lower bound).
FLOATING_DEFAULT = 0.10
FLOATING_BY_SECTOR = {
    "Utilities": 0.05,
    "Consumer Staples": 0.08,
    "Consumer NonDurables": 0.08,
    "Health Care": 0.08,
    "Health": 0.08,
    "Information Technology": 0.08,
    "Business Equipment": 0.08,
    "Communication Services": 0.12,
    "Telecom": 0.12,
    "Industrials": 0.12,
    "Manufacturing": 0.12,
    "Materials": 0.12,
    "Chemicals": 0.12,
    "Energy": 0.15,
    "Consumer Discretionary": 0.15,
    "Consumer Durables": 0.15,
    "Shops": 0.15,
    "Real Estate": 0.25,
    "Financials": 0.20,
    "Money": 0.20,
}


def select_walk_forward(
    years: np.ndarray, errors: dict, test_year: int, lag: int = 3, min_obs: int = 500
) -> object | None:
    """Walk-forward choice of a calibration hyper-parameter (MM-F1 tau, MM-F3 lambda), as REVISION_PLAN_2 rule 1.1.

    `errors` maps each candidate to the absolute forecast errors of the panel's firm-years (aligned with `years`),
    computed with that candidate. Returns the candidate with the lowest median error over firm-years whose outcome was
    known at `test_year` (year <= test_year - lag), or None when fewer than `min_obs` are available.
    """
    years = np.asarray(years)
    past = years <= test_year - lag
    if past.sum() < min_obs:
        return None
    score = {}
    for cand, e in errors.items():
        e = np.abs(np.asarray(e, float)[past])
        e = e[np.isfinite(e)]
        score[cand] = float(np.median(e)) if len(e) else np.inf
    return min(score, key=lambda k: score[k])


def _fixed_variable_split(
    rev: np.ndarray,
    costs: np.ndarray,
    prior_share: float = FIXED_SHARE_PRIOR,
    prior_weight: float = PRIOR_WEIGHT,
    grid: np.ndarray | None = None,
) -> tuple[float, float]:
    """Revision-2 estimator: penalized least squares costs = F + v*rev, F >= 0, on a grid of v.

    Note (MM-F1): both terms are scale-free and neither grows with n or with revenue variation, so the prior keeps
    about 2/3 of the weight however much revenue varied. `_posterior_split` is the corrected estimator.
    """
    ratio = float(np.median(costs / rev))
    v_prior = ratio * (1 - prior_share)
    scale = float(np.var(costs)) * len(costs) + 1e-9
    best = (np.inf, 0.0, v_prior)
    for v in np.arange(0.1, 1.051, 0.005) if grid is None else grid:
        F = max(float(np.mean(costs - v * rev)), 0.0)
        sse = float(np.sum((costs - F - v * rev) ** 2)) / scale
        obj = sse + prior_weight * ((v - v_prior) / max(ratio, 1e-9)) ** 2
        if obj < best[0]:
            best = (obj, F, float(v))
    return best[1], best[2]


def _ar1(x: np.ndarray) -> tuple[float, float, np.ndarray]:
    x = x[np.isfinite(x)]
    if len(x) < 6:
        return 0.0, float(np.std(x)) if len(x) else 0.05, x - x.mean() if len(x) else x
    m = x.mean()
    y, z = x[1:] - m, x[:-1] - m
    phi = float(np.dot(y, z) / max(np.dot(z, z), 1e-12))
    resid = y - phi * z
    robust_sd = 1.4826 * float(np.median(np.abs(resid - np.median(resid))))  # MAD: crises go to the t tails
    return phi, robust_sd, resid


def _ar1_resid_series(s: pd.Series) -> pd.Series:
    """`_ar1` residuals keyed by date, so two residual series can be aligned by quarter (MM-F6)."""
    s = s[np.isfinite(s.to_numpy(float))]
    if len(s) < 6:
        return pd.Series(dtype=float)
    _, _, resid = _ar1(s.to_numpy(float))
    return pd.Series(resid, index=s.index[1:])


def _posterior_split(
    rev: np.ndarray,
    costs: np.ndarray,
    prior_share: float,
    tau: float,
    overlap: float = 1.0,
    bounds: tuple[float, float] = (0.1, 1.05),
) -> dict:
    """MM-F1: Bayesian (ridge) fit of costs = F + v*rev with F >= 0 and v in `bounds`.

    Objective SSE/(overlap*s2) + ((v - v_prior)/(tau*ratio))^2 with s2 the OLS residual variance, so the data's
    weight n*var(rev)/s2 grows with the sample and with how much revenue varied. `overlap` deflates the precision of
    overlapping observations (4 for rolling TTM sums). tau = inf (or prior weight 0 upstream) is plain constrained OLS.
    Closed form: the convex QP's optimum is interior or on one of the edges F = 0, v = lo, v = hi.
    """
    r, c = np.asarray(rev, float), np.asarray(costs, float)
    n = len(r)
    rbar, cbar = float(r.mean()), float(c.mean())
    ratio = float(np.median(c / r))
    v_prior = ratio * (1 - prior_share)
    sxx = float(np.sum((r - rbar) ** 2))
    sxy = float(np.sum((r - rbar) * (c - cbar)))
    v_ols = sxy / sxx if sxx > 0 else v_prior
    resid = c - cbar - v_ols * (r - rbar)
    s2 = max(float(np.sum(resid**2)) / max(n - 2, 1), (1e-3 * abs(cbar)) ** 2, 1e-12)
    prec = 1.0 / (s2 * overlap)
    tau_v = tau * max(abs(ratio), 1e-9)
    pp = 1.0 / tau_v**2 if np.isfinite(tau_v) and tau_v > 0 else 0.0
    lo, hi = bounds

    def obj(F: float, v: float) -> float:
        return prec * float(np.sum((c - F - v * r) ** 2)) + pp * (v - v_prior) ** 2

    cands = []
    if prec * sxx + pp > 0:
        v_u = (prec * sxy + pp * v_prior) / (prec * sxx + pp)
        cands.append((cbar - v_u * rbar, v_u))
    den0 = prec * float(np.sum(r * r)) + pp
    if den0 > 0:  # edge F = 0
        cands.append((0.0, float(np.clip((prec * float(np.sum(r * c)) + pp * v_prior) / den0, lo, hi))))
    for vb in (lo, hi):  # edges v = lo, v = hi
        cands.append((max(cbar - vb * rbar, 0.0), vb))
    feas = [(F, v) for F, v in cands if F >= -1e-9 and lo - 1e-12 <= v <= hi + 1e-12]
    F, v = min(feas, key=lambda fv: obj(*fv))
    F = max(F, 0.0)
    sd_v = 1.0 / np.sqrt(prec * sxx + pp) if prec * sxx + pp > 0 else np.inf
    return {
        "F": float(F),
        "v": float(v),
        "sd_share": float(sd_v * rbar / cbar) if cbar > 0 else np.nan,
        "data_weight": float(prec * sxx / (prec * sxx + pp)) if prec * sxx + pp > 0 else 0.0,
        "v_prior": v_prior,
    }


def _ttm(df: pd.DataFrame) -> pd.DataFrame:
    """Rolling 4-quarter sums, only over 4 consecutive quarter-ends (MM-F2; robust to calendar gaps)."""
    span = pd.Series(df.index, index=df.index).diff(3).dt.days
    out = df.rolling(4, min_periods=4).sum()
    return out[(span >= 250) & (span <= 300)].dropna()


def _quarters_before_last(idx: pd.DatetimeIndex) -> np.ndarray:
    return np.round((idx[-1] - idx).days / DAYS_Q).to_numpy(float)


def _fit_costs(rev: pd.Series, costs: pd.Series, a: dict, infl: float) -> dict:
    """Fixed/variable cost split on the last 16 quarters, with the active MM-F1/F2/F10/F12 switches.

    Returns quarterly F (in cutoff dollars under F10) and v, the quarterly window used for the margin residuals and,
    under F1, the posterior summaries.
    """
    full = pd.DataFrame({"rev": rev, "costs": costs})
    win = full.dropna().tail(16)
    f10, f2, f1, f12 = S.active("F10"), S.active("F2"), S.active("F1"), S.active("F12")
    if not (f10 or f2 or f1 or f12):
        F, v = _fixed_variable_split(win["rev"].values, win["costs"].values, a["fixed_share_prior"], a["prior_weight"])
        return {"F": F, "v": v, "win": win, "defl": np.ones(len(win)), "n": len(win), "basis": "quarterly"}

    full = full.dropna()
    if f12:  # guard: the cost ratio and the split are undefined for non-positive revenue
        full = full[full["rev"] > 0]
        win = full.tail(16)
    # F10: express every quarter in cutoff dollars, so F is today's fixed cost and the model's inflation index starts
    # from the right base (the regression intercept otherwise sits at the window's midpoint, ~8 quarters back)
    defl_full = (1.0 + infl) ** _quarters_before_last(full.index) if f10 and len(full) else np.ones(len(full))
    fx = full.mul(defl_full, axis=0)
    basis, overlap, per_q = "quarterly", 1.0, 1.0
    fit = fx.tail(16)
    if f2:  # annual horizon: TTM costs on TTM revenue (seasonal swings that costs smooth are not operating leverage)
        ttm = _ttm(fx).tail(16)
        if len(ttm) >= 6:
            fit, basis, overlap, per_q = ttm, "TTM", 4.0, 4.0
    r, c = fit["rev"].to_numpy(float), fit["costs"].to_numpy(float)
    ratio = float(np.median(c / r)) if len(r) else 1.0
    bounds = (0.0, max(1.5 * ratio, 1e-6)) if f12 else (0.1, 1.05)
    out: dict = {"win": win, "defl": defl_full[-len(win) :] if len(win) else np.ones(0), "n": len(fit), "basis": basis}
    if f1:
        tau = float("inf") if a["prior_weight"] == 0 else float(a.get("prior_tau", PRIOR_TAU))
        res = _posterior_split(r, c, a["fixed_share_prior"], tau, overlap, bounds)
        out.update(res, F=res["F"] / per_q, tau=tau)
    else:
        grid = np.linspace(bounds[0], bounds[1], 191) if f12 else None
        F, v = _fixed_variable_split(r, c, a["fixed_share_prior"], a["prior_weight"], grid)
        out.update(F=F / per_q, v=v)
    return out


def _anchor_ocf(
    q: pd.DataFrame,
    da_used: pd.Series,
    short_rate: pd.Series,
    F: float,
    v: float,
    k: dict,
) -> float | None:
    """MM-F5: the CFO residual that makes the twin's own components reproduce cumulative CFO over the last 16 quarters.

    The twin's income statement is rebuilt at historical revenue with its own parameters (F, v, dep_rate, tax_rate,
    sbc_ratio, interest at reported expense, interest income on cash), and the residual is sum/sum on the same window.
    The twin then nests the 16-quarter CFO margin at constant revenue; non-operating income, tax one-offs and
    unmodelled items all land in this one line instead of being estimated (and mismatched) separately.
    """
    h = q.tail(16)
    rev = h["revenue"]
    Ft = F / (1.0 + k["infl"]) ** _quarters_before_last(h.index) if k["f10"] else F
    ebitda = rev - Ft - v * rev
    da = (k["dep_rate"] * q["ppe"].shift(1).loc[h.index]).fillna(da_used.loc[h.index])
    interest = h["interest_expense"].fillna(h["total_debt"] * k["coupon"] / 4.0).fillna(0.0)
    cash = (q["cash"].ffill() + q["short_investments"].fillna(0)).loc[h.index]
    r = short_rate.dropna().sort_index().asof(h.index).to_numpy(float)
    ebt = ebitda - da - interest + np.maximum(cash, 0.0) * np.nan_to_num(r) * 0.9 / 4.0
    ni = ebt - k["tax_rate"] * np.maximum(ebt, 0.0)
    comp = {c: q[c].ffill().fillna(0.0) for c in ("receivables", "inventory", "payables", "deferred_revenue")}
    nwc = comp["receivables"] + comp["inventory"] - comp["payables"] - comp["deferred_revenue"]
    explained = ni + da + k["sbc_ratio"] * rev - nwc.diff().loc[h.index]
    ok = np.isfinite(h["cfo"]) & np.isfinite(explained) & np.isfinite(rev)
    if ok.sum() < 8 or float(rev[ok].sum()) <= 0:
        return None
    return _clip(float((h["cfo"] - explained)[ok].sum()) / float(rev[ok].sum()), -0.4, 0.4, 0.0)


def _param_draws(
    p: dict,
    g: pd.Series,
    rev: pd.Series,
    costs: pd.Series,
    fit: dict,
    q: pd.DataFrame,
    a: dict,
    da_used: pd.Series,
    short_rate: pd.Series,
    anchor_k: dict,
    f5: bool,
    reg: dict,
    k: int,
) -> list[dict]:
    """MM-F9: parameter vectors from a residual bootstrap, re-estimated with the same estimators as the point fit.

    Growth: AR(1) residuals resampled and the series rebuilt, then mu, phi and sigma_g re-estimated. Costs: the split's
    quarterly residuals resampled around the fitted costs, then F, v, rho_m, sigma_m (and, under F5, the anchored CFO
    residual) re-estimated. Seeded by ticker and quarter, so a firm-year always gets the same draws.
    """
    rng = np.random.default_rng(zlib.crc32(f"{p['ticker']}|{p['last_quarter']}".encode()))
    x = g.tail(32).to_numpy(float)
    x = x[np.isfinite(x)]
    phi_raw, _, e_g = _ar1(x)
    e_g = e_g - e_g.mean() if len(e_g) else e_g
    x_mean = float(x.mean()) if len(x) else 0.0
    w_g = a["growth_shrink"]
    offset = 0.0
    if S.active("F14"):
        offset = -reg["hazard"] / max(reg["hazard"] + reg["exit"], 1e-9) * p["rec_drift"]
    cw = pd.DataFrame({"rev": rev, "costs": costs}).dropna().tail(19)
    F_nom = p["F"] / (1.0 + anchor_k["infl"]) ** _quarters_before_last(cw.index) if anchor_k["f10"] else p["F"]
    fitted = F_nom + p["v"] * cw["rev"]
    e_c = (cw["costs"] - fitted).to_numpy(float)
    f6 = S.active("F6")
    out = []
    for _ in range(k):
        d = {"mu": p["mu"], "phi": p["phi"], "sigma_g": p["sigma_g"]}
        if len(x) >= 6:
            eb = rng.choice(e_g, size=len(x) - 1, replace=True)
            xs = np.empty(len(x))
            xs[0] = x[0]
            for t in range(1, len(x)):
                xs[t] = x_mean + phi_raw * (xs[t - 1] - x_mean) + eb[t - 1]
            mu_h = float(np.median(xs[-12:]))
            d["mu"] = _clip(w_g * mu_h + (1 - w_g) * LONG_RUN_GROWTH_Q + offset, -0.04, 0.06, LONG_RUN_GROWTH_Q)
            ph, sg, _ = _ar1(xs)
            d["phi"], d["sigma_g"] = _clip(ph, 0.0, 0.8, 0.2), _clip(sg, 0.01, 0.35, 0.05)
        d.update(F=p["F"], v=p["v"], rho_m=p["rho_m"], sigma_m=p["sigma_m"])
        if len(e_c) >= 6:
            cs = costs.copy()
            cs.loc[cw.index] = fitted.to_numpy(float) + rng.choice(e_c, size=len(cw), replace=True)
            fi = _fit_costs(rev, cs, a, anchor_k["infl"])
            rm, sm, _ = _ar1(_margin_resid(fi, q["season"], f6).to_numpy(float))
            d.update(
                F=float(fi["F"]), v=float(fi["v"]), rho_m=_clip(rm, 0.0, 0.9, 0.5), sigma_m=_clip(sm, 0.002, 0.08, 0.01)
            )
            if f5:
                oc = _anchor_ocf(q, da_used, short_rate, d["F"], d["v"], anchor_k)
                if oc is not None:
                    d["ocf_ratio"] = oc
            if "fixed_adj_f" in p and p["base_rev0"] > 0:
                d["fixed_adj_f"] = d["F"] / p["base_rev0"]
        out.append({kk: float(vv) for kk, vv in d.items()})
    return out


def _margin_resid(fit: dict, seasons: pd.Series, demean_season: bool) -> pd.Series:
    """Cost-ratio residuals of the quarterly window around the fitted split (in the fit's dollars)."""
    win = fit["win"]
    r = win["rev"] * fit["defl"]
    c = win["costs"] * fit["defl"]
    m = (c - fit["F"] - fit["v"] * r) / r
    if demean_season and len(m) >= 8:  # MM-F6: the seasonal pattern is predictable, not a margin shock
        m = m - m.groupby(seasons.loc[m.index]).transform("mean")
    return m


def fit_vasicek(short_rate: pd.Series) -> dict:
    r = short_rate.dropna().values
    a, b = np.polyfit(r[:-1], r[1:], 1)[::-1]
    b = min(b, 0.995)
    resid = r[1:] - (a + b * r[:-1])
    return {
        "kappa": _clip(1 - b, 0.01, 0.5, 0.05),
        "theta": _clip(a / (1 - b), 0.01, 0.05, 0.03),
        "sigma_r": _clip(np.std(resid, ddof=1), 0.001, 0.01, 0.004),
    }


# Judgement calls that are not estimated from the company's filings. The research code varies them for the
# sensitivity analysis; the product always uses these values.
ASSUMPTIONS = {
    "fixed_share_prior": FIXED_SHARE_PRIOR,
    "prior_weight": PRIOR_WEIGHT,
    "revolver_share": 0.08,  # committed facility as a share of TTM revenue when none is tagged
    "growth_shrink": 0.5,  # weight on the company's own trend growth (rest: long-run anchor)
    "beta_shrink": 0.5,  # weight on the company's own GDP beta (rest: 1.5)
    # revision-3 keys, read only when their switch is active
    "prior_tau": PRIOR_TAU,  # MM-F1 prior s.d. of the fixed share
    "fixed_adj_lambda": FIXED_ADJ_LAMBDA,  # MM-F3 speed of fixed-cost adjustment (up)
    "fixed_adj_lambda_down": None,  # MM-F3 speed down (sticky costs); None = same as up
    "t_df_pooled": None,  # MM-F7 panel df to shrink the firm's df toward (research supplies it walk-forward)
    "t_df_pool_weight": 0.5,
    "n_param_draws": N_PARAM_DRAWS,  # MM-F9
}


def calibrate(c: CompanyData, macro: pd.DataFrame, horizon: int = 12, assumptions: dict | None = None) -> dict:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN windows fall back to documented defaults
        a = {**ASSUMPTIONS, "fixed_share_prior": S.fixed_share_prior(), **(assumptions or {})}
        return _calibrate(c, macro, horizon, a)


def _calibrate(c: CompanyData, macro: pd.DataFrame, horizon: int, a: dict) -> dict:
    q = c.quarters.copy()
    src: dict[str, str] = {}
    rev = q["revenue"]
    last = q.iloc[-1]
    n_hist = len(q)
    # Revision-3 data layer (workstream A): calendar gap rows and NaN for "not reported" instead of 0. Legacy frames
    # (FINTWIN_DATA_LEGACY=1, revision 2) have no `gap` column and take the revision-2 code paths below unchanged.
    new_data = "gap" in q.columns
    reported = q
    if new_data:
        gap = q["gap"].astype("boolean").fillna(False).astype(bool)
        reported = q[~gap]
        n_hist = int((~gap).sum())
        last, stale = _last_known(q, STOCK_FIELDS, STALE_ROWS)
        if stale:
            src["stale"] = "; ".join(stale)

    # ---- revenue process ----
    seasonal = _seasonal(rev, q["season"])
    deseason = rev / seasonal[q["season"].values]
    g = np.log(deseason).diff().dropna()
    g = g[np.isfinite(g)]
    g_recent = g.tail(12)
    mu_hist = float(np.median(g_recent)) if len(g_recent) else LONG_RUN_GROWTH_Q
    w_g = a["growth_shrink"]
    mu = _clip(w_g * mu_hist + (1 - w_g) * LONG_RUN_GROWTH_Q, -0.04, 0.06, LONG_RUN_GROWTH_Q)
    phi, sigma_g, resid_g = _ar1(g.tail(32).values)
    phi = _clip(phi, 0.0, 0.8, 0.2)
    sigma_g = _clip(sigma_g, 0.01, 0.35, 0.05)
    src["mu"] = f"median deseasonalized log-growth of last {len(g_recent)} quarters, shrunk 50% toward 1.2%/q"
    src["sigma_g"] = f"robust (MAD) AR(1) residual s.d. over {min(len(g), 32)} quarters"

    # Student-t tail thickness on standardized growth residuals
    df = 30.0
    f7 = S.active("F7")
    if len(resid_g) >= 12:
        try:
            z = resid_g / max(sigma_g, 1e-9)
            # MM-F7: with the scale fixed at 1 on MAD-standardized data the t fit is misspecified; fit df and scale
            df = _clip(stats.t.fit(z, floc=0)[0] if f7 else stats.t.fit(z, floc=0, fscale=1)[0], 3.0, 30.0, 30.0)
        except Exception:
            pass
    src["t_df"] = "MLE Student-t fit on standardized growth residuals"
    if f7 and a.get("t_df_pooled"):  # per-firm df is noise (weakly identified): shrink toward the panel in 1/df
        w = float(a["t_df_pool_weight"])
        df = _clip(1.0 / (w / float(a["t_df_pooled"]) + (1 - w) / df), 3.0, 30.0, 30.0)
        src["t_df"] += f", shrunk {w:.0%} toward the panel's {float(a['t_df_pooled']):.1f}"

    # ---- macro recession regime (IFRS 9-style probability-weighted downturns) ----
    reg = recession_regime(str(q.index[-1].date()))
    yoy_rev = np.log(rev / rev.shift(4)).dropna()
    gdp = reg["gdp_yoy"]
    pairs = []
    for d, v in yoy_rev.tail(40).items():
        near = gdp.index[np.abs((gdp.index - d).days) <= 46]
        if len(near) and np.isfinite(v):
            pairs.append((float(gdp.loc[near[0]]), float(v)))
    beta_ols = np.nan
    if len(pairs) >= 12:
        xg, yr = np.array(pairs).T
        if np.var(xg) > 0:
            beta_ols = float(np.cov(xg, yr)[0, 1] / np.var(xg, ddof=1))
    w_b = a["beta_shrink"]
    beta_gdp = _clip(w_b * beta_ols + (1 - w_b) * 1.5 if np.isfinite(beta_ols) else 1.5, 0.5, 5.0, 1.5)
    src["beta_gdp"] = (
        f"revenue sensitivity to nominal GDP ({len(pairs)} quarters), shrunk 50% toward 1.5"
        if np.isfinite(beta_ols)
        else "assumption: cyclicality 1.5 (insufficient history)"
    )
    src["recession"] = (
        f"NBER recessions since 1947 ({reg['n_recessions']}): entry {reg['hazard']:.1%}/q, "
        f"mean length {1 / reg['exit']:.1f}q"
    )
    rec_drift = -beta_gdp * reg["gdp_shortfall_q"]
    if S.active("F14"):
        # MM-F14: mu is a median of mostly-expansion growth; offset the regime drift so the regime-weighted mean
        # growth equals the estimated trend instead of falling below it
        pi_rec = reg["hazard"] / max(reg["hazard"] + reg["exit"], 1e-9)
        mu = _clip(w_g * mu_hist + (1 - w_g) * LONG_RUN_GROWTH_Q - pi_rec * rec_drift, -0.04, 0.06, LONG_RUN_GROWTH_Q)
        src["mu"] += f", plus the expected recession drift ({pi_rec:.0%} of quarters in recession)"

    # ---- D&A (MM-F4): a missing tag must not leave depreciation inside the cost base AND charge it again ----
    f4 = S.active("F4")
    da_used = q["da"]
    da_flag = pd.Series(False, index=q.index)
    if f4:
        da_flag = q["da"].isna()
        if "da_missing" in q:  # data-layer flag (workstream A): not reported, even if zero-filled
            da_flag = da_flag | q["da_missing"].astype("boolean").fillna(False).astype(bool)
        t16 = q.tail(16)
        if (t16["da"].fillna(0) == 0).all() and (t16["ppe"] > 0.05 * t16["revenue"]).any():
            da_flag = da_flag | (q["da"].fillna(0) == 0)  # a zero-filled never-reported tag with material PP&E
        ppe_lag = q["ppe"].shift(1)
        obs_rate = (q["da"].where(~da_flag) / ppe_lag).tail(8)
        if not np.isfinite(obs_rate).any():
            obs_rate = (q["da"].where(~da_flag) / ppe_lag).tail(16)
        annual = q["da_annual"].where(da_flag) if "da_annual" in q else pd.Series(np.nan, index=q.index)
        if not np.isfinite(obs_rate).any():  # no quarterly D&A at all: the fiscal-year figure / 4 gives the rate
            obs_rate = (annual / ppe_lag).tail(8)
        dep_rate_f4 = _clip(np.nanmedian(obs_rate), 0.005, 0.15, 0.03)
        # the reported fiscal-year D&A / 4 where the data layer has it; else impute at the rate the twin will use,
        # so history and projection treat D&A the same way
        imputed = annual.fillna(dep_rate_f4 * ppe_lag.fillna(q["ppe"]).fillna(0.0))
        da_used = q["da"].where(~da_flag, imputed)
        da_flag = da_flag & q.index.isin(reported.index)  # gap rows carry no flows to impute
        share = float(da_flag.loc[reported.index].tail(16).mean())
        n_ann = int((da_flag & annual.notna()).loc[reported.index].tail(16).sum())
        src["da"] = (
            f"D&A missing in {share:.0%} of the last 16 quarters: {n_ann} from the fiscal-year total / 4, the rest "
            f"imputed as {dep_rate_f4:.2%}/q of PP&E"
            if share > 0
            else "reported D&A"
        )

    # ---- cost structure: operating leverage ----
    ebitda = q["operating_income"] + da_used.fillna(0)
    costs = rev - ebitda
    fit = _fit_costs(rev, costs, a, 0.006)
    F, v, win = fit["F"], fit["v"], fit["win"]
    src["F,v"] = f"constrained regression of cash operating costs on revenue, {len(win)} quarters"
    if S.active("F1"):
        fs = 1 - v * float(win["rev"].mean()) / max(float(win["costs"].mean()), 1e-9) if len(win) else np.nan
        src["F,v"] = (
            f"Bayesian regression of {fit['basis']} cash operating costs on revenue ({fit['n']} obs): prior fixed share "
            f"{a['fixed_share_prior']:.0%} (s.d. {fit['tau']:.2f}), data weight {fit['data_weight']:.0%}, "
            f"posterior fixed share {fs:.0%} ± {fit['sd_share']:.0%}"
        )
    elif fit["basis"] == "TTM":
        src["F,v"] = f"constrained regression of TTM cash operating costs on TTM revenue, {fit['n']} rolling years"
    f6 = S.active("F6")
    m_resid = _margin_resid(fit, q["season"], f6)
    rho_m, sigma_m, resid_m = _ar1(m_resid.values)
    rho_m = _clip(rho_m, 0.0, 0.9, 0.5)
    sigma_m = _clip(sigma_m, 0.002, 0.08, 0.01)
    margin_hist = (ebitda / rev).tail(16)
    target_margin = _clip(np.nanmedian(margin_hist) - 0.05, -0.5, 0.8, 0.05)

    # correlation between demand and margin shocks (aligned tails)
    n = min(len(resid_g), len(resid_m))
    rho_gm = 0.0
    if f6:  # align the two residual series by quarter, not by their tails
        rg, rm = _ar1_resid_series(g.tail(32)), _ar1_resid_series(m_resid)
        common = rg.index.intersection(rm.index)
        if len(common) >= 8:
            rho_gm = _clip(np.corrcoef(rg.loc[common], rm.loc[common])[0, 1], -0.8, 0.8, 0.0)
        m_dev0 = _clip(float(m_resid.tail(2).mean()) - float(m_resid.mean()), -0.2, 0.2, 0.0)
    elif n >= 8:
        rho_gm = _clip(np.corrcoef(resid_g[-n:], resid_m[-n:])[0, 1], -0.8, 0.8, 0.0)

    # ---- balance-sheet ratios ----
    t4 = reported.tail(4)
    cost_t4 = (F + v * t4["revenue"]).clip(lower=1e-9)
    dso = _clip((t4["receivables"] / t4["revenue"]).mean() * DAYS_Q, 0, 200, 30)
    dio = _clip((t4["inventory"] / cost_t4).mean() * DAYS_Q, 0, 600, 0)
    dpo = _clip((t4["payables"] / cost_t4).mean() * DAYS_Q, 0, 365, 45)
    ddays = _clip((t4["deferred_revenue"] / t4["revenue"]).mean() * DAYS_Q, 0, 400, 0)
    src["ddays"] = "customer deposits / deferred revenue in days of revenue (cash collected in advance)"

    t8 = reported.tail(8)
    ppe_prev = q["ppe"].shift(1).loc[t8.index]
    dep_rate = dep_rate_f4 if f4 else _clip(np.nanmedian(t8["da"] / ppe_prev), 0.005, 0.15, 0.03)
    capex_ratio = _clip(np.nanmedian(t8["capex"] / t8["revenue"]), 0.0, 0.6, 0.05)
    sbc_ratio = _clip(np.nanmedian(t8["sbc"] / t8["revenue"]), 0.0, 0.3, 0.0)

    nwc = q["receivables"] + q["inventory"] - q["payables"] - q["deferred_revenue"]
    explained = q["net_income"] + da_used + q["sbc"] - nwc.diff()
    ocf_ratio = _clip(np.nanmedian(((q["cfo"] - explained) / rev).tail(8)), -0.4, 0.4, 0.0)
    src["ocf_ratio"] = "median unexplained operating cash flow / revenue (e.g. content spend, deferred revenue)"

    f5 = S.active("F5")
    if f5:  # MM-F5: tax on the same 16-quarter window and estimator (sum/sum) as the anchored CFO residual
        t16 = q.tail(16)
        ok = np.isfinite(t16["tax"]) & np.isfinite(t16["net_income"])
        ebt16 = float((t16["net_income"] + t16["tax"])[ok].sum())
        tax_rate = _clip(float(t16["tax"][ok].sum()) / ebt16 if ebt16 > 0 else np.nan, 0.05, 0.30, 0.21)
        src["tax_rate"] = "income tax / pre-tax income, sum over the last 16 quarters (residual anchored on the same)"
    else:
        ebt = t8["net_income"] + t8["tax"]
        tax_rate = _clip(t8["tax"].sum() / ebt.sum() if ebt.sum() > 0 else np.nan, 0.05, 0.30, 0.21)

    tau_ar = 1.0
    if S.active("F13"):
        # MM-F13: estimate the receivables delay, AR_t - AR_{t-1} = (dso*rev_t/91.25 - AR_{t-1}) / tau
        h = q[["receivables", "revenue"]].tail(17)
        gap = (dso / DAYS_Q * h["revenue"] - h["receivables"].shift(1)).iloc[1:]
        step = h["receivables"].diff().iloc[1:]
        okr = np.isfinite(gap) & np.isfinite(step)
        if okr.sum() >= 8 and float((gap[okr] ** 2).sum()) > 0:
            k = float((gap[okr] * step[okr]).sum() / (gap[okr] ** 2).sum())
            tau_ar = _clip(1.0 / k if k > 0 else np.nan, 1.0, 4.0, 1.0)
        src["tau_ar"] = f"receivables adjustment delay estimated from {int(okr.sum())} quarters"

    # ---- financing ----
    debt0 = float(last["total_debt"])
    pair = q[["interest_expense", "total_debt"]].dropna()
    pair = pair[pair["total_debt"] > 0].tail(4)
    if len(pair):
        coupon = _clip((pair["interest_expense"] / pair["total_debt"]).mean() * 4, 0.005, 0.12, 0.04)
        src["coupon"] = f"interest expense / debt, last {len(pair)} reported quarters (to {pair.index[-1].date()})"
    else:
        coupon = 0.04
        src["coupon"] = "assumption: 4% (no interest expense reported)"

    # Rollover policy: share of maturing debt replaced with new debt, inferred from the 2-year debt trend.
    if new_data:  # 8 calendar quarters back, last reported debt at or just before then
        back = q["total_debt"].iloc[:-8].tail(STALE_ROWS + 1).dropna() if len(q) > 8 else pd.Series(dtype=float)
        debt_change_8q = debt0 - float(back.iloc[-1]) if len(back) else 0.0
    else:
        debt_change_8q = float(q["total_debt"].iloc[-1] - q["total_debt"].iloc[-9]) if n_hist > 8 else 0.0
    yearly_maturity = max(float(sum(c.maturities[:1])) if c.maturities else debt0 / 6, debt0 / 20, 1.0)
    refi_ratio = _clip(1 + debt_change_8q / (2 * yearly_maturity), 0.0, 1.0, 1.0)
    src["refi_ratio"] = "share of maturities refinanced, inferred from the last 8 quarters' debt trend"
    debt_hist = q["total_debt"].tail(21)
    rel = (debt_hist.diff() / debt_hist.shift(1).where(debt_hist.shift(1) > 0)).dropna()
    sigma_fin = _clip(
        1.4826 * float(np.median(np.abs(rel - rel.median()))) if len(rel) >= 6 else np.nan, 0.005, 0.15, 0.03
    )
    src["sigma_fin"] = "robust s.d. of quarterly % debt changes (discretionary financing), last 20 quarters"

    if new_data:  # dividends missing now means unknown: mean of the reported ones among the last 4 quarters
        div_recent = reported["dividends"].tail(4).dropna()
        div_q = float(div_recent.tail(2).mean()) if len(div_recent) else 0.0
        if not len(div_recent):
            src["div_q"] = "no dividends reported in the last 4 quarters, assumed 0"
    else:
        div_q = float(q["dividends"].tail(2).mean())
    fcf8 = (t8["cfo"] - t8["capex"]).clip(lower=0).sum()
    bb_ratio = _clip(t8["buybacks"].sum() / fcf8 if fcf8 > 0 else 0.0, 0.0, 1.2, 0.0)

    rev_ttm = float(reported["revenue"].tail(4).sum())
    cap_recent = q["revolver_capacity"].dropna()
    if len(cap_recent) and (q.index[-1] - cap_recent.index[-1]).days < 730:
        revolver_cap = float(cap_recent.iloc[-1])
        src["revolver_cap"] = "LineOfCreditFacilityMaximumBorrowingCapacity tag"
    else:
        revolver_cap = a["revolver_share"] * rev_ttm
        src["revolver_cap"] = f"assumption: committed facility = {a['revolver_share']:.0%} of TTM revenue"

    # the latest quarter occasionally lacks the cash tag: carry the last reported balance forward
    cash0 = float(q["cash"].ffill().iloc[-1] + q["short_investments"].fillna(0).iloc[-1])
    quarterly_costs = F + v * reported["revenue"].tail(4).mean()
    # Minimum operating cash revealed by the company's own behaviour: half its 10th-percentile cash balance over
    # three years, bounded by 1% of quarterly revenue and 20% of quarterly costs. (A cost-based floor alone forces
    # high-turnover, low-cash retailers such as Walmart to "borrow up" to cash levels they never hold.)
    hist_cash = (q["cash"] + (q["short_investments"].fillna(0) if new_data else q["short_investments"])).tail(12)
    hist_cash = hist_cash.dropna()
    revealed = 0.5 * float(hist_cash.quantile(0.1)) if len(hist_cash) >= 4 else 0.2 * quarterly_costs
    cash_floor = float(np.clip(revealed, 0.01 * reported["revenue"].tail(4).mean(), 0.2 * quarterly_costs))
    src["cash_floor"] = "half the company's 10th-percentile cash balance over 12 quarters (revealed minimum)"
    cash_target = max(0.6 * cash0, 1.5 * cash_floor)
    cash_cap = 1.5 * max(cash0, cash_target)
    src["cash_cap"] = "assumption: cash above 150% of today's level is swept into debt paydown"
    src["cash_target"] = "assumption: treasury raises new debt when cash falls below 60% of today's level"

    # maturity ladder (annual -> quarterly). Stale or missing ladders fall back to a 6-year average life.
    ladder_q = np.zeros(horizon)
    fresh = c.maturities_date and (q.index[-1] - pd.Timestamp(c.maturities_date)).days <= 450
    if fresh and sum(c.maturities) > 0:
        elapsed_q = int(round((q.index[-1] - pd.Timestamp(c.maturities_date)).days / DAYS_Q))
        yearly = list(c.maturities[:5])
        per_q = np.repeat(np.array(yearly) / 4.0, 4)[elapsed_q:]
        ladder_q[: min(horizon, len(per_q))] = per_q[:horizon]
        # short-term borrowings / commercial paper not in the ladder roll every quarter
        st = float(last["short_borrowings"] + last["commercial_paper"])
        ladder_q[:4] += st / 4.0
        src["maturities"] = f"XBRL maturity schedule as of {c.maturities_date}"
    elif S.active("M3"):
        # M3: the ladder is unknown, so say so and assume bullets: short-term borrowings roll within the year, the
        # rest matures in equal annual bullets over a 6-year average life (lumpier, and earlier, than amortization)
        st = float(np.nan_to_num(last["short_borrowings"]) + np.nan_to_num(last["commercial_paper"]))
        st = min(max(st, 0.0), debt0)
        ladder_q[:4] += st / 4.0
        ladder_q[3::4] += (debt0 - st) / 6.0
        src["maturities"] = "assumption: ladder unknown (missing/stale); annual bullets over a 6-year average life"
    else:
        ladder_q[:] = debt0 / 24.0
        src["maturities"] = "assumption: uniform amortization, 6-year average life (ladder missing/stale)"
    ladder_q = np.minimum(ladder_q, debt0)

    floating = 0.1
    if S.active("M2"):
        tagged = q["floating_debt"].dropna() if "floating_debt" in q else pd.Series(dtype=float)
        st_share = float(np.nan_to_num(last["short_borrowings"]) + np.nan_to_num(last["commercial_paper"]))
        st_share = st_share / debt0 if debt0 > 0 else 0.0
        if len(tagged) and debt0 > 0 and (q.index[-1] - tagged.index[-1]).days < 730:
            floating = _clip(float(tagged.iloc[-1]) / debt0, 0.0, 1.0, FLOATING_DEFAULT)
            src["floating"] = "variable-rate debt tag / total debt"
        else:
            from ..universe import classify

            sector = classify(c.ticker)[0]
            base = FLOATING_BY_SECTOR.get(sector, FLOATING_DEFAULT)
            floating = _clip(max(base, st_share), 0.0, 1.0, FLOATING_DEFAULT)
            src["floating"] = f"assumption: {sector or 'default'} floating share {base:.0%}" + (
                f", raised to the short-term debt share {st_share:.0%}" if st_share > base else ""
            )

    # ---- rates ----
    m = macro[macro.index <= q.index[-1] + pd.Timedelta(days=45)]
    vas = fit_vasicek(m["short_rate"].loc["2000":])
    term_premium = _clip(float((m["long_rate"] - m["short_rate"]).tail(40).median()), 0.0, 0.03, 0.012)

    anchor_k = {
        "infl": 0.006,
        "f10": S.active("F10"),
        "dep_rate": dep_rate,
        "coupon": coupon,
        "tax_rate": tax_rate,
        "sbc_ratio": sbc_ratio,
    }
    if f5:
        anchored = _anchor_ocf(q, da_used, m["short_rate"], F, v, anchor_k)
        if anchored is not None:
            ocf_ratio = anchored
            src["ocf_ratio"] = (
                "residual that makes the twin's components reproduce cumulative operating cash flow over the last "
                "16 quarters (sum/sum; includes non-operating items)"
            )

    # ---- initial stocks ----
    ar0, inv0, ap0 = float(last["receivables"]), float(last["inventory"]), float(last["payables"])
    def0 = float(last["deferred_revenue"])
    ppe0 = float(last["ppe"]) if np.isfinite(last["ppe"]) else 0.0
    equity0 = float(last["equity"])
    assets0 = float(last["assets"])
    liabilities0 = float(last["liabilities"]) if np.isfinite(last["liabilities"]) else assets0 - equity0
    other_net0 = equity0 + ap0 + def0 + debt0 - (cash0 + ar0 + inv0 + ppe0)
    other_liab0 = max(liabilities0 - ap0 - def0 - debt0, 0.0)
    ca, cl = last["current_assets"], last["current_liabilities"]
    wc_other0 = float((ca - cl) - (cash0 + ar0 + inv0 - ap0 - def0)) if np.isfinite(ca) and np.isfinite(cl) else 0.0
    retained0 = float(last["retained_earnings"]) if np.isfinite(last["retained_earnings"]) else 0.0

    hist4 = reported.tail(4)  # the last 4 reported quarters (a gap row would count as zero EBIT)
    ebit4 = hist4["operating_income"].fillna(0).values
    ebitda4 = (hist4["operating_income"] + da_used.loc[hist4.index].fillna(0)).fillna(0).values
    int4 = hist4["interest_expense"].fillna(reported["total_debt"].tail(4) * coupon / 4)
    if new_data:
        int4 = int4.fillna(debt0 * coupon / 4)
    int4 = int4.values

    season_next = (int(q["season"].iloc[-1]) + 1) % 4
    base_rev0 = float(deseason.iloc[-1])

    p = {
        "ticker": c.ticker,
        "name": c.name,
        "last_quarter": q.index[-1].date().isoformat(),
        "horizon": horizon,
        "history_quarters": n_hist,
        "seasonal": seasonal.tolist(),
        "season0": season_next,
        "base_rev0": base_rev0,
        "mu": mu,
        "phi": phi,
        "sigma_g": sigma_g,
        "g0": _clip(g.iloc[-1] if len(g) else mu, mu - 0.1, mu + 0.1, mu),
        "t_df": df,
        "rho_gm": rho_gm,
        "rec_hazard": reg["hazard"],
        "rec_exit": reg["exit"],
        "rec_drift": rec_drift,
        "rec_vol_mult": 1.5,
        "rec_state0": 1.0 if reg["in_recession_now"] else 0.0,
        "beta_gdp": beta_gdp,
        "F": F,
        "v": v,
        "rho_m": rho_m,
        "sigma_m": sigma_m,
        "infl": 0.006,
        "target_margin": target_margin,
        "cut_delay": 2,
        "cut_speed": 0.04,
        "cut_floor": 0.85,
        "dso": dso,
        "dio": dio,
        "dpo": dpo,
        "ddays": ddays,
        "tau_ar": tau_ar,
        "tau_inv": 2.0,
        "dep_rate": dep_rate,
        "capex_ratio": capex_ratio,
        "maint_capex": 0.8,
        "sbc_ratio": sbc_ratio,
        "ocf_ratio": ocf_ratio,
        "tax_rate": tax_rate,
        "coupon": coupon,
        "floating": floating,
        "refi_ratio": refi_ratio,
        "sigma_fin": sigma_fin,
        "cash_target": cash_target,
        "cash_cap": cash_cap,
        "div_q": div_q,
        "bb_ratio": bb_ratio,
        "revolver_cap": revolver_cap,
        "cash_floor": cash_floor,
        "maturities_q": ladder_q.tolist(),
        "r0": float(m["short_rate"].iloc[-1]),
        "term_premium": term_premium,
        **vas,
        "cash0": cash0,
        "ar0": ar0,
        "inv0": inv0,
        "ap0": ap0,
        "def0": def0,
        "ppe0": ppe0,
        "debt0": debt0,
        "equity0": equity0,
        "other_net0": other_net0,
        "other_liab0": other_liab0,
        "wc_other0": wc_other0,
        "retained0": retained0,
        "ebit_ttm0": ebit4.tolist(),
        "ebitda_ttm0": ebitda4.tolist(),
        "interest_ttm0": int4.tolist(),
        "_sources": src,
    }
    # revision-3 keys exist only when their switch is on, so the v2 specifications return exactly the v2 dict
    if S.active("F1"):
        p["fixed_share_sd"] = _clip(fit["sd_share"], 0.0, 10.0, 1.0)
        p["fixed_share_data_weight"] = fit["data_weight"]
    if f4:
        p["da_imputed_share"] = share
    if f6:
        p["m_dev0"] = m_dev0
        src["m_dev0"] = "mean of the last 2 cost-ratio residuals (deseasonalized), decaying at rho_m"
    if f7:
        # MAD-consistent t draws: sigma_g and sigma_m are MAD s.d.s, so match the MAD instead of the variance
        p["t_scale"] = float(1.0 / (1.4826 * stats.t.ppf(0.75, df))) if df < 30 else 1.0
    if S.active("F8"):
        p["t_mix_indep"] = 1.0  # separate mixing variables: no artificial tail dependence of demand and margin
    if S.active("F3"):
        lam = float(a["fixed_adj_lambda"])
        lam_dn = a.get("fixed_adj_lambda_down")
        p["fixed_adj_lambda"] = lam
        p["fixed_adj_lambda_down"] = float(lam if lam_dn is None else lam_dn)
        p["fixed_adj_f"] = float(F / base_rev0) if base_rev0 > 0 else 0.0
        src["fixed_adj"] = f"fixed costs adjust {lam:.0%}/q toward {p['fixed_adj_f']:.1%} of deseasonalized revenue"
        if "acquisitions" in q:
            acq = float(q["acquisitions"].tail(8).fillna(0).clip(lower=0).sum())
            p["ma_flag"] = 1.0 if acq > MA_THRESHOLD * float(rev.tail(8).sum()) else 0.0
    if S.active("M3"):
        p["ladder_unknown"] = 0.0 if src["maturities"].startswith("XBRL") else 1.0
    bad = [k for k, val in p.items() if isinstance(val, (float, np.floating)) and not np.isfinite(val)]
    bad += [k for k, val in p.items() if isinstance(val, list) and not np.all(np.isfinite(np.asarray(val, float)))]
    if bad:
        raise ValueError(f"{c.ticker}: non-finite calibrated parameters {bad}")
    if S.active("F9"):
        p["_param_draws"] = _param_draws(
            p, g, rev, costs, fit, q, a, da_used, m["short_rate"], anchor_k, f5, reg, int(a["n_param_draws"])
        )
        src["_param_draws"] = (
            f"{len(p['_param_draws'])} residual-bootstrap parameter vectors (mu, phi, sigma_g, F, v, rho_m, sigma_m)"
        )
    from ..universe import classify, sector_tolerance

    p["sector_tol"] = sector_tolerance(c.ticker)
    src["sector_tol"] = (
        f"{classify(c.ticker)[0]} sector leverage norm (median net debt/EBITDA vs universe)"
        if p["sector_tol"] != 1.0
        else "no sector adjustment"
    )
    return {k: (float(val) if isinstance(val, np.floating) else val) for k, val in p.items()}
