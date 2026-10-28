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
