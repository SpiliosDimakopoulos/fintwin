"""Stock-and-flow model of a company's financial machinery, stepped quarterly.

Stocks:  cash, receivables, inventory, payables, net PP&E, term debt, revolver, equity, other net assets.
Flows:   revenue, cash operating costs, D&A, interest, tax, SBC, working-capital changes, capex,
         dividends, buybacks, debt maturities, refinancing, revolver draws/repayments, equity issuance.
Loops:   R1 leverage -> coverage -> rating spread -> interest -> cash -> revolver -> leverage
         R2 distress -> lost market access -> maturities paid from cash
         B1 cash below floor -> capex, dividend and buyback cuts
         B2 margin squeeze -> delayed fixed-cost cuts

The core is deterministic given pre-drawn shocks `eps` [N, T, 5]
(revenue, margin, rate, discretionary financing, regime uniform),
so a second implementation (TypeScript, in the browser) can be checked against it number for number.
Everything is vectorized across the N Monte Carlo paths.
"""

from __future__ import annotations

import numpy as np

# revision-3 specification switches: B1's spec module is the single source of truth. M1, M4 and M5 are
# pre-specified extensions, off in every specification; they are turned on with FINTWIN_FIXES.
from ..stochastic.spec import active
from .constants import CASH_YIELD_SHARE, DAYS_Q, EPS, HEALTH_WEIGHTS, REVOLVER_SPREAD
from .ratings import ICR_LOWER, ICR_MATERIALITY, SPREADS, effective_icr

G_LOG_MAX = 50.0  # see the revenue step in `simulate`


def _switch(levers: dict, fix_id: str) -> bool:
    """A lever with the fix id as key (e.g. levers["M1"] = True) overrides the environment for one run."""
    return bool(levers[fix_id]) if fix_id in levers else active(fix_id)


# M1: maintenance covenant defaults (override per company with the p keys of the same name).
# 4.0x net debt / EBITDA and 2.5x EBITDA / interest are the usual levels of maintenance tests in US leveraged
# and crossover revolvers (most cluster between 3.5x and 4.5x leverage and 2.0x and 3.0x coverage). One quarter of
# cure: a failed test must be fixed by the next test date (equity cure or waiver), else it is a breach. On breach the
# undrawn commitment is frozen (revolver availability 0); drawn amounts are not accelerated.
COVENANT_DEFAULTS = {
    "cov_max_nd_ebitda": 4.0,
    "cov_min_icr": 2.5,
    "cov_cure_q": 1,
    "cov_revolver_avail": 0.0,
    "revolver_maturity_q": None,
}
# M5: payout floors. A REIT must distribute 90% of taxable income (IRC §857(a)); net income stands in for it.
# Utilities protect their dividend: under stress they keep `payout_keep_div` of it instead of cutting to zero
# (assumption; FirstEnergy's 2014 cut, one of the largest, kept 64%).
PAYOUT_DEFAULTS = {
    "reit": {"payout_floor_ni": 0.9, "payout_keep_div": 0.0},
    "utility": {"payout_floor_ni": 0.0, "payout_keep_div": 0.65},
}
NO_PAYOUT_FLOOR = {"payout_floor_ni": 0.0, "payout_keep_div": 0.0}

# B1 stress trigger (docs/METHODOLOGY.md): cash below 1.5x the floor or trailing coverage below 2.5x (the BBB bucket's
# lower bound) cuts capex to maintenance and suspends payouts. Assumption.
STRESS_CASH_MULT = 1.5
STRESS_ICR = 2.5
# Health-score scales (docs/METHODOLOGY.md): 8 quarters of runway score 100; net debt / EBITDA scores 100 at 0x and 0 at
# 6x (times the sector tolerance); Altman Z'' maps 1.1 (distress zone) to 0 and 2.6 (safe zone) to 100.
RUNWAY_FULL_Q = 8.0
LEV_CAP = 6.0
Z_DISTRESS, Z_SPAN = 1.1, 1.5
BREACH_HEALTH_CAP = 25.0  # a path that ran out of cash scores at most this
ND_EBITDA_NO_EBITDA = 99.0  # reported net debt / EBITDA when TTM EBITDA <= 0


def payout_class(sic: int | None) -> str:
    """'reit' (SIC 6798), 'utility' (4900-4949) or '' for the M5 payout floor."""
    if sic is None:
        return ""
    if int(sic) == 6798:
        return "reit"
    return "utility" if 4900 <= int(sic) <= 4949 else ""


OUTPUTS = [
    "revenue",
    "ebitda",
    "ebit",
    "net_income",
    "cfo",
    "fcf",
    "capex",
    "cash",
    "debt",
    "revolver",
    "liquidity",
    "interest",
    "icr",
    "nd_ebitda",
    "rating",
    "zscore",
    "health",
    "breach",
    "equity",
    "issued",
    "fixed_cost_mult",
    "debt_issued",
    "recession",
    "dividends",
    "buybacks",
    "h_liq",
    "h_cov",
    "h_lev",
    "h_solv",
]


def _rank(icr):
    return np.searchsorted(ICR_LOWER, icr, side="right") - 1


def simulate(p: dict, scn: dict, eps: np.ndarray, levers: dict) -> dict:
    """Run the model.

    p:      calibrated parameters (see stochastic.calibrate.calibrate)
    scn:    per-quarter scenario arrays of length T: sales_shock, rate_shift, spread_shift,
            cost_shift, dio_shift, refi_access
    eps:    shocks [N, T, 5] (4 standardized + 1 uniform for the recession regime)
    levers: CFO responses: cut_capex, cut_payouts, issue_debt, draw_revolver, issue_equity, cut_costs
    """
    N, T, _ = eps.shape
    f = np.float64

    # --- initial stocks ---
    cash = np.full(N, p["cash0"], f)
    ar = np.full(N, p["ar0"], f)
    inv = np.full(N, p["inv0"], f)
    ap = np.full(N, p["ap0"], f)
    deferred = np.full(N, p["def0"], f)
    ppe = np.full(N, p["ppe0"], f)
    debt = np.full(N, p["debt0"], f)
    revolver = np.zeros(N, f)
    equity = np.full(N, p["equity0"], f)
    other_net = np.full(N, p["other_net0"], f)
    ret_earn = np.full(N, p["retained0"], f)
    wc_other = p["wc_other0"]  # non-modelled current items, held fixed

    base = np.full(N, p["base_rev0"], f)
    g_prev = np.full(N, p["g0"], f)
    # MM-F6: start from the current margin deviation (calibrated), which then decays at rho_m
    m_dev = np.full(N, p.get("m_dev0", 0.0), f) if _switch(levers, "F6") else np.zeros(N, f)
    rate = np.full(N, p["r0"], f)
    coupon = np.full(N, p["coupon"], f)
    cut_mult = np.ones(N, f)
    low_count = np.zeros(N, f)
    ebit_hist = np.tile(np.asarray(p["ebit_ttm0"], f), (N, 1))
    ebitda_hist = np.tile(np.asarray(p["ebitda_ttm0"], f), (N, 1))
    int_hist = np.tile(np.asarray(p["interest_ttm0"], f), (N, 1))
    breached = np.zeros(N, bool)
    regime = np.full(N, p.get("rec_state0", 0.0), f)  # 1 = economy in recession
    use_regime = levers.get("recessions", True)
    # research switches (loop ablations); both loops are always on in the product and the browser engine
    loop_r1, loop_r2 = levers.get("loop_r1", True), levers.get("loop_r2", True)
    # research-only assumptions (sensitivity analysis); the product and the browser engine use the defaults
    spread_scale = p.get("spread_scale", 1.0)
    spreads = np.asarray(p.get("spreads", SPREADS), f)  # point-in-time table in research runs
    acc_hi, acc_lo = p.get("access_icr", (1.5, 0.8))
    acc_mid, acc_low = p.get("access_levels", (0.6, 0.3))
    icr_fixed = np.full(N, float(np.sum(p["ebit_ttm0"])) / max(float(np.sum(p["interest_ttm0"])), EPS), f)

    # revision-3 switches; every branch below is skipped when they are off, so v2-pre outputs are unchanged
    on_m1, on_f11, on_m5 = _switch(levers, "M1"), _switch(levers, "F11"), _switch(levers, "M5")
    mat = p.get("icr_materiality", ICR_MATERIALITY)
    lam_up = lam_dn = 0.0  # MM-F3 off: lambda 0 is exactly the v2 recursion
    if _switch(levers, "F3"):
        lam_up = p.get("fixed_adj_lambda", 0.0)
        lam_dn = p.get("fixed_adj_lambda_down", lam_up)
        f_adj = p.get("fixed_adj_f", 0.0)
        F_t = np.full(N, p["F"], f)
    if on_m1 or on_f11:
        rev_hist = np.full((N, 4), p.get("rev_ttm0", 4.0 * p["base_rev0"]) / 4.0, f)
    if on_f11:
        icr_fixed = effective_icr(icr_fixed, float(np.sum(p["interest_ttm0"])), rev_hist.sum(1), cash - debt, mat)
    if on_m1:
        cv = {k: p.get(k, d) for k, d in COVENANT_DEFAULTS.items()}
        rcap = np.full(N, p["revolver_cap"], f)  # committed facility still available to draw
        cov_fail = np.zeros(N, f)
        cov_breached = np.zeros(N, bool)
    if on_m5:
        po = {k: p.get(k, d) for k, d in PAYOUT_DEFAULTS.get(p.get("payout_class", ""), NO_PAYOUT_FLOOR).items()}

    out = {k: np.zeros((N, T), f) for k in OUTPUTS}
    if on_m1:
        out["cov_breach"] = np.zeros((N, T), f)
        out["revolver_avail"] = np.zeros((N, T), f)
    # identity residual: assets - liabilities - equity must stay at its initial value (zero by construction); a
    # diagnostic for the tests, not a model output
    out["identity_gap"] = np.zeros((N, T), f)
    ladder = np.asarray(p["maturities_q"], f)
    seasonal = np.asarray(p["seasonal"], f)

    for t in range(T):
        e_g, e_m, e_r, e_d, u = eps[:, t, 0], eps[:, t, 1], eps[:, t, 2], eps[:, t, 3], eps[:, t, 4]

        # --- macro regime: Markov switching between expansion and recession (NBER base rates) ---
        if use_regime:
            regime = np.where(
                regime > 0, np.where(u < p["rec_exit"], 0.0, 1.0), np.where(u < p["rec_hazard"], 1.0, 0.0)
            )
        else:
            regime = np.zeros(N, f)

        # --- revenue: AR(1) growth in deseasonalized level, then season and scenario shock ---
        vol = p["sigma_g"] * (1.0 + (p["rec_vol_mult"] - 1.0) * regime)
        g = p["mu"] + p["phi"] * (g_prev - p["mu"]) + vol * e_g + p["rec_drift"] * regime
        # numerical floor only: a quarterly log growth above 50 (x5e21) cannot be a forecast, and 12 such quarters
        # overflow float64 to inf -> NaN; no path of a realistic draw comes near it (fat tails stay as specified)
        base = base * np.exp(np.minimum(g, G_LOG_MAX))
        g_prev = g
        rev = base * seasonal[(p["season0"] + t) % 4] * (1.0 + scn["sales_shock"][t])
        override = scn.get("revenue_override")
        if override is not None and np.isfinite(override[t]):
            rev = np.full(N, override[t], f)  # conditional (structural) backtests feed realized revenue

        # --- costs: fixed (inflating, cuttable) + variable ratio with mean-reverting shocks ---
        m_dev = p["rho_m"] * m_dev + p["sigma_m"] * e_m
        v = np.maximum(p["v"] + m_dev + scn["cost_shift"][t], 0.0)
        if lam_up > 0 or lam_dn > 0:
            # MM-F3: fixed costs adjust partially (lambda per quarter) toward f_adj x deseasonalized revenue;
            # the revenue is taken after the override, so realized revenue drives it in the transmission test
            F_t = F_t * (1.0 + p["infl"])
            rbar = rev / seasonal[(p["season0"] + t) % 4]
            gap = f_adj * rbar - F_t
            F_t = F_t + np.where(gap > 0, lam_up, lam_dn) * gap
            fixed = F_t * cut_mult
        else:
            fixed = p["F"] * (1.0 + p["infl"]) ** (t + 1) * cut_mult
        costs = fixed + v * rev
        ebitda = rev - costs
        da = p["dep_rate"] * ppe
        ebit = ebitda - da

        # --- rates and credit spread (R1: spread follows last TTM coverage) ---
        rate = rate + p["kappa"] * (p["theta"] - rate) + p["sigma_r"] * e_r
        r_eff = np.maximum(rate + scn["rate_shift"][t], 0.0)
        icr_prev = ebit_hist.sum(1) / np.maximum(int_hist.sum(1), EPS)
        if on_f11:
            icr_prev = effective_icr(icr_prev, int_hist.sum(1), rev_hist.sum(1), cash - debt - revolver, mat)
        spread = spreads[_rank(icr_prev if loop_r1 else icr_fixed)] * spread_scale + scn["spread_shift"][t]
        mkt_rate = r_eff + p["term_premium"] + spread

        eff_rate = (1.0 - p["floating"]) * coupon + p["floating"] * (r_eff + spread)
        interest = debt * eff_rate / 4.0 + revolver * (r_eff + spread + REVOLVER_SPREAD) / 4.0
        int_income = np.maximum(cash, 0.0) * r_eff * CASH_YIELD_SHARE / 4.0
        ebt = ebit - interest + int_income
        tax = p["tax_rate"] * np.maximum(ebt, 0.0)
        ni = ebt - tax

        # --- working capital: receivables and inventory adjust toward targets with first-order delays
        # (production and collections lag demand), payables and customer deposits move immediately ---
        ar_new = ar + (p["dso"] / DAYS_Q * rev - ar) / p["tau_ar"]
        inv_target = np.maximum(p["dio"] + scn["dio_shift"][t], 0.0) / DAYS_Q * costs
        inv_new = inv + (inv_target - inv) / p["tau_inv"]
        ap_new = p["dpo"] / DAYS_Q * costs
        def_new = p["ddays"] / DAYS_Q * rev
        d_nwc = (ar_new - ar) + (inv_new - inv) - (ap_new - ap) - (def_new - deferred)
        ar, inv, ap, deferred = ar_new, inv_new, ap_new, def_new

        sbc = p["sbc_ratio"] * rev
        other_cfo = p["ocf_ratio"] * rev
        cfo = ni + da + sbc - d_nwc + other_cfo
        other_net = other_net - other_cfo

        # --- B1: stress triggers management responses ---
        stressed = (cash < STRESS_CASH_MULT * p["cash_floor"]) | (icr_prev < STRESS_ICR)
        capex = p["capex_ratio"] * rev
        if levers.get("cut_capex", True):
            capex = np.where(stressed, np.minimum(capex, p["maint_capex"] * da), capex)
        ppe = ppe + capex - da

        div = np.full(N, p["div_q"], f)
        bb = p["bb_ratio"] * np.maximum(cfo - capex, 0.0)
        if levers.get("cut_payouts", True):
            div = np.where(stressed, 0.0, div)
            bb = np.where(stressed, 0.0, bb)
            if on_m5:  # M5: utilities keep part of the dividend under stress
                div = np.where(stressed, np.maximum(div, po["payout_keep_div"] * p["div_q"]), div)
        if on_m5:  # M5: the REIT distribution requirement binds whatever the stress
            div = np.maximum(div, po["payout_floor_ni"] * np.maximum(ni, 0.0))

        # --- debt: maturities, rollover and new issuance.
        # R2: market access shrinks as coverage deteriorates (distressed issuers only place part of
        # what they need, at punitive spreads), and closes entirely in a credit freeze ---
        maturing = np.minimum(ladder[t], debt)
        access = (
            np.where(icr_prev >= acc_hi, 1.0, np.where(icr_prev >= acc_lo, acc_mid, acc_low))
            if loop_r2
            else np.ones(N, f)
        )
        access = access * scn["refi_access"][t]
        refi = maturing * p["refi_ratio"] * access
        cash = cash + cfo - capex - div - bb - maturing + refi
        issued_debt = np.zeros(N, f)
        if levers.get("issue_debt", True):
            issued_debt = np.maximum(p["cash_target"] - cash, 0.0) * access
            cash = cash + issued_debt
        # discretionary financing (opportunistic issuance / early paydown), calibrated from history
        disc = p["sigma_fin"] * debt * e_d
        disc = np.where(disc > 0, disc * access, -np.minimum(-disc, np.maximum(cash - p["cash_target"], 0.0)))
        cash = cash + disc
        issued_debt = issued_debt + np.maximum(disc, 0.0)
        remaining = debt - maturing + np.minimum(disc, 0.0)
        new_debt = remaining + refi + issued_debt
        coupon = np.where(
            new_debt > 0, (coupon * remaining + mkt_rate * (refi + issued_debt)) / np.maximum(new_debt, EPS), coupon
        )
        debt = new_debt

        rev_cap = p["revolver_cap"]
        if on_m1:
            # M1: the facility expires at its maturity; the drawn balance is termed out like maturing debt (as far
            # as market access allows), the rest is repaid from cash, and nothing can be drawn afterwards
            if cv["revolver_maturity_q"] is not None and t == int(cv["revolver_maturity_q"]):
                termed = revolver * p["refi_ratio"] * access
                coupon = np.where(
                    debt + termed > 0, (coupon * debt + mkt_rate * termed) / np.maximum(debt + termed, EPS), coupon
                )
                cash = cash - (revolver - termed)
                debt = debt + termed
                revolver = np.zeros(N, f)
                rcap = np.zeros(N, f)
            rev_cap = rcap

        # --- liquidity backstops: revolver, then equity ---
        floor = p["cash_floor"]
        if levers.get("draw_revolver", True):
            draw = np.clip(floor - cash, 0.0, np.maximum(rev_cap - revolver, 0.0))
        else:
            draw = np.zeros(N, f)
        repay = np.where(cash > p["cash_target"], np.minimum(revolver, cash - p["cash_target"]), 0.0)
        revolver = revolver + draw - repay
        cash = cash + draw - repay
        # cash sweep: idle cash far above the treasury target pays down debt
        sweep = np.minimum(np.maximum(cash - p["cash_cap"], 0.0), debt)
        debt = debt - sweep
        cash = cash - sweep
        issued = np.zeros(N, f)
        if levers.get("issue_equity", False):
            issued = np.maximum(floor - cash, 0.0) * (access > 0)
            cash = cash + issued
        equity = equity + ni + sbc - div - bb + issued
        ret_earn = ret_earn + ni - div

        # --- B2: sustained margin squeeze -> fixed-cost cuts after a delay ---
        margin = ebitda / np.maximum(rev, EPS)
        low = margin < p["target_margin"]
        low_count = np.where(low, low_count + 1, 0)
        if levers.get("cut_costs", True):
            cut_mult = np.where(
                low_count >= p["cut_delay"],
                np.maximum(cut_mult - p["cut_speed"], p["cut_floor"]),
                np.minimum(cut_mult + 0.5 * p["cut_speed"], 1.0),
            )

        # --- rolling TTM metrics ---
        ebit_hist = np.column_stack([ebit_hist[:, 1:], ebit])
        ebitda_hist = np.column_stack([ebitda_hist[:, 1:], ebitda])
        int_hist = np.column_stack([int_hist[:, 1:], interest])
        icr = ebit_hist.sum(1) / np.maximum(int_hist.sum(1), EPS)
        ebitda_ttm = ebitda_hist.sum(1)
        net_debt = debt + revolver - cash
        nd_ebitda = np.where(ebitda_ttm > 0, net_debt / np.maximum(ebitda_ttm, EPS), ND_EBITDA_NO_EBITDA)
        if on_m1 or on_f11:
            rev_hist = np.column_stack([rev_hist[:, 1:], rev])
        if on_f11:
            icr = effective_icr(icr, int_hist.sum(1), rev_hist.sum(1), -net_debt, mat)
        if on_m1:
            # M1: quarter-end maintenance test on TTM figures; it governs the revolver from the next quarter
            int_ttm = int_hist.sum(1)
            fail = np.zeros(N, bool)
            if cv["cov_max_nd_ebitda"] is not None:
                fail |= (net_debt > 0) & ((ebitda_ttm <= 0) | (nd_ebitda > cv["cov_max_nd_ebitda"]))
            if cv["cov_min_icr"] is not None:  # coverage tested only where interest is material (as MM-F11)
                material = int_ttm > mat * np.abs(rev_hist.sum(1))
                fail |= material & (ebitda_ttm / np.maximum(int_ttm, EPS) < cv["cov_min_icr"])
            cov_fail = np.where(fail, cov_fail + 1, 0)
            cov_breached = cov_breached | (cov_fail > cv["cov_cure_q"])
            # lenders freeze (or cut to a share of) the undrawn commitment; once cut it is not restored
            rcap = np.where(cov_breached, np.minimum(rcap, np.maximum(revolver, cv["cov_revolver_avail"] * rcap)), rcap)
            rev_cap = rcap
        rank = _rank(icr)
        undrawn = np.maximum(rev_cap - revolver, 0.0)
        liquidity = cash + undrawn
        breached = breached | (cash < 0)

        # --- Altman Z'' (book-value version for non-manufacturers) ---
        assets = cash + ar + inv + ppe + other_net + p["other_liab0"]
        liabilities = np.maximum(assets - equity, EPS)
        working_cap = cash + ar + inv - ap - deferred + wc_other
        z = (6.56 * working_cap + 3.26 * ret_earn + 6.72 * ebit_hist.sum(1)) / np.maximum(
            assets, EPS
        ) + 1.05 * equity / liabilities

        # --- health score 0-100 ---
        burn = np.maximum(fixed + interest + ladder[min(t + 1, T - 1)] * (1 - access), EPS)
        s_liq = np.clip(liquidity / burn / RUNWAY_FULL_Q, 0.0, 1.0) * 100
        # sector tolerance: sectors that structurally carry more leverage (utilities, telecom, rail) are scored
        # against their own norms; the dynamics (spreads, market access) still use the raw coverage
        tol = p.get("sector_tol", 1.0)
        s_cov = _rank(icr * tol) / 14.0 * 100
        lev_cap = LEV_CAP * tol
        s_lev = np.where(ebitda_ttm > 0, np.clip((lev_cap - nd_ebitda) / lev_cap, 0.0, 1.0), 0.0) * 100
        s_solv = np.clip((z - Z_DISTRESS) / Z_SPAN, 0.0, 1.0) * 100
        w = HEALTH_WEIGHTS
        health = w["liq"] * s_liq + w["cov"] * s_cov + w["lev"] * s_lev + w["solv"] * s_solv
        health = np.where(breached, np.minimum(health, BREACH_HEALTH_CAP), health)

        for k, val in (
            ("revenue", rev),
            ("ebitda", ebitda),
            ("ebit", ebit),
            ("net_income", ni),
            ("cfo", cfo),
            ("fcf", cfo - capex),
            ("capex", capex),
            ("cash", cash),
            ("debt", debt),
            ("revolver", revolver),
            ("liquidity", liquidity),
            ("interest", interest),
            ("icr", icr),
            ("nd_ebitda", nd_ebitda),
            ("rating", rank),
            ("zscore", z),
            ("health", health),
            ("breach", breached),
            ("equity", equity),
            ("issued", issued),
            ("fixed_cost_mult", cut_mult),
            ("debt_issued", issued_debt),
            ("recession", regime),
            ("dividends", div),
            ("buybacks", bb),
            ("h_liq", s_liq),
            ("h_cov", s_cov),
            ("h_lev", s_lev),
            ("h_solv", s_solv),
        ):
            out[k][:, t] = val
        if on_m1:
            out["cov_breach"][:, t] = cov_breached
            out["revolver_avail"][:, t] = undrawn

        out["identity_gap"][:, t] = cash + ar + inv + ppe + other_net - ap - deferred - debt - revolver - equity
    return out


# ---------------------------------------------------------------- M7: decision outputs (pure functions of `out`)
def p_liquidity_below(out: dict, x: float, n: int | None = None) -> float:
    """P(cash + undrawn revolver < x in any of the first n quarters); n = None means the whole horizon."""
    liq = out["liquidity"][:, : (n or out["liquidity"].shape[1])]
    return float((liq.min(1) < x).mean())


def maturity_wall(p: dict, horizon: int | None = None) -> list[float]:
    """Contractual term-debt maturities by quarter (the calibrated ladder). The revolver is drawn path by path, so
    its maturity (M1 `revolver_maturity_q`) is reported by `decision_outputs` from the simulated balance."""
    T = horizon or p["horizon"]
    wall = np.zeros(T)
    ladder = np.asarray(p["maturities_q"], float)[:T]
    wall[: len(ladder)] = ladder
    return wall.tolist()


def first_covenant_breach(out: dict) -> np.ndarray:
    """Per path, the first quarter (0-based) of a covenant breach, -1 if none (needs M1 on)."""
    b = out["cov_breach"] > 0
    return np.where(b.any(1), b.argmax(1), -1)


def decision_outputs(out: dict, p: dict, x: float | None = None, n: int | None = None) -> dict:
    """Runway, funding gap, maturity wall, P(liquidity < x within n) and the first covenant breach (M1).

    Quarter indices are 0-based (0 = the first simulated quarter), as in `first_covenant_breach`.
    runway: index of the first quarter in which cash + undrawn revolver falls below zero, T if it never does
    (censored at the horizon), so a breach in the first quarter gives 0;
    funding gap: per path, the worst shortfall of cash below the floor left after the model's own backstops.
    """
    liq, cash = out["liquidity"], out["cash"]
    T = liq.shape[1]
    gone = liq < 0
    runway = np.where(gone.any(1), gone.argmax(1), T).astype(float)
    gap = np.maximum(p["cash_floor"] - cash, 0.0).max(1)
    res = {
        "runway_q_median": float(np.median(runway)),
        "runway_q_p10": float(np.percentile(runway, 10)),
        "runway_censored_share": float((runway >= T).mean()),
        "funding_gap_p50": float(np.percentile(gap, 50)),
        "funding_gap_p95": float(np.percentile(gap, 95)),
        "funding_gap_mean": float(gap.mean()),
        "p_funding_gap": float((gap > 0).mean()),
        "maturity_wall": maturity_wall(p, T),
    }
    mq = p.get("revolver_maturity_q")
    if mq is not None and 0 < int(mq) < T:  # drawn balance falling due at the revolver's maturity (median path)
        res["revolver_due"] = {"q": int(mq), "median": float(np.median(out["revolver"][:, int(mq) - 1]))}
    if x is not None:
        res["p_liquidity_below"] = {"x": float(x), "n": int(n or T), "p": p_liquidity_below(out, x, n)}
    if "cov_breach" in out:
        first = first_covenant_breach(out)
        res["p_cov_breach"] = float((first >= 0).mean())
        res["first_cov_breach_q_median"] = float(np.median(first[first >= 0])) if (first >= 0).any() else None
    return res
