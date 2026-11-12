#!/usr/bin/env bash
# Revision-3 runs on a burst server (never on the shared PC), in stages of at most ~3 h (docs/review_2026-10/REV3_LIGHT_PLAN.md).
# Each stage is one `burst.py do engine "bash scripts/rev3_server.sh <stage>" --pull out --keep`; shards resume by stamp
# on the same server, and every stage leaves out/results_<stage>.tgz (also on failure) for the pull.
#   probe     snapshot check, test suite, 60-firm v3 run over all origins with per-stage timing, one Sobol firm-year
#   dry       300 firms x 2015/2020/2022, every rung, its own walk-forward selection and stats
#   universe  grid pass of the confirmatory rungs (v2-pre, v3, v2-rev) on every firm
#   sample    the descriptive ladder (+F5, +F4, +F1, +F2, with v2-pre and v3) and the legacy data layer on 1,000 firms
#   select    walk-forward tables (v3 on the universe; +F1, +F2, v3 on the sample) and the second passes
#   stats     stats of every rung on both runs (refuses mixed, stale or incomplete shard directories)
#   sobol     assumption Sobol (v3)
# Expects engine/snapshot/<tarball in manifest.json>. Logs and results go to engine/out/.
# Every stage runs on x86 (cpx42: --x86 --ram 16), the platform of the whole run; shards of another machine are refused.
# Exact commands per stage (hours, cost caps, pulls): docs/review_2026-10/RERUN5_PLAN.md section 4 (runbook).
#   lost server:  extract the last pulled archive into an EMPTY directory (never into .cache, which may hold shards of
#                 an earlier code that would be pushed and refused): mkdir R && tar -xzf out/results_<last>.tgz -C R,
#                 then `python $B up ...`, the first-stage push, and `python $B push R/research` (lands in
#                 /work/research; this script resumes from it, without its _selection and _results)
set -euo pipefail
cd "$(dirname "$0")/.."
STAGE="${1:?stage: probe|dry|universe|sample|select|stats|sobol}"
export PATH="$HOME/.local/bin:$PATH"
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null
uv sync --locked -q
N=$(nproc --all)  # before the thread pinning: GNU nproc honours OMP_NUM_THREADS and would report 1
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
export FINTWIN_REQUIRE_SPEC=1  # every research command names its spec; the tests below run without this
export SEC_USER_AGENT="${SEC_USER_AGENT:-FinTwin research spiliosdimakk@gmail.com}"
mkdir -p out
py() { uv run --quiet python "$@"; }
t0=$(date +%s)
stamp() { echo "[$STAGE $(( $(date +%s) - t0 ))s] $*" | tee -a out/timeline.log; }
pack() {  # pack what exists of .cache/{research,sobol} into out/results_<stage>.tgz, atomically (own .part + mv)
  local dirs rc=0 part="out/results_${STAGE}.tgz.part.$BASHPID"
  dirs=$(cd .cache 2>/dev/null && ls -d research sobol 2>/dev/null | tr '
' ' ')
  [ -n "$dirs" ] || return 0
  # GNU tar exits 1 when a file changed while it was read (shards keep being written): the archive is still valid,
  # and a shard caught half-written is recomputed on resume; 2 or more is a real failure
  # shellcheck disable=SC2086
  tar -czf "$part" --warning=no-file-changed --warning=no-file-shrank -C .cache $dirs 2>/dev/null || rc=$?
  if [ "$rc" -le 1 ]; then mv -f "$part" "out/results_${STAGE}.tgz"; else rm -f "$part"; return 1; fi
}
# Every 20 minutes too: a job stopped at the cost cap (or a server that dies) still leaves a recent archive for the
# partial pull; before 12-11-2026 the archive existed only after the EXIT trap, so a capped stage lost everything.
( while sleep "${PACK_EVERY:-1200}"; do pack || true; done ) &
PACKER=$!
pack_results() {  # on every exit, success or not: what exists so far goes back with the pull
  pkill -P "$PACKER" 2>/dev/null || true  # an in-flight tar of the packer must not overwrite the final archive
  kill "$PACKER" 2>/dev/null || true
  wait "$PACKER" 2>/dev/null || true
  pack || true
  rm -f out/results_"${STAGE}".tgz.part.* 2>/dev/null || true
  stamp "exit $1, results packed ($(du -h "out/results_${STAGE}.tgz" 2>/dev/null | cut -f1))"
}
trap 'pack_results $?' EXIT

SAMPLE=1000
DRY=(--limit 300 --cutoffs 2015,2020,2022)
DRY_RUNS=(v2-pre_s300_c2015.2020.2022 v2-pre+F5_s300_c2015.2020.2022 v2-pre+F5+F4_s300_c2015.2020.2022
          v2-pre+F5+F4+F1_s300_c2015.2020.2022 v2-pre+F5+F4+F1+F2_s300_c2015.2020.2022 v3_s300_c2015.2020.2022
          v2-rev_s300_c2015.2020.2022)
CONFIRM="v2-pre,v3,v2-rev"
LADDER_SAMPLE="v2-pre,v2-pre+F5,v2-pre+F5+F4,v2-pre+F5+F4+F1,v2-pre+F5+F4+F1+F2,v3"

# The data: restore only when the cache does not match the manifest (a marker file once skipped the restore on a
# fresh server and every shard failed with FrozenMiss); then the check must pass, or nothing runs.
if ! py scripts/freeze_snapshot.py verify > out/verify.log 2>&1; then
  tarball=$(py -c "import json; print(json.load(open('snapshot/manifest.json'))['tarball']['name'])")
  stamp "restore snapshot $tarball"
  py scripts/freeze_snapshot.py restore "snapshot/$tarball" > out/restore.log 2>&1
fi
py scripts/freeze_snapshot.py verify > out/verify.log 2>&1
export FINTWIN_FROZEN=1
# Shards pulled from an earlier (lost) server, pushed back as /work/research: resume from them.
# Tables and results of the lost server are not reused: `select` and `stats` rebuild them from the shards.
if [ -d /work/research ]; then
  mkdir -p .cache/research
  tar -C /work/research --exclude=./_selection --exclude=./_results -cf - . | tar -C .cache/research --skip-old-files -xf -
fi

# What ran: code digest (it enters every stamp), snapshot digest, lock file, platform; and the commit, if the PC
# wrote SOURCE.json before the push (its digest must match the code on the server).
py - "$STAGE" <<'EOF' > "out/run_meta_${STAGE}.json.tmp"
import hashlib, json, os, platform, sys
from importlib.metadata import version
from pathlib import Path
from fintwin.research.__main__ import _code_digest
src = json.loads(Path("SOURCE.json").read_text()) if Path("SOURCE.json").exists() else None
meta = {"stage": sys.argv[1], "code_digest": _code_digest(),
        "snapshot": json.loads(Path("snapshot/manifest.json").read_text())["digest"],
        "uv_lock": hashlib.sha256(Path("uv.lock").read_bytes()).hexdigest(),
        "platform": platform.platform(), "machine": platform.machine(), "nproc": os.cpu_count(), "source": src,
        "python": platform.python_version(),
        "libs": {m: version(m) for m in ("numpy", "scipy", "pandas", "statsmodels")}}
if src and src.get("code_digest") != meta["code_digest"]:
    sys.exit(f"code on the server ({meta['code_digest'][:12]}) differs from SOURCE.json ({src['code_digest'][:12]})")
if src and src.get("dirty") and os.environ.get("FINTWIN_ALLOW_DIRTY") != "1":
    sys.exit(f"SOURCE.json: uncommitted changes {src.get('dirty_files')}: commit first (or FINTWIN_ALLOW_DIRTY=1)")
if meta["machine"] != "x86_64" and os.environ.get("FINTWIN_ALLOW_MACHINE") != "1":
    sys.exit(f"machine {meta['machine']}: every stage of this run is x86_64")
# one code for every stage of a run: an earlier stage's meta on this server with another digest stops the stage
for f in sorted(Path("out").glob("run_meta_*.json")):
    if f.name == f"run_meta_{sys.argv[1]}.json":
        continue
    old = json.loads(f.read_text())
    if old.get("code_digest") != meta["code_digest"] and os.environ.get("FINTWIN_NEW_RUN") != "1":
        sys.exit(f"{f.name} ran under code {old.get('code_digest', '')[:12]}, this stage {meta['code_digest'][:12]}")
print(json.dumps(meta, indent=1))
EOF
mv -f "out/run_meta_${STAGE}.json.tmp" "out/run_meta_${STAGE}.json"  # a failed check leaves no 0-byte meta

ladder_all() {  # shard the ladder over all cores; waits for its own jobs only (the packer runs in the background)
  local pids=() rc=0
  for i in $(seq 0 $((N - 1))); do py -m fintwin.research ladder "$i" "$N" "$@" >> "out/ladder_${STAGE}_$i.log" 2>&1 & pids+=($!); done
  for j in "${pids[@]}"; do wait "$j" || rc=1; done
  return $rc
}
rung_env() {  # run a command under one rung's environment: rung_env RUNG cmd...
  py - "$@" <<'EOF'
import os, subprocess, sys
from fintwin.research.experiments import LADDER
env = {k: v for k, v in os.environ.items() if k not in ("FINTWIN_SPEC", "FINTWIN_FIXES", "FINTWIN_SELECTION")}
sys.exit(subprocess.run(sys.argv[2:], env=env | dict(LADDER)[sys.argv[1]]).returncode)
EOF
}
select_rung() {  # select_rung RUNG [--limit N] [--cutoffs ...]
  local r=$1; shift
  rung_env "$r" uv run --quiet python -m fintwin.research select "$@" >> out/select.log 2>&1
}
stats_runs() {  # stats_runs RUNGS [run options]: grid pass and, where a table exists, the walk-forward pass
  py - "$@" <<'EOF'
import os, subprocess, sys
from fintwin.research.experiments import LADDER
from fintwin.research.__main__ import _opts, run_tag, selection_path
rungs, extra = sys.argv[1].split(","), sys.argv[2:]
_, opt = _opts(extra)
tag = run_tag(int(opt["limit"]) if "limit" in opt else None,
              {int(y) for y in opt["cutoffs"].split(",")} if "cutoffs" in opt else None)
WF = {"v2-pre+F5+F4+F1", "v2-pre+F5+F4+F1+F2", "v3"}  # rungs with a walk-forward pass (F1 or F3 on)
bad = 0
for name, env in LADDER:
    if name not in rungs:
        continue
    base = {k: v for k, v in os.environ.items() if k not in ("FINTWIN_SPEC", "FINTWIN_FIXES", "FINTWIN_SELECTION")}
    passes = [base | env]
    if selection_path(name, tag).exists():
        passes.append(base | env | {"FINTWIN_SELECTION": str(selection_path(name, tag))})
    elif name in WF:  # stats before select would report the grid pass alone, silently
        bad += 1
        print(name, tag, "wf FAILED: no walk-forward table; run `select` first", flush=True)
    for e in passes:
        r = subprocess.run([sys.executable, "-m", "fintwin.research", "stats", *extra], env=e, capture_output=True, text=True)
        bad += r.returncode != 0
        print(name, tag, "wf" if "FINTWIN_SELECTION" in e else "", "ok" if r.returncode == 0 else "FAILED", r.stderr[-800:], flush=True)
sys.exit(1 if bad else 0)
EOF
}

audit() {  # audit RUN... : every shard of these runs (same tag) before the next stage; RED stops the stage
  py scripts/audit_shards.py --runs "$@" --group "$@" --out "out/audit_${STAGE}_$1.json" >> out/audit.log 2>&1 \
    || { stamp "AUDIT RED for $*: see out/audit_${STAGE}_$1.json"; exit 1; }
  stamp "audit clean: $*"
}
# Firms behind the 12-11-2026 findings (zero revenue tags, restated annuals, cash without short investments, diverged
# v3 paths): the probe runs them in v2-pre and v3 and audits the result, so every fix is checked on real data.
KNOWN_BAD="766421 818479 47217 10456 20212 1320461 911216 1648365 106040 1109357 935703 5981"
known_bad() {
  for spec in v2-pre v3; do
    FINTWIN_SPEC=$spec py - "$spec" $KNOWN_BAD <<'EOF'
import json, sys
from pathlib import Path
from fintwin.clean import _clean
from fintwin.research.experiments import company
d = Path(".cache/research") / f"_known_bad_{sys.argv[1]}"
d.mkdir(parents=True, exist_ok=True)
for c in sys.argv[2:]:
    t = f"CIK{int(c):010d}"
    try:
        r = company(t, with_forecasts=True)
    except Exception as e:  # recorded like a shard
        r = {"ticker": t, "errors": {"company": f"{type(e).__name__}: {e}"}}
    (d / f"{t}.json").write_text(json.dumps(_clean(r)), encoding="utf-8")
    print(t, len(r.get("panel", [])), "panel rows", len(r.get("errors") or {}), "errors", flush=True)
EOF
  done > out/known_bad.log 2>&1
  audit _known_bad_v2-pre _known_bad_v3
}

case "$STAGE" in
probe)
  stamp "test suite"
  # unit tests use their own fixtures, not the snapshot; test_d_repo needs the repo root, which is not pushed
  if env -u FINTWIN_FROZEN -u FINTWIN_REQUIRE_SPEC uv run --quiet python -m pytest -q -p no:cacheprovider --deselect tests/test_d_repo.py > out/tests.log 2>&1
  then stamp "tests: $(tail -1 out/tests.log)"; else stamp "TESTS FAILED: $(tail -1 out/tests.log)"; TESTS_FAILED=1; fi
  env -u FINTWIN_FROZEN -u FINTWIN_REQUIRE_SPEC uv run --quiet python -m pytest -q -p no:cacheprovider -vv tests/test_B1_parity.py > out/tests_B1.log 2>&1 || true
  stamp "probe: 60 firms, v3, all origins"
  ladder_all --limit 60 --rungs v3
  stamp "probe: one Sobol firm-year"
  FINTWIN_SPEC=v3 py - > out/probe_sobol.log 2>&1 <<'EOF'
import time
from fintwin.research import assumption_sobol as AS
X = AS.points()
for key, year in AS.sample():
    try:
        ok = isinstance(AS._one(key, year, None), dict)
    except Exception as e:  # a failing candidate is skipped, as the Sobol stage does
        print({"key": key, "year": year, "error": f"{type(e).__name__}: {e}"}); ok = False
    if ok:
        t = time.perf_counter(); AS._one(key, year, X)
        print({"key": key, "year": year, "design_points": len(X), "seconds": round(time.perf_counter() - t, 1)})
        break
EOF
  audit v3_s60
  stamp "probe: known-bad firms in v2-pre and v3"
  known_bad
  [ -z "${TESTS_FAILED:-}" ] || { stamp "probe failed: the test suite did not pass"; exit 1; }
  stamp "probe done"
  ;;
dry)
  stamp "dry ladder: 300 firms x 2015/2020/2022, grid pass"
  ladder_all "${DRY[@]}"
  audit "${DRY_RUNS[@]}"
  stamp "dry walk-forward tables and second pass"
  for r in v2-pre+F5+F4+F1 v2-pre+F5+F4+F1+F2 v3; do select_rung "$r" "${DRY[@]}"; done
  ladder_all "${DRY[@]}"
  stamp "dry stats"
  audit v3-wf_s300_c2015.2020.2022 v2-pre+F5+F4+F1-wf_s300_c2015.2020.2022 v2-pre+F5+F4+F1+F2-wf_s300_c2015.2020.2022
  FINTWIN_B_FAMILY=500 stats_runs "$LADDER_SAMPLE,v2-rev" "${DRY[@]}" > out/stats_dry.log 2>&1
  # the whole stats stage in small: the confirmatory v3 vs v2-pre test and the family pass
  py -m fintwin.research cross-spec v3-wf_s300_c2015.2020.2022 v2-pre_s300_c2015.2020.2022 >> out/stats_dry.log 2>&1
  py -m fintwin.research families >> out/stats_dry.log 2>&1
  FINTWIN_B_FAMILY=500 FINTWIN_FAMILIES="$PWD/.cache/research/_results/families.json" \
    stats_runs "$CONFIRM" "${DRY[@]}" >> out/stats_dry.log 2>&1
  stamp "dry done"
  ;;
universe)
  stamp "universe grid pass: $CONFIRM"
  ladder_all --rungs "$CONFIRM"
  audit v2-pre v3 v2-rev
  ;;
sample)
  stamp "sample ladder ($SAMPLE firms): $LADDER_SAMPLE"
  ladder_all --limit "$SAMPLE" --rungs "$LADDER_SAMPLE"
  stamp "sample: legacy data layer, v2-pre"
  FINTWIN_DATA_LEGACY=1 ladder_all --limit "$SAMPLE" --rungs v2-pre
  audit v2-pre_s1000 v2-pre+F5_s1000 v2-pre+F5+F4_s1000 v2-pre+F5+F4+F1_s1000 v2-pre+F5+F4+F1+F2_s1000 v3_s1000
  audit v2-pre-legacydata_s1000
  ;;
select)
  stamp "walk-forward tables"
  select_rung v3
  for r in v2-pre+F5+F4+F1 v2-pre+F5+F4+F1+F2 v3; do select_rung "$r" --limit "$SAMPLE"; done
  stamp "second pass: universe v3, sample +F1 / +F2 / v3"
  ladder_all --rungs v3
  ladder_all --limit "$SAMPLE" --rungs v2-pre+F5+F4+F1,v2-pre+F5+F4+F1+F2,v3
  audit v3-wf v2-pre
  audit v3-wf_s1000 v2-pre+F5+F4+F1-wf_s1000 v2-pre+F5+F4+F1+F2-wf_s1000
  ;;
stats)
  stamp "stats"
  # every group runs even if an earlier one failed (set -e would stop at the first), and the stage fails at the end
  rc=0
  stats_runs "$CONFIRM" > out/stats.log 2>&1 || rc=1
  # the pre-specified confirmatory test v3 vs v2-pre (walk-forward v3; the grid pass beside it), from the error files
  # each `stats` above wrote after its stamp check
  py -m fintwin.research cross-spec v3-wf v2-pre >> out/stats.log 2>&1 || rc=1
  py -m fintwin.research cross-spec v3 v2-pre >> out/stats.log 2>&1 || rc=1
  # robustness after the pre-specification (WP6): corporate families as the resampling unit, one bankruptcy per
  # family and cutoff, on the confirmatory rungs and the confirmatory v3 vs v2-pre test
  py -m fintwin.research families >> out/stats.log 2>&1 || rc=1
  FINTWIN_FAMILIES="$PWD/.cache/research/_results/families.json" stats_runs "$CONFIRM" >> out/stats.log 2>&1 || rc=1
  py -m fintwin.research cross-spec v3-wf_family v2-pre_family >> out/stats.log 2>&1 || rc=1
  stats_runs "$LADDER_SAMPLE" --limit "$SAMPLE" >> out/stats.log 2>&1 || rc=1
  FINTWIN_DATA_LEGACY=1 FINTWIN_SPEC=v2-pre py -m fintwin.research stats --limit "$SAMPLE" >> out/stats.log 2>&1 || rc=1
  [ "$rc" = 0 ] || { stamp "a stats group failed: see out/stats.log"; exit 1; }
  ;;
sobol)
  stamp "Sobol (v3): firm-year set"
  FINTWIN_SPEC=v3 py -c "from fintwin.research.assumption_sobol import eligible; k, f, e = eligible(); print(len(k), f, e)" > out/sobol_eligible.log 2>&1
  stamp "Sobol (v3): design points"
  pids=(); rc=0
  for i in $(seq 0 $((N - 1))); do FINTWIN_SPEC=v3 py -m fintwin.research sobol-shard "$i" "$N" > "out/sobol_$i.log" 2>&1 & pids+=($!); done
  for j in "${pids[@]}"; do wait "$j" || rc=1; done
  [ "$rc" = 0 ] || { stamp "a Sobol shard failed: see out/sobol_*.log"; exit 1; }
  FINTWIN_SPEC=v3 py -m fintwin.research sobol-stats > out/sobol_stats.log 2>&1
  ;;
*) echo "unknown stage $STAGE"; exit 2 ;;
esac
stamp "$STAGE done"
