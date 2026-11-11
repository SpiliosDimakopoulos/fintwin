"""Minimal SEC EDGAR client: ticker lookup and XBRL company facts, with disk cache.

SEC fair-access rules: declare a User-Agent with contact info and stay under 10 requests/s.
data.sec.gov does not send CORS headers, so this always runs server-side / offline.
"""

from __future__ import annotations

import csv
import gzip
import json
import os
import re
import threading
import time
from functools import lru_cache
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[3]
CACHE_DIR = Path(__file__).resolve().parents[2] / ".cache" / "edgar"
load_dotenv(ROOT / ".env")

_MIN_INTERVAL = 0.15  # seconds between requests (< 10 req/s)
_last_request = 0.0
_REQUEST_LOCK = threading.Lock()
_ATTEMPTS = 4

# 10-K / 10-Q filings and their amendments; the loader also accepts foreign filers' annual reports
PERIODIC_FORMS = {"10-K", "10-Q", "10-K/A", "10-Q/A", "10-KT"}


def _user_agent() -> str:
    ua = os.environ.get("SEC_USER_AGENT")
    if not ua:
        raise RuntimeError("Set SEC_USER_AGENT in .env (e.g. 'FinTwin research you@example.com')")
    return ua


def frozen() -> bool:
    """FINTWIN_FROZEN=1: read only the archived snapshot (any age), never the network; a missing file is an error."""
    return os.environ.get("FINTWIN_FROZEN", "0") == "1"


def data_legacy() -> bool:
    """FINTWIN_DATA_LEGACY=1: the revision-2 data layer (no revision-3 data fixes D1-D13), for one comparison run."""
    return os.environ.get("FINTWIN_DATA_LEGACY", "0") == "1"


def fill_only() -> bool:
    """FINTWIN_FILL_ONLY=1: every cached file counts as fresh, only missing files are fetched (topping up a snapshot
    without mixing in newer vintages of files it already holds)."""
    return os.environ.get("FINTWIN_FILL_ONLY", "0") == "1"


class FrozenMiss(FileNotFoundError):
    """A file the frozen snapshot does not contain."""


def throttle() -> None:
    """Wait until _MIN_INTERVAL has passed since the last SEC request; every caller must use this one clock."""
    global _last_request
    with _REQUEST_LOCK:
        wait = _MIN_INTERVAL - (time.monotonic() - _last_request)
        if wait > 0:
            time.sleep(wait)
        _last_request = time.monotonic()


def write_atomic(path: Path, data: bytes) -> None:
    """Write via a temporary sibling and rename, so a killed run or a second thread never leaves a truncated file
    that a later run (or frozen mode) would take for a complete one."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _retry_after(resp: requests.Response) -> float:
    try:
        return float(resp.headers.get("Retry-After", 0))
    except ValueError:  # an HTTP-date; the exponential backoff applies instead
        return 0.0


def fetch(url: str, sec: bool = True) -> requests.Response:
    """GET with retries: connection errors, 429 and 5xx back off exponentially (or for the server's Retry-After if
    longer); any other error status, 404 included, is raised at once. ``sec`` adds SEC's fair-access headers and the
    shared throttle."""
    headers = {"User-Agent": _user_agent(), "Accept-Encoding": "gzip, deflate"} if sec else {}
    for attempt in range(_ATTEMPTS):
        backoff = 5 * 2**attempt
        try:
            if sec:
                throttle()
            resp = requests.get(url, headers=headers, timeout=60)
        except (requests.ConnectionError, requests.Timeout):
            if attempt == _ATTEMPTS - 1:
                raise
            time.sleep(backoff)
            continue
        if (resp.status_code == 429 or resp.status_code >= 500) and attempt < _ATTEMPTS - 1:
            time.sleep(max(_retry_after(resp), backoff))
            continue
        break
    if sec and resp.status_code == 403:
        # not retried: requests during a block extend it; SEC lifts it after about 10 minutes under the rate limit
        raise requests.HTTPError(
            f"403 Forbidden from {url}: SEC is refusing this client (no contact in SEC_USER_AGENT, or more than "
            "10 requests/s); wait before retrying",
            response=resp,
        )
    resp.raise_for_status()
    return resp


def _get_json(url: str, cache_name: str, max_age_hours: float) -> dict:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / (cache_name + ".gz")  # gzip: company facts compress ~8x
    if path.exists() and (frozen() or fill_only() or (time.time() - path.stat().st_mtime) < max_age_hours * 3600):
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    if frozen():
        raise FrozenMiss(f"not in the frozen snapshot: {path.name}")
    resp = fetch(url)
    try:
        data = resp.json()
    except ValueError as e:  # SEC's block page for undeclared tools can arrive as a 200 text/html
        raise RuntimeError(
            f"non-JSON response from {url} (status {resp.status_code}); check SEC_USER_AGENT and the request rate"
        ) from e
    write_atomic(path, gzip.compress(json.dumps(data).encode("utf-8")))
    return data


def submission_pages(cik: int, max_age_hours: float) -> tuple[dict, list[dict]]:
    """The `submissions` record of a company and its filing pages, newest first (older filings are paged into
    separate files, which never change and are cached for a year)."""
    d = _get_json(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", f"submissions_{cik:010d}.json", max_age_hours)
    pages = [d["filings"]["recent"]]
    for f in d["filings"].get("files", []):
        pages.append(_get_json(f"https://data.sec.gov/submissions/{f['name']}", f["name"], 24 * 365))
    return d, pages


@lru_cache(maxsize=2)
def _local_rows(name: str) -> tuple[dict, ...]:
    path = Path(__file__).with_name(name)
    if not path.exists():
        return ()
    with open(path, encoding="utf-8") as fh:
        return tuple(csv.DictReader(fh))


def ticker_to_cik(ticker: str) -> tuple[int, str]:
    """Return (cik, company title) for a ticker. Keys like ``HTZ~2020`` name delisted 2020 Chapter 11 filers, keys
    like ``CIK0000012345`` any company in the EDGAR research universe (including ones that no longer exist)."""
    if re.fullmatch(r"CIK\d+", ticker.upper()):
        cik = int(ticker[3:])
        return cik, next((r["name"] for r in _local_rows("universe_edgar.csv") if int(r["cik"]) == cik), "")
    if "~" in ticker:
        for r in _local_rows("bankruptcies_2020.csv"):
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
