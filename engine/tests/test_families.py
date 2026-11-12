"""WP6 (a reader): corporate families from joint filings."""

from __future__ import annotations

import pandas as pd

from fintwin.research import families as F


def _f(rows):
    return pd.DataFrame(rows, columns=["accessionNumber", "form"])


def test_joint_periodic_reports_link_and_ownership_filings_do_not():
    filings = {
        1: _f([("a1", "10-K"), ("own", "4"), ("m1", "8-K")]),
        2: _f([("a1", "10-K")]),  # co-registrant subsidiary of 1
        3: _f([("own", "4")]),  # an investor: Form 4 lists issuer and holder under one accession
        4: _f([("b1", "10-Q/A")]),
        5: _f([("b1", "10-Q/A")]),
        6: _f([("m1", "8-K")]),  # joint 8-K with 1: joins the group too
    }
    pairs = F.links(filings)
    assert pairs == [(1, 2), (1, 6), (4, 5)]
    fam = F.families(filings, pairs)
    assert fam == {1: 1, 2: 1, 3: 3, 4: 4, 5: 4, 6: 1}
    assert F.summary(fam) == {"ciks": 6, "families": 3, "multi_member": 2, "ciks_in_multi": 5, "largest": 3}


def test_families_are_transitive_and_order_free():
    fam = F.families([5, 3, 9, 7], [(7, 9), (3, 7)])
    assert fam == {5: 5, 3: 3, 9: 3, 7: 3}


def test_family_pass_sets_units_and_counts_a_group_bankruptcy_once(tmp_path, monkeypatch):
    import json

    import numpy as np

    from fintwin.research import units as U

    df = pd.DataFrame({"ticker": ["CIK0000000001", "CIK0000000002", "CIK0000000003"], "cik": [1, 2, 3],
                       "year": [2019, 2019, 2019], "log_rev": [22.0, 20.0, 21.0], "y_bk8": [1.0, 1.0, 1.0]})  # fmt: skip
    assert U.unit(df).tolist() == df["ticker"].tolist()  # firm units by default
    assert U.dedupe_events(df, ["y_bk8"], "year") == (df, {})  # no family pass: nothing changes
    fam = tmp_path / "families.json"
    fam.write_text(json.dumps({"1": 1, "2": 1, "3": 3}), encoding="utf-8")
    monkeypatch.setenv("FINTWIN_FAMILIES", str(fam))
    U._families.cache_clear()
    df["cluster"] = [U.cluster_of(t, c) for t, c in zip(df["ticker"], df["cik"], strict=True)]
    assert df["cluster"].tolist() == ["F0000000001", "F0000000001", "F0000000003"]
    out, removed = U.dedupe_events(df, ["y_bk8"], "year")
    assert removed == {"y_bk8": 1} and np.isnan(out.loc[1, "y_bk8"]) and out.loc[0, "y_bk8"] == 1.0  # larger keeps it
    # one member for every label; a sibling without the event leaves the test too (not a survivor of a failed group)
    df2 = df.assign(y_bk8=[1.0, 0.0, 0.0], y_bk4=[0.0, 1.0, 0.0])
    out2, removed2 = U.dedupe_events(df2, ["y_bk8", "y_bk4"], "year")
    assert (
        out2.loc[0, ["y_bk8", "y_bk4"]].tolist() == [1.0, 1.0] and out2.loc[1, ["y_bk8", "y_bk4"]].isna().all()
    )  # the family had a 4-quarter event (B)
    assert removed2 == {"y_bk8": 1, "y_bk4": 1} and out2.loc[2, "y_bk8"] == 0.0  # another family untouched


def test_the_family_switch_does_not_change_the_shard_stamp(monkeypatch):
    import fintwin.research.__main__ as M

    monkeypatch.setenv("FINTWIN_SPEC", "v3")
    monkeypatch.delenv("FINTWIN_FAMILIES", raising=False)
    before = M.stamp()
    for k in ("FINTWIN_FAMILIES", "FINTWIN_REQUIRE_SPEC", "FINTWIN_NEW_RUN"):
        monkeypatch.setenv(k, "1")
    assert M.stamp() == before


def test_the_kept_member_carries_the_family_labels(tmp_path, monkeypatch):
    # round 3: A (larger) has y_short8 = 1, ce8 = 0; B has ce8 = 1 -> the family must keep ce8 = 1
    import json

    import numpy as np

    from fintwin.research import units as U

    fam = tmp_path / "f.json"
    fam.write_text(json.dumps({"1": 1, "2": 1}), encoding="utf-8")
    monkeypatch.setenv("FINTWIN_FAMILIES", str(fam))
    U._families.cache_clear()
    df = pd.DataFrame({"ticker": ["A", "B"], "cluster": ["F1", "F1"], "year": [2019, 2019], "log_rev": [22.0, 20.0],
                       "y_short8": [1.0, 0.0], "ce8": [0.0, 1.0], "ce4": [np.nan, 1.0]})  # fmt: skip
    out, _ = U.dedupe_events(df, ["y_short8", "ce8", "ce4"], "year")
    assert out.loc[0, ["y_short8", "ce8", "ce4"]].tolist() == [1.0, 1.0, 1.0] and out.loc[1, ["ce8"]].isna().all()
