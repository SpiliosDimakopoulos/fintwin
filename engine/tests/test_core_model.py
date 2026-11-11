"""Model constants, scenario shape, calibration provenance and ladder branches (quality pass EC-05, EC-07, EC-12,
EC-13, EC-25; S1)."""

from __future__ import annotations

import numpy as np
import pytest
from conftest import make_params
from test_B1_parity import synthetic_company

from fintwin import changes
from fintwin.model.constants import HEALTH_WEIGHTS
from fintwin.scenarios.presets import build_scenario
from fintwin.stochastic import calibrate as C
from fintwin.stochastic import spec
from fintwin.stochastic.mc import run


def cal(c, macro, spec_name="v2-rev", fixes=None):  # noqa: F811
    with spec.using(spec_name, fixes):
        return C.calibrate(c, macro, 8)


def test_health_is_the_weighted_sum_of_its_components_until_a_breach():
    out = run(make_params(), n_paths=200, seed=3)
    weighted = sum(w * out[f"h_{k}"] for k, w in HEALTH_WEIGHTS.items())
    ok = out["breach"] == 0
    assert ok.any()
    np.testing.assert_allclose(out["health"][ok], weighted[ok], rtol=0, atol=1e-9)
    assert np.all(out["health"][~ok] <= 25.0)
    assert changes.WEIGHTS is HEALTH_WEIGHTS and sum(HEALTH_WEIGHTS.values()) == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("hold", "first"),
    [(0, [-0.1333, -0.0667, 0.0, 0.0]), (1, [-0.2, -0.1333, -0.0667, 0.0]), (2, [-0.1, -0.2, -0.1333, -0.0667])],
)
def test_sales_duration_counts_the_half_depth_first_quarter(hold, first):
    # documented in KNOBS: with 2 or more quarters the first takes half the drop, so hold - 1 are at full depth
    s = build_scenario({"sales_depth": 0.2, "sales_duration": hold, "sales_recovery": 2}, 6)["sales_shock"]
    np.testing.assert_allclose(s[:4], first, atol=1e-4)


def test_fresh_xbrl_ladder_is_spread_by_quarter(macro):  # noqa: F811
    p = cal(synthetic_company(), macro, "v3", "M3")
    lad = np.asarray(p["maturities_q"])
    st = 40.0 + 10.0  # short-term borrowings + commercial paper roll within the first year
    assert lad[:4] == pytest.approx(200.0 / 4 + st / 4) and lad[4:8] == pytest.approx(180.0 / 4)
    assert p["_sources"]["maturities"].startswith("XBRL") and p["ladder_unknown"] == 0.0


def test_stale_ladder_without_M3_amortizes_uniformly(macro):  # noqa: F811
    p = cal(synthetic_company(stale_ladder=True), macro)
    assert p["maturities_q"] == pytest.approx([p["debt0"] / 24.0] * 8)
    assert p["_sources"]["maturities"].startswith("assumption: uniform amortization")


def test_failed_t_fit_falls_back_to_normal_and_says_so(macro, monkeypatch):  # noqa: F811
    def fail(*a, **k):
        raise RuntimeError("no convergence")

    monkeypatch.setattr(C.stats.t, "fit", fail)
    p = cal(synthetic_company(), macro)
    assert p["t_df"] == 30.0
    assert p["_sources"]["t_df"] == "assumption: normal tails (Student-t fit failed: RuntimeError)"


def test_t_fit_bug_is_not_swallowed(macro, monkeypatch):  # noqa: F811
    def bug(*a, **k):
        raise TypeError("unexpected keyword")

    monkeypatch.setattr(C.stats.t, "fit", bug)
    with pytest.raises(TypeError):
        cal(synthetic_company(), macro)


def test_receivables_delay_without_enough_data_is_labelled_an_assumption(macro):  # noqa: F811
    c = synthetic_company()
    c.quarters.loc[c.quarters.index[-17:-5], "receivables"] = np.nan  # 4 usable quarter-on-quarter steps left
    p = cal(c, macro, "v3", "F13")
    assert p["tau_ar"] == 1.0 and p["_sources"]["tau_ar"].startswith("assumption")
    assert "estimated" in cal(synthetic_company(), macro, "v3", "F13")["_sources"]["tau_ar"]
