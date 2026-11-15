"""Live API de-duplication, pipeline usage, weekly feed text and cached loaders (quality pass EC-17-EC-19, EC-22)."""

from __future__ import annotations

import subprocess
import sys
import threading
import time

from fintwin import api, changes, universe
from fintwin.scenarios import presets


def test_concurrent_requests_for_a_cold_ticker_build_once(monkeypatch):
    builds = []
    monkeypatch.setattr(api, "macro_quarterly", lambda: None)

    def slow_build(ticker, macro, n_paths):
        builds.append(ticker)
        time.sleep(0.2)
        return {"build": len(builds)}

    monkeypatch.setattr(api, "company_block", slow_build)
    api._BUILD_CACHE.clear()
    results = []
    threads = [threading.Thread(target=lambda: results.append(api._build("ACME"))) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    api._BUILD_CACHE.clear()
    assert builds == ["ACME"] and len(set(results)) == 1 and len(results) == 4


def test_pipeline_without_a_command_prints_usage():
    r = subprocess.run([sys.executable, "-m", "fintwin.pipeline"], capture_output=True, text=True, timeout=120)
    assert r.returncode != 0 and "usage: python -m fintwin.pipeline" in r.stderr


def test_quiet_week_names_the_threshold(monkeypatch):
    monkeypatch.setattr(changes, "THRESHOLD", 7.5)
    week = {"date": "2026-10-19", "n_weaker": 0, "n_stronger": 0, "n_new_filings": 0, "movers": []}
    assert "moved by 7.5 points or more" in changes.rss({"weeks": [week]})


def test_loaders_are_cached():
    assert universe._bankruptcies() is universe._bankruptcies()
    assert presets.load_sector_shocks() is presets.load_sector_shocks()
