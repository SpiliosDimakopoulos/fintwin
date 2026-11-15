"""The pre-specified confirmatory test v3 vs v2-pre (REVISION_PLAN_3, "Νέο επιβεβαιωτικό τεστ")."""

from __future__ import annotations

import numpy as np
import pandas as pd

from fintwin.research.cross_spec import cfo_errors_frame, compare


def _errors(scale: float, years=range(2014, 2025), firms=60, seed=0, drop=()):
    rng = np.random.default_rng(seed)
    rows = [
        {"ticker": f"T{f}", "year": y, "abs_e": abs(rng.normal(0, scale))}
        for y in years
        for f in range(firms)
        if (f"T{f}", y) not in drop
    ]
    return pd.DataFrame(rows)


def test_a_better_candidate_succeeds_and_counts_are_paired():
    res = compare(_errors(5.0, seed=1), _errors(10.0, seed=2), boot=200)
    assert res["n_common"] == 11 * 60
    assert res["statistic"] < 0 and res["success"]
    assert res["decision"]["G"] == 11 and res["decision"]["ci"][1] < 0
    assert res["year_block"]["blocks"] == 11 and res["dm"]["mean"] < 0
    assert res["continuity"]["years"] == [2018, 2024]


def test_no_difference_does_not_succeed():
    res = compare(_errors(10.0, seed=1), _errors(10.0, seed=2), boot=200)
    assert not res["success"]


def test_units_lost_on_one_side_are_reported():
    lost = {("T0", 2015), ("T1", 2016), ("T2", 2017)}
    res = compare(_errors(5.0, seed=1, drop=lost), _errors(10.0, seed=2), names=("v3-wf", "v2-pre"), boot=50)
    assert res["lost"] == {"v3-wf": 3, "v2-pre": 0}
    assert res["n_common"] == 11 * 60 - 3 and not res["losses_differ_gt_1pp"]


def test_cfo_errors_frame_drops_non_finite_and_duplicates():
    df = pd.DataFrame(
        {
            "ticker": ["A", "A", "B", "C"],
            "year": [2015, 2015, 2015, 2016],
            "T1_cfo": [1.0, 1.0, np.nan, 3.0],
            "real_cfo": [2.0, 2.0, 1.0, 1.0],
        }
    )
    out = cfo_errors_frame(df)
    assert out.to_dict("list") == {
        "ticker": ["A", "C"],
        "year": [2015, 2016],
        "abs_e": [1.0, 2.0],
        "cluster": ["A", "C"],
    }
