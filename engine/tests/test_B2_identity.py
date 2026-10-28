"""B2: with every revision-3 switch off, the model is bit-identical to the v2 code (rev3 @ 20b2610).

`_reference_simulate` below is a verbatim copy of `simulate` from engine/fintwin/model/sd_model.py at rev3 before
workstream B2; only its name changed. Do not edit it.
"""

# ruff: noqa: E501

from __future__ import annotations

import numpy as np
import pytest
from conftest import make_params

from fintwin.model import sd_model
from fintwin.model.ratings import ICR_LOWER, SPREADS
from fintwin.scenarios.presets import DEFAULT_LEVERS, PRESETS, build_scenario
from fintwin.stochastic.shocks import draw_shocks

DAYS_Q = 91.25
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


def _reference_simulate(p: dict, scn: dict, eps: np.ndarray, levers: dict) -> dict:
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
    m_dev = np.zeros(N, f)
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
    icr_fixed = np.full(N, float(np.sum(p["ebit_ttm0"])) / max(float(np.sum(p["interest_ttm0"])), 1e-9), f)

    out = {k: np.zeros((N, T), f) for k in OUTPUTS}
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
        base = base * np.exp(g)
        g_prev = g
        rev = base * seasonal[(p["season0"] + t) % 4] * (1.0 + scn["sales_shock"][t])
        override = scn.get("revenue_override")
        if override is not None and np.isfinite(override[t]):
            rev = np.full(N, override[t], f)  # conditional (structural) backtests feed realized revenue

        # --- costs: fixed (inflating, cuttable) + variable ratio with mean-reverting shocks ---
        m_dev = p["rho_m"] * m_dev + p["sigma_m"] * e_m
        v = np.maximum(p["v"] + m_dev + scn["cost_shift"][t], 0.0)
        fixed = p["F"] * (1.0 + p["infl"]) ** (t + 1) * cut_mult
        costs = fixed + v * rev
        ebitda = rev - costs
        da = p["dep_rate"] * ppe
        ebit = ebitda - da

        # --- rates and credit spread (R1: spread follows last TTM coverage) ---
        rate = rate + p["kappa"] * (p["theta"] - rate) + p["sigma_r"] * e_r
        r_eff = np.maximum(rate + scn["rate_shift"][t], 0.0)
        icr_prev = ebit_hist.sum(1) / np.maximum(int_hist.sum(1), 1e-9)
        spread = spreads[_rank(icr_prev if loop_r1 else icr_fixed)] * spread_scale + scn["spread_shift"][t]
        mkt_rate = r_eff + p["term_premium"] + spread

        eff_rate = (1.0 - p["floating"]) * coupon + p["floating"] * (r_eff + spread)
        interest = debt * eff_rate / 4.0 + revolver * (r_eff + spread + 0.015) / 4.0
        int_income = np.maximum(cash, 0.0) * r_eff * 0.9 / 4.0
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
        stressed = (cash < 1.5 * p["cash_floor"]) | (icr_prev < 2.5)
        capex = p["capex_ratio"] * rev
        if levers.get("cut_capex", True):
            capex = np.where(stressed, np.minimum(capex, p["maint_capex"] * da), capex)
        ppe = ppe + capex - da

        div = np.full(N, p["div_q"], f)
        bb = p["bb_ratio"] * np.maximum(cfo - capex, 0.0)
        if levers.get("cut_payouts", True):
            div = np.where(stressed, 0.0, div)
            bb = np.where(stressed, 0.0, bb)

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
            new_debt > 0, (coupon * remaining + mkt_rate * (refi + issued_debt)) / np.maximum(new_debt, 1e-9), coupon
        )
        debt = new_debt

        # --- liquidity backstops: revolver, then equity ---
        floor = p["cash_floor"]
        if levers.get("draw_revolver", True):
            draw = np.clip(floor - cash, 0.0, np.maximum(p["revolver_cap"] - revolver, 0.0))
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
        margin = ebitda / np.maximum(rev, 1e-9)
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
        icr = ebit_hist.sum(1) / np.maximum(int_hist.sum(1), 1e-9)
        ebitda_ttm = ebitda_hist.sum(1)
        net_debt = debt + revolver - cash
        nd_ebitda = np.where(ebitda_ttm > 0, net_debt / np.maximum(ebitda_ttm, 1e-9), 99.0)
        rank = _rank(icr)
        undrawn = np.maximum(p["revolver_cap"] - revolver, 0.0)
        liquidity = cash + undrawn
        breached = breached | (cash < 0)

        # --- Altman Z'' (book-value version for non-manufacturers) ---
        assets = cash + ar + inv + ppe + other_net + p["other_liab0"]
        liabilities = np.maximum(assets - equity, 1e-9)
        working_cap = cash + ar + inv - ap - deferred + wc_other
        z = (6.56 * working_cap + 3.26 * ret_earn + 6.72 * ebit_hist.sum(1)) / np.maximum(
            assets, 1e-9
        ) + 1.05 * equity / liabilities

        # --- health score 0-100 ---
        burn = np.maximum(fixed + interest + ladder[min(t + 1, T - 1)] * (1 - access), 1e-9)
        s_liq = np.clip(liquidity / burn / 8.0, 0.0, 1.0) * 100
        # sector tolerance: sectors that structurally carry more leverage (utilities, telecom, rail) are scored
        # against their own norms; the dynamics (spreads, market access) still use the raw coverage
        tol = p.get("sector_tol", 1.0)
        s_cov = _rank(icr * tol) / 14.0 * 100
        lev_cap = 6.0 * tol
        s_lev = np.where(ebitda_ttm > 0, np.clip((lev_cap - nd_ebitda) / lev_cap, 0.0, 1.0), 0.0) * 100
        s_solv = np.clip((z - 1.1) / 1.5, 0.0, 1.0) * 100
        health = 0.3 * s_liq + 0.3 * s_cov + 0.2 * s_lev + 0.2 * s_solv
        health = np.where(breached, np.minimum(health, 25.0), health)

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

        # identity residual: assets - liabilities - equity must stay at its initial value (zero by construction)
        out.setdefault("identity_gap", np.zeros((N, T), f))[:, t] = (
            cash + ar + inv + ppe + other_net - ap - deferred - debt - revolver - equity
        )
    return out


# ---------------------------------------------------------------------------------------------------- the tests
def _firms():
    """A levered firm, a stressed one that draws its revolver, and a debt-free loss-maker (the MM-F11 case)."""
    return {
        "levered": make_params(),
        "stressed": make_params(F=420.0, cash0=150.0, debt0=2500.0, interest_ttm0=[40.0] * 4, ebit_ttm0=[20.0] * 4),
        "debt_free_loss": make_params(
            F=560.0, debt0=0.0, maturities_q=[0.0] * 12, interest_ttm0=[0.0] * 4, ebit_ttm0=[-30.0] * 4
        ),
    }


@pytest.fixture
def no_switch_env(monkeypatch):
    monkeypatch.delenv("FINTWIN_FIXES", raising=False)
    monkeypatch.delenv("FINTWIN_SPEC", raising=False)


@pytest.mark.parametrize("firm", ["levered", "stressed", "debt_free_loss"])
@pytest.mark.parametrize("preset", list(PRESETS))
def test_switches_off_is_bit_identical_to_v2(no_switch_env, firm, preset):
    p = _firms()[firm]
    scn = build_scenario(PRESETS[preset]["knobs"], p["horizon"])
    eps = draw_shocks(p, 300, p["horizon"], seed=11)
    ref = _reference_simulate(p, scn, eps, DEFAULT_LEVERS)
    new = sd_model.simulate(p, scn, eps, DEFAULT_LEVERS)
    assert set(new) == set(ref)
    for k in ref:
        assert np.array_equal(new[k], ref[k]), k


@pytest.mark.parametrize("spec", ["v2-pre", "v2-rev"])
def test_v2_specs_are_bit_identical(monkeypatch, spec):
    monkeypatch.delenv("FINTWIN_FIXES", raising=False)
    monkeypatch.setenv("FINTWIN_SPEC", spec)
    for p in _firms().values():
        scn = build_scenario(PRESETS["pandemic"]["knobs"], p["horizon"])
        eps = draw_shocks(p, 300, p["horizon"], seed=3)
        ref = _reference_simulate(p, scn, eps, DEFAULT_LEVERS)
        new = sd_model.simulate(p, scn, eps, DEFAULT_LEVERS)
        assert all(np.array_equal(new[k], ref[k]) for k in ref)


def test_explicit_off_levers_are_bit_identical(monkeypatch):
    monkeypatch.setenv("FINTWIN_FIXES", "M1,F11,M5")
    p = _firms()["stressed"]
    scn = build_scenario(PRESETS["recession"]["knobs"], p["horizon"])
    eps = draw_shocks(p, 300, p["horizon"], seed=5)
    ref = _reference_simulate(p, scn, eps, DEFAULT_LEVERS)
    new = sd_model.simulate(p, scn, eps, {**DEFAULT_LEVERS, "M1": False, "F11": False, "M5": False})
    assert all(np.array_equal(new[k], ref[k]) for k in ref)
