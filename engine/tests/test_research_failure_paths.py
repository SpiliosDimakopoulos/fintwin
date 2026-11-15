"""Failure paths of the research and backtest code: a failure stays visible, and the success path is unchanged."""

import numpy as np
import pandas as pd
import pytest

from fintwin.backtest import batch, scoring
from fintwin.backtest import walk_forward as W
from fintwin.research import stats


def test_dm_stat_matches_a_hand_computed_cluster_t():
    d = np.array([1.0, 2.0, 3.0, 4.0, 1.0, 2.0, 3.0, 4.0, 2.0, 3.0, 5.0, 1.0])
    g = np.array(["a"] * 4 + ["b"] * 4 + ["c"] * 4)
    r = batch.dm_stat(d, g)
    e = d - d.mean()
    s = np.array([e[:4].sum(), e[4:8].sum(), e[8:].sum()])
    var = (3 / 2) * np.sum(s**2) / len(d) ** 2
    assert r["clusters"] == 3
    assert r["t"] == pytest.approx(d.mean() / np.sqrt(var))


def test_dm_stat_returns_none_with_too_few_clusters():
    r = batch.dm_stat(np.arange(20.0), np.array(["a"] * 10 + ["b"] * 10))
    assert r["t"] is None and r["p"] is None


def test_structural_backtest_stops_at_the_first_missing_quarter(monkeypatch):
    monkeypatch.delenv("FINTWIN_DATA_LEGACY", raising=False)
    monkeypatch.setattr(W, "simulate", lambda p, scn, eps, levers: {"fcf": np.ones((5, 4))})
    idx = pd.date_range("2020-03-31", periods=4, freq="QE")
    real = pd.DataFrame({"revenue": [10.0] * 4, "fcf": [1.0, np.nan, 1.0, 1.0]}, index=idx)
    out = W.structural_backtest({"horizon": 4}, real, np.zeros((5, 4)))
    assert out["dates"] == ["2020-03-31"]
    assert out["actual_cum_fcf"] == [1.0]


def test_cross_section_raises_with_the_failures_when_no_ticker_survives(monkeypatch):
    def boom(*a, **k):
        raise ValueError("no filings")

    monkeypatch.setattr(W, "macro_quarterly", lambda cutoff: pd.DataFrame())
    monkeypatch.setattr(W, "load_company", boom)
    with pytest.raises(RuntimeError, match="no filings"):
        W.cross_section(["AAA", "BBB"])


def test_crps_gaussian_of_a_nan_scale_is_nan():
    assert np.isnan(scoring.crps_gaussian(0.0, float("nan"), 1.0))


def test_error_paths_lists_every_failed_section():
    res = {"a": {"x": 1}, "b": {"error": "KeyError: 'col'"}, "c": {"d": {"error": "ValueError: empty"}}}
    assert stats._error_paths(res) == ["/b: KeyError: 'col'", "/c/d: ValueError: empty"]
    assert stats._error_paths({"a": {"x": 1}}) == []


def test_safe_records_the_exception_in_place():
    def bad():
        raise KeyError("col")

    assert stats._safe(bad) == {"error": "KeyError: 'col'"}
