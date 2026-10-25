"""Calibrate model parameters from a company's own filing history (and FRED rates).

Every parameter records how it was obtained in `p["_sources"]`, so the dashboard can show
"estimated from 16 quarters of filings" versus "assumption" for each number.
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
from scipy import stats

from ..data.facts import CompanyData
from ..data.fred import recession_regime

DAYS_Q = 91.25
LONG_RUN_GROWTH_Q = 0.012  # ~5% nominal p.a., the anchor that trend growth is shrunk toward


def _clip(x, lo, hi, default):
    x = float(x) if x is not None and np.isfinite(x) else default
    return float(min(max(x, lo), hi))


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


def _fixed_variable_split(
    rev: np.ndarray, costs: np.ndarray, prior_share: float = FIXED_SHARE_PRIOR, prior_weight: float = PRIOR_WEIGHT
) -> tuple[float, float]:
    """Penalized least squares costs = F + v*rev, F >= 0.

    When revenue barely moves the regression cannot tell fixed from variable costs, so the fit is shrunk
    toward `prior_share` (FIXED_SHARE_PRIOR, 5% by default); the data dominate once revenue has varied enough to
    identify the slope.
    """
    ratio = float(np.median(costs / rev))
    v_prior = ratio * (1 - prior_share)
    scale = float(np.var(costs)) * len(costs) + 1e-9
    best = (np.inf, 0.0, v_prior)
    for v in np.arange(0.1, 1.051, 0.005):
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
}


def calibrate(c: CompanyData, macro: pd.DataFrame, horizon: int = 12, assumptions: dict | None = None) -> dict:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN windows fall back to documented defaults
        return _calibrate(c, macro, horizon, {**ASSUMPTIONS, **(assumptions or {})})


def _calibrate(c: CompanyData, macro: pd.DataFrame, horizon: int, a: dict) -> dict:
    q = c.quarters.copy()
    src: dict[str, str] = {}
    rev = q["revenue"]
    last = q.iloc[-1]
    n_hist = len(q)

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
    if len(resid_g) >= 12:
        try:
            z = resid_g / max(sigma_g, 1e-9)
            df = _clip(stats.t.fit(z, floc=0, fscale=1)[0], 3.0, 30.0, 30.0)
        except Exception:
            pass
    src["t_df"] = "MLE Student-t fit on standardized growth residuals"

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

    # ---- cost structure: operating leverage ----
    ebitda = q["operating_income"] + q["da"].fillna(0)
    costs = rev - ebitda
    win = pd.DataFrame({"rev": rev, "costs": costs}).dropna().tail(16)
    F, v = _fixed_variable_split(win["rev"].values, win["costs"].values, a["fixed_share_prior"], a["prior_weight"])
    src["F,v"] = f"constrained regression of cash operating costs on revenue, {len(win)} quarters"
    m_resid = (win["costs"] - F - v * win["rev"]) / win["rev"]
    rho_m, sigma_m, resid_m = _ar1(m_resid.values)
    rho_m = _clip(rho_m, 0.0, 0.9, 0.5)
    sigma_m = _clip(sigma_m, 0.002, 0.08, 0.01)
    margin_hist = (ebitda / rev).tail(16)
    target_margin = _clip(np.nanmedian(margin_hist) - 0.05, -0.5, 0.8, 0.05)

    # correlation between demand and margin shocks (aligned tails)
    n = min(len(resid_g), len(resid_m))
    rho_gm = 0.0
    if n >= 8:
        rho_gm = _clip(np.corrcoef(resid_g[-n:], resid_m[-n:])[0, 1], -0.8, 0.8, 0.0)

    # ---- balance-sheet ratios ----
    t4 = q.tail(4)
    cost_t4 = (F + v * t4["revenue"]).clip(lower=1e-9)
    dso = _clip((t4["receivables"] / t4["revenue"]).mean() * DAYS_Q, 0, 200, 30)
    dio = _clip((t4["inventory"] / cost_t4).mean() * DAYS_Q, 0, 600, 0)
    dpo = _clip((t4["payables"] / cost_t4).mean() * DAYS_Q, 0, 365, 45)
    ddays = _clip((t4["deferred_revenue"] / t4["revenue"]).mean() * DAYS_Q, 0, 400, 0)
    src["ddays"] = "customer deposits / deferred revenue in days of revenue (cash collected in advance)"

    t8 = q.tail(8)
    ppe_prev = q["ppe"].shift(1).tail(8)
    dep_rate = _clip(np.nanmedian(t8["da"] / ppe_prev), 0.005, 0.15, 0.03)
    capex_ratio = _clip(np.nanmedian(t8["capex"] / t8["revenue"]), 0.0, 0.6, 0.05)
    sbc_ratio = _clip(np.nanmedian(t8["sbc"] / t8["revenue"]), 0.0, 0.3, 0.0)

    nwc = q["receivables"] + q["inventory"] - q["payables"] - q["deferred_revenue"]
    explained = q["net_income"] + q["da"] + q["sbc"] - nwc.diff()
    ocf_ratio = _clip(np.nanmedian(((q["cfo"] - explained) / rev).tail(8)), -0.4, 0.4, 0.0)
    src["ocf_ratio"] = "median unexplained operating cash flow / revenue (e.g. content spend, deferred revenue)"

    ebt = t8["net_income"] + t8["tax"]
    tax_rate = _clip(t8["tax"].sum() / ebt.sum() if ebt.sum() > 0 else np.nan, 0.05, 0.30, 0.21)

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

    div_q = float(q["dividends"].tail(2).mean())
    fcf8 = (t8["cfo"] - t8["capex"]).clip(lower=0).sum()
    bb_ratio = _clip(t8["buybacks"].sum() / fcf8 if fcf8 > 0 else 0.0, 0.0, 1.2, 0.0)

    rev_ttm = float(rev.tail(4).sum())
    cap_recent = q["revolver_capacity"].dropna()
    if len(cap_recent) and (q.index[-1] - cap_recent.index[-1]).days < 730:
        revolver_cap = float(cap_recent.iloc[-1])
        src["revolver_cap"] = "LineOfCreditFacilityMaximumBorrowingCapacity tag"
    else:
        revolver_cap = a["revolver_share"] * rev_ttm
        src["revolver_cap"] = f"assumption: committed facility = {a['revolver_share']:.0%} of TTM revenue"

    # the latest quarter occasionally lacks the cash tag: carry the last reported balance forward
    cash0 = float(q["cash"].ffill().iloc[-1] + q["short_investments"].fillna(0).iloc[-1])
    quarterly_costs = F + v * rev.tail(4).mean()
    # Minimum operating cash revealed by the company's own behaviour: half its 10th-percentile cash balance over
    # three years, bounded by 1% of quarterly revenue and 20% of quarterly costs. (A cost-based floor alone forces
    # high-turnover, low-cash retailers such as Walmart to "borrow up" to cash levels they never hold.)
    hist_cash = (q["cash"] + q["short_investments"]).tail(12).dropna()
    revealed = 0.5 * float(hist_cash.quantile(0.1)) if len(hist_cash) >= 4 else 0.2 * quarterly_costs
    cash_floor = float(np.clip(revealed, 0.01 * rev.tail(4).mean(), 0.2 * quarterly_costs))
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
    else:
        ladder_q[:] = debt0 / 24.0
        src["maturities"] = "assumption: uniform amortization, 6-year average life (ladder missing/stale)"
    ladder_q = np.minimum(ladder_q, debt0)

    # ---- rates ----
    m = macro[macro.index <= q.index[-1] + pd.Timedelta(days=45)]
    vas = fit_vasicek(m["short_rate"].loc["2000":])
    term_premium = _clip(float((m["long_rate"] - m["short_rate"]).tail(40).median()), 0.0, 0.03, 0.012)

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

    hist4 = q.tail(4)
    ebit4 = hist4["operating_income"].fillna(0).values
    ebitda4 = (hist4["operating_income"] + hist4["da"].fillna(0)).fillna(0).values
    int4 = hist4["interest_expense"].fillna(q["total_debt"].tail(4) * coupon / 4).values

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
        "rec_drift": -beta_gdp * reg["gdp_shortfall_q"],
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
        "tau_ar": 1.0,
        "tau_inv": 2.0,
        "dep_rate": dep_rate,
        "capex_ratio": capex_ratio,
        "maint_capex": 0.8,
        "sbc_ratio": sbc_ratio,
        "ocf_ratio": ocf_ratio,
        "tax_rate": tax_rate,
        "coupon": coupon,
        "floating": 0.1,
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
    bad = [k for k, val in p.items() if isinstance(val, (float, np.floating)) and not np.isfinite(val)]
    bad += [k for k, val in p.items() if isinstance(val, list) and not np.all(np.isfinite(np.asarray(val, float)))]
    if bad:
        raise ValueError(f"{c.ticker}: non-finite calibrated parameters {bad}")
    from ..universe import classify, sector_tolerance

    p["sector_tol"] = sector_tolerance(c.ticker)
    src["sector_tol"] = (
        f"{classify(c.ticker)[0]} sector leverage norm (median net debt/EBITDA vs universe)"
        if p["sector_tol"] != 1.0
        else "no sector adjustment"
    )
    return {k: (float(val) if isinstance(val, np.floating) else val) for k, val in p.items()}
