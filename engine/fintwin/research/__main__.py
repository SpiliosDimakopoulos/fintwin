"""Sharded research runs (free GitHub Actions runners, a burst server, or locally).

python -m fintwin.research prefetch                 # download every company's XBRL facts once (SEC rate limit: serial)
python -m fintwin.research shard 3 16               # shard 3 of 16 -> .cache/research/<spec>/<key>.json
python -m fintwin.research shard 0 1 --limit 300 --cutoffs 2015,2020,2022   # dry run -> .cache/research/<spec>_s300_c2015.2020.2022/
python -m fintwin.research select                   # tau / lambda walk-forward -> .cache/research/_selection/<spec>.json
python -m fintwin.research ladder 3 16 [--limit ...] # every rung of REVISION_PLAN_3 §0.2, one cache dir per rung
python -m fintwin.research stats                    # merge one spec's shards -> docs/paper/research.json (+ a copy)

The specification comes from FINTWIN_SPEC (v2-pre, v2-rev, v3) and FINTWIN_FIXES (a comma list that replaces the
spec's fixes). Each one writes to its own directory, `spec_label()` (e.g. ``v2-pre+F5+F4``), so the ladder never mixes.

The sample is the survivorship-free EDGAR universe (data/universe_edgar.csv): every non-financial US-GAAP XBRL filer
reporting in USD with $50M+ revenue in some year 2012-2024, keyed by CIK. Probabilistic forecasts, which need ETS fits
and are not about survivorship, run for S&P 500 members (today's and those of 20 February 2020) only.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import time
import warnings
from functools import lru_cache
from pathlib import Path
from typing import cast

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2] / ".cache" / "research"
DATA = Path(__file__).resolve().parents[1] / "data"
DRY_SEED = 2026
MAX_FAIL_SHARE = float(os.environ.get("FINTWIN_MAX_FAIL_SHARE", "0.10"))


# Entry points of the code that writes shards (`shard`, `ladder`, `select`, `sobol-shard`): the shard digest covers
# these files and everything they import, at any depth and also inside functions (static closure below). Analysis
# commands live in research/analysis.py, reached by name only, so a change to a statistic never makes shards stale.
SHARD_ROOTS = ("fintwin.research.__main__", "fintwin.research.experiments", "fintwin.research.assumption_sobol")


def _module_file(root: Path, mod: str) -> Path | None:
    parts = mod.split(".")[1:]
    if not parts:
        return root / "__init__.py"
    rel = Path(*parts)
    for p in (root / rel.with_suffix(".py"), root / rel / "__init__.py"):
        if p.exists():
            return p
    return None


def shard_modules() -> list[str]:
    """Static import closure of SHARD_ROOTS inside the fintwin package (module-level and function-level imports;
    each package's __init__ on the way is included)."""
    import ast

    root = Path(__file__).resolve().parents[1]
    seen: set[str] = set()
    todo = list(SHARD_ROOTS)
    while todo:
        mod = todo.pop()
        if mod in seen or _module_file(root, mod) is None:
            continue
        seen.add(mod)
        parts = mod.split(".")
        for i in range(1, len(parts)):  # importing a.b.c runs a/__init__ and a/b/__init__
            todo.append(".".join(parts[:i]))
        path = _module_file(root, mod)
        assert path is not None  # checked at the top of the loop
        pkg = parts if path.name == "__init__.py" else parts[:-1]
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                todo += [a.name for a in node.names if a.name.startswith("fintwin")]
            elif isinstance(node, ast.ImportFrom):
                base = pkg[: len(pkg) - node.level + 1] if node.level else []
                target = ".".join(base + (node.module.split(".") if node.module else []))
                if not target.startswith("fintwin"):
                    continue
                todo.append(target)
                todo += [f"{target}.{a.name}" for a in node.names]  # `from . import calibrate` imports a module
    return sorted(seen)


@lru_cache(maxsize=1)
def _code_digest() -> str:
    """Digest of the code and inputs that can change a shard: the shard modules, the committed data files
    (*.csv / *.json in fintwin/data, read on the shard path) and the snapshot."""
    root = Path(__file__).resolve().parents[1]
    files = [cast(Path, _module_file(root, m)) for m in shard_modules()]
    h = hashlib.sha256()
    for p in sorted({*files, *DATA.glob("*.csv"), *DATA.glob("*.json")}):
        h.update(p.relative_to(root).as_posix().encode())
        h.update(p.read_bytes().replace(b"\r\n", b"\n"))
    snap = root.parent / "snapshot" / "manifest.json"
    h.update(json.loads(snap.read_text(encoding="utf-8"))["digest"].encode() if snap.exists() else b"live")
    return h.hexdigest()


def analysis_digest() -> str:
    """Digest of the fintwin code outside the shard closure (statistics, export, web), recorded with each result."""
    root = Path(__file__).resolve().parents[1]
    shard = {_module_file(root, m) for m in shard_modules()}
    h = hashlib.sha256()
    for p in sorted(set(root.rglob("*.py")) - shard):
        h.update(p.relative_to(root).as_posix().encode())
        h.update(p.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()


# Switches that change how a run is executed or merged, not what a shard contains (stats bootstrap sizes, fetch policy).
RUN_ONLY_ENV = frozenset(
    {
        "FINTWIN_MAX_FAIL_SHARE",
        "FINTWIN_B",
        "FINTWIN_B_PANEL",
        "FINTWIN_B_FAMILY",
        "FINTWIN_B_LAD",
        "FINTWIN_FILL_ONLY",
        "FINTWIN_FAMILIES",
        "FINTWIN_REQUIRE_SPEC",
        "FINTWIN_NEW_RUN",
        "FINTWIN_ALLOW_DIRTY",
        "FINTWIN_ALLOW_MACHINE",
    }
)


def _env_hash(with_selection: bool = True) -> hashlib._Hash:
    h = hashlib.sha256(_code_digest().encode())
    for k in sorted(os.environ):
        # FINTWIN_SELECTION enters by content below, not by its (machine-specific) absolute path
        if k.startswith("FINTWIN_") and k not in RUN_ONLY_ENV and k != "FINTWIN_SELECTION":
            h.update(f"{k}={os.environ[k]}".encode())
    sel = os.environ.get("FINTWIN_SELECTION")
    if with_selection and sel and Path(sel).exists():
        h.update(Path(sel).read_bytes())
    return h


def stamp() -> str:
    """Hash of the code, committed inputs, data snapshot and switches that produce a shard: `stats` refuses to merge
    shards of mixed stamps, and `shard` refuses to overwrite one of another stamp unless FINTWIN_NEW_RUN=1 (a code
    change between stages would otherwise recompute a finished stage silently). A walk-forward selection table enters
    by its content, not its path."""
    return _env_hash().hexdigest()[:16]


def grid_stamp() -> str:
    """The stamp of the grid pass under the current switches (the selection table left out): a table records it, and
    the second pass refuses a table written from another grid pass."""
    return _env_hash(with_selection=False).hexdigest()[:16]


def _stamp_of(path: Path) -> str | None:
    return _meta_of(path)[0]


def _meta_of(path: Path) -> tuple[str | None, dict | None]:
    try:
        rec = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, None
    return rec.get("_stamp"), rec.get("_run")


def run_tag(limit: int | None = None, years: set[int] | None = None) -> str:
    """Directory suffix of a restricted run: every (firm sample, cutoffs) combination gets its own directory, so a
    300-firm x 3-cutoff dry run, a 40-firm probe and a 1,000-firm sample never resume into or merge with each
    other (each has the same stamp). The full run has no suffix."""
    return (f"_s{limit}" if limit is not None else "") + (
        "_c" + ".".join(str(y) for y in sorted(years)) if years else ""
    )


def run_record(limit: int | None = None, years: set[int] | None = None) -> dict:
    # the platform is part of the run: x86 and ARM differ in the last digits (B1 parity), so shards never mix
    return {"limit": limit, "cutoffs": sorted(years) if years else None, "machine": platform.machine()}


def spec_dir(tag: str = "") -> Path:
    from .experiments import spec_label

    return ROOT / (spec_label() + tag)


def selection_path(label: str | None = None, tag: str = "") -> Path:
    """The walk-forward table of one rung on one run (a sample's table comes from that sample's own shards)."""
    from .experiments import spec_label

    return ROOT / "_selection" / f"{label or spec_label()}{tag}.json"


def research_tickers() -> list[str]:
    return pd.read_csv(DATA / "universe_edgar.csv")["key"].tolist()


def dry_tickers(limit: int, seed: int = DRY_SEED) -> list[str]:
    """A fixed random sample of the universe for dry runs (the same firms in every rung and every shard count)."""
    keys = research_tickers()
    if limit >= len(keys):
        return keys
    idx = np.random.default_rng(seed).choice(len(keys), limit, replace=False)
    return [keys[i] for i in sorted(idx)]


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


def shard(i: int, n: int, limit: int | None = None, years: set[int] | None = None) -> Path:
    """Run shard i of n under the current specification. `limit` / `years` restrict the run (own directory)."""
    from ..clean import _clean
    from .experiments import company

    out_dir = spec_dir(run_tag(limit, years))
    out_dir.mkdir(parents=True, exist_ok=True)
    fc = forecast_ciks()
    st = stamp()
    keys = dry_tickers(limit) if limit is not None else research_tickers()
    run = run_record(limit, years)
    sel = os.environ.get("FINTWIN_SELECTION")
    if sel:
        made_from = json.loads(Path(sel).read_text(encoding="utf-8")).get("_grid_stamp")
        if made_from != grid_stamp():  # a table from another grid pass (an earlier code, a lost server): this pass
            # is skipped, not run on it; `select` rebuilds the table and `stats` refuses an incomplete "-wf" run
            print(f"  skip: selection table {sel} comes from another grid pass ({made_from} != {grid_stamp()})")
            return out_dir
    new_run = os.environ.get("FINTWIN_NEW_RUN") == "1"
    for k, t in enumerate(keys):
        if k % n != i:
            continue
        out = out_dir / f"{t}.json"
        old = _meta_of(out) if out.exists() else (None, None)
        if old == (st, run):  # resumable only under the same code, data, switches, run
            continue
        if old[0] is not None and not new_run:
            why = "another stamp" if old[0] != st else f"another run {old[1]}"
            raise SystemExit(f"{out} was written under {why}: set FINTWIN_NEW_RUN=1 to recompute deliberately")
        t0 = time.time()
        try:
            res = company(t, with_forecasts=int(t[3:]) in fc, years=years)
        except Exception as e:  # keep the shard going; the failure is recorded
            res = {"ticker": t, "errors": {"company": f"{type(e).__name__}: {e}"}, "failures": {}}
            res["failures"]["company"] = {"n": 1, "failed": {type(e).__name__: 1}, "skipped": {}}
        res["_stamp"] = st
        res["_run"] = run
        out.write_text(json.dumps(_clean(res)), encoding="utf-8")
        print(
            f"  {t}: {len(res.get('panel', []))} panel rows, {len(res.get('forecasts', []))} forecasts, "
            f"{len(res.get('errors', {}))} errors ({time.time() - t0:.0f}s)",
            flush=True,
        )
    return out_dir


def _shards(d: Path) -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(d.glob("*.json"))]


def check_failures(shards: list[dict], max_share: float = MAX_FAIL_SHARE) -> dict:
    """Failure counts by stage and type; refuse to build the paper numbers if any stage failed too often."""
    from .experiments import failure_summary

    summary = failure_summary(shards)
    for where, s in sorted(summary.items()):
        print(f"  {where}: {s['n']} tried, {sum(s['failed'].values())} failed {s['failed']}, skipped {s['skipped']}")
    bad = {w: s["failed_share"] for w, s in summary.items() if s["n"] >= 20 and s["failed_share"] > max_share}
    if bad:
        raise SystemExit(f"failure share above {max_share:.0%} in {bad}: inspect the shards before merging")
    return summary


def check_run(d: Path, limit: int | None = None, years: set[int] | None = None) -> list[Path]:
    """The shard files of one run, refusing an empty, stale (another stamp), mixed (another `_run`) or incomplete
    directory: `stats` and `select` both read only complete runs."""
    st, run = stamp(), run_record(limit, years)
    files = list(d.glob("*.json"))
    if not files:
        raise SystemExit(f"no shards in {d}: run the grid pass for this run first")
    stale = [p.name for p in files if _stamp_of(p) != st]
    if stale:
        raise SystemExit(f"{len(stale)} shard files were written under another stamp (e.g. {stale[:3]}): rerun them")
    other = [p.name for p in files if _meta_of(p)[1] != run]
    if other:
        raise SystemExit(f"{len(other)} shard files belong to another run than {run} (e.g. {other[:3]})")
    expected = len(dry_tickers(limit)) if limit is not None else len(research_tickers())
    if len(files) != expected:
        raise SystemExit(f"{len(files)} shards in {d}, expected {expected}: the run is incomplete")
    return files


def select(limit: int | None = None, years: set[int] | None = None) -> Path:
    """Choose tau / lambda per cutoff year from earlier years of this spec's first-pass shards (REVISION_PLAN_3 §0.1),
    on one run: a sample's selection comes from that sample's shards, and only from a complete grid pass (a table
    from a partial panel, or from none, would be stamped into the "-wf" pass without any sign of it)."""
    from .experiments import select_from_shards

    tag = run_tag(limit, years)
    d = spec_dir(tag)
    check_run(d, limit, years)
    sel = select_from_shards(d)
    skipped = {k: v for k, v in sel.items() if k.endswith("_skipped") and v}
    if skipped:  # years with enough history but too few firm-years where every grid value is finite
        rejected = selection_path(tag=tag).with_suffix(".rejected.json")  # evidence kept; never read as a table
        rejected.parent.mkdir(parents=True, exist_ok=True)
        rejected.write_text(json.dumps(sel, indent=1), encoding="utf-8")
        raise SystemExit(f"walk-forward selection skipped years {skipped}: evidence in {rejected}")
    sel["_grid_stamp"] = grid_stamp()  # the second pass checks that the table comes from this grid pass
    path = selection_path(tag=tag)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sel, indent=1), encoding="utf-8")
    print(json.dumps({k: sel.get(k) for k in ("rule", "n_rows", "tau", "lambda")}))
    return path


def ladder(i: int, n: int, extra: list[str], rungs: list[str] | None = None, tag: str = "") -> None:
    """Every rung of the ladder (and v2-rev) for shard i of n, each in a subprocess with its own environment. Rungs
    with F1 or F3 get a second pass at the walk-forward tau / lambda once `select` has written their table for
    this run (`tag`)."""
    from .experiments import LADDER

    for name, env in LADDER:
        if rungs and name not in rungs:
            continue
        e = {k: v for k, v in os.environ.items() if k not in ("FINTWIN_SPEC", "FINTWIN_FIXES", "FINTWIN_SELECTION")}
        e |= env
        print(f"== {name}", flush=True)
        subprocess.run([sys.executable, "-m", "fintwin.research", "shard", str(i), str(n), *extra], env=e, check=True)
        sel = selection_path(name, tag)
        if sel.exists():
            print(f"== {name} at the walk-forward selection", flush=True)
            subprocess.run(
                [sys.executable, "-m", "fintwin.research", "shard", str(i), str(n), *extra],
                env=e | {"FINTWIN_SELECTION": str(sel)},
                check=True,
            )


def _opts(args: list[str]) -> tuple[list[str], dict]:
    pos, opt = [], {}
    it = iter(args)
    for a in it:
        if a.startswith("--"):
            opt[a[2:]] = next(it) if a[2:] in ("limit", "cutoffs", "rungs") else True
        else:
            pos.append(a)
    return pos, opt


def main(argv: list[str]) -> None:
    pos, opt = _opts(argv)
    limit = int(opt["limit"]) if "limit" in opt else None
    years = {int(y) for y in str(opt["cutoffs"]).split(",")} if "cutoffs" in opt else None
    cmd = pos[0]
    if cmd == "prefetch":
        prefetch()
    elif cmd == "shard":
        shard(int(pos[1]), int(pos[2]), limit, years)
    elif cmd == "select":
        select(limit, years)
    elif cmd == "ladder":
        extra = [
            *(["--limit", str(limit)] if limit is not None else []),
            *(["--cutoffs", opt["cutoffs"]] if years else []),
        ]
        rungs = opt["rungs"].split(",") if "rungs" in opt else None
        ladder(int(pos[1]), int(pos[2]), extra, rungs, run_tag(limit, years))
    elif cmd == "sobol-shard":
        from .assumption_sobol import shard as sobol_shard

        sobol_shard(int(pos[1]), int(pos[2]))
    elif cmd == "sobol-stats":
        from .assumption_sobol import stats as sobol_stats

        print(json.dumps({k: v for k, v in sobol_stats().items() if k != "indices"}, default=str)[:2000])
    else:  # analysis commands (stats, cross-spec, ...): by name, outside the shard code digest
        import importlib

        importlib.import_module("fintwin.research.analysis").main(argv)


if __name__ == "__main__":
    warnings.simplefilter("ignore")
    main(sys.argv[1:])
