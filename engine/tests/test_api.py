from fastapi.testclient import TestClient

from fintwin import api


def test_build_cache_expires(monkeypatch):
    now = 100.0
    builds = []
    monkeypatch.setattr(api, "monotonic", lambda: now)
    monkeypatch.setattr(api, "_BUILD_CACHE_TTL_SECONDS", 60)
    monkeypatch.setattr(api, "macro_quarterly", lambda: None)

    def build(ticker, macro, n_paths):
        builds.append(ticker)
        return {"build": len(builds)}

    monkeypatch.setattr(api, "company_block", build)
    api._BUILD_CACHE.clear()
    client = TestClient(api.app)

    first = client.get("/api/company/acme")
    cached = client.get("/api/company/ACME")
    now += 61
    refreshed = client.get("/api/company/ACME")

    assert first.status_code == cached.status_code == refreshed.status_code == 200
    assert first.json() == cached.json() == {"build": 1}
    assert refreshed.json() == {"build": 2}
    assert builds == ["ACME", "ACME"]
    api._BUILD_CACHE.clear()


def test_build_error_is_logged_but_not_returned(monkeypatch, caplog):
    monkeypatch.setattr(api, "macro_quarterly", lambda: None)

    def fail_build(*args, **kwargs):
        raise RuntimeError("private provider details")

    monkeypatch.setattr(api, "company_block", fail_build)
    response = TestClient(api.app).get("/api/company/acme")

    assert response.status_code == 422
    assert "Could not build a twin" in response.json()["detail"]
    assert "private provider details" not in response.text
    assert "RuntimeError" not in response.text
    assert "private provider details" in caplog.text


def test_unknown_ticker_keeps_not_found_response(monkeypatch):
    monkeypatch.setattr(api, "macro_quarterly", lambda: None)

    def unknown_ticker(*args, **kwargs):
        raise KeyError("unknown ticker")

    monkeypatch.setattr(api, "company_block", unknown_ticker)
    response = TestClient(api.app).get("/api/company/acme")

    assert response.status_code == 404
    assert "ACME is not a known SEC ticker" == response.json()["detail"]
