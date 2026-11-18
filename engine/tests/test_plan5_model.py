"""REVISION_PLAN_5 model corrections (v4a: G3, G4, G5, G7, G8, G9, G10) and acquisitions (v4b: G6).

Each correction is shown to act when its switch is on and to do nothing when it is off (v3)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from test_B1_parity import synthetic_company
from test_B2_mechanics import bal

from fintwin.model import sd_model
from fintwin.scenarios.presets import DEFAULT_LEVERS, PRESETS, build_scenario
from fintwin.stochastic import calibrate as C
from fintwin.stochastic import spec
from fintwin.stochastic.shocks import draw_shocks

G_ALL = ("G3", "G4", "G6", "G7", "G8")


def cal(c, macro, spec_name="v3", fixes=None, **a):
    with spec.using(spec_name, fixes):
        return C.calibrate(c, macro, 8, a or None)


def flat_run(p, rev_path, spec_name="v3", fixes=None, **lev):
    """One path, no shocks or recessions, revenue fed as realized (the conditional test)."""
    T = len(rev_path)
    scn = build_scenario({}, T)
    scn["revenue_override"] = np.asarray(rev_path, float)
    eps = np.zeros((1, T, 5))
    eps[:, :, 4] = 0.99
    with spec.using(spec_name, fixes):
        return sd_model.simulate(p, scn, eps, {**DEFAULT_LEVERS, "recessions": False, **lev})


def flat_p(**over):
    return bal(**{"sigma_m": 0.0, "sigma_fin": 0.0, "sigma_r": 0.0, "horizon": 8, **over})


# ---------------------------------------------------------------- G3 liquidity mechanics
def test_G3_cash_target_40pct_and_assumption(macro):
    c = synthetic_company()
    off, on = cal(c, macro, "v3"), cal(c, macro, "v3", "+G3")
    assert off["cash_target"] == pytest.approx(max(0.6 * off["cash0"], 1.5 * off["cash_floor"]))
    assert on["cash_target"] == pytest.approx(max(0.4 * on["cash0"], 1.5 * on["cash_floor"]))
    assert "40%" in on["_sources"]["cash_target"] and "60%" in off["_sources"]["cash_target"]
    sens = cal(c, macro, "v3", "+G3", cash_target_frac=0.3)
    assert sens["cash_target"] == pytest.approx(max(0.3 * sens["cash0"], 1.5 * sens["cash_floor"]))
    assert cal(c, macro, "v3", cash_target_frac=0.3)["cash_target"] == off["cash_target"]  # read only under G3


def test_G3_dividend_cut_is_proportional_to_coverage_shortfall():
    # trailing ICR 1.25 = half of 2.5, cash far above the floor: G3 pays half the dividend, v3 pays none
    p = flat_p(ebit_ttm0=[25.0] * 4, interest_ttm0=[20.0] * 4, cash0=2000.0, div_q=10.0)
    rev = [1000.0] * 8
    off, on = flat_run(p, rev, "v3"), flat_run(p, rev, "v3", "+G3")
    assert off["dividends"][0, 0] == 0.0
    assert on["dividends"][0, 0] == pytest.approx(5.0)
    healthy = flat_p(ebit_ttm0=[200.0] * 4, interest_ttm0=[20.0] * 4, cash0=2000.0)
    assert flat_run(healthy, rev, "v3", "+G3")["dividends"][0, 0] == pytest.approx(healthy["div_q"])


def test_G3_cash_floor_smoothed():
    # coverage fine, cash at 0.75 x the old trigger (1.5 x floor): G3 pays 75%, v3 pays nothing
    p = flat_p(ebit_ttm0=[200.0] * 4, interest_ttm0=[20.0] * 4, cash_floor=80.0, cash0=90.0, div_q=10.0)
    rev = [1000.0] * 8
    assert flat_run(p, rev, "v3")["dividends"][0, 0] == 0.0
    assert flat_run(p, rev, "v3", "+G3")["dividends"][0, 0] == pytest.approx(10.0 * 90.0 / 120.0)


# ---------------------------------------------------------------- G4 loss carryforward
def test_G4_losses_offset_later_taxable_income():
    p = flat_p(F=300.0, v=0.5, debt0=0.0, maturities_q=[0.0] * 8, cash0=3000.0)
    rev = [400.0] * 4 + [1400.0] * 4  # four loss quarters, then profits
    off, on = flat_run(p, rev, "v3"), flat_run(p, rev, "v3", "+G4")
    assert np.array_equal(off["net_income"][:, :4], on["net_income"][:, :4])  # no tax on losses either way
    assert (on["net_income"][0, 4:] >= off["net_income"][0, 4:] - 1e-9).all()
    assert on["net_income"][0, 4] > off["net_income"][0, 4]
    # once the carryforward is used up, the tax is the same again (up to interest on the cash the shield kept)
    assert on["net_income"][0, -1] == pytest.approx(off["net_income"][0, -1], rel=1e-2)


# ---------------------------------------------------------------- G5 dividend run-rate
def test_G5_run_rate_rule():
    rr = C._dividend_run_rate
    assert rr(pd.Series([1.0, 1.0, 1.0, 10.0])) == pytest.approx(1.0)  # special replaced by the median of the others
    assert rr(pd.Series([5.0, 1.0, 2.0, 3.0, 4.0])) == pytest.approx(2.5)  # sum of the last four / 4
    assert rr(pd.Series([np.nan, 2.0, 2.0, 2.0])) == pytest.approx(2.0)  # missing quarters left out
    assert rr(pd.Series([], dtype=float)) == 0.0


def test_G5_special_dividend_not_annualized(macro):
    c = synthetic_company()
    c.quarters.loc[c.quarters.index[-1], "dividends"] = 500.0  # a special dividend in the last quarter
    off, on = cal(c, macro, "v3"), cal(c, macro, "v3", "+G5")
    assert off["div_q"] == pytest.approx(260.0)  # v3: mean of the last two quarters
    assert on["div_q"] == pytest.approx(20.0)


# ---------------------------------------------------------------- G6 acquisitions and divestitures
def test_G6_flag_components():
    c = synthetic_company()
    q = c.quarters.copy()
    assert C.acquisition_flag(q)["g6_flag"] == 0.0
    assert C.acquisition_flag(q)["g6_acq_share_max"] is None
    q["acquisitions"] = 0.0
    q.loc[q.index[-2], "acquisitions"] = 0.15 * float(q["revenue"].tail(5).head(4).sum())
    f = C.acquisition_flag(q)
    assert f["g6_flag"] == 1.0 and f["g6_acq_share_max"] > 0.10
    jump = c.quarters.copy()
    jump.loc[jump.index[-3]:, ["revenue", "assets"]] *= 1.5  # revenue and assets both +50% in one quarter
    assert C.acquisition_flag(jump)["g6_jump_quarters"] == 1 and C.acquisition_flag(jump)["g6_flag"] == 1.0
    assert C.acquisition_flag(jump, n=2)["g6_flag"] == 0.0  # outside the window


def test_G6_flag_stored_but_model_unchanged_in_v3(macro):
    c = synthetic_company()
    c.quarters.loc[c.quarters.index[-3]:, ["revenue", "assets"]] *= 1.5
    v3, v4b = cal(c, macro, "v3"), cal(c, macro, "v4b")
    assert v3["g6_flag"] == 1.0 and "ma_scale" not in v3
    assert v4b["ma_scale"] == 1.0
    assert cal(c, macro, "v4b", ma_scale=False)["ma_scale"] == 0.0  # imposed (e.g. the hindsight flag)
    assert cal(synthetic_company(), macro, "v4b", ma_scale=True)["ma_scale"] == 1.0
    assert "g6_flag" not in cal(c, macro, "v2-rev")  # the v2 dicts stay exactly revision 2


def test_G6_fixed_cost_scales_with_revenue():
    p = flat_p(F=300.0, v=0.5, ma_scale=1.0)
    rev = [2000.0] * 8  # revenue doubled from base_rev0 = 1000 (an acquisition)
    off, on = flat_run(p, rev, "v4a"), flat_run(p, rev, "v4b")
    fixed_on = rev[0] * (1 - p["v"]) - on["ebitda"][0, 0]
    fixed_off = rev[0] * (1 - p["v"]) - off["ebitda"][0, 0]
    assert fixed_on == pytest.approx(600.0)
    assert fixed_off == pytest.approx(300.0 * (1 + p["infl"]))
    unflagged = flat_run({**p, "ma_scale": 0.0}, rev, "v4b")
    assert np.array_equal(unflagged["ebitda"], off["ebitda"])


# ---------------------------------------------------------------- G7 bound on the F3 move
def test_G7_bounds_the_F3_adjustment():
    p = flat_p(F=300.0, v=0.5, fixed_adj_lambda=1.0, fixed_adj_lambda_down=1.0, fixed_adj_f=1.5)  # target 5x F
    rev = [1000.0] * 8
    f_cal = 300.0 * (1 + p["infl"])
    off, on = flat_run(p, rev, "v3"), flat_run(p, rev, "v3", "+G7")
    assert rev[0] * 0.5 - off["ebitda"][0, 0] == pytest.approx(1500.0)
    assert rev[0] * 0.5 - on["ebitda"][0, 0] == pytest.approx(2.0 * f_cal)
    low = {**p, "fixed_adj_f": 0.01}
    assert rev[0] * 0.5 - flat_run(low, rev, "v3", "+G7")["ebitda"][0, 0] == pytest.approx(0.5 * f_cal)


# ---------------------------------------------------------------- G8 NaN coverage rated D
def test_G8_nan_coverage_rated_d():
    icr = np.array([np.nan, 100.0, -1.0])
    assert sd_model._rank(icr).tolist() == [14, 14, 0]
    assert sd_model._rank(icr, True).tolist() == [0, 14, 0]
    p = flat_p(ebit_ttm0=[np.nan] * 4)  # undefined trailing coverage
    rev = [1000.0] * 8
    off, on = flat_run(p, rev, "v3"), flat_run(p, rev, "v3", "+G8")
    assert on["interest"][0, 0] > off["interest"][0, 0]  # D spread instead of AAA


# ---------------------------------------------------------------- G9 opening cash, G10 interest sign
def test_G9_opening_cash_uses_stale_balance_rule(macro):
    c = synthetic_company()
    c.quarters.loc[c.quarters.index[-1], "short_investments"] = np.nan
    off, on = cal(c, macro, "v3"), cal(c, macro, "v3", "+G9")
    cash_last = float(c.quarters["cash"].iloc[-1])
    assert off["cash0"] == pytest.approx(cash_last)  # v3: a missing last balance counted as 0
    assert on["cash0"] == pytest.approx(cash_last + 50.0)  # G9: carried from the previous quarter
    assert on["other_net0"] - off["other_net0"] == pytest.approx(-50.0)  # the opening balance sheet still balances


def test_G10_negative_interest_is_a_cost(macro):
    c = synthetic_company()
    c.quarters["interest_expense"] = -c.quarters["interest_expense"]
    off, on = cal(c, macro, "v3"), cal(c, macro, "v3", "+G10")
    assert off["coupon"] == pytest.approx(0.005)  # negative ratio clipped to the floor
    assert on["coupon"] == pytest.approx(0.045, rel=0.02)
    assert min(on["interest_ttm0"]) > 0 > max(off["interest_ttm0"])


# ---------------------------------------------------------------- identity and v3 invariance
@pytest.mark.parametrize("spec_name", ["v4a", "v4b"])
def test_balance_sheet_identity_holds_under_v4(macro, spec_name):
    c = synthetic_company()
    c.quarters.loc[c.quarters.index[-3]:, ["revenue", "assets"]] *= 1.5  # flagged under G6
    p = cal(c, macro, spec_name)
    assert p.get("ma_scale", 1.0) == 1.0
    for preset in ("recession", "pandemic"):
        scn = build_scenario(PRESETS[preset]["knobs"], p["horizon"])
        eps = draw_shocks(p, 300, p["horizon"], seed=7)
        with spec.using(spec_name):
            out = sd_model.simulate(p, scn, eps, DEFAULT_LEVERS)
        scale = max(abs(p["equity0"]), 1.0)
        assert np.abs(out["identity_gap"]).max() / scale < 1e-9
    stressed = bal(F=420.0, cash0=150.0, debt0=2500.0, interest_ttm0=[40.0] * 4, ebit_ttm0=[20.0] * 4, ma_scale=1.0)
    eps = draw_shocks(stressed, 300, stressed["horizon"], seed=3)
    with spec.using(spec_name):
        out = sd_model.simulate(stressed, build_scenario(PRESETS["recession"]["knobs"], 12), eps, DEFAULT_LEVERS)
    assert np.abs(out["identity_gap"]).max() < 1e-6


def test_g_switches_off_leave_v3_unchanged(macro):
    """v3 with every G lever explicitly off equals v3; v4b with them off equals v3 on the same parameters."""
    p = bal(F=420.0, cash0=150.0, debt0=2500.0, interest_ttm0=[40.0] * 4, ebit_ttm0=[20.0] * 4, ma_scale=1.0)
    scn = build_scenario(PRESETS["recession"]["knobs"], 12)
    eps = draw_shocks(p, 200, 12, seed=5)
    with spec.using("v3"):
        ref = sd_model.simulate(p, scn, eps, DEFAULT_LEVERS)
    with spec.using("v4b"):
        off = sd_model.simulate(p, scn, eps, {**DEFAULT_LEVERS, **{g: False for g in G_ALL}})
        on = sd_model.simulate(p, scn, eps, DEFAULT_LEVERS)
    assert all(np.array_equal(off[k], ref[k]) for k in ref)
    assert not np.array_equal(on["dividends"], ref["dividends"])
    c = synthetic_company()
    with spec.using("v3"):
        base = C.calibrate(c, macro, 8)
    with spec.using("v4b", "-G2,-G3,-G4,-G5,-G6,-G7,-G8,-G9,-G10"):
        g_off = C.calibrate(c, macro, 8)
    assert base == g_off


def test_G10_facts_negative_interest_read_as_cost():
    import numpy as np
    import pandas as pd

    from fintwin.data import facts
    from fintwin.stochastic import spec as S

    def run(name):
        q = pd.DataFrame({k: [5.0, 5.0, 5.0, 5.0] for k in facts.SIGNED_OUTFLOWS})
        q.loc[2, "interest_expense"] = -5.0
        with S.using(name):
            facts._normalise_signs(q, [], {})
        return q["interest_expense"].tolist()

    assert np.isnan(run("v3")[2])
    assert run("v4a")[2] == 5.0


# ---------------------------------------------------------------- P1 pooled structural parameters (v4p)
def test_P1_shrink_is_precision_weighted():
    assert C._shrink(10.0, 1.0, {"m": 20.0, "s": 1.0}) == pytest.approx(15.0)
    assert C._shrink(10.0, 0.1, {"m": 20.0, "s": 10.0}) == pytest.approx(10.0, abs=0.01)
    assert C._shrink(10.0, np.nan, {"m": 20.0, "s": 1.0}) == pytest.approx(15.0)  # no s.e.: fixed weight 0.5
    assert C._shrink(np.nan, 1.0, {"m": 20.0, "s": 1.0}) == 20.0


def test_P1_pool_table_walk_forward_and_industry_fallback():
    from fintwin.research.pooling import prior_for, pool_table

    rows = [{"origin": f"{y}-02-15", "industry": "A", "pool_inputs": {"dso": [30.0 + y - 2014, 1.0]}}
            for y in range(2014, 2020) for _ in range(40)]
    rows += [{"origin": "2014-02-15", "industry": "B", "pool_inputs": {"dso": [90.0, 1.0]}} for _ in range(5)]
    t = pool_table(rows)
    assert "2016" not in t["prior"]  # nothing at cutoffs <= 2013
    assert prior_for(t, "2017-02-15", "A")["dso"]["m"] == pytest.approx(30.0)  # only 2014 rows
    assert prior_for(t, "2017-02-15", "B")["dso"]["n"] > 5  # B has < 30 firm-years: all-firm prior


def test_P1_records_inputs_in_v4_and_shrinks_only_in_v4p(macro):
    c = synthetic_company()
    b = cal(c, macro, "v4b")
    assert "pool_inputs" in b and "pool_inputs" not in cal(c, macro, "v3")
    # the synthetic firm's ratios are constant (s.e. 0: its own value is exact); refi has no s.e. (fixed weight)
    prior = {"dso": {"m": b["dso"] + 50.0, "s": 1.0}, "refi_ratio": {"m": 0.0, "s": 0.1}, "elast": {"m": 0.5, "s": 0.1}}
    p = cal(c, macro, "v4p", pool_prior=prior)
    assert p["dso"] == pytest.approx(b["dso"])
    assert p["refi_ratio"] == pytest.approx(0.5 * b["refi_ratio"])
    assert cal(c, macro, "v4b", pool_prior=prior)["refi_ratio"] == pytest.approx(b["refi_ratio"])  # off without P1
    assert p["F"] != pytest.approx(b["F"])  # the pooled elasticity moved the cost-split prior
