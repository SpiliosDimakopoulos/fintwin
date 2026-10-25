from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock
from time import monotonic

from fintwin.data import edgar


class FakeResponse:
    status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return {"ok": True}


def test_concurrent_requests_respect_minimum_spacing(monkeypatch, tmp_path):
    worker_count = 4
    start = Barrier(worker_count + 1)
    starts = []
    starts_lock = Lock()
    monkeypatch.setattr(edgar, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(edgar, "_last_request", monotonic())
    monkeypatch.setattr(edgar, "_user_agent", lambda: "FinTwin test contact@example.com")

    def get(*args, **kwargs):
        with starts_lock:
            starts.append(monotonic())
        return FakeResponse()

    monkeypatch.setattr(edgar.requests, "get", get)

    def request(index):
        start.wait()
        return edgar._get_json(f"https://example.test/{index}", f"concurrent-{index}", 0)

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [executor.submit(request, index) for index in range(worker_count)]
        start.wait()
        results = [future.result() for future in futures]

    assert results == [{"ok": True}] * worker_count
    ordered_starts = sorted(starts)
    gaps = [later - earlier for earlier, later in zip(ordered_starts, ordered_starts[1:], strict=False)]
    assert len(gaps) == worker_count - 1
    assert min(gaps) >= edgar._MIN_INTERVAL - 0.02
