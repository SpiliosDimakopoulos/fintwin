"""B1: recovery and behaviour tests for the revision-3 calibration fixes (MM-F*, M2, M3), each behind its switch."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from scipy import stats
from test_B1_parity import synthetic_company

from fintwin.model.sd_model import simulate
from fintwin.scenarios.presets import DEFAULT_LEVERS, build_scenario
from fintwin.stochastic import calibrate as C
from fintwin.stochastic import spec
from fintwin.stochastic.mc import simulate_paths
from fintwin.stochastic.shocks import draw_shocks


def cal(c, macro, spec_name="v3", fixes=None, **a):
    with spec.using(spec_name, fixes):
        return C.calibrate(c, macro, 8, a or None)


def fixed_share(p, c):
    r = float(c.quarters["revenue"].tail(4).mean())
    return p["F"] / (p["F"] + p["v"] * r)


def twin_cfo_margin(p, rev_level, T=8):
    """Twin CFO / revenue with revenue held flat and no shocks."""
    scn = build_scenario({}, T)
    scn["revenue_override"] = np.full(T, rev_level)
    eps = np.zeros((1, T, 5))
    eps[:, :, 4] = 0.99
    out = simulate(p, scn, eps, {**DEFAULT_LEVERS, "recessions": False})
    return float(out["cfo"].sum() / out["revenue"].sum())


# ---------------------------------------------------------------- spec switches
def test_spec_parsing(monkeypatch):
    monkeypatch.delenv("FINTWIN_SPEC", raising=False)
    monkeypatch.delenv("FINTWIN_FIXES", raising=False)
    assert spec.spec() == "v2-rev" and spec.fixes() == frozenset() and spec.fixed_share_prior() == 0.05
    monkeypatch.setenv("FINTWIN_SPEC", "v3")
    assert spec.active("MM-F5") and spec.active("F1") and not spec.active("F9") and not spec.active("M2")
    monkeypatch.setenv("FINTWIN_FIXES", "+F9,-F3")
    assert spec.active("F9") and not spec.active("F3") and spec.active("F1")
    monkeypatch.setenv("FINTWIN_FIXES", "F5,F4")
    assert spec.fixes() == {"F5", "F4"}
    monkeypatch.setenv("FINTWIN_FIXES", "none")
    assert spec.fixes() == frozenset()
    with spec.using("v2-pre", "F5"):
        assert spec.spec() == "v2-pre" and spec.fixes() == {"F5"} and spec.fixed_share_prior() == 0.35
    monkeypatch.setenv("FINTWIN_SPEC", "v4")
    with pytest.raises(ValueError):
        spec.spec()
    assert [s for s, _ in spec.LADDER] == ["v2-pre", "+F5", "+F4", "+F1", "+F2", "+F3"]


# ---------------------------------------------------------------- MM-F1
@pytest.mark.parametrize("prior", [0.05, 0.35, 0.60])
def test_F1_fully_variable_firm_recovers_zero_fixed_share_whatever_the_prior(macro, prior):
    c = synthetic_company(fixed=0.0, v=0.85, noise=0.002, trend=0.03, season_amp=0.0)
    assert fixed_share(cal(c, macro, "v3", "F1", fixed_share_prior=prior), c) < 0.05
    if prior == 0.35:  # revision 2: about 2/3 prior, whatever the data say
        assert fixed_share(cal(c, macro, "v2-pre"), c) > 0.15


@pytest.mark.parametrize("prior", [0.05, 0.35])
def test_F1_recovers_a_40pct_fixed_share_when_revenue_varies(macro, prior):
    c = synthetic_company(fixed=600.0, v=0.4, trend=0.05, season_amp=0.0, noise=0.005)
    q = c.quarters.tail(16)
    truth = 600.0 / (600.0 + 0.4 * q["revenue"].mean())
    assert q["revenue"].std() / q["revenue"].mean() > 0.2
    p = cal(c, macro, "v3", "F1", fixed_share_prior=prior)
    est = p["F"] / (p["F"] + p["v"] * q["revenue"].mean())
    assert abs(est - truth) < 0.05
    assert p["fixed_share_data_weight"] > 0.9 and 0 < p["fixed_share_sd"] < 0.1


def test_F1_flat_revenue_falls_back_on_the_prior(macro):
    c = synthetic_company(fixed=0.0, v=0.85, trend=0.0, season_amp=0.0, noise=0.02)
    q = c.quarters.tail(16)
    q_mean = q["revenue"].mean()
    p = cal(c, macro, "v3", "F1", fixed_share_prior=0.35, prior_tau=0.05)
    assert p["fixed_share_data_weight"] < 0.9
    assert p["F"] / (p["F"] + p["v"] * q_mean) > 0.1  # little information: shrunk toward 35%


def test_F1_posterior_split_closed_form_matches_brute_force():
    rng = np.random.default_rng(3)
    r = 1000 + 300 * rng.random(16)
    c = 200 + 0.6 * r + 10 * rng.standard_normal(16)
    res = C._posterior_split(r, c, 0.35, 0.15)
    ratio = np.median(c / r)
    best = (np.inf, 0, 0)
    for v in np.linspace(0.1, 1.05, 4001):
        F = max(np.mean(c - v * r), 0.0)
        resid = c - c.mean() - (np.cov(r, c, ddof=0)[0, 1] / np.var(r)) * (r - r.mean())
        s2 = max(np.sum(resid**2) / 14, (1e-3 * c.mean()) ** 2)
        o = np.sum((c - F - v * r) ** 2) / s2 + ((v - ratio * 0.65) / (0.15 * ratio)) ** 2
        best = min(best, (o, F, v))
    assert res["v"] == pytest.approx(best[2], abs=1e-3) and res["F"] == pytest.approx(best[1], rel=1e-2)


def test_F1_walk_forward_selection_uses_earlier_years_only():
    years = np.repeat(np.arange(2010, 2020), 100)
    err = {0.05: np.where(years <= 2014, 1.0, 9.0), 0.5: np.where(years <= 2014, 2.0, 0.0)}
    assert C.select_walk_forward(years, err, 2017) == 0.05  # 2015+ outcomes not yet known in 2017
    assert C.select_walk_forward(years, err, 2012) is None  # fewer than 500 earlier firm-years
    assert set(C.TAU_GRID) >= {C.PRIOR_TAU, float("inf")} and C.FIXED_ADJ_LAMBDA in C.LAMBDA_GRID


# ---------------------------------------------------------------- MM-F2
def test_F2_seasonal_firm_is_not_read_as_fixed(macro):
    # costs track the trend fully but only 10% of a +-25% seasonal swing (budgeted annually); no fixed costs at all
    c = synthetic_company(fixed=0.0, v=0.8, season_amp=0.25, cost_season=0.1, trend=0.02)
    assert fixed_share(cal(c, macro, "v3", "F1,F2"), c) < 0.1
    assert fixed_share(cal(c, macro, "v3", "F1"), c) > 0.3  # quarterly levels read the smoothing as fixed cost


def test_F2_ttm_requires_consecutive_quarters():
    idx = pd.DatetimeIndex(["2020-03-31", "2020-06-30", "2020-09-30", "2020-12-31", "2021-06-30", "2021-09-30"])
    out = C._ttm(pd.DataFrame({"rev": np.ones(6), "costs": np.ones(6)}, index=idx))
    assert list(out.index) == [pd.Timestamp("2020-12-31")]  # the windows over the missing 2021Q1 are dropped


# ---------------------------------------------------------------- MM-F3
def test_F3_partial_adjustment_keys_and_acquirer_flag(macro):
    c = synthetic_company()
    c.quarters["acquisitions"] = 0.0
    c.quarters.loc[c.quarters.index[-3], "acquisitions"] = 0.2 * float(c.quarters["revenue"].tail(8).sum())
    p = cal(c, macro, "v3", "F3", fixed_adj_lambda=0.3)
    assert p["fixed_adj_lambda"] == 0.3 and p["fixed_adj_lambda_down"] == 0.3
    assert p["fixed_adj_f"] == pytest.approx(p["F"] / p["base_rev0"])
    assert p["ma_flag"] == 1.0
    assert "fixed_adj_f" not in cal(c, macro, "v3", "-F3")


# ---------------------------------------------------------------- MM-F4
def test_F4_missing_da_no_longer_double_counts(macro):
    full = synthetic_company(fixed_infl=0.006, seed=4)
    miss = synthetic_company(fixed_infl=0.006, seed=4, da_missing=True)
    lvl = float(full.quarters["revenue"].tail(16).mean())
    ref = twin_cfo_margin(cal(full, macro, "v3"), lvl)
    assert abs(twin_cfo_margin(cal(miss, macro, "v3"), lvl) - ref) < 0.005
    v2_gap = twin_cfo_margin(cal(full, macro, "v2-pre"), lvl) - twin_cfo_margin(cal(miss, macro, "v2-pre"), lvl)
    assert v2_gap > 0.02  # revision 2: D&A inside costs, charged again at 3% of PP&E, no compensation
    p = cal(miss, macro, "v3", "F4")
    assert p["da_imputed_share"] == 1.0 and "imputed" in p["_sources"]["da"]
    oi = miss.quarters["operating_income"].tail(4).to_numpy()
    assert np.all(np.asarray(p["ebitda_ttm0"]) > oi)


def test_F4_zero_filled_or_flagged_da_counts_as_missing(macro):
    zero = synthetic_company(seed=5)
    zero.quarters["da"] = 0.0  # a data layer that zero-fills a never-reported tag
    flagged = synthetic_company(seed=5)
    flagged.quarters["da_missing"] = True
    flagged.quarters["da"] = 0.0
    for c in (zero, flagged):
        assert cal(c, macro, "v3", "F4")["da_imputed_share"] == 1.0


# ---------------------------------------------------------------- MM-F5
def test_F5_non_cash_tax_one_off_does_not_move_twin_cfo(macro):
    base = synthetic_company(fixed_infl=0.006, seed=3)
    shock = synthetic_company(fixed_infl=0.006, seed=3)
    i = shock.quarters.index[-5]
    shock.quarters.loc[i, "tax"] += 400.0  # e.g. DTA remeasurement: NI falls, cash does not
    shock.quarters.loc[i, "net_income"] -= 400.0
    lvl = float(base.quarters["revenue"].tail(16).mean())
    d3 = twin_cfo_margin(cal(shock, macro, "v3", "F5"), lvl) - twin_cfo_margin(cal(base, macro, "v3", "F5"), lvl)
    d2 = twin_cfo_margin(cal(shock, macro, "v2-pre"), lvl) - twin_cfo_margin(cal(base, macro, "v2-pre"), lvl)
    assert abs(d3) < 0.001 and d2 < -0.008


def test_F5_twin_nests_the_16_quarter_cfo_margin_at_constant_revenue(macro):
    c = synthetic_company(trend=0.0, season_amp=0.0, noise=0.002, fixed_infl=0.0)
    # lumpy unmodelled operating cash (e.g. annual dividends from affiliates): 2% of revenue on average, which a
    # median of quarterly residuals ignores
    c.quarters["cfo"] += np.where(c.quarters["season"] == 3, 0.08, 0.0) * c.quarters["revenue"]
    h = c.quarters.tail(16)
    hist = float(h["cfo"].sum() / h["revenue"].sum())
    lvl = float(h["revenue"].mean())
    assert abs(twin_cfo_margin(cal(c, macro, "v3", "F5"), lvl) - hist) < 0.004
    assert abs(twin_cfo_margin(cal(c, macro, "v2-rev"), lvl) - hist) > 0.01
    assert cal(c, macro, "v3", "F5")["_sources"]["tax_rate"].startswith(
        "income tax / pre-tax income, sum over the last 16"
    )


# ---------------------------------------------------------------- MM-F6
def test_F6_margin_residuals_and_current_deviation(macro):
    c = synthetic_company(seed=6)
    c.quarters.loc[c.quarters.index[-2:], "operating_income"] -= 0.03 * c.quarters["revenue"].iloc[-2:]
    p = cal(c, macro, "v3", "F6")
    assert p["m_dev0"] > 0.02  # costs 3% of revenue above the fit in the last two quarters: carried, not dropped
    assert "m_dev0" not in cal(c, macro, "v2-rev")
    s = synthetic_company(fixed=0.0, v=0.8, season_amp=0.25, cost_season=0.1)
    assert cal(s, macro, "v3", "F1,F2,F6")["sigma_m"] < cal(s, macro, "v3", "F1,F2")["sigma_m"]


# ---------------------------------------------------------------- MM-F7, MM-F8
def _mad_sd(x):
    return 1.4826 * np.median(np.abs(x - np.median(x)))


def test_F7_t_draws_match_the_mad_sd():
    p = {"rho_gm": 0.0, "t_df": 4.0}
    z_old = draw_shocks(p, 4000, 12, seed=1)[:, :, 0].ravel()
    p7 = {**p, "t_scale": float(1 / (1.4826 * stats.t.ppf(0.75, 4.0)))}
    z_new = draw_shocks(p7, 4000, 12, seed=1)[:, :, 0].ravel()
    assert _mad_sd(z_old) == pytest.approx(0.78, abs=0.03)  # body 22% too narrow at df 4
    assert _mad_sd(z_new) == pytest.approx(1.0, abs=0.03)


def test_F7_calibration_emits_scale(macro):
    p = cal(synthetic_company(), macro, "v3", "F7")
    want = 1 / (1.4826 * stats.t.ppf(0.75, p["t_df"])) if p["t_df"] < 30 else 1.0
    assert p["t_scale"] == pytest.approx(want)
    p = cal(synthetic_company(), macro, "v3", "F7", t_df_pooled=5.0, t_df_pool_weight=1.0)
    assert p["t_df"] == pytest.approx(5.0)


def test_F8_independent_mixing_removes_tail_dependence():
    p = {"rho_gm": 0.0, "t_df": 3.0}
    a = draw_shocks(p, 5000, 8, seed=2)
    b = draw_shocks({**p, "t_mix_indep": 1.0}, 5000, 8, seed=2)

    def tail_dep(z):
        x, y = np.abs(z[:, :, 0].ravel()), np.abs(z[:, :, 1].ravel())
        return np.corrcoef(x, y)[0, 1]

    assert tail_dep(a) > 0.1 and abs(tail_dep(b)) < 0.03


# ---------------------------------------------------------------- MM-F9
def test_F9_parameter_draws_widen_the_distribution(macro):
    c = synthetic_company(seed=7)
    p = cal(c, macro, "v3", "+F9", n_param_draws=20)
    assert (
        len(p["_param_draws"]) == 20
        and p["_param_draws"] == cal(c, macro, "v3", "+F9", n_param_draws=20)["_param_draws"]
    )
    assert np.std([d["v"] for d in p["_param_draws"]]) > 0
    assert "_param_draws" not in cal(c, macro, "v3")  # off in v3 by default (H2 unaffected)
    scn = build_scenario({}, 8)
    eps = draw_shocks(p, 2000, 8, seed=3)
    base = {k: v for k, v in p.items() if k != "_param_draws"}
    with_unc = simulate_paths(p, scn, eps, DEFAULT_LEVERS)
    without = simulate_paths(base, scn, eps, DEFAULT_LEVERS)
    exact = simulate(base, scn, eps, DEFAULT_LEVERS)
    assert all(np.array_equal(without[k], exact[k]) for k in exact)
    iqr = lambda x: np.subtract(*np.percentile(x, [75, 25]))  # noqa: E731
    assert iqr(with_unc["cfo"].sum(1)) > iqr(without["cfo"].sum(1))


# ---------------------------------------------------------------- MM-F10
def test_F10_fixed_costs_rebased_to_the_cutoff(macro):
    c = synthetic_company(fixed=400.0, v=0.5, fixed_infl=0.006, season_amp=0.0, noise=0.002, trend=0.03)
    truth = 400.0 * 1.006 ** (len(c.quarters) - 1)
    assert cal(c, macro, "v3", "F1,F10")["F"] == pytest.approx(truth, rel=0.05)
    assert cal(c, macro, "v3", "F1")["F"] < 0.95 * truth  # the window-midpoint intercept


# ---------------------------------------------------------------- MM-F12
def test_F12_asset_light_and_loss_making_firms(macro):
    light = synthetic_company(fixed=0.0, v=0.06, trend=0.03, season_amp=0.0)
    p = cal(light, macro, "v3", "F1,F12")
    assert p["v"] < 0.1 and fixed_share(p, light) < 0.1  # revision-2 grid forced v >= 0.10
    assert cal(light, macro, "v2-rev")["v"] >= 0.1
    loss = synthetic_company(fixed=0.0, v=2.0, trend=0.03, season_amp=0.0)
    assert fixed_share(cal(loss, macro, "v3", "F1,F12"), loss) < 0.1  # v capped at 1.05 put ~half in F
    assert fixed_share(cal(loss, macro, "v2-rev"), loss) > 0.4
    neg = synthetic_company(seed=8)
    neg.quarters.loc[neg.quarters.index[-6], "revenue"] = -5.0
    assert np.isfinite(cal(neg, macro, "v3", "F1,F12")["v"])


# ---------------------------------------------------------------- MM-F13
def test_F13_receivables_delay_is_estimated(macro):
    c = synthetic_company(seed=9)
    q = c.quarters
    target = 0.4 * q["revenue"].to_numpy()
    ar = target.copy()
    for t in range(1, len(ar)):
        ar[t] = ar[t - 1] + (target[t] - ar[t - 1]) / 2.5
    q["receivables"] = ar
    assert 1.6 < cal(c, macro, "v3", "F13")["tau_ar"] < 3.5
    assert cal(c, macro, "v2-rev")["tau_ar"] == 1.0


# ---------------------------------------------------------------- MM-F14
def test_F14_recession_drift_is_offset_in_mu(macro):
    c = synthetic_company(seed=10)
    p3, p2 = cal(c, macro, "v3", "F14"), cal(c, macro, "v2-rev")
    pi = 0.045 / (0.045 + 0.24)
    assert p3["mu"] - p2["mu"] == pytest.approx(-pi * p2["rec_drift"], abs=1e-9)


# ---------------------------------------------------------------- M2, M3
def test_M2_floating_share(macro, monkeypatch):
    import fintwin.universe as U

    monkeypatch.setattr(U, "classify", lambda t: ("Real Estate", ""))
    c = synthetic_company()
    assert cal(c, macro, "v3", "M2")["floating"] == C.FLOATING_BY_SECTOR["Real Estate"]
    c.quarters["short_borrowings"] = 0.5 * c.quarters["total_debt"]
    assert cal(c, macro, "v3", "M2")["floating"] == pytest.approx(0.5 + 10 / c.quarters["total_debt"].iloc[-1])
    c.quarters["floating_debt"] = 0.4 * c.quarters["total_debt"]
    assert cal(c, macro, "v3", "M2")["floating"] == pytest.approx(0.4)
    assert cal(c, macro, "v3")["floating"] == 0.1  # extension: off in v3


def test_M3_unknown_ladder_is_flagged_with_bullets(macro):
    c = synthetic_company(stale_ladder=True)
    p = cal(c, macro, "v3", "M3")
    lad = np.asarray(p["maturities_q"])
    debt0, st = p["debt0"], 50.0
    assert p["ladder_unknown"] == 1.0 and "unknown" in p["_sources"]["maturities"]
    assert (
        lad[3] == pytest.approx(st / 4 + (debt0 - st) / 6)
        and lad[4] == 0.0
        and lad[7] == pytest.approx((debt0 - st) / 6)
    )
    assert cal(synthetic_company(), macro, "v3", "M3")["ladder_unknown"] == 0.0


def test_v3_full_spec_runs(macro):
    for kw in ({}, {"da_missing": True}, {"stale_ladder": True, "season_amp": 0.3}):
        p = cal(synthetic_company(**kw), macro, "v3", "+F9,+M2", n_param_draws=5)
        assert np.isfinite(p["F"]) and p["F"] >= 0 and 0 <= p["v"]


# ---------------------------------------------------------------- revision-3 data layer (workstream A) guards
def _new_layer(c):
    """Turn a synthetic firm into a revision-3 data-layer frame: flag columns, a gap row, NaN where not reported."""
    q = c.quarters
    q["gap"] = False
    q["da_missing"] = False
    q["da_annual"] = np.nan
    g = q.index[-3]  # a calendar quarter with no revenue fact, inside the last 4 rows
    flows = ["revenue", "operating_income", "da", "net_income", "tax", "cfo", "capex", "sbc", "dividends", "buybacks"]
    q.loc[g, flows] = np.nan
    q.loc[g, "gap"] = True
    q.loc[q.index[-2:], "dividends"] = np.nan  # not reported in the last two quarters
    q.loc[q.index[-1], ["inventory", "deferred_revenue", "receivables"]] = np.nan
    q.loc[q.index[-6:], "total_debt"] = np.nan  # debt evidence stops 6 quarters back
    q.loc[q.index[-1], "short_investments"] = np.nan
    return c


@pytest.mark.parametrize("spec_name", ["v2-pre", "v3"])
def test_data_layer_gaps_and_missing_last_values_give_finite_params(macro, spec_name):
    c = _new_layer(synthetic_company(seed=12))
    p = cal(c, macro, spec_name)
    q = c.quarters
    assert p["history_quarters"] == len(q) - 1
    assert p["inv0"] == pytest.approx(q["inventory"].iloc[-2]) and p["debt0"] == 0.0
    assert p["div_q"] == pytest.approx(q["dividends"].dropna().tail(2).mean())
    x = q["operating_income"].tail(2).to_numpy()  # the 2-quarter run after the gap row, earlier slots at its mean
    assert p["ebit_ttm0"] == pytest.approx([x.mean(), x.mean(), *x])  # no zero quarter from the gap row (CR-4)
    assert "x 4/2" in p["_sources"]["trailing"]
    assert "total_debt not reported" in p["_sources"]["stale"]


def test_F4_uses_the_fiscal_year_da_when_quarterly_da_is_missing(macro):
    c = _new_layer(synthetic_company(seed=13))
    q = c.quarters
    miss = q.index[-8:]
    miss = miss[~q.loc[miss, "gap"].to_numpy(bool)]
    q.loc[miss, "da_annual"] = q.loc[miss, "da"] * 1.0
    q.loc[miss, "da"] = np.nan
    q.loc[miss, "da_missing"] = True
    p = cal(c, macro, "v3", "F4")
    x = (q["operating_income"] + q["da_annual"]).tail(2).to_numpy()
    assert p["ebitda_ttm0"] == pytest.approx([x.mean(), x.mean(), *x])
    assert "fiscal-year total" in p["_sources"]["da"]
