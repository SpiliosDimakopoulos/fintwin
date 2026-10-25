import json

import numpy as np
import pytest

from fintwin.export import _clean
from fintwin.memo import unverified_numbers


@pytest.mark.parametrize("figure", [950, 1000, 1050, -1050])
def test_unverified_numbers_accepts_figures_within_five_percent(figure):
    assert unverified_numbers({"summary": str(figure)}, {"revenue": 1000}) == []


def test_unverified_numbers_returns_only_unmatched_figures_in_order():
    memo = {"summary": "revenue 1000, debt 1500, cash 1750.5"}
    assert unverified_numbers(memo, {"revenue": 1000}) == [1500.0, 1750.5]


def test_unverified_numbers_ignores_counts_but_not_thirteen():
    memo = {"summary": " ".join(str(n) for n in range(-12, 14))}
    assert unverified_numbers(memo, {}) == [13.0]


def test_unverified_numbers_ignores_years_only_in_the_requested_range():
    memo = {"summary": " ".join(str(year) for year in range(1989, 2037))}
    assert unverified_numbers(memo, {}) == [1989.0, 2036.0]


def test_unverified_numbers_parses_dollars_commas_and_decimals():
    memo = {"summary": "revenue $1,234.5; debt -$4,567.8"}
    assert unverified_numbers(memo, {"revenue": 1234.5}) == [-4567.8]
    assert unverified_numbers(memo, {}) == [1234.5, -4567.8]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), np.float32("nan"), np.float64("inf")])
def test_clean_converts_nonfinite_floats_to_none(value):
    assert _clean(value) is None


@pytest.mark.parametrize("value", [np.int32(42), np.int64(-42)])
def test_clean_converts_numpy_integers_to_python_ints(value):
    cleaned = _clean(value)
    assert type(cleaned) is int
    assert cleaned == int(value)


@pytest.mark.parametrize("value", [np.bool_(True), np.bool_(False)])
def test_clean_converts_numpy_booleans_to_python_bools(value):
    cleaned = _clean(value)
    assert type(cleaned) is bool
    assert cleaned is bool(value)


def test_clean_recurses_through_dicts_tuples_and_arrays():
    original = {
        "nested": {7: (np.int64(42), np.bool_(True), None)},
        "array": np.array([[1.25, np.nan], [np.inf, -np.inf]]),
    }
    expected = {"nested": {"7": [42, True, None]}, "array": [[1.25, None], [None, None]]}
    cleaned = _clean(original)
    assert cleaned == expected
    assert json.loads(json.dumps(cleaned, allow_nan=False)) == expected
    assert isinstance(original["nested"][7], tuple)
    assert np.isnan(original["array"][0, 1])


def test_clean_rounds_to_significant_digits_in_nested_values():
    assert _clean(1.23456789, 3) == 1.23
    assert _clean({"values": (12345.6789, np.float64(0.00123456789))}, 3) == {"values": [12300.0, 0.00123]}
