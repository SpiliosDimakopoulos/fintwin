"""Optional local API: build a twin for any ticker on demand.

    uv run --extra api python -m fintwin.api        # then the dashboard's dev server proxies /api here

The static dashboard works without it (it reads JSON snapshots); this only adds tickers outside the snapshot.
"""

from __future__ import annotations

import json
import logging
import threading
from collections import OrderedDict
from time import monotonic

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response

from .data.fred import macro_quarterly
from .export import _clean, company_block

app = FastAPI(title="FinTwin live API")

logger = logging.getLogger(__name__)
_BUILD_CACHE_MAXSIZE = 32
_BUILD_CACHE_TTL_SECONDS = 60 * 60
_BUILD_CACHE: OrderedDict[str, tuple[float, str]] = OrderedDict()
_BUILD_CACHE_LOCK = threading.Lock()


def _build(ticker: str) -> str:
    requested_at = monotonic()
    with _BUILD_CACHE_LOCK:
        cached = _BUILD_CACHE.get(ticker)
        if cached is not None:
            cached_at, payload = cached
            if requested_at - cached_at < _BUILD_CACHE_TTL_SECONDS:
                _BUILD_CACHE.move_to_end(ticker)
                return payload
            del _BUILD_CACHE[ticker]

    payload = json.dumps(_clean(company_block(ticker, macro_quarterly(), n_paths=3000)))

    with _BUILD_CACHE_LOCK:
        # Do not let a slower concurrent build overwrite a newer cached result.
        cached = _BUILD_CACHE.get(ticker)
        if cached is None or cached[0] <= requested_at:
            _BUILD_CACHE[ticker] = (monotonic(), payload)
            _BUILD_CACHE.move_to_end(ticker)
            while len(_BUILD_CACHE) > _BUILD_CACHE_MAXSIZE:
                _BUILD_CACHE.popitem(last=False)
        else:
            payload = cached[1]
    return payload


@app.get("/api/company/{ticker}")
def company(ticker: str) -> Response:
    t = ticker.upper().strip()
    if not t.replace(".", "").replace("-", "").isalnum() or len(t) > 10:
        raise HTTPException(400, "invalid ticker")
    try:
        return Response(_build(t), media_type="application/json")
    except KeyError as e:
        raise HTTPException(404, f"{t} is not a known SEC ticker") from e
    except Exception:  # data gaps for unusual filers (banks, foreign issuers, custom taxonomies)
        logger.exception("Could not build a twin for %s", t)
        raise HTTPException(422, "Could not build a twin for this ticker.") from None


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8765)
