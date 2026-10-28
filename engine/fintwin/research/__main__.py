"""Sharded research runs (free GitHub Actions runners, or locally).

python -m fintwin.research prefetch          # download every company's XBRL facts once (SEC rate limit: serial)
python -m fintwin.research shard 3 16      # shard 3 of 16 -> .cache/research/<key>.json
python -m fintwin.research stats           # merge shards -> docs/paper/research.json

The sample is the survivorship-free EDGAR universe (data/universe_edgar.csv): every non-financial XBRL filer with
$50M+ revenue in some year 2012-2024, keyed by CIK. Probabilistic forecasts, which need ETS fits and are not about
survivorship, run for S&P 500 members (today's and those of 20 February 2020) only.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import warnings
from pathlib import Path

import pandas as pd

CACHE = Path(__file__).resolve().parents[2] / ".cache" / "research"
DATA = Path(__file__).resolve().parents[1] / "data"


def stamp() -> str:
    """Hash of the code, committed inputs, data snapshot and switches that produce a shard: a shard written under a
    different stamp is stale and is recomputed, and `stats` refuses to merge shards of mixed stamps."""
    root = Path(__file__).resolve().parents[1]
    h = hashlib.sha256()
    for p in sorted([*root.rglob("*.py"), *DATA.glob("*.csv")]):
        h.update(p.relative_to(root).as_posix().encode())
        h.update(p.read_bytes().replace(b"\r\n", b"\n"))
    snap = root.parent / "snapshot" / "manifest.json"
    h.update(json.loads(snap.read_text(encoding="utf-8"))["digest"].encode() if snap.exists() else b"live")
    for k in sorted(os.environ):
        if k.startswith("FINTWIN_"):
            h.update(f"{k}={os.environ[k]}".encode())
    return h.hexdigest()[:16]


def _stamp_of(path: Path) -> str | None:
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("_stamp")
    except (OSError, ValueError):
        return None


def research_tickers() -> list[str]:
    return pd.read_csv(DATA / "universe_edgar.csv")["key"].tolist()


def forecast_ciks() -> set[int]:
    today = pd.read_csv(DATA / "universe_sp500.csv")["cik"]
    then = pd.read_csv(DATA / "sp500_2020-02-20.csv")["cik"]
    return set(today.dropna().astype(int)) | set(then.astype(int))


def prefetch() -> None:
    from ..data.facts import company_facts

    keys = research_tickers()
    for k, t in enumerate(keys):
        try:
            company_facts(int(t[3:]))
        except Exception as e:
            print(f"  {t}: {type(e).__name__}: {e}", flush=True)
        if k % 250 == 0:
            print(f"  {k}/{len(keys)}", flush=True)


def shard(i: int, n: int) -> None:
    from ..export import _clean
    from .experiments import company

    CACHE.mkdir(parents=True, exist_ok=True)
    fc = forecast_ciks()
    st = stamp()
    for k, t in enumerate(research_tickers()):
        if k % n != i:
            continue
        out = CACHE / f"{t}.json"
        if out.exists() and _stamp_of(out) == st:  # resumable, but only under the same code, data and switches
            continue
        t0 = time.time()
        try:
            res = company(t, with_forecasts=int(t[3:]) in fc)
        except Exception as e:  # keep the shard going; the failure is recorded
            res = {"ticker": t, "errors": {"company": f"{type(e).__name__}: {e}"}}
        res["_stamp"] = st
        out.write_text(json.dumps(_clean(res)), encoding="utf-8")
        print(
            f"  {t}: {len(res.get('panel', []))} panel rows, {len(res.get('forecasts', []))} forecasts, "
            f"{len(res.get('errors', {}))} errors ({time.time() - t0:.0f}s)",
            flush=True,
        )


if __name__ == "__main__":
    warnings.simplefilter("ignore")
    if sys.argv[1] == "prefetch":
        prefetch()
    elif sys.argv[1] == "shard":
        shard(int(sys.argv[2]), int(sys.argv[3]))
    elif sys.argv[1] == "sobol-shard":
        from .assumption_sobol import shard as sobol_shard

        sobol_shard(int(sys.argv[2]), int(sys.argv[3]))
    elif sys.argv[1] == "sobol-stats":
        import json as _json

        from .assumption_sobol import stats as sobol_stats

        print(_json.dumps({k: v for k, v in sobol_stats().items() if k != "indices"}, default=str)[:2000])
    elif sys.argv[1] == "stats":
        from .stats import main

        st = stamp()
        stale = [p.name for p in CACHE.glob("*.json") if _stamp_of(p) != st]
        if stale:
            raise SystemExit(
                f"{len(stale)} shard files were written under another stamp (e.g. {stale[:3]}): rerun them"
            )
        main(CACHE)
    else:
        raise SystemExit(f"unknown command {sys.argv[1]}")
