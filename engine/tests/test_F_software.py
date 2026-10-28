"""Workstream F: software cleanup (SW-5, SW-6 export side, SW-11, SW-16, null-safe changes feed)."""

from __future__ import annotations

import json
import math
import os
import time

import numpy as np
from fastapi.testclient import TestClient

from fintwin import api, memo, notes, pipeline
from fintwin.changes import diff
from fintwin.export import _clean, _write, dumps, index_entry


def _entry(health, p=0.01, quarter="2026-06-30"):
    return {
        "name": "Co",
        "sector": "Industrials",
        "last_quarter": quarter,
        "matrix": {"base": {"health": health, "p_breach": p}},
        "components": {"liq": None, "cov": 50, "lev": 50, "solv": 50},
    }


def _block(t, health=60.0):
    return {
        "ticker": t,
        "name": t,
        "sector": "S",
        "gics": "G",
        "params": {"last_quarter": "2026-06-30"},
        "presets": {"base": {"health_score": health, "p_breach": 0.02, "components": {"liq": 1, "cov": 2}}},
    }


# SW-6 / JSON safety
def test_dumps_emits_null_not_nan_literals():
    s = dumps({"a": float("nan"), "b": [np.float64("inf"), np.nan], "c": np.array([1.0, -np.inf])})
    assert "NaN" not in s and "Infinity" not in s
    assert json.loads(s) == {"a": None, "b": [None, None], "c": [1.0, None]}


def test_write_is_strict_json(tmp_path):
    _write(tmp_path / "x.json", {"v": math.nan})
    assert (tmp_path / "x.json").read_text() == '{"v":null}'


def test_clean_keeps_finite_values():
    assert _clean({"x": np.int64(3), "y": np.float64(0.5), "z": np.bool_(True)}) == {"x": 3, "y": 0.5, "z": True}


# changes feed: null health must not crash the aggregate
def test_diff_skips_null_health_and_null_p_breach():
    prev = {"companies": {"A": _entry(None), "B": _entry(70, p=None), "C": _entry(70)}}
    new = {"companies": {"A": _entry(50), "B": _entry(50, p=None), "C": _entry(50)}}
    w = diff(prev, new, today="2026-10-19")
    assert [m["ticker"] for m in w["movers"]] == ["B", "C"]
    assert w["movers"][0]["p_breach_before"] is None
    assert w["movers"][0]["drivers"] == []  # all components unchanged, and the null "liq" is skipped


# SW-5: index from this run's universe only
def test_build_index_excludes_failed_and_orphans(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "DATA", tmp_path / "data")
    monkeypatch.setattr(pipeline, "CACHE", tmp_path / "cache")
    for t in ("AAA", "BBB", "ZZZ"):
        pipeline._json(pipeline.DATA / "companies" / f"{t}.json", _block(t))
    idx = pipeline.build_index(tickers=["AAA", "BBB"], failed={"BBB": "boom"})
    assert list(idx["companies"]) == ["AAA"]
    assert idx["_stale"] == ["BBB"] and idx["_orphans"] == ["ZZZ"]
    written = json.loads((pipeline.DATA / "index.json").read_text())
    assert "_stale" not in written and list(written["companies"]) == ["AAA"]
    assert written["companies"]["AAA"]["gics"] == "G" and written["companies"]["AAA"]["components"]


def test_failed_record_dropped_once_company_file_is_newer(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "DATA", tmp_path / "data")
    monkeypatch.setattr(pipeline, "CACHE", tmp_path / "cache")
    rec = pipeline.CACHE / "failed" / "shard0.json"
    pipeline._json(rec, {"AAA": "x", "BBB": "y"})
    pipeline._json(pipeline.DATA / "companies" / "AAA.json", _block("AAA"))
    now = time.time()
    os.utime(rec, (now - 100, now - 100))  # AAA was rebuilt after the failure; BBB has no file
    assert pipeline.failed_tickers() == {"BBB": "y"}


def test_index_entry_has_one_schema():
    e = index_entry(_block("AAA"))
    assert set(e) == {"name", "sector", "gics", "showcase", "last_quarter", "matrix", "components"}


# SW-11: memo number check and the notes/memo path collision
def test_unicode_minus_keeps_sign():
    assert memo._numbers("loss of −$3.0B and $2.5B") == [-3.0, 2.5]
    assert memo.unverified_numbers({"s": "a drop of -$300M"}, {"x": "−$300M"}) == []
    # a negative figure in the memo must match a negative sheet figure
    assert memo.unverified_numbers({"s": "-$300M"}, {"x": "$300M"}, strict=True) == [-300.0]


def test_strict_checks_small_numbers():
    sheet = {"rating": "BB", "coverage": 2.3, "n": 8}
    assert memo.unverified_numbers({"s": "7 risks"}, sheet) == []  # legacy default ignores small counts
    assert memo.unverified_numbers({"s": "7 risks"}, sheet, strict=True) == [7.0]
    assert memo.unverified_numbers({"s": "coverage 2.3x over 8 quarters"}, sheet, strict=True) == []
    assert memo.unverified_numbers({"s": "coverage 2.9x"}, sheet, strict=True) == [2.9]


def test_notes_build_does_not_overwrite_llm_memo(tmp_path, monkeypatch):
    monkeypatch.setattr(notes, "DATA", tmp_path)
    (tmp_path / "companies").mkdir()
    (tmp_path / "memos").mkdir()
    (tmp_path / "index.json").write_text(json.dumps({"companies": {"AAA": {}, "BBB": {}}, "meta": {}}))
    for t in ("AAA", "BBB"):
        (tmp_path / "companies" / f"{t}.json").write_text("{}")
    (tmp_path / "memos" / "AAA.json").write_text(json.dumps({"generated_by": "claude-opus-5-5", "headline": "mine"}))
    monkeypatch.setattr(notes, "write_note", lambda c, m: {"generated_by": notes.RULE_BASED + " (x)"})
    notes.build()
    assert json.loads((tmp_path / "memos" / "AAA.json").read_text())["headline"] == "mine"
    assert json.loads((tmp_path / "memos" / "BBB.json").read_text())["generated_by"].startswith(notes.RULE_BASED)


# SW-16: only an unknown ticker is a 404
def _failing(monkeypatch, exc):
    monkeypatch.setattr(api, "macro_quarterly", lambda: None)
    api._BUILD_CACHE.clear()

    def build(*a, **k):
        raise exc

    monkeypatch.setattr(api, "company_block", build)


def test_api_deep_keyerror_is_422_not_404(monkeypatch):
    _failing(monkeypatch, KeyError("total_debt"))
    assert TestClient(api.app).get("/api/company/acme").status_code == 422


def test_api_unknown_ticker_is_404(monkeypatch):
    _failing(monkeypatch, KeyError("Unknown ticker: NOPE"))
    assert TestClient(api.app).get("/api/company/nope").status_code == 404
