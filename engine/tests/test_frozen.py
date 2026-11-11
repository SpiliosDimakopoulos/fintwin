import gzip
import json
import os
import time

import pytest

from fintwin.data import edgar


def test_frozen_reads_stale_cache_and_never_fetches(tmp_path, monkeypatch):
    monkeypatch.setattr(edgar, "CACHE_DIR", tmp_path)
    old = tmp_path / "companyfacts_0000000001.json.gz"
    with gzip.open(old, "wt", encoding="utf-8") as fh:
        json.dump({"cik": 1}, fh)
    os.utime(old, (time.time() - 1e7, time.time() - 1e7))  # far older than any max age
    monkeypatch.setenv("FINTWIN_FROZEN", "1")
    monkeypatch.setattr(edgar.requests, "get", lambda *a, **k: pytest.fail("frozen mode must not fetch"))

    assert edgar.company_facts(1) == {"cik": 1}
    with pytest.raises(edgar.FrozenMiss):
        edgar.company_facts(2)


def test_fallback_download_and_json_share_one_throttle_clock(tmp_path, monkeypatch):
    """A fallback download followed by a JSON request waits one interval each (time.time vs time.monotonic)."""
    from fintwin.data import xbrl_fallback

    class R:
        status_code, content = 200, b"<xbrl/>"

        def raise_for_status(self):
            pass

        def json(self):
            return {}

    class Clock:
        now = 1000.0
        slept: list[float] = []

        def monotonic(self):
            return self.now

        def time(self):
            return self.now

        def sleep(self, seconds):
            self.slept.append(seconds)
            self.now += seconds

    clock = Clock()
    monkeypatch.setattr(edgar, "time", clock)
    monkeypatch.setattr(edgar, "_last_request", clock.now)
    monkeypatch.setattr(edgar, "CACHE_DIR", tmp_path)
    monkeypatch.setenv("SEC_USER_AGENT", "test test@example.com")
    monkeypatch.setattr(edgar.requests, "get", lambda *a, **k: R())
    xbrl_fallback._download(1, "0000000001-26-000001", "x.xml")
    edgar._get_json("https://example.com/a.json", "a.json", 0)
    assert clock.slept == [edgar._MIN_INTERVAL, edgar._MIN_INTERVAL]
