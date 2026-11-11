"""FRED layer, offline: the cache rules, the GDP vintage dating and the recession-regime formulas."""

import os
import time

import numpy as np
import pandas as pd
import pytest

from fintwin.data import fred

CSV = "DATE,X\n2020-01-01,150\n2020-02-01,250\n"


@pytest.fixture(autouse=True)
def _fresh_vintages():
    """The vintage table is read once per process; a test that swaps in a toy table must not leak it."""
    fred._vintages.cache_clear()
    yield
    fred._vintages.cache_clear()


@pytest.fixture
def served(monkeypatch, tmp_path):
    monkeypatch.setattr(fred, "CACHE_DIR", tmp_path)
    calls = []

    class Resp:
        text = CSV

        def raise_for_status(self):
            pass

    monkeypatch.setattr(fred, "fetch", lambda url, **k: calls.append(url) or Resp())
    return calls


def _age(path, seconds):
    old = time.time() - seconds
    os.utime(path, (old, old))


def test_fresh_cache_is_read_without_fetching(served, tmp_path):
    (tmp_path / "X.csv").write_text(CSV, encoding="utf-8")
    assert list(fred.fred_series("X")) == [1.5, 2.5]
    assert not served


def test_stale_cache_is_refetched(served, tmp_path):
    path = tmp_path / "X.csv"
    path.write_text("DATE,X\n2019-01-01,100\n", encoding="utf-8")
    _age(path, 48 * 3600)
    assert list(fred.fred_series("X", max_age_hours=24)) == [1.5, 2.5]
    assert len(served) == 1


def test_frozen_missing_file_raises_and_never_fetches(served, monkeypatch):
    monkeypatch.setenv("FINTWIN_FROZEN", "1")
    with pytest.raises(fred.FrozenMiss):
        fred.fred_series("X")
    assert not served


def test_frozen_reads_a_stale_file(served, monkeypatch, tmp_path):
    path = tmp_path / "X.csv"
    path.write_text(CSV, encoding="utf-8")
    _age(path, 1e7)
    monkeypatch.setenv("FINTWIN_FROZEN", "1")
    assert list(fred.fred_series("X")) == [1.5, 2.5]
    assert not served


def test_fill_only_keeps_a_stale_file_but_fetches_a_missing_one(served, monkeypatch, tmp_path):
    path = tmp_path / "X.csv"
    path.write_text(CSV, encoding="utf-8")
    _age(path, 1e7)
    monkeypatch.setenv("FINTWIN_FILL_ONLY", "1")
    fred.fred_series("X")
    assert not served
    fred.fred_series("Y")
    assert len(served) == 1


# ------------------------------------------------------------------------------------------------ gdp_vintage
def _vintage_table(tmp_path, monkeypatch):
    v = pd.DataFrame(
        {"2010Q1": [100.0, 110.0, np.nan], "2010Q2": [101.0, 111.0, 120.0]},
        index=pd.Index(["2009:Q4", "2010:Q1", "2010:Q2"], name="DATE"),
    )
    path = tmp_path / "vintages.csv"
    v.to_csv(path)
    monkeypatch.setattr(fred, "VINTAGES", path)


def test_gdp_vintage_is_used_from_the_20th_of_the_quarters_second_month(tmp_path, monkeypatch):
    _vintage_table(tmp_path, monkeypatch)
    assert fred.gdp_vintage("2010-02-19") is None  # a day before the first vintage
    q1 = fred.gdp_vintage("2010-02-20")
    assert list(q1) == [100.0, 110.0] and q1.index[-1] == pd.Timestamp("2010-03-31")
    assert list(fred.gdp_vintage("2010-05-19")) == [100.0, 110.0]  # still the older one a day before the next
    q2 = fred.gdp_vintage("2010-05-20")
    assert list(q2) == [101.0, 111.0, 120.0] and q2.index[-1] == pd.Timestamp("2010-06-30")
    assert list(fred.gdp_vintage("2030-01-01")) == [101.0, 111.0, 120.0]


def test_committed_gdp_vintages_respect_the_publication_date():
    before, after = fred.gdp_vintage("2020-08-19"), fred.gdp_vintage("2020-08-20")
    assert before.index[-1] == pd.Timestamp(
        "2020-03-31"
    )  # the 2020Q3 vintage (first to hold 2020Q2) is dated 2020-08-20
    assert after.index[-1] == pd.Timestamp("2020-06-30")
    assert fred.gdp_vintage("2009-12-31") is None


# ------------------------------------------------------------------------------------------ recession_regime
@pytest.fixture
def regime_series(monkeypatch):
    """Sixteen quarters from 1947: recessions in quarters 3-4 (two quarters) and 9-11 (three), expansion elsewhere."""
    months = pd.date_range("1947-01-31", periods=48, freq="ME")
    quarters = pd.date_range("1947-03-31", periods=16, freq="QE")
    in_rec = np.zeros(16)
    in_rec[[3, 4, 9, 10, 11]] = 1
    # nominal GDP grows 2% a quarter, and falls 1% in a recession quarter
    gdp = 100 * np.exp(np.cumsum(np.where(in_rec == 1, -0.01, 0.02)))
    series = {
        "USREC": pd.Series(np.repeat(in_rec, 3) / 100.0, index=months),
        "GDP": pd.Series(gdp / 100.0, index=quarters),
    }
    monkeypatch.setattr(fred, "fred_series", lambda sid, max_age_hours=24: series[sid])
    return quarters


def test_recession_regime_hazard_and_exit_by_hand(regime_series):
    r = fred.recession_regime()
    assert r["n_recessions"] == 2
    assert r["hazard"] == pytest.approx(2 / (16 - 5))
    assert r["exit"] == pytest.approx(2 / 5)
    assert r["in_recession_now"] is False
    assert r["gdp_shortfall_q"] > 0  # growth is lower in recession quarters


def test_recession_regime_asof_truncates_the_history(regime_series):
    r = fred.recession_regime(asof=str(regime_series[4].date()))  # ends inside the first recession
    assert r["n_recessions"] == 1
    assert r["in_recession_now"] is True
    assert r["hazard"] == pytest.approx(1 / (5 - 2))
    assert r["exit"] == pytest.approx(1 / 2)
