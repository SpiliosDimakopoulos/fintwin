"""B2 side of MM-F3 (partial adjustment of fixed costs) and MM-F6 (current margin deviation), per requests/B1.md."""

from __future__ import annotations

import numpy as np
import pytest
from conftest import make_params

from fintwin.model import sd_model
from fintwin.scenarios.presets import DEFAULT_LEVERS, build_scenario
from fintwin.stochastic.shocks import draw_shocks

QUIET = {"sigma_g": 0.0, "sigma_m": 0.0, "sigma_r": 0.0, "sigma_fin": 0.0}


def sim(p, knobs=None, **lev):
    eps = draw_shocks(p, 4, p["horizon"], 1)
    lv = {**DEFAULT_LEVERS, "recessions": False, **lev}
    return sd_model.simulate(p, build_scenario(knobs or {}, p["horizon"]), eps, lv)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("FINTWIN_FIXES", raising=False)
    monkeypatch.delenv("FINTWIN_SPEC", raising=False)


def test_f6_margin_deviation_starts_at_m_dev0_and_decays():
    p = make_params(**QUIET, m_dev0=0.04)
    on, off = sim(p, F6=True), sim(p, F6=False)
    rev = on["revenue"]
    # first quarter: m_dev = rho_m * m_dev0 = 0.02, so EBITDA is 2% of revenue lower; then it halves each quarter
    assert np.allclose(off["ebitda"][:, 0] - on["ebitda"][:, 0], 0.02 * rev[:, 0])
    assert np.allclose(off["ebitda"][:, 1] - on["ebitda"][:, 1], 0.01 * rev[:, 1], rtol=1e-6)
    assert np.array_equal(off["ebitda"], sim(make_params(**QUIET), F6=True)["ebitda"])  # m_dev0 absent = 0


def test_f3_lambda_one_sets_fixed_costs_to_share_of_revenue():
    p = make_params(**QUIET, fixed_adj_lambda=1.0, fixed_adj_f=0.25)
    out = sim(p, F3=True)
    # t = 0: fixed = 0.25 x revenue (seasonal 1, cut_mult 1), variable 0.5 x revenue
    assert np.allclose(out["ebitda"][:, 0], 0.25 * out["revenue"][:, 0])


def test_f3_recursion_matches_hand_computation():
    p = make_params(**QUIET, fixed_adj_lambda=0.5, fixed_adj_f=0.25)
    out = sim(p, F3=True)
    rev = out["revenue"][0]
    F_t = p["F"]
    for t in range(3):
        F_t *= 1.0 + p["infl"]
        F_t += 0.5 * (0.25 * rev[t] - F_t)
        # margin stays above target_margin, so cut_mult is 1
        assert out["ebitda"][0, t] == pytest.approx(rev[t] - F_t - p["v"] * rev[t], rel=1e-12)


def test_f3_asymmetric_lambda_and_sales_shock():
    base = make_params(**QUIET)
    shock = {"sales_depth": 0.3}
    sticky = sim({**base, "fixed_adj_lambda": 0.4, "fixed_adj_lambda_down": 0.0, "fixed_adj_f": 0.2}, shock, F3=True)
    v2 = sim(base, shock, F3=True)
    # target below today's fixed costs and no downward adjustment: the v2 inflating fixed costs (up to rounding of
    # the recursive product against (1 + infl) ** (t + 1))
    assert np.allclose(sticky["ebitda"], v2["ebitda"], rtol=1e-12, atol=1e-9)
    flexible = sim({**base, "fixed_adj_lambda": 0.4, "fixed_adj_f": 0.2}, shock, F3=True)
    assert (flexible["ebitda"][:, 2:] > v2["ebitda"][:, 2:]).all()  # costs fall with the revenue drop
    assert np.abs(flexible["identity_gap"]).max() < 1e-6


def test_f3_off_ignores_lambda():
    p = make_params(**QUIET, fixed_adj_lambda=1.0, fixed_adj_f=0.25)
    assert np.array_equal(sim(p, F3=False)["ebitda"], sim(make_params(**QUIET), F3=False)["ebitda"])
