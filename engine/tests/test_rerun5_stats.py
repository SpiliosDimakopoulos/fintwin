"""Rerun 5, WP5: statistics findings of the 12-11-2026 review, each with the case that showed it."""

from __future__ import annotations

from fintwin.research import stats as S


def test_holm_family_reads_the_training_limit_combinations():
    cell = {"N3+T1_vs_N3+N1": {"p": 0.9}, "N3+T1_vs_N3+N5": {"p": 0.9}, "N3+T1_vs_N3+N6": {"p": 0.9}}
    train = {k: {"p": 0.01} for k in cell}
    res = {"transmission": {"panel": {"cfo": {"hybrid": cell, "hybrid_train": train}}}}
    p = S._secondary_pvalues(res)
    assert p["hybrid_cfo_N3+T1_vs_N3+N1"] == 0.01 and len(p) == 3
