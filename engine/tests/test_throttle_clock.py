"""The SEC throttle has one clock. The XBRL fallback used time.time() while edgar used time.monotonic(); after the first
fallback download the next JSON request computed a wait of decades and the weekly build hung (data runs of 2 and 9
November 2026, both cancelled at the 90-minute timeout)."""

from __future__ import annotations

import time

import fintwin.data.edgar as E
import fintwin.data.xbrl_fallback as X


class _Resp:
    content = b"<xbrl/>"
    status_code = 200

    def raise_for_status(self) -> None:
        return None


def test_fallback_download_then_json_request_does_not_stall(monkeypatch, tmp_path):
    monkeypatch.setenv("SEC_USER_AGENT", "test test@example.com")
    monkeypatch.setattr(E, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(X.requests, "get", lambda *a, **k: _Resp())
    sleeps: list[float] = []
    monkeypatch.setattr(E.time, "sleep", lambda s: sleeps.append(s))
    E._last_request = 0.0
    X._download(1, "0000000001-26-000001", "x.xml")  # a fallback download sets the shared clock
    E.throttle()  # the next request through edgar's clock
    assert all(s <= E._MIN_INTERVAL + 1e-9 for s in sleeps), sleeps
    assert abs(E._last_request - time.monotonic()) < 60  # monotonic, not wall-clock time
