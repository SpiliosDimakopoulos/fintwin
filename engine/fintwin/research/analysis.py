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
    from .units import family_pass

    d = M.spec_dir(M.run_tag(limit, years))
    name = d.name + ("_family" if family_pass() else "")  # the family pass (WP6) writes beside the firm pass
    for old in (M.ROOT / "_results" / f"{name}_cfo_errors.csv", M.ROOT / "_results" / f"{name}.json"):
        old.unlink(missing_ok=True)  # before any check: a failed stats leaves no earlier file for cross-spec (round 3)
    M.check_run(d, limit, years)
    summary = M.check_failures(M._shards(d))
    main(d, cfo_errors=M.ROOT / "_results" / f"{name}_cfo_errors.csv")
    copy = M.ROOT / "_results" / f"{name}.json"  # one result per spec, next to the shared docs/paper/research.json
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
    res = compare(frames[0], frames[1], names=(a, b))
    # the one confirmatory test of REVISION_PLAN_3: walk-forward v3 against v2-pre, firm units; every other pairing
    # (grid v3, the family pass) is descriptive (round 2, N1; RERUN5_SUPPLEMENT)
    res["role"] = "confirmatory" if (a, b) == ("v3-wf", "v2-pre") else "descriptive"
    dest = M.ROOT / "_results" / f"cross_spec_{a}_vs_{b}.json"
    dest.write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    print(
        json.dumps(
            {k: res.get(k) for k in ("role", "n_common", "lost", "statistic", "decision", "success")}, default=str
        )
    )
    return res


REPRO_MEDIAN_MAX = 0.05  # REVISION_PLAN_5: median |difference| of firm-year errors, points of revenue
REPRO_SHARE_MAX = 0.01  # share of firm-years differing by more than REPRO_LARGE
REPRO_LARGE = 0.5


def reproduce(name: str, reference: Path) -> dict:
    """REVISION_PLAN_5 "Platform": the ARM v3-wf firm-year errors against rerun 5's (x86), on the common firm-years."""
    mine = pd.read_csv(M.ROOT / "_results" / f"{name}_cfo_errors.csv", dtype={"ticker": str})
    ref = pd.read_csv(reference, dtype={"ticker": str})
    j = mine.merge(ref, on=["ticker", "year"], suffixes=("", "_ref"))
    d = (j["abs_e"] - j["abs_e_ref"]).abs()
    med = float(d.median()) if len(d) else float("nan")
    share = float((d > REPRO_LARGE).mean()) if len(d) else float("nan")
    return {
        "name": name, "n_common": int(len(j)), "n_mine": int(len(mine)), "n_reference": int(len(ref)),
        "median_abs_diff": med, "share_large": share,
        # and the ARM run must cover the reference's firm-years (a lost firm-year is not a reproduced one)
        "pass": bool(len(j) >= 0.99 * len(ref) and med <= REPRO_MEDIAN_MAX and share <= REPRO_SHARE_MAX),
    }


def main(argv: list[str]) -> None:
    pos, opt = M._opts(argv)
    limit = int(opt["limit"]) if "limit" in opt else None
    years = {int(y) for y in str(opt["cutoffs"]).split(",")} if "cutoffs" in opt else None
    cmd = pos[0]
    if cmd == "stats":
        if "dry" in opt:
            raise SystemExit("`stats --dry` is gone: pass the run's --limit / --cutoffs (one directory per run)")
        stats(limit, years)
    elif cmd == "families":  # CIK -> family of the universe from the snapshot's joint filings (WP6)
        from . import families as F

        out = M.ROOT / "_results" / "families.json"
        fam = F.build([int(k[3:]) for k in M.research_tickers()], out)
        print(json.dumps(F.summary(fam)), "->", out)
    elif cmd == "cross-spec":  # cross-spec CANDIDATE REFERENCE, e.g. v3-wf v2-pre (each after its own `stats`)
        cross_spec(pos[1], pos[2])
    elif cmd == "reproduce":  # reproduce NAME REFERENCE_CSV: REVISION_PLAN_5's platform check (exit 1 if it fails)
        res = reproduce(pos[1], Path(pos[2]))
        print(json.dumps(res))
        if not res["pass"]:
            raise SystemExit(1)
    else:
        raise SystemExit(f"unknown command {cmd}")
