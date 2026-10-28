"""B2: M1 covenants and revolver, MM-F11 debt-free loss-makers, M4 sector shocks and named presets, M5 payout floors,
M7 decision outputs, and the specification switches."""

from __future__ import annotations

import numpy as np
import pytest
from conftest import make_params

from fintwin.model import sd_model
from fintwin.model.ratings import NET_CASH_ICR, effective_icr
from fintwin.scenarios import presets as P
from fintwin.scenarios.presets import DEFAULT_LEVERS, KNOBS, PRESETS, build_scenario
from fintwin.scenarios.reverse_stress import headline
from fintwin.stochastic.shocks import draw_shocks


def bal(**over) -> dict:
    """make_params with overrides, the opening balance sheet re-balanced through other_net0."""
    p = make_params(**over)
    p["other_net0"] = p["equity0"] + p["ap0"] + p["def0"] + p["debt0"] - (p["cash0"] + p["ar0"] + p["inv0"] + p["ppe0"])
    return p


def sim(p, knobs=None, n=200, seed=1, **lev):
    eps = draw_shocks(p, n, p["horizon"], seed)
    return sd_model.simulate(p, build_scenario(knobs or {}, p["horizon"]), eps, {**DEFAULT_LEVERS, **lev})


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("FINTWIN_FIXES", raising=False)
    monkeypatch.delenv("FINTWIN_SPEC", raising=False)


# ------------------------------------------------------------------------------------------- switches (spec.py stub)
def test_spec_fallback_semantics(monkeypatch):
    assert not sd_model.active("F11") and not sd_model.active("M1")
    monkeypatch.setenv("FINTWIN_SPEC", "v3")
    assert sd_model.active("F11") and not sd_model.active("M1") and not sd_model.active("M4")
    monkeypatch.setenv("FINTWIN_FIXES", "M1, M4")  # overrides the spec's defaults
    assert sd_model.active("M1") and sd_model.active("M4") and not sd_model.active("F11")


def test_lever_overrides_environment(monkeypatch):
    monkeypatch.setenv("FINTWIN_FIXES", "M1")
    assert "cov_breach" in sim(bal(), n=20)
    assert "cov_breach" not in sim(bal(), n=20, M1=False)


# ------------------------------------------------------------------------------------------------------ MM-F11
DEBT_FREE_LOSS = {"F": 560.0, "debt0": 0.0, "maturities_q": [0.0] * 12, "interest_ttm0": [0.0] * 4}


def test_f11_debt_free_loss_maker_not_rated_d_and_not_stressed():
    p = bal(**DEBT_FREE_LOSS, ebit_ttm0=[-30.0] * 4, ebitda_ttm0=[30.0] * 4)
    old = sim(p, F11=False)
    new = sim(p, F11=True)
    # v2: coverage of a debt-free loss-maker is ~ -1e9, rating D, dividends cut although cash is 5x the floor
    assert (old["rating"][:, 0] == 0).all() and (old["dividends"][:, 0] == 0).all()
    assert (new["rating"][:, 0] >= 9).all()
    assert np.allclose(new["dividends"][:, 0], p["div_q"])
    assert (new["capex"][:, 0] > old["capex"][:, 0]).all()
    # once it burns through its cash and borrows, coverage is material again and the raw test applies
    assert (new["h_cov"][:, 0] > old["h_cov"][:, 0]).all() and (new["h_cov"] >= old["h_cov"]).mean() > 0.95


def test_f11_leaves_material_interest_alone():
    p = bal()
    assert all(np.array_equal(sim(p, F11=True)[k], sim(p, F11=False)[k]) for k in sd_model.OUTPUTS)
    icr = np.array([-5.0, 1.0, 9.0])
    # material interest, or net debt: unchanged; immaterial interest and net cash: floored at BBB
    assert np.array_equal(effective_icr(icr, 10.0, 1000.0, 1.0), icr)
    assert np.array_equal(effective_icr(icr, 0.1, 1000.0, -1.0), icr)
    assert np.array_equal(effective_icr(icr, 0.1, 1000.0, 1.0), [NET_CASH_ICR, NET_CASH_ICR, 9.0])


# ---------------------------------------------------------------------------------------------------------- M1
LEVERED = {"debt0": 5000.0, "cash0": 150.0}  # net debt / EBITDA about 7x, well above the 4.0x covenant


def test_m1_breach_after_cure_freezes_revolver():
    p = bal(**LEVERED, sigma_g=0.0, sigma_m=0.0, sigma_r=0.0, sigma_fin=0.0)
    out = sim(p, M1=True)
    first = sd_model.first_covenant_breach(out)
    assert (first == 1).all()  # fails at quarter 0 and 1; one quarter of cure, so a breach at quarter 1
    assert (out["revolver_avail"][:, 1:] == 0).all()
    assert (np.diff(out["revolver"][:, 1:], axis=1) <= 1e-9).all()  # no new draws after the breach
    off = sim(p, M1=False)
    assert (off["liquidity"][:, 1:] >= out["liquidity"][:, 1:] - 1e-9).all()
    assert "cov_breach" not in off


def test_m1_cure_period_and_thresholds():
    p = bal(**LEVERED, sigma_g=0.0, sigma_m=0.0, sigma_r=0.0, sigma_fin=0.0)
    assert (sd_model.first_covenant_breach(sim({**p, "cov_cure_q": 3}, M1=True)) >= 3).all()
    loose = sim({**p, "cov_max_nd_ebitda": 8.0, "cov_min_icr": None}, M1=True, recessions=False)
    assert (sd_model.first_covenant_breach(loose) == -1).all()
    assert np.array_equal(loose["liquidity"], sim(p, M1=False, recessions=False)["liquidity"])


def test_m1_icr_covenant_only_with_material_interest():
    p = bal(**DEBT_FREE_LOSS, cash0=3000.0, sigma_g=0.0, sigma_m=0.0, ebit_ttm0=[-30.0] * 4, ebitda_ttm0=[-10.0] * 4)
    assert (sd_model.first_covenant_breach(sim(p, M1=True)) == -1).all()  # net cash, no interest: nothing to test


def test_m1_revolver_maturity_terms_out_or_repays_and_keeps_identity():
    p = bal(F=480.0, cash0=90.0, revolver_maturity_q=4, cov_max_nd_ebitda=None, cov_min_icr=None)
    out = sim(p, {"refi_freeze": 12}, M1=True)
    assert (out["revolver"][:, 3] > 0).any()
    assert (out["revolver"][:, 4:] == 0).all() and (out["revolver_avail"][:, 4:] == 0).all()
    assert np.abs(out["identity_gap"]).max() < 1e-6


# ---------------------------------------------------------------------------------------------------------- M5
def test_m5_reit_distributes_90pct_of_income_even_under_stress():
    p = bal(cash0=90.0, payout_class="reit", div_q=0.0)
    out = sim(p, M5=True)
    assert (out["dividends"] >= 0.9 * np.maximum(out["net_income"], 0.0) - 1e-9).all()
    assert (out["dividends"] > 0).any() and (sim(p, M5=False)["dividends"] == 0).all()


def test_m5_utility_keeps_part_of_dividend_and_plain_firm_unchanged():
    p = bal(cash0=90.0, payout_class="utility")
    stressed = sim(p, M5=False)["dividends"] == 0
    assert stressed.any()
    assert np.allclose(sim(p, M5=True)["dividends"][stressed], 0.65 * p["div_q"])
    plain = bal(cash0=90.0)
    assert np.array_equal(sim(plain, M5=True)["dividends"], sim(plain, M5=False)["dividends"])
    assert sd_model.payout_class(6798) == "reit" and sd_model.payout_class(4911) == "utility"
    assert sd_model.payout_class(3571) == "" and sd_model.payout_class(None) == ""


# ---------------------------------------------------------------------------------------------------------- M4
def test_m4_named_presets_are_sourced_and_valid():
    allp = P.all_presets()
    for k, v in PRESETS.items():  # product presets unchanged, now with a source
        assert {kk: allp[k][kk] for kk in v} == v and allp[k]["source"]
    for k, v in P.SUPERVISORY_PRESETS.items():
        assert not set(v["knobs"]) - set(KNOBS), k
        assert "20" in v["source"] and v["label"] and v["desc"]
        assert build_scenario(v["knobs"], 12)["sales_shock"].min() == pytest.approx(-v["knobs"]["sales_depth"])
    assert set(P.SUPERVISORY_PRESETS).isdisjoint(PRESETS)


def test_m4_sector_multipliers():
    drops = [-60, -50, -40, -10, -5, 0, -20, -20, -18]
    sectors = ["Shops"] * 3 + ["Health"] * 3 + ["Energy"] * 3
    t = P.sector_shock_table(drops, sectors, min_n=3)
    assert t["Shops"] == -50 and t["_all"] == -20
    assert P.sector_multiplier("Shops", t) == pytest.approx(2.5)
    assert P.sector_multiplier("Health", t) == pytest.approx(0.25)
    assert P.sector_multiplier("Unknown", t) == 1.0 and P.sector_multiplier("Shops", {}) == 1.0
    assert P.sector_shock_table(drops, sectors, min_n=4) == {"_all": -20.0}
    k = PRESETS["sales_20"]["knobs"]
    assert P.sector_knobs(k, "Shops", t, on=False) is k  # switch off: untouched
    assert P.sector_knobs(k, "Shops", t, on=True)["sales_depth"] == pytest.approx(0.5)
    assert P.sector_knobs(PRESETS["pandemic"]["knobs"], "Shops", t, on=True)["sales_depth"] == 0.95
    assert P.sector_knobs(k, "Shops", t) is k  # M4 off by default


def test_reverse_stress_headline():
    rs = {
        "sales_depth": {"label": "Revenue drop", "unit": "pct", "p10": 0.3, "p50": 0.42},
        "rate_bp": {"label": "Interest-rate rise", "unit": "bp", "p10": 900.0, "p50": None},
    }
    assert headline(rs) == "A 50% chance of running out of cash takes any one of: revenue drop of 42%."
    assert "interest-rate rise of 900bp" in headline(rs, "p10")
    assert headline({"x": {"label": "x", "unit": "pp", "p50": None}}).startswith("No single shock")


# ---------------------------------------------------------------------------------------------------------- M7
def test_m7_decision_outputs():
    p = bal()
    out = sim(p, {"sales_depth": 0.6, "refi_freeze": 4}, n=400)
    d = sd_model.decision_outputs(out, p, x=0.0, n=8)
    liq_gone = (out["liquidity"] < 0).any(1).mean()
    assert d["runway_censored_share"] == pytest.approx(1 - liq_gone)
    assert 0 <= d["runway_q_p10"] <= d["runway_q_median"] <= p["horizon"]
    assert d["funding_gap_p95"] >= d["funding_gap_p50"] >= 0
    assert d["maturity_wall"] == p["maturities_q"]
    assert d["p_liquidity_below"]["p"] == sd_model.p_liquidity_below(out, 0.0, 8)
    assert "p_cov_breach" not in d
    # P(liquidity < x within n) grows with x and with n
    ps = [sd_model.p_liquidity_below(out, x, 8) for x in (0.0, 200.0, 400.0)]
    assert ps == sorted(ps)
    assert sd_model.p_liquidity_below(out, 200.0, 4) <= sd_model.p_liquidity_below(out, 200.0, 12)


def test_m7_with_covenants_and_revolver_maturity():
    p = bal(**LEVERED, revolver_maturity_q=6)
    out = sim(p, M1=True)
    d = sd_model.decision_outputs(out, p)
    assert d["p_cov_breach"] == pytest.approx((sd_model.first_covenant_breach(out) >= 0).mean())
    assert d["first_cov_breach_q_median"] is not None and d["revolver_due"]["q"] == 6


def test_sw9_nan_coverage_ranks_worst():
    from fintwin.model.ratings import rating_rank

    assert rating_rank(np.array([np.nan, 100.0, -1.0])).tolist()[0] == 0
