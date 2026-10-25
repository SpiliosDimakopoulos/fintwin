import numpy as np
import pandas as pd

from fintwin.research.stats import bk_event, ci, p_two_sided, petitions


def test_petitions_merges_filings_within_1095_days():
    d0 = pd.Timestamp("2018-01-10")
    raw = [d0, d0 + pd.Timedelta(days=200), d0 + pd.Timedelta(days=1095)]
    assert petitions(raw) == [d0]


def test_petitions_opens_a_case_after_more_than_1095_days():
    dates0 = [pd.Timestamp("2018-01-10")]
    dates0.append(dates0[0] + pd.Timedelta(days=1096))
    assert petitions(dates0) == dates0


def test_petitions_works_on_unsorted_dates():
    a = pd.Timestamp("2015-03-01")
    b = a + pd.Timedelta(days=400)
    c = a + pd.Timedelta(days=3000)
    assert petitions([c, a, b]) == [a, c]


def test_bk_event_window_is_origin_exclusive_plus_730():
    o = pd.Timestamp("2020-02-20")
    assert bk_event([o + pd.Timedelta(days=1)], "2020-02-20") == 1.0
    assert bk_event([o + pd.Timedelta(days=730)], "2020-02-20") == 1.0
    assert bk_event([o + pd.Timedelta(days=731)], "2020-02-20") == 0.0
    assert bk_event([o - pd.Timedelta(days=731)], "2020-02-20") == 0.0


def test_bk_event_nan_for_a_filing_in_the_two_years_before_origin():
    o = pd.Timestamp("2020-02-20")
    assert np.isnan(bk_event([o - pd.Timedelta(days=1)], "2020-02-20"))
    assert np.isnan(bk_event([o], "2020-02-20"))
    assert bk_event([o - pd.Timedelta(days=730)], "2020-02-20") == 0.0


def test_p_two_sided_zero_for_all_positive():
    assert p_two_sided(np.array([0.1, 0.2, 0.3])) == 0.0


def test_p_two_sided_one_for_a_symmetric_bootstrap():
    assert p_two_sided(np.array([-1.0, -1.0, 1.0, 1.0])) == 1.0


def test_p_two_sided_nan_for_empty_or_all_nan():
    assert np.isnan(p_two_sided(np.array([])))
    assert np.isnan(p_two_sided(np.array([np.nan, np.nan])))


def test_ci_returns_two_ordered_bounds():
    x = np.arange(100.0)
    lo, hi = ci(x)
    assert len(ci(x)) == 2
    assert lo <= hi
    assert lo < np.median(x) < hi
    lo2, hi2 = ci(np.array([np.nan, 1.0, np.nan, 2.0]))
    assert lo2 <= hi2
