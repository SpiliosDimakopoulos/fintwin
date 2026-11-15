#!/usr/bin/env bash
# REVISION_PLAN_4 simulation runs (P4-1 unconditional, P4-8 real-time regime 2021) on a burst server, under the exact
# code of the plan-3 full run (commit 77f3b7f, shard digest 9f7e4114b07a) plus fintwin/research/plan4_run.py.
# The snapshot is pushed separately to /work/snapshot. Results: out/results_p4.tgz (also on failure).
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null
uv sync --locked -q
N=$(nproc --all)
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
mkdir -p out
py() { uv run --quiet python "$@"; }
t0=$(date +%s)
stamp() { echo "[p4 $(( $(date +%s) - t0 ))s] $*" | tee -a out/timeline.log; }
pack() {
  [ -d .cache/research/p4 ] || [ -d .cache/research/p4_s50 ] || return 0
  local rc=0 part="out/results_p4.tgz.part.$BASHPID"
  tar -czf "$part" --warning=no-file-changed -C .cache $(cd .cache && ls -d research/p4 research/p4_s50 2>/dev/null) 2>/dev/null || rc=$?
  if [ "$rc" -le 1 ]; then mv -f "$part" out/results_p4.tgz; else rm -f "$part"; fi
}
( while sleep 1200; do pack || true; done ) &
PACKER=$!
trap 'kill $PACKER 2>/dev/null || true; pack || true; stamp "exit, packed $(du -h out/results_p4.tgz 2>/dev/null | cut -f1)"' EXIT

# the frozen data: the tarball named in the manifest, from /work/snapshot
tarball=$(py -c "import json; print(json.load(open('snapshot/manifest.json'))['tarball']['name'])")
ln -sfn "/work/snapshot/$tarball" "snapshot/$tarball"
if ! py scripts/freeze_snapshot.py verify > out/verify.log 2>&1; then
  stamp "restore snapshot $tarball"
  py scripts/freeze_snapshot.py restore "snapshot/$tarball" > out/restore.log 2>&1
fi
py scripts/freeze_snapshot.py verify > out/verify.log 2>&1
export FINTWIN_FROZEN=1 FINTWIN_REQUIRE_SPEC=1 FINTWIN_SPEC=v3
export FINTWIN_SELECTION="$PWD/p4_inputs/research/_selection/v3.json"
py - > out/run_meta_p4.json <<'EOF'
import json, platform, os
from fintwin.research.__main__ import _code_digest
from fintwin.research.experiments import spec_record
d = _code_digest()
assert d.startswith("9f7e4114b07a"), f"shard code digest {d[:12]} is not the plan-3 run's 9f7e4114b07a"
assert spec_record()["selection"] == "d20049b4d5b431d8", spec_record()
print(json.dumps({"code_digest": d, "spec": spec_record(), "machine": platform.machine(), "nproc": os.cpu_count(),
                  "platform": platform.platform()}, indent=1))
EOF
[ "$(uname -m)" = "x86_64" ] || { stamp "not x86_64: the plan-3 run was x86"; exit 1; }

run_all() {
  local pids=() rc=0
  for i in $(seq 0 $((N - 1))); do py -m fintwin.research.plan4_run "$i" "$N" "$@" >> "out/p4_$i.log" 2>&1 & pids+=($!); done
  for j in "${pids[@]}"; do wait "$j" || rc=1; done
  return $rc
}
stamp "dry: 50 firms (runs only; counts, errors, units)"
run_all --limit 50
py - >> out/timeline.log <<'EOF'
import json, glob
rows = errs = 0
for f in glob.glob(".cache/research/p4_s50/*.json"):
    d = json.load(open(f)); rows += len(d["rows"]); errs += len(d["errors"])
print(f"dry: {rows} rows, {errs} errors")
EOF
stamp "full: every firm"
run_all
stamp "simulations done: $(ls .cache/research/p4 | wc -l) firms"
pack || true
stamp "analysis: plan-3 shards"
tar -xzf /work/stats_in/results_stats.tgz -C .cache
stamp "analysis: plan4 statistics"
py -m fintwin.research.plan4 .cache out/plan4.json > out/plan4.log 2>&1 || { stamp "plan4 FAILED: $(tail -3 out/plan4.log)"; exit 1; }
stamp "p4 done"
