#!/usr/bin/env bash
# Revision plan 5 runs on a burst server (never on the shared PC), one stage per `burst.py do engine
# "bash scripts/p5_server.sh <stage>" --keep`; every stage leaves out/results_<stage>.tgz (also on failure).
#   probe      snapshot check, full test suite, D4 text probe, 60 firms in v3-wf / v4a / v4b, known-bad firms
#   text       filings filed by each cutoff (SEC, rate-limited), text snapshot, T1 features and dated embeddings
#   dry        the whole ladder on 300 firms x 2015/2020/2022, with its own pool table, selection and text table
#   universe   v3-wf (reproduction check against rerun 5), v4a, v4b on every firm
#   pool       pool table from v4b, v4p grid pass, walk-forward selection, v4p-wf
#   texttable  T2 ridge table from v4p-wf, then v4t
#   sample     side results on 1,000 firms: G3 cash 30% / 45%, pool-only, G6 hindsight, text placebo and control
#   stats      stats of every rung and the plan-5 comparisons (cross-spec), from the shards
# Platform: x86 (Hetzner cpx, --x86 --ram 16) for every stage, v3-wf included (REVISION_PLAN_5 addendum 2). The SEC contact comes
# from engine/.env (SEC_USER_AGENT), never from this file.
set -euo pipefail
cd "$(dirname "$0")/.."
STAGE="${1:?stage: probe|text|dry|universe|pool|texttable|sample|stats}"
export PATH="$HOME/.local/bin:$PATH"
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null
uv sync --locked -q --extra text
N=$(nproc --all)
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
export FINTWIN_REQUIRE_SPEC=1
[ -f .env ] && set -a && . ./.env && set +a
mkdir -p out
py() { uv run --quiet python "$@"; }
t0=$(date +%s)
stamp() { echo "[$STAGE $(( $(date +%s) - t0 ))s] $*" | tee -a out/timeline.log; }
pack() {
  local dirs rc=0 part="out/results_${STAGE}.tgz.part.$BASHPID"
  dirs=$(cd .cache 2>/dev/null && ls -d research text p5text 2>/dev/null | tr '\n' ' ')
  [ -n "$dirs" ] || return 0
  # shellcheck disable=SC2086
  tar -czf "$part" --warning=no-file-changed --warning=no-file-shrank -C .cache $dirs 2>/dev/null || rc=$?
  if [ "$rc" -le 1 ]; then mv -f "$part" "out/results_${STAGE}.tgz"; else rm -f "$part"; return 1; fi
}
( while sleep "${PACK_EVERY:-1200}"; do pack || true; done ) &
PACKER=$!
pack_results() {
  pkill -P "$PACKER" 2>/dev/null || true; kill "$PACKER" 2>/dev/null || true; wait "$PACKER" 2>/dev/null || true
  pack || true
  rm -f out/results_"${STAGE}".tgz.part.* 2>/dev/null || true
  stamp "exit $1, results packed ($(du -h "out/results_${STAGE}.tgz" 2>/dev/null | cut -f1))"
}
trap 'pack_results $?' EXIT

SAMPLE=1000
DRY=(--limit 300 --cutoffs 2015,2020,2022)
DRYTAG=_s300_c2015.2020.2022
export FINTWIN_TEXT="$PWD/.cache/p5text"
SEL_V3="$PWD/p5_inputs/v3_selection.json"   # rerun 5's table (digest d20049b4d5b431d8): v3-wf, v4a, v4b, v4t keep it

if ! py scripts/freeze_snapshot.py verify > out/verify.log 2>&1; then
  tarball=$(py -c "import json; print(json.load(open('snapshot/manifest.json'))['tarball']['name'])")
  stamp "restore snapshot $tarball"
  py scripts/freeze_snapshot.py restore "snapshot/$tarball" > out/restore.log 2>&1
fi
py scripts/freeze_snapshot.py verify > out/verify.log 2>&1
export FINTWIN_FROZEN=1
if [ -d /work/research ]; then
  mkdir -p .cache/research
  tar -C /work/research --exclude=./_selection --exclude=./_results -cf - . | tar -C .cache/research --skip-old-files -xf -
fi

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
    sys.exit(f"SOURCE.json: uncommitted changes {src.get('dirty_files')}: commit first")
if meta["machine"] != "x86_64":  # addendum 2: no ARM capacity for 20 h, so the run is x86 (rerun 5's platform)
    sys.exit(f"machine {meta['machine']}: every stage of the plan-5 run is x86_64")
for f in sorted(Path("out").glob("run_meta_*.json")):
    if f.name == f"run_meta_{sys.argv[1]}.json":
        continue
    old = json.loads(f.read_text())
    if old.get("code_digest") != meta["code_digest"] and os.environ.get("FINTWIN_NEW_RUN") != "1":
        sys.exit(f"{f.name} ran under code {old.get('code_digest', '')[:12]}, this stage {meta['code_digest'][:12]}")
print(json.dumps(meta, indent=1))
EOF
mv -f "out/run_meta_${STAGE}.json.tmp" "out/run_meta_${STAGE}.json"

# rung RUNG [run options]: shard one rung over all cores with its tables (selection, pool, text) as the plan says
rung() {
  local r=$1; shift
  local env; mapfile -t env < <(rung_env "$r") || return 1
  [ "${#env[@]}" -gt 0 ] || { stamp "no environment for rung $r"; return 1; }
  local pids=() rc=0
  for i in $(seq 0 $((N - 1))); do
    env "${env[@]}" uv run --quiet python -m fintwin.research shard "$i" "$N" "$@" >> "out/shard_${STAGE}_${r}_$i.log" 2>&1 & pids+=($!)
  done
  for j in "${pids[@]}"; do wait "$j" || rc=1; done
  return $rc
}
digest() { py -c "import sys; from fintwin.research.__main__ import _table_digest; print(_table_digest(sys.argv[1]))" "$1"; }
rung_env() {  # rung_env RUNG: the environment of a rung, one assignment per line (empty output = error)
  local r=$1 spec=${1%%+*} env=()
  [ "$r" = v4p-wf ] && spec=v4p
  env+=(FINTWIN_SPEC="$spec")
  case "$r" in  # selection: v3's pre-specified table (accepted by its digest), or v4p's own walk-forward table
    v3|v4a|v4b|v4a+cash*) env+=(FINTWIN_SELECTION="$SEL_V3" FINTWIN_SELECTION_DIGEST="$SEL_V3_DIGEST") ;;
    v4p-wf) env+=(FINTWIN_SELECTION="$SEL_V4P") ;;
    v4t) env+=(FINTWIN_SELECTION="$SEL_V4P" FINTWIN_SELECTION_DIGEST="$(digest "$SEL_V4P")") ;;
  esac
  case "$r" in v4a+cash30) env+=(FINTWIN_CASH_TARGET=0.30) ;; v4a+cash45) env+=(FINTWIN_CASH_TARGET=0.45) ;; esac
  case "$r" in v4p|v4p-wf|v4t)
    [ -f "$POOL" ] || { echo "rung $r: no pool table $POOL" >&2; return 1; }
    env+=(FINTWIN_POOL="$POOL") ;;
  esac
  printf '%s\n' "${env[@]}"
}
stats_rung() {  # stats_rung RUNG [run options]: `stats` of one rung (writes its _results/<label>_cfo_errors.csv)
  local r=$1; shift
  local e; mapfile -t e < <(rung_env "$r") || return 1
  env "${e[@]}" uv run --quiet python -m fintwin.research stats "$@" >> out/stats.log 2>&1
}
audit() {
  py scripts/audit_shards.py --runs "$@" --group "$@" --out "out/audit_${STAGE}_$1.json" >> out/audit.log 2>&1 \
    || { stamp "AUDIT RED for $*: see out/audit_${STAGE}_$1.json"; exit 1; }
  stamp "audit clean: $*"
}
KNOWN_BAD="766421 818479 47217 10456 20212 1320461 911216 1648365 106040 1109357 935703 5981"
known_bad() {
  for spec in v3 v4a v4b; do
    FINTWIN_SPEC=$spec FINTWIN_SELECTION="$SEL_V3" FINTWIN_SELECTION_DIGEST="$SEL_V3_DIGEST" \
      py scripts/known_bad.py "$spec" $KNOWN_BAD
  done > out/known_bad.log 2>&1
  audit _known_bad_v3 _known_bad_v4a _known_bad_v4b
}
text_all() {  # text_all CMD [options]: the text driver over all cores (features only; fetch is one process)
  local pids=() rc=0
  for i in $(seq 0 $((N - 1))); do py scripts/text_build.py "$1" "$i" "$N" "${@:2}" >> "out/text_${1}_$i.log" 2>&1 & pids+=($!); done
  for j in "${pids[@]}"; do wait "$j" || rc=1; done
  return $rc
}
pool_and_select() {  # pool_and_select TAG [run options]: pool table from v4b-wf, v4p grid pass, v4p selection, v4p-wf
  local tag=$1; shift
  FINTWIN_SPEC=v4b FINTWIN_SELECTION="$SEL_V3" FINTWIN_SELECTION_DIGEST="$SEL_V3_DIGEST" \
    py -m fintwin.research pool "$@" >> out/pool.log 2>&1
  POOL="$PWD/.cache/research/_selection/pool_v4b-wf$tag.json"
  rung v4p "$@"
  audit "v4p$tag"
  FINTWIN_SPEC=v4p FINTWIN_POOL="$POOL" py -m fintwin.research select "$@" >> out/select.log 2>&1
  SEL_V4P="$PWD/.cache/research/_selection/v4p$tag.json"
  rung v4p-wf "$@"
  audit "v4p-wf$tag"
}
text_and_v4t() {  # text_and_v4t TAG [run options]: T2 ridge table from v4p-wf, then v4t
  local tag=$1; shift
  FINTWIN_SPEC=v4p FINTWIN_POOL="$POOL" FINTWIN_SELECTION="$SEL_V4P" py -m fintwin.research text-table "$@" >> out/texttable.log 2>&1
  rung v4t "$@"
  audit "v4t-wf$tag"
}
tables() {  # the full run's tables, for the stages after `pool`
  POOL="$PWD/.cache/research/_selection/pool_v4b-wf.json"; SEL_V4P="$PWD/.cache/research/_selection/v4p.json"
}
SEL_V3_DIGEST=d20049b4d5b431d8
[ "$(digest "$SEL_V3")" = "$SEL_V3_DIGEST" ] || { stamp "v3 selection table is not $SEL_V3_DIGEST"; exit 1; }
POOL=""; SEL_V4P=""

case "$STAGE" in
probe)
  stamp "test suite"
  if env -u FINTWIN_FROZEN -u FINTWIN_REQUIRE_SPEC uv run --quiet python -m pytest -q -p no:cacheprovider --deselect tests/test_d_repo.py > out/tests.log 2>&1
  then stamp "tests: $(tail -1 out/tests.log)"; else stamp "TESTS FAILED: $(tail -1 out/tests.log)"; TESTS_FAILED=1; fi
  stamp "D4 text probe (vintages, attention, speed)"
  py scripts/text_probe.py --total-sections 2000000 > out/text_probe.log 2>&1 || stamp "TEXT PROBE FAILED: see out/text_probe.log"
  stamp "60 firms: v3-wf, v4a, v4b"
  rung v3 --limit 60; rung v4a --limit 60; rung v4b --limit 60
  audit v3-wf_s60 v4a-wf_s60 v4b-wf_s60
  known_bad
  [ -z "${TESTS_FAILED:-}" ] || { stamp "probe failed: the test suite did not pass"; exit 1; }
  ;;
text)
  [ -n "${SEC_USER_AGENT:-}" ] || { stamp "SEC_USER_AGENT missing (engine/.env): the SEC requires a contact"; exit 2; }
  stamp "filings by cutoff (SEC, one process, stops at a 403)"
  env -u FINTWIN_FROZEN uv run --quiet python scripts/text_build.py fetch > out/text_fetch.log 2>&1
  stamp "text snapshot"; py scripts/text_build.py freeze > out/text_freeze.log 2>&1
  cp snapshot/text/manifest.json out/text_manifest.json 2>/dev/null || true
  stamp "T1 features and dated embeddings"; text_all features
  stamp "placebo and vintage control (sample)"
  text_all features --limit "$SAMPLE" --masked; text_all features --limit "$SAMPLE" --vintage-control
  ;;
dry)
  export FINTWIN_TEXT_MIN_TRAIN=50  # the dry run's few training firm-years still exercise the T2 path
  stamp "dry ladder"
  rung v3 "${DRY[@]}"; rung v4a "${DRY[@]}"; rung v4b "${DRY[@]}"
  audit "v3-wf$DRYTAG" "v4a-wf$DRYTAG" "v4b-wf$DRYTAG"
  pool_and_select "$DRYTAG" "${DRY[@]}"
  text_and_v4t "$DRYTAG" "${DRY[@]}"
  stamp "dry stats"
  for r in v3 v4a v4b v4p-wf v4t; do stats_rung "$r" "${DRY[@]}" || { stamp "dry stats $r FAILED"; exit 1; }; done
  for pair in "v4a-wf v3-wf" "v4b-wf v4a-wf" "v4p-wf v4b-wf" "v4t-wf v4p-wf"; do
    set -- $pair
    py -m fintwin.research cross-spec "$1$DRYTAG" "$2$DRYTAG" >> out/stats.log 2>&1 || { stamp "dry cross-spec $pair FAILED"; exit 1; }
  done
  rm -f "$FINTWIN_TEXT/table.json"  # the dry table must never reach the full run
  ;;
universe)
  rung v3; rung v4a; rung v4b
  audit v3-wf v4a-wf v4b-wf
  stamp "reproduction check: v3-wf on ARM against rerun 5"
  stats_rung v3
  py -m fintwin.research reproduce v3-wf p5_inputs/v3-wf_cfo_errors.csv >> out/repro.log 2>&1 \
    || { stamp "REPRODUCTION FAILED: see out/repro.log (REVISION_PLAN_5 stops here)"; exit 1; }
  ;;
pool)
  pool_and_select ""
  ;;
texttable)
  tables; text_and_v4t ""
  ;;
sample)
  tables
  rung v4a+cash30 --limit "$SAMPLE"; rung v4a+cash45 --limit "$SAMPLE"
  FINTWIN_MA_HINDSIGHT=1 rung v4b --limit "$SAMPLE"
  FINTWIN_POOL_ONLY=1 rung v4p-wf --limit "$SAMPLE"
  for ctl in masked v2024; do  # ridge on the full v4p-wf labels, embeddings of the sample's firm-years only
    FINTWIN_TEXT="$FINTWIN_TEXT/$ctl" FINTWIN_SPEC=v4p FINTWIN_POOL="$POOL" FINTWIN_SELECTION="$SEL_V4P" \
      py -m fintwin.research text-table >> "out/texttable_$ctl.log" 2>&1
    FINTWIN_TEXT="$FINTWIN_TEXT/$ctl" FINTWIN_TEXT_VARIANT="$ctl" rung v4t --limit "$SAMPLE"
  done
  ;;
stats)
  tables; rc=0
  rm -f .cache/research/_results/*_cfo_errors.csv .cache/research/_results/cross_spec_*.json
  for r in v3 v4a v4b v4p-wf v4t; do stats_rung "$r" || rc=1; done
  for r in v4a+cash30 v4a+cash45; do stats_rung "$r" --limit "$SAMPLE" || rc=1; done
  FINTWIN_MA_HINDSIGHT=1 stats_rung v4b --limit "$SAMPLE" || rc=1
  FINTWIN_POOL_ONLY=1 stats_rung v4p-wf --limit "$SAMPLE" || rc=1
  for ctl in masked v2024; do
    FINTWIN_TEXT="$FINTWIN_TEXT/$ctl" FINTWIN_TEXT_VARIANT="$ctl" stats_rung v4t --limit "$SAMPLE" || rc=1
  done
  for pair in "v4a-wf v3-wf" "v4b-wf v4a-wf" "v4p-wf v4b-wf" "v4t-wf v4p-wf"; do
    set -- $pair
    py -m fintwin.research cross-spec "$1" "$2" >> out/stats.log 2>&1 || rc=1
  done
  [ "$rc" = 0 ] || { stamp "a stats group failed: see out/stats.log"; exit 1; }
  ;;
*) echo "unknown stage $STAGE"; exit 2 ;;
esac
stamp "$STAGE done"
