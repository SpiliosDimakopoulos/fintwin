"""Minimal SEC EDGAR client: ticker lookup and XBRL company facts, with disk cache.

SEC fair-access rules: declare a User-Agent with contact info and stay under 10 requests/s.
data.sec.gov does not send CORS headers, so this always runs server-side / offline.
"""

from __future__ import annotations

import gzip
import json
import os
import threading
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[3]
CACHE_DIR = Path(__file__).resolve().parents[2] / ".cache" / "edgar"
load_dotenv(ROOT / ".env")

_MIN_INTERVAL = 0.15  # seconds between requests (< 10 req/s)
_last_request = 0.0
_REQUEST_LOCK = threading.Lock()


def _user_agent() -> str:
    ua = os.environ.get("SEC_USER_AGENT")
    if not ua:
        raise RuntimeError("Set SEC_USER_AGENT in .env (e.g. 'FinTwin research you@example.com')")
    return ua


def _get_json(url: str, cache_name: str, max_age_hours: float) -> dict:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / (cache_name + ".gz")  # gzip: company facts compress ~8x
    if path.exists() and (time.time() - path.stat().st_mtime) < max_age_hours * 3600:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return json.load(fh)

    global _last_request
    for attempt in range(4):  # transient network errors, SEC throttling (429) and 5xx are retried with backoff
        try:
            with _REQUEST_LOCK:
                wait = _MIN_INTERVAL - (time.monotonic() - _last_request)
                if wait > 0:
                    time.sleep(wait)
                _last_request = time.monotonic()
                resp = requests.get(
                    url, headers={"User-Agent": _user_agent(), "Accept-Encoding": "gzip, deflate"}, timeout=60
                )
        except (requests.ConnectionError, requests.Timeout):
            if attempt == 3:
                raise
            time.sleep(5 * 2**attempt)
            continue
        if (resp.status_code == 429 or resp.status_code >= 500) and attempt < 3:
            time.sleep(5 * 2**attempt)
            continue
        break
    resp.raise_for_status()
    data = resp.json()
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(data, fh)
    return data


def ticker_to_cik(ticker: str) -> tuple[int, str]:
    """Return (cik, company title) for a ticker. Keys like ``HTZ~2020`` name delisted 2020 Chapter 11 filers, keys
    like ``CIK0000012345`` any company in the EDGAR research universe (including ones that no longer exist)."""
    if ticker.upper().startswith("CIK"):
        import csv

        cik, path = int(ticker[3:]), Path(__file__).with_name("universe_edgar.csv")
        if not path.exists():
            return cik, ""
        with open(path, encoding="utf-8") as fh:
            name = next((r["name"] for r in csv.DictReader(fh) if int(r["cik"]) == cik), "")
        return cik, name
    if "~" in ticker:
        import csv

        with open(Path(__file__).with_name("bankruptcies_2020.csv"), encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r["key"] == ticker.upper():
                    return int(r["cik"]), r["name"]
    data = _get_json("https://www.sec.gov/files/company_tickers.json", "company_tickers.json", 24 * 7)
    t = ticker.upper()
    for row in data.values():
        if row["ticker"].upper() == t:
            return int(row["cik_str"]), row["title"]
    raise KeyError(f"Unknown ticker: {ticker}")


def company_facts(cik: int, max_age_hours: float | None = None) -> dict:
    """XBRL company facts. FINTWIN_FACTS_MAX_AGE (hours) freezes the data vintage for long research runs."""
    if max_age_hours is None:
        max_age_hours = float(os.environ.get("FINTWIN_FACTS_MAX_AGE", 24))
    return _get_json(
        f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json",
        f"companyfacts_{cik:010d}.json",
        max_age_hours,
    )


def filing_url(cik: int, accn: str) -> str:
    """Human-readable link to the filing index for provenance."""
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn.replace('-', '')}/{accn}-index.htm"
