"""Workstream F: pipeline/export survive the gap rows and NaN balances of the revision-3 data layer."""

from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np
import pandas as pd

from fintwin import pipeline, universe
from fintwin.export import dumps, history_block


def _frame(gap_at: int | None = None, n: int = 12) -> pd.DataFrame:
    idx = pd.date_range("2021-03-31", periods=n, freq="QE")
    q = pd.DataFrame(
        {
            "revenue": 100.0,
            "operating_income": 20.0,
            "da": 5.0,
            "interest_expense": 5.0,
            "net_income": 10.0,
            "cfo": 15.0,
            "capex": 5.0,
            "cash": 50.0,
            "short_investments": 0.0,
            "total_debt": 100.0,
            "equity": 80.0,
        },
        index=idx,
    )
    q["gap"] = False
    q["fye_break"] = False
    if gap_at is not None:
        flows = ["revenue", "operating_income", "da", "interest_expense", "net_income", "cfo", "capex"]
        q.loc[q.index[gap_at], flows] = np.nan  # balances may survive on a gap row
        q.loc[q.index[gap_at], "gap"] = True
    return q


def _co(q):
    return SimpleNamespace(quarters=q, provenance={}, cik=1)


def _isnull(x):
    return x is None or np.isnan(x)


def test_history_ttm_is_null_across_a_gap():
    h = history_block(_co(_frame(gap_at=8)), n=12)
    icr = h["series"]["icr"]
    assert icr[7] == 4.0  # 4 quarters of EBIT 20 over interest 5
    assert all(_isnull(icr[i]) for i in (8, 9, 10, 11))  # windows touching the gap
    assert _isnull(h["series"]["revenue"][8])
    out = json.loads(dumps(h))  # strict JSON: NaN -> null, no crash
    assert out["series"]["icr"][9] is None and out["series"]["nd_ebitda"][10] is None
    assert out["series"]["icr"][7] == 4.0


def test_history_without_gap_unchanged():
    h = history_block(_co(_frame()), n=12)
    assert h["series"]["icr"][3] == 4.0 and h["series"]["icr"][11] == 4.0


def test_history_nan_debt_gives_null_leverage():
    q = _frame()
    q.loc[q.index[-1], "total_debt"] = np.nan
    out = json.loads(dumps(history_block(_co(q), n=12)))
    assert out["series"]["nd_ebitda"][-1] is None and out["series"]["nd_ebitda"][-2] is not None


def test_norms_skips_firm_with_gap_in_last_four(monkeypatch):
    frames = {"GAP": _frame(gap_at=10), "OK": _frame()}
    seen = {}
    monkeypatch.setattr(universe, "tickers", lambda: list(frames))
    monkeypatch.setattr(pipeline, "load_company", lambda t: SimpleNamespace(quarters=frames[t]))

    def fake_norms(lev):
        seen.update(lev)
        return {"tolerance": {}, "n": len(lev)}

    monkeypatch.setattr(universe, "compute_norms", fake_norms)
    pipeline.norms()
    assert list(seen) == ["OK"]


def test_norms_survives_nan_debt(monkeypatch):
    q = _frame()
    q.loc[q.index[-1], "total_debt"] = np.nan
    monkeypatch.setattr(universe, "tickers", lambda: ["X"])
    monkeypatch.setattr(pipeline, "load_company", lambda t: SimpleNamespace(quarters=q))
    got = {}
    monkeypatch.setattr(universe, "compute_norms", lambda lev: got.update(lev) or {"tolerance": {}, "n": 0})
    pipeline.norms()
    assert got == {}
