"""SEC fetch helper: retries, Retry-After, 403/404 handling, non-JSON bodies and atomic cache writes. No network."""

import gzip
import json

import pytest
import requests

from fintwin.data import edgar, edgar_universe, xbrl_fallback


def _resp(status: int, body: bytes = b"{}", headers: dict | None = None) -> requests.Response:
    r = requests.Response()
    r.status_code, r._content, r.url = status, body, "https://example.test/x"
    r.headers.update(headers or {})
    return r


@pytest.fixture
def sec(monkeypatch, tmp_path):
    """Serve queued responses (or exceptions) to requests.get and record sleeps instead of sleeping."""
    queue: list = []
    calls: list[str] = []
    slept: list[float] = []

    def get(url, **kwargs):
        calls.append(url)
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(edgar, "CACHE_DIR", tmp_path)
    monkeypatch.setenv("SEC_USER_AGENT", "test test@example.com")
    monkeypatch.setattr(edgar.requests, "get", get)
    monkeypatch.setattr(edgar.time, "sleep", slept.append)
    monkeypatch.setattr(edgar, "_MIN_INTERVAL", 0.0)
    return queue, calls, slept


def test_429_waits_for_retry_after_then_succeeds(sec):
    queue, calls, slept = sec
    queue += [_resp(429, headers={"Retry-After": "30"}), _resp(200, b'{"a": 1}')]
    assert edgar._get_json("https://example.test/a", "a.json", 0) == {"a": 1}
    assert len(calls) == 2 and 30 in slept


def test_retry_after_shorter_than_backoff_and_http_date_fall_back_to_backoff(sec):
    queue, _, slept = sec
    queue += [_resp(503, headers={"Retry-After": "1"}), _resp(503, headers={"Retry-After": "Wed, 21 Oct 2026"})]
    queue.append(_resp(200))
    edgar.fetch("https://example.test/a")
    assert [s for s in slept if s >= 5] == [5, 10]


def test_5xx_on_every_attempt_raises_after_four(sec):
    queue, calls, _ = sec
    queue += [_resp(500)] * 4
    with pytest.raises(requests.HTTPError):
        edgar.fetch("https://example.test/a")
    assert len(calls) == 4


def test_connection_errors_are_retried_then_raised(sec):
    queue, calls, _ = sec
    queue += [requests.ConnectionError("down"), _resp(200)]
    assert edgar.fetch("https://example.test/a").status_code == 200
    queue += [requests.Timeout("slow")] * 4
    with pytest.raises(requests.Timeout):
        edgar.fetch("https://example.test/a")
    assert len(calls) == 6


def test_403_is_a_clear_error_and_not_retried(sec):
    queue, calls, _ = sec
    queue.append(_resp(403, b"<html>Your Request Originates from an Undeclared Automated Tool</html>"))
    with pytest.raises(requests.HTTPError, match="SEC is refusing this client"):
        edgar.fetch("https://example.test/a")
    assert len(calls) == 1


def test_404_is_not_retried(sec):
    queue, calls, _ = sec
    queue.append(_resp(404))
    with pytest.raises(requests.HTTPError) as e:
        edgar.fetch("https://example.test/a")
    assert e.value.response.status_code == 404 and len(calls) == 1


def test_html_instead_of_json_is_reported_and_not_cached(sec, tmp_path):
    queue, _, _ = sec
    queue.append(_resp(200, b"<!DOCTYPE html><html>blocked</html>", {"Content-Type": "text/html"}))
    with pytest.raises(RuntimeError, match="non-JSON response"):
        edgar._get_json("https://example.test/a", "a.json", 0)
    assert list(tmp_path.iterdir()) == []


def test_cache_write_is_atomic_and_leaves_no_temp_file(sec, tmp_path):
    queue, _, _ = sec
    queue.append(_resp(200, b'{"b": 2}'))
    edgar._get_json("https://example.test/b", "b.json", 0)
    assert [p.name for p in tmp_path.iterdir()] == ["b.json.gz"]
    with gzip.open(tmp_path / "b.json.gz", "rt", encoding="utf-8") as fh:
        assert json.load(fh) == {"b": 2}


def test_failed_write_keeps_the_previous_file(tmp_path, monkeypatch):
    target = tmp_path / "x.gz"
    target.write_bytes(b"old")

    def fail(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(edgar.os, "replace", fail)
    with pytest.raises(OSError):
        edgar.write_atomic(target, b"new")
    assert target.read_bytes() == b"old"


def test_xbrl_download_refuses_an_html_block_page(sec, tmp_path):
    queue, _, _ = sec
    queue.append(_resp(200, b"\n<html><body>Request Rate Threshold Exceeded</body></html>"))
    with pytest.raises(RuntimeError, match="HTML page instead of XBRL"):
        xbrl_fallback._download(1, "0000000001-26-000001", "x_htm.xml")
    assert list(tmp_path.iterdir()) == []
    queue.append(_resp(200, b"<xbrli:xbrl/>"))
    assert xbrl_fallback._download(1, "0000000001-26-000001", "x_htm.xml") == b"<xbrli:xbrl/>"
    assert [p.name for p in tmp_path.iterdir()] == ["xbrl_0000000001-26-000001_x_htm.xml.gz"]


def test_frame_treats_only_404_as_an_unused_tag(sec):
    queue, _, _ = sec
    queue.append(_resp(404))
    assert edgar_universe.frame("Revenues", 2012) == []
    queue += [_resp(429)] * 4
    with pytest.raises(requests.HTTPError):
        edgar_universe.frame("Revenues", 2013)


def test_submission_pages_reads_the_older_pages(sec):
    queue, calls, _ = sec
    recent = {"form": ["10-K"], "accessionNumber": ["a"], "filingDate": ["2020-01-01"]}
    older = {"form": ["10-Q"], "accessionNumber": ["b"], "filingDate": ["2010-01-01"]}
    first = {"filings": {"recent": recent, "files": [{"name": "CIK0000000001-submissions-001.json"}]}}
    queue += [_resp(200, json.dumps(first).encode()), _resp(200, json.dumps(older).encode())]
    meta, pages = edgar.submission_pages(1, 24)
    assert meta == first and pages == [recent, older]
    assert calls[1].endswith("CIK0000000001-submissions-001.json")
