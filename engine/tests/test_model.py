import numpy as np
import pytest
from conftest import make_params
from hypothesis import given, settings
from hypothesis import strategies as st

from fintwin.model import sd_model
from fintwin.model.ratings import ICR_LOWER, rating_rank
from fintwin.scenarios.presets import PRESETS, build_scenario
from fintwin.stochastic.mc import run, summarize
from fintwin.stochastic.shocks import draw_shocks


def test_balance_sheet_balances_every_quarter(params):
    out = run(params, n_paths=500)
    assert np.abs(out["identity_gap"]).max() < 1e-8


@settings(max_examples=40, deadline=None)
@given(
    depth=st.floats(0, 0.95),
    rate=st.integers(-300, 500),
    spread=st.integers(0, 800),
    cost=st.floats(0, 10),
    freeze=st.integers(0, 12),
    dio=st.integers(0, 90),
    equity=st.booleans(),
    revolver=st.booleans(),
)
def test_identity_holds_under_any_scenario(depth, rate, spread, cost, freeze, dio, equity, revolver):
    p = make_params()
    knobs = {
        "sales_depth": depth,
        "rate_bp": rate,
        "spread_bp": spread,
        "cost_pp": cost,
        "refi_freeze": freeze,
        "dio_days": dio,
    }
    out = run(p, knobs, {"issue_equity": equity, "draw_revolver": revolver}, n_paths=200)
    scale = p["equity0"] + p["debt0"]
    assert np.abs(out["identity_gap"]).max() / scale < 1e-10
    assert np.isfinite(out["health"]).all()
    assert (out["health"] >= 0).all() and (out["health"] <= 100).all()


def test_same_seed_same_result(params):
    a, b = run(params, n_paths=300, seed=11), run(params, n_paths=300, seed=11)
    np.testing.assert_array_equal(a["cash"], b["cash"])
    c = run(params, n_paths=300, seed=12)
    assert not np.array_equal(a["cash"], c["cash"])


def test_zero_volatility_is_deterministic_across_paths(params):
    p = {**params, "sigma_g": 0.0, "sigma_m": 0.0, "sigma_r": 0.0, "sigma_fin": 0.0}
    out = run(p, levers={"recessions": False}, n_paths=50)
    assert np.ptp(out["cash"], axis=0).max() < 1e-9


def test_deeper_sales_shock_hurts_more(params):
    eps = draw_shocks(params, 2000, params["horizon"], seed=3)
    health, breach = [], []
    for depth in [0.0, 0.2, 0.4, 0.6]:
        sm = summarize(run(params, {"sales_depth": depth}, eps=eps))
        health.append(sm["health_score"])
        breach.append(sm["p_breach"])
    assert health == sorted(health, reverse=True)
    assert breach == sorted(breach)


def test_rate_shock_raises_interest_cost(params):
    eps = draw_shocks(params, 1000, params["horizon"], seed=5)
    base = run(params, {}, eps=eps)["interest"][:, -1].mean()
    up = run(params, {"rate_bp": 300}, eps=eps)["interest"][:, -1].mean()
    assert up > base


def test_refi_freeze_drains_cash(params):
    eps = draw_shocks(params, 1000, params["horizon"], seed=5)
    base = run(params, {}, eps=eps)
    frozen = run(params, {"refi_freeze": 4}, eps=eps)
    assert frozen["debt"][:, 3].mean() < base["debt"][:, 3].mean()
    assert frozen["revolver"][:, 3].mean() >= base["revolver"][:, 3].mean()


def test_equity_lever_prevents_breach_when_market_open(params):
    knobs = {"sales_depth": 0.8, "sales_duration": 6}
    eps = draw_shocks(params, 1000, params["horizon"], seed=9)
    without = summarize(run(params, knobs, {"issue_equity": False}, eps=eps))
    with_eq = summarize(run(params, knobs, {"issue_equity": True}, eps=eps))
    assert with_eq["p_breach"] <= without["p_breach"]


BUCKET_EDGES = [(i, lower) for i, lower in enumerate(ICR_LOWER) if i > 0]


@pytest.mark.parametrize("rank_fn", [rating_rank, sd_model._rank], ids=["ratings", "sd_model"])
@pytest.mark.parametrize(("i", "lower"), BUCKET_EDGES)
def test_rating_bucket_edges(rank_fn, i, lower):
    assert rank_fn(np.array([lower]))[0] == i  # a bucket includes its lower bound
    assert rank_fn(np.array([np.nextafter(lower, -np.inf)]))[0] == i - 1


def test_rating_extremes_and_undefined_coverage():
    assert list(rating_rank(np.array([-np.inf, -5.0, 2.6, 50.0, np.inf]))) == [0, 0, 9, 14, 14]
    assert rating_rank(np.array([np.nan]))[0] == 0  # SW-9: undefined coverage ranks worst


def test_presets_do_not_beat_the_base_case(params):
    eps = draw_shocks(params, 200, params["horizon"], seed=1)
    base = summarize(run(params, {}, eps=eps))["health_score"]
    for key, preset in PRESETS.items():
        sm = summarize(run(params, preset["knobs"], eps=eps))
        assert 0 <= sm["p_breach"] <= 1, key
        assert sm["health_score"] <= base + 1e-9, key


def test_scenario_shapes():
    s = build_scenario({"sales_depth": 0.3, "sales_duration": 2, "sales_recovery": 4, "refi_freeze": 3}, 12)
    assert s["sales_shock"].min() == -0.3
    assert s["sales_shock"][-1] == 0.0
    assert list(s["refi_access"][:4]) == [0, 0, 0, 1]


def test_recession_regime_frequency_and_effect(params):
    eps = draw_shocks(params, 4000, params["horizon"], seed=17)
    on = run(params, eps=eps)
    off = run(params, {}, {"recessions": False}, eps=eps)
    # stationary share of time in recession = h / (h + exit), starting from expansion it is below that
    share = on["recession"].mean()
    stationary = params["rec_hazard"] / (params["rec_hazard"] + params["rec_exit"])
    assert 0.03 < share < stationary + 0.03
    assert off["recession"].max() == 0
    assert on["revenue"][:, -1].mean() < off["revenue"][:, -1].mean()


@pytest.mark.slow
def test_sobol_indices_are_sane(params):
    from fintwin.sensitivity.sobol import sobol

    rows = sobol(params, n_base=48, n_paths=100, n_boot=20)["rows"]
    st = {r["knob"]: r["ST"] for r in rows}
    assert all(0 <= r["S1"] <= 1.2 and 0 <= r["ST"] <= 1.5 for r in rows)  # smoke only; the estimator is tested below
    # a 0-50% revenue shock must matter more than a 0-60 day inventory build-up for this company
    assert st["sales_depth"] > st["dio_days"]


def test_sector_tolerance_raises_health_of_levered_company(params):
    levered = {**params, "debt0": 4000.0, "maturities_q": [20.0] * 12}
    levered["other_net0"] = (
        levered["equity0"]
        + levered["ap0"]
        + levered["def0"]
        + levered["debt0"]
        - (levered["cash0"] + levered["ar0"] + levered["inv0"] + levered["ppe0"])
    )
    eps = draw_shocks(levered, 800, levered["horizon"], seed=4)
    plain = summarize(run({**levered, "sector_tol": 1.0}, eps=eps))
    tolerant = summarize(run({**levered, "sector_tol": 2.0}, eps=eps))
    assert tolerant["health_score"] > plain["health_score"]
    # the dynamics are unchanged: only the scoring moves
    assert tolerant["p_breach"] == plain["p_breach"]


def _weighted_components(out):
    # the model's health weights, 0.3/0.3/0.2/0.2 (sd_model.simulate), kept here as an independent check
    return 0.3 * out["h_liq"] + 0.3 * out["h_cov"] + 0.2 * out["h_lev"] + 0.2 * out["h_solv"]


def test_health_waterfall_adds_up_without_breach(params):
    out = run(params, {}, {"recessions": False}, n_paths=300)
    assert not out["breach"].any()
    sm = summarize(out)
    c = sm["components"]
    weighted = 0.3 * c["liq"] + 0.3 * c["cov"] + 0.2 * c["lev"] + 0.2 * c["solv"]
    assert weighted == pytest.approx(sm["health_mean"])
    assert all(0 <= v <= 100 for v in c.values())


def test_health_waterfall_subtracts_the_breach_cap(params):
    out = run(params, {"sales_depth": 0.8, "sales_duration": 6}, n_paths=800, seed=9)
    assert out["breach"].any()
    w = _weighted_components(out)
    capped = np.where(out["breach"], np.minimum(w, 25.0), w)
    assert out["health"] == pytest.approx(capped)
    sm = summarize(out)
    c = sm["components"]
    weighted = 0.3 * c["liq"] + 0.3 * c["cov"] + 0.2 * c["lev"] + 0.2 * c["solv"]
    assert weighted - (w - capped).mean() == pytest.approx(sm["health_mean"])
    assert (w - capped).mean() > 0


def test_sobol_estimator_on_an_additive_function(params, monkeypatch):
    """Y = sum w_i x_i has S1_i = ST_i = w_i^2 var_i / sum, and no interaction."""
    import fintwin.sensitivity.sobol as sobol_mod

    k = len(sobol_mod.FACTORS)
    lo = np.array([f[1] for f in sobol_mod.FACTORS])
    hi = np.array([f[2] for f in sobol_mod.FACTORS])
    w = np.arange(1, k + 1, dtype=float)
    monkeypatch.setattr(sobol_mod, "_evaluate", lambda p, X, eps: ((X - lo) / (hi - lo)) @ w)
    res = sobol_mod.sobol(params, n_base=4000, n_paths=10, n_boot=10)
    truth = w**2 / (w**2).sum()
    by_knob = {r["knob"]: r for r in res["rows"]}
    for i, (key, *_) in enumerate(sobol_mod.FACTORS):
        assert by_knob[key]["S1"] == pytest.approx(truth[i], abs=0.04)
        assert by_knob[key]["ST"] == pytest.approx(truth[i], abs=0.04)
    assert res["interaction_share"] < 0.1
