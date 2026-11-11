"""Optional local API: build a twin for any ticker on demand.

    uv run --extra api python -m fintwin.api        # then the dashboard's dev server proxies /api here

The static dashboard works without it (it reads JSON snapshots); this only adds tickers outside the snapshot.
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from time import monotonic

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response

from .data.fred import macro_quarterly
from .export import company_block, dumps

app = FastAPI(title="FinTwin live API")

logger = logging.getLogger(__name__)
_BUILD_CACHE_MAXSIZE = 32
_BUILD_CACHE_TTL_SECONDS = 60 * 60
_BUILD_CACHE: OrderedDict[str, tuple[float, str]] = OrderedDict()
_BUILD_CACHE_LOCK = threading.Lock()
# One lock per ticker: concurrent requests for a cold ticker wait for the first build instead of each starting one.
_TICKER_LOCKS: dict[str, threading.Lock] = {}


def _cached(ticker: str) -> str | None:
    with _BUILD_CACHE_LOCK:
        cached = _BUILD_CACHE.get(ticker)
        if cached is None:
            return None
        cached_at, payload = cached
        if monotonic() - cached_at < _BUILD_CACHE_TTL_SECONDS:
            _BUILD_CACHE.move_to_end(ticker)
            return payload
        del _BUILD_CACHE[ticker]
        return None


def _build(ticker: str) -> str:
    payload = _cached(ticker)
    if payload is not None:
        return payload
    with _BUILD_CACHE_LOCK:
        lock = _TICKER_LOCKS.setdefault(ticker, threading.Lock())
    with lock:
        payload = _cached(ticker)  # built by the request this one waited for
        if payload is not None:
            return payload
        payload = dumps(company_block(ticker, macro_quarterly(), n_paths=3000))
        with _BUILD_CACHE_LOCK:
            _BUILD_CACHE[ticker] = (monotonic(), payload)
            _BUILD_CACHE.move_to_end(ticker)
            while len(_BUILD_CACHE) > _BUILD_CACHE_MAXSIZE:
                _BUILD_CACHE.popitem(last=False)
    return payload


@app.get("/api/company/{ticker}")
def company(ticker: str) -> Response:
    t = ticker.upper().strip()
    if not t.replace(".", "").replace("-", "").isalnum() or len(t) > 10:
        raise HTTPException(400, "invalid ticker")
    try:
        return Response(_build(t), media_type="application/json")
    except KeyError as e:
        # only edgar.ticker_to_cik's "Unknown ticker" is a 404; a KeyError from deep inside calibration is a data gap
        if not str(e.args[0] if e.args else "").lower().startswith("unknown ticker"):
            logger.exception("Could not build a twin for %s", t)
            raise HTTPException(422, "Could not build a twin for this ticker.") from None
        raise HTTPException(404, f"{t} is not a known SEC ticker") from e
    except Exception:  # data gaps for unusual filers (banks, foreign issuers, custom taxonomies)
        logger.exception("Could not build a twin for %s", t)
        raise HTTPException(422, "Could not build a twin for this ticker.") from None


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8765)
