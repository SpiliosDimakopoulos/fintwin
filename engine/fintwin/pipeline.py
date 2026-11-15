"""Sharded build pipeline, designed for free GitHub Actions runners (and runnable locally).

    python -m fintwin.pipeline norms                 # sector leverage norms for the whole universe
    python -m fintwin.pipeline shard 3 10            # shard 3 of 10: company snapshots, validation, time machine
    python -m fintwin.pipeline aggregate             # index, calibration, backtests, goldens, notes

Each shard writes self-contained files, so shards can run in parallel on separate machines and be merged by
simply copying their output directories together before `aggregate`.
"""

from __future__ import annotations

import json
import sys
import time
import traceback
import warnings
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

from . import universe
from .data.facts import contiguous, load_company

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "web" / "public" / "data"
CACHE = Path(__file__).resolve().parents[1] / ".cache"


def _json(path: Path, obj) -> None:
    from .export import dumps

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps(obj, separators=(",", ":")), encoding="utf-8")


def norms() -> None:
    lev: dict[str, float] = {}
    for t in universe.tickers():
        try:
            q = load_company(t).quarters
            if not contiguous(q, 4):  # a gap row would make the 4-row sum a 3-quarter sum
                continue
            ebitda = float((q["operating_income"] + q["da"].fillna(0)).tail(4).sum())
            nd = float(q["total_debt"].iloc[-1] - q["cash"].iloc[-1] - q["short_investments"].iloc[-1])
            if ebitda > 0 and np.isfinite(nd):
                lev[t] = nd / ebitda
        except Exception as e:
            print(f"  norms skip {t}: {type(e).__name__}: {e}")
    out = universe.compute_norms(lev)
    print(json.dumps(out["tolerance"], indent=1), f"n={out['n']}")


def shard(i: int, n: int) -> None:
    from .backtest.batch import company_cases
    from .data.fred import macro_quarterly
    from .export import SOBOL_SET, company_block

    tickers = [t for k, t in enumerate(expected_tickers()) if k % n == i]
    macro = macro_quarterly()
    (CACHE / "failed" / f"shard{i}.json").unlink(missing_ok=True)  # a fixed failure must not linger in the report
    failed = {}
    for t in tickers:
        t0 = time.time()
        try:
            block = company_block(t, macro, with_sobol=t in SOBOL_SET)
            _json(DATA / "companies" / f"{t}.json", block)
            res = company_cases(t)
            _json(DATA / "timeline" / f"{t}.json", res.pop("timeline"))
            _json(CACHE / "batch" / f"{t}.json", res)
            print(
                f"  {t}: health {block['presets']['base']['health_score']:.0f}, {len(res['cases'])} forecasts ({time.time() - t0:.0f}s)"
            )
        except Exception as e:
            failed[t] = f"{type(e).__name__}: {e}"
            print(f"  {t}: FAILED {failed[t]}")
            traceback.print_exc(limit=2)
    _json(CACHE / "failed" / f"shard{i}.json", failed)


def expected_tickers() -> list[str]:
    from .export import SHOWCASE

    base = universe.tickers()
    return base + [t for t in SHOWCASE if t not in base]


def failed_tickers() -> dict[str, str]:
    """Failures of the latest shard runs. A record is dropped once the ticker's company file is newer than it."""
    out = {}
    for f in (CACHE / "failed").glob("*.json"):
        for t, msg in json.loads(f.read_text(encoding="utf-8")).items():
            cf = DATA / "companies" / f"{t}.json"
            if not (cf.exists() and cf.stat().st_mtime > f.stat().st_mtime):
                out[t] = msg
    return out


def build_index(tickers: list[str] | None = None, failed: dict[str, str] | None = None) -> dict:
    """Index of this run's universe. Failed tickers (stale company file) and orphans (not in the universe) are left
    out, so a stale week-old JSON is never re-stamped as current and `changes.diff` can report removals."""
    from .export import index_entry, meta_block

    want = set(expected_tickers() if tickers is None else tickers)
    failed = failed_tickers() if failed is None else failed
    companies, stale, orphans = {}, [], []
    for f in sorted((DATA / "companies").glob("*.json")):
        b = json.loads(f.read_text(encoding="utf-8"))
        t = b["ticker"]
        if t not in want:
            orphans.append(t)
        elif t in failed:
            stale.append(t)
        else:
            companies[t] = index_entry(b)
    index: dict[str, Any] = {
        "companies": companies,
        "meta": {**meta_block(), "generated": date.today().isoformat(), "n_companies": len(companies)},
    }
    _json(DATA / "index.json", index)
    index["_stale"], index["_orphans"] = stale, orphans  # returned to aggregate for the build report, not written
    return index


def aggregate() -> None:
    from . import changes
    from .backtest.batch import aggregate as calib
    from .data.fred import macro_quarterly
    from .export import build_backtests, golden_cases
    from .notes import build as notes

    # last week's index (committed by the weekly workflow) is the baseline for the "what changed" feed
    prev = json.loads((DATA / "index.json").read_text(encoding="utf-8")) if (DATA / "index.json").exists() else None
    failed = failed_tickers()
    idx = build_index(failed=failed)
    stale, orphans = idx.pop("_stale"), idx.pop("_orphans")
    print(f"  index: {len(idx['companies'])} companies ({len(stale)} stale left out, {len(orphans)} orphans)")
    if prev:
        hist_path = DATA / "changes.json"
        history = json.loads(hist_path.read_text(encoding="utf-8")) if hist_path.exists() else None
        week = changes.diff(prev, idx)
        history = changes.update_history(history, week)
        _json(hist_path, history)
        (DATA / "feed.xml").write_text(changes.rss(history), encoding="utf-8")
        print(
            f"  changes: {week['n_weaker']} weaker, {week['n_stronger']} stronger, {week['n_new_filings']} new filings"
        )
    r = calib()
    print(
        f"  calibration: {r['n_companies']} companies, {r['n_forecasts']} forecasts, rho={r['cross_section']['spearman']:.2f}"
    )
    golden_cases(macro_quarterly())
    build_backtests()
    notes()
    _json(
        DATA / "build_report.json",
        {
            "generated": date.today().isoformat(),
            "failed": failed,
            "stale_excluded": stale,
            "orphans": orphans,
            "n_companies": len(idx["companies"]),
        },
    )
    print(f"  failed: {len(failed)} {list(failed)[:12]}")


if __name__ == "__main__":
    warnings.simplefilter("ignore")
    usage = "usage: python -m fintwin.pipeline norms | shard I N | aggregate"
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "shard" and len(sys.argv) != 4:
        raise SystemExit(usage)
    if cmd == "norms":
        norms()
    elif cmd == "shard":
        shard(int(sys.argv[2]), int(sys.argv[3]))
    elif cmd == "aggregate":
        aggregate()
    else:
        raise SystemExit(f"unknown command {cmd!r}; {usage}")
