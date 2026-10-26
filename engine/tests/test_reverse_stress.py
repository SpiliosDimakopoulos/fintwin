from conftest import make_params

from fintwin.scenarios.reverse_stress import TARGETS, breaking_point, reverse_stress


def test_breaking_point_returns_none_for_unreachable_target():
    assert breaking_point(make_params(), "cost_pp", target_p=1.01, n_paths=300) is None


def test_breaking_point_returns_lower_bound_when_target_is_already_met():
    assert breaking_point(make_params(), "cost_pp", target_p=0.0, n_paths=300) == TARGETS["cost_pp"]["lo"]


def test_cost_breaking_points_are_bounded_and_ordered():
    params = make_params()
    low = breaking_point(params, "cost_pp", target_p=0.10, n_paths=300)
    median = breaking_point(params, "cost_pp", target_p=0.50, n_paths=300)
    lo, hi = TARGETS["cost_pp"]["lo"], TARGETS["cost_pp"]["hi"]

    assert low is not None
    assert median is not None
    assert lo <= low <= median <= hi


def test_breaking_point_is_reproducible_and_returns_python_float():
    params = make_params()
    first = breaking_point(params, "cost_pp", target_p=0.10, n_paths=300, seed=47)
    second = breaking_point(params, "cost_pp", target_p=0.10, n_paths=300, seed=47)

    assert type(first) is float
    assert first == second


def test_reverse_stress_returns_complete_ordered_results():
    results = reverse_stress(make_params(), n_paths=300)

    assert set(results) == set(TARGETS)
    for knob, spec in TARGETS.items():
        result = results[knob]
        assert result.keys() == {"label", "unit", "p10", "p50"}
        assert result["label"] == spec["label"]
        assert result["unit"] == spec["unit"]
        if result["p10"] is not None and result["p50"] is not None:
            assert result["p10"] <= result["p50"]
