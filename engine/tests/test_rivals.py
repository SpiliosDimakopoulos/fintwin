"""WP6 (a reader): non-accounting rivals, point in time."""

from __future__ import annotations

import numpy as np
import pandas as pd

from fintwin.research import rivals as RV
from fintwin.research import stats as S


def test_filing_features_use_only_filings_up_to_the_cutoff():
    f = pd.DataFrame(
        [("1995-03-01", "10-K", ""), ("2017-05-01", "10-K/A", ""), ("2018-01-10", "8-K", "4.02,9.01"),
         ("2018-01-20", "NT 10-K", ""), ("2019-06-01", "10-Q/A", ""), ("2019-07-01", "8-K", "4.02")],
        columns=["filingDate", "form", "items"],
    )  # fmt: skip
    a = RV.filing_features(f, "2018-02-15")
    assert round(a["age"], 1) == 23.0 and a["amend_3y"] == 1 and a["nonreliance_3y"] == 1 and a["late_2y"] == 1
    b = RV.filing_features(f, "2017-02-15")  # nothing after the cutoff counts
    assert b["amend_3y"] == 0 and b["nonreliance_3y"] == 0 and b["late_2y"] == 0
    assert RV.filing_features(f, "1990-01-01")["age"] != RV.filing_features(f, "1990-01-01")["age"]  # NaN


def test_item_402_is_not_matched_inside_other_items():
    f = pd.DataFrame([("2018-01-10", "8-K", "14.02,2.02")], columns=["filingDate", "form", "items"])
    assert RV.filing_features(f, "2018-02-15")["nonreliance_3y"] == 0


def test_industry_base_rate_sees_only_closed_outcome_windows():
    years = np.array([2014] * 100 + [2016] * 100 + [2017] * 100)
    groups = np.array(["A"] * 300)
    y = np.r_[np.zeros(100), np.ones(100), np.zeros(100)]  # 2016's outcomes are not known at a 2017 cutoff
    r = RV.industry_base_rate(years, groups, y)
    assert np.isnan(r[:200]).all()  # no year <= Y-3 for 2014 and 2016
    assert r[200] == 0.0  # 2017 uses 2014 only (Y-3), never 2016


def test_raw_features_accept_plain_columns():
    p = pd.DataFrame({"age": [1.0, 2.0], "z2": [3.0, 4.0]})
    X = S._raw(p, ["age", "altman_z2"])
    assert X["age"].tolist() == [1.0, 2.0] and X["altman_z2"].tolist() == [-3.0, -4.0]
