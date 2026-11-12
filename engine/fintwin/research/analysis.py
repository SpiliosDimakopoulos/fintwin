"""Analysis commands on finished shards (`python -m fintwin.research <command>` forwards here).

Outside the shard code digest on purpose (research/__main__ reaches this module only by name): changing a statistic
never makes the shards of a finished run stale. Shards are still checked (`check_run`: stamp, run, completeness)
before anything reads them.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from . import __main__ as M  # the shard CLI: stamp checks, run directories (ROOT read at call time)


def stats(limit: int | None = None, years: set[int] | None = None) -> None:
    from .stats import OUT, main

    d = M.spec_dir(M.run_tag(limit, years))
    M.check_run(d, limit, years)
    summary = M.check_failures(M._shards(d))
    main(d, cfo_errors=M.ROOT / "_results" / f"{d.name}_cfo_errors.csv")
    copy = M.ROOT / "_results" / f"{d.name}.json"  # one result per spec, next to the shared docs/paper/research.json
    copy.parent.mkdir(parents=True, exist_ok=True)
    res = json.loads(Path(OUT).read_text(encoding="utf-8"))
    res["failures"] = summary
    # which code made the shards (their stamps) and which made these numbers
    res["provenance_code"] = {"shard_digest": M._code_digest(), "analysis_digest": M.analysis_digest()}
    copy.write_text(json.dumps(res, indent=1), encoding="utf-8")


def cross_spec(a: str, b: str) -> dict:
    """The confirmatory test v3 vs v2-pre from the error files each spec's `stats` wrote (cross_spec.py)."""
    from .cross_spec import compare

    files = [M.ROOT / "_results" / f"{n}_cfo_errors.csv" for n in (a, b)]
    missing = [f.name for f in files if not f.exists()]
    if missing:
        raise SystemExit(f"cross-spec: run `stats` for both specifications first (missing {missing})")
    frames = [pd.read_csv(f, dtype={"ticker": str}) for f in files]
    res = compare(*frames, names=(a, b))
    dest = M.ROOT / "_results" / f"cross_spec_{a}_vs_{b}.json"
    dest.write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: res.get(k) for k in ("n_common", "lost", "statistic", "decision", "success")}, default=str))
    return res


def main(argv: list[str]) -> None:
    pos, opt = M._opts(argv)
    limit = int(opt["limit"]) if "limit" in opt else None
    years = {int(y) for y in str(opt["cutoffs"]).split(",")} if "cutoffs" in opt else None
    cmd = pos[0]
    if cmd == "stats":
        if "dry" in opt:
            raise SystemExit("`stats --dry` is gone: pass the run's --limit / --cutoffs (one directory per run)")
        stats(limit, years)
    elif cmd == "cross-spec":  # cross-spec CANDIDATE REFERENCE, e.g. v3-wf v2-pre (each after its own `stats`)
        cross_spec(pos[1], pos[2])
    else:
        raise SystemExit(f"unknown command {cmd}")
