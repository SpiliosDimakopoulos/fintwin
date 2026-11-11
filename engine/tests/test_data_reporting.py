"""Failure reporting and small untested paths of the data layer and the export (no network)."""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from fintwin import export
from fintwin.data import edgar, fred, xbrl_fallback
from fintwin.data.quality import quality_report


def test_ticker_starting_with_cik_is_a_ticker_not_a_key(monkeypatch):
    rows = {"0": {"ticker": "CIK", "cik_str": 5, "title": "A Real Ticker Inc"}}
    monkeypatch.setattr(edgar, "_get_json", lambda *a: rows)
    assert edgar.ticker_to_cik("cik") == (5, "A Real Ticker Inc")
    assert edgar.ticker_to_cik("CIK0000000123")[0] == 123


def test_quality_report_on_an_empty_panel_says_so():
    c = SimpleNamespace(ticker="X", quarters=pd.DataFrame(index=pd.DatetimeIndex([])), maturities_date=None, notes=[])
    with pytest.raises(ValueError, match="no reported quarters"):
        quality_report(c)


def test_augment_logs_and_lists_a_failed_filing(monkeypatch, caplog):
    filings = [{"accn": "a", "form": "10-Q", "filed": "2026-07-29", "primary": "a.htm"}]
    monkeypatch.setattr(xbrl_fallback, "periodic_filings", lambda cik: filings)

    def broken(cik, f, tags):
        raise OSError("truncated")

    monkeypatch.setattr(xbrl_fallback, "_filing_facts", broken)
    with caplog.at_level(logging.WARNING):
        raw = xbrl_fallback.augment(1, {"facts": {"us-gaap": {}}}, {"Revenues"})
    assert raw["_fallback"] == [] and raw["_fallback_errors"] == ["a: OSError: truncated"]
    assert "filing skipped: a: OSError" in caplog.text


def test_augment_that_cannot_list_filings_returns_raw_and_says_why(monkeypatch, caplog):
    def missing(cik):
        raise edgar.FrozenMiss("not in the frozen snapshot: submissions_0000000001.json.gz")

    monkeypatch.setattr(xbrl_fallback, "periodic_filings", missing)
    with caplog.at_level(logging.WARNING):
        raw = xbrl_fallback.augment(1, {"facts": {"us-gaap": {}}}, {"Revenues"})
    assert raw == {
        "facts": {"us-gaap": {}},
        "_fallback_errors": ["FrozenMiss: not in the frozen snapshot: submissions_0000000001.json.gz"],
    }
    assert "abandoned" in caplog.text
    monkeypatch.setattr(xbrl_fallback, "periodic_filings", lambda cik: [])
    assert "_fallback_errors" not in xbrl_fallback.augment(1, {"facts": {"us-gaap": {}}}, {"Revenues"})


def test_recession_regime_on_a_short_usrec_fixture(monkeypatch):
    idx = pd.date_range("1950-03-31", periods=40, freq="QE")
    rec = pd.Series(0.0, index=idx)
    rec.iloc[[10, 11, 25, 26, 27]] = 0.01  # fred_series returns percent / 100; USREC is 0 or 1
    growth = np.where(rec > 0, 0.0, 0.01)
    gdp = pd.Series(100 * np.exp(np.cumsum(growth)), index=idx) / 100
    monkeypatch.setattr(fred, "fred_series", lambda sid: {"USREC": rec, "GDP": gdp}[sid])
    r = fred.recession_regime()
    assert r["n_recessions"] == 2 and not r["in_recession_now"]
    assert r["hazard"] == pytest.approx(2 / 35) and r["exit"] == pytest.approx(2 / 5)
    assert r["gdp_shortfall_q"] > 0 and len(r["gdp_yoy"]) == 36


def test_history_icr_needs_positive_interest_and_links_filings():
    idx = pd.date_range("2021-03-31", periods=8, freq="QE")
    cols = ["revenue", "operating_income", "da", "net_income", "cfo", "capex", "cash", "short_investments"]
    q = pd.DataFrame({c: 10.0 for c in cols}, index=idx)
    q["total_debt"], q["equity"], q["gap"], q["fye_break"] = 50.0, 40.0, False, False
    q["interest_expense"] = [2.0] * 4 + [0.0] * 4
    accn = "0000000001-22-000001"
    c = SimpleNamespace(quarters=q, cik=1, provenance={"revenue": {"2022-12-31": accn}})
    h = json.loads(export.dumps(export.history_block(c, n=8)))
    icr = h["series"]["icr"]
    assert icr[3] == 5.0 and icr[7] is None  # TTM interest 0 in the last window: no ratio, not infinity
    assert h["provenance"]["revenue"][-1] == edgar.filing_url(1, accn) and h["provenance"]["revenue"][0] is None
    assert h["provenance"]["cash"] == [None] * 8


def _block(t: str) -> dict:
    base = {"health_score": 70.0, "p_breach": 0.1, "components": {}}
    return {"ticker": t, "name": t, "sector": "", "params": {"last_quarter": "2026-06-30"}, "presets": {"base": base}}


def test_build_marks_a_failed_ticker_stale_and_leaves_the_goldens(monkeypatch, tmp_path):
    (tmp_path / "index.json").write_text(json.dumps({"companies": {"BAD": {"name": "old"}}}), encoding="utf-8")
    monkeypatch.setattr(export, "OUT", tmp_path)
    monkeypatch.setattr(export, "GOLDEN", tmp_path / "missing_golden_dir")
    monkeypatch.setattr(export, "macro_quarterly", lambda: None)
    monkeypatch.setattr(export, "golden_cases", lambda macro: pytest.fail("goldens are rewritten only by GOLDEN"))

    def company_block(t, macro, with_sobol=False):
        if t == "BAD":
            raise KeyError("no data")
        return _block(t)

    monkeypatch.setattr(export, "company_block", company_block)
    with pytest.raises(SystemExit, match="BAD"):
        export.build(["OK", "BAD", "OK2"], with_backtests=False)
    index = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    assert index["companies"]["BAD"] == {"name": "old", "stale": True}
    assert "stale" not in index["companies"]["OK"] and (tmp_path / "companies" / "OK2.json").exists()
    assert not list(tmp_path.rglob("*.tmp"))


def test_build_backtests_weights_coverage_by_cases(monkeypatch, tmp_path):
    monkeypatch.setattr(export, "OUT", tmp_path)
    monkeypatch.setattr(export, "CUTOFFS", ["2019-12-31", "2020-12-31"])
    monkeypatch.setattr(export, "cross_section", lambda: {})

    def forecast_backtest(t, ck):
        n = 1 if ck.startswith("2019") else 3
        s = {"coverage50": 0.0 if n == 1 else 1.0, "coverage90": 1.0, "crps_skill": 0.1, "n": n}
        return {"ticker": t, "cutoff": ck, "scores": {"revenue": s}}

    monkeypatch.setattr(export, "forecast_backtest", forecast_backtest)
    export.build_backtests()
    agg = json.loads((tmp_path / "backtest.json").read_text(encoding="utf-8"))["aggregate"]["revenue"]
    assert agg["coverage50"] == 0.75 and agg["cases"] == 2 * len(export.SHOWCASE)
    assert agg["share_beating_baseline"] == 1.0
