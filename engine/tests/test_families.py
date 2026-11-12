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
