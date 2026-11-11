import gzip
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
import requests

from fintwin.data import edgar


class FakeClock:
    """A clock that only moves when something sleeps, so throttling is exact and takes no real time."""

    def __init__(self, now: float = 1000.0):
        self.now = now
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self.headers = {}
        self._payload = {"ok": True} if payload is None else payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)

    def json(self):
        return self._payload


@pytest.fixture
def clock(monkeypatch, tmp_path):
    fake = FakeClock()
    monkeypatch.setattr(edgar, "time", fake)
    monkeypatch.setattr(edgar, "_last_request", fake.now)
    monkeypatch.setattr(edgar, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(edgar, "_user_agent", lambda: "FinTwin test contact@example.com")
    return fake


def _serve(monkeypatch, responses):
    """requests.get returning (or raising) each item in turn; returns the call counter."""
    calls = []

    def get(*args, **kwargs):
        item = responses[len(calls)]
        calls.append(args)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(edgar.requests, "get", get)
    return calls


def test_concurrent_requests_respect_minimum_spacing(monkeypatch, clock):
    worker_count = 4
    start = Barrier(worker_count)
    starts = []

    def get(*args, **kwargs):
        starts.append(clock.now)
        return FakeResponse()

    monkeypatch.setattr(edgar.requests, "get", get)

    def request(index):
        start.wait()
        return edgar._get_json(f"https://example.test/{index}", f"concurrent-{index}", 0)

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        results = list(executor.map(request, range(worker_count)))

    assert results == [{"ok": True}] * worker_count
    assert len(starts) == worker_count
    gaps = [later - earlier for earlier, later in zip(starts, starts[1:], strict=False)]
    assert min(gaps) >= edgar._MIN_INTERVAL - 1e-9


def test_429_is_retried_with_backoff(monkeypatch, clock):
    calls = _serve(monkeypatch, [FakeResponse(429), FakeResponse(200, {"n": 1})])
    assert edgar._get_json("https://example.test/a", "a", 0) == {"n": 1}
    assert len(calls) == 2
    assert 5 in clock.slept


def test_persistent_5xx_raises_after_four_attempts(monkeypatch, clock):
    calls = _serve(monkeypatch, [FakeResponse(500)] * 4)
    with pytest.raises(requests.HTTPError):
        edgar._get_json("https://example.test/a", "a", 0)
    assert len(calls) == 4
    assert [s for s in clock.slept if s >= 5] == [5, 10, 20]


def test_403_is_not_retried(monkeypatch, clock):
    calls = _serve(monkeypatch, [FakeResponse(403)])
    with pytest.raises(requests.HTTPError):
        edgar._get_json("https://example.test/a", "a", 0)
    assert len(calls) == 1


def test_connection_errors_are_retried_then_raised(monkeypatch, clock):
    calls = _serve(monkeypatch, [requests.ConnectionError("down")] * 4)
    with pytest.raises(requests.ConnectionError):
        edgar._get_json("https://example.test/a", "a", 0)
    assert len(calls) == 4


def test_truncated_cache_file_raises_instead_of_returning_partial_data(monkeypatch, clock):
    full = gzip.compress(b'{"cik": 1, "facts": {"a": [1, 2, 3]}}')
    (edgar.CACHE_DIR / "a.gz").write_bytes(full[: len(full) // 2])
    calls = _serve(monkeypatch, [])
    with pytest.raises(EOFError):
        edgar._get_json("https://example.test/a", "a", 1e9)
    assert not calls
