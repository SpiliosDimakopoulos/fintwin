#!/usr/bin/env bash
# Revision-3 runs on a burst server (never on the shared PC).
#   scripts/rev3_server.sh dry    restore + top up the snapshot, regenerate the universe, full test suite, dry ladder
#   scripts/rev3_server.sh full   full ladder with the walk-forward pass, stats per rung, legacy-data check, Sobol
# Expects engine/snapshot/fintwin_snapshot_*.tar (+ manifest.json). Logs and results go to engine/out/.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null
uv sync --locked -q
N=$(nproc --all)  # before the thread pinning: GNU nproc honours OMP_NUM_THREADS and would report 1
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
export SEC_USER_AGENT="${SEC_USER_AGENT:-FinTwin research spiliosdimakk@gmail.com}"
mkdir -p out
py() { uv run --quiet python "$@"; }
t0=$(date +%s)
stamp() { echo "[$(( $(date +%s) - t0 ))s] $*" | tee -a out/timeline.log; }

if [ ! -f snapshot/.topped_up ]; then
  stamp "restore snapshot"
  py scripts/freeze_snapshot.py restore "$(ls snapshot/fintwin_snapshot_*.tar | head -1)" > out/restore.log
  stamp "regenerate universe (D12), fetching only missing files"
  FINTWIN_FILL_ONLY=1 py -m fintwin.data.edgar_universe > out/universe.log 2>&1
  stamp "top up facts and filings for the (new) universe"
  FINTWIN_FILL_ONLY=1 py -m fintwin.research prefetch > out/topup.log 2>&1
  FINTWIN_FILL_ONLY=1 py scripts/freeze_snapshot.py fred >> out/topup.log 2>&1
  py scripts/freeze_snapshot.py pack > out/pack.log
  touch snapshot/.topped_up
  stamp "snapshot: $(tail -1 out/pack.log)"
fi
export FINTWIN_FROZEN=1

ladder_all() {  # shard the whole ladder over all cores
  for i in $(seq 0 $((N - 1))); do py -m fintwin.research ladder "$i" "$N" "$@" > "out/ladder_$i.log" 2>&1 & done
  wait
}
stats_all() {  # stats for every rung (and its walk-forward pass), each with its own environment
  py - "$@" <<'EOF'
import json, os, subprocess, sys
from fintwin.research.experiments import LADDER
from fintwin.research.__main__ import selection_path
extra = sys.argv[1:]
for name, env in LADDER:
    base = {k: v for k, v in os.environ.items() if k not in ("FINTWIN_SPEC", "FINTWIN_FIXES", "FINTWIN_SELECTION")}
    passes = [base | env]
    if selection_path(name).exists():
        passes.append(base | env | {"FINTWIN_SELECTION": str(selection_path(name))})
    for e in passes:
        r = subprocess.run([sys.executable, "-m", "fintwin.research", "stats", *extra], env=e, capture_output=True, text=True)
        print(name, "wf" if "FINTWIN_SELECTION" in e else "", "ok" if r.returncode == 0 else "FAILED", r.stderr[-800:], flush=True)
EOF
}

case "${1:-dry}" in
dry)
  stamp "full test suite"
  # unit tests use their own fixtures, not the snapshot; test_d_repo needs the repo root, which is not pushed
  if env -u FINTWIN_FROZEN uv run --quiet python -m pytest -q -p no:cacheprovider --deselect tests/test_d_repo.py > out/tests.log 2>&1; then stamp "tests: $(tail -1 out/tests.log)"; else stamp "TESTS FAILED: $(tail -1 out/tests.log)"; fi
  stamp "dry ladder: 300 firms x 2015/2020/2022"
  ladder_all --limit 300 --cutoffs 2015,2020,2022
  stamp "dry stats"
  FINTWIN_B_FAMILY=500 stats_all --dry > out/stats_dry.log 2>&1
  stamp "done"
  ;;
full)
  stamp "full ladder, grid pass"
  ladder_all
  stamp "walk-forward selection"
  for rung in v2-pre+F5+F4+F1 v2-pre+F5+F4+F1+F2 v3; do
    py - "$rung" <<'EOF' >> out/select.log 2>&1
import os, subprocess, sys
from fintwin.research.experiments import LADDER
env = dict(LADDER)[sys.argv[1]]
subprocess.run([sys.executable, "-m", "fintwin.research", "select"], env={**os.environ, **env}, check=True)
EOF
  done
  stamp "full ladder, walk-forward pass"
  ladder_all
  stamp "legacy data layer, v2-pre"
  FINTWIN_DATA_LEGACY=1 ladder_all --rungs v2-pre
  stamp "stats"
  stats_all > out/stats.log 2>&1
  FINTWIN_DATA_LEGACY=1 FINTWIN_SPEC=v2-pre py -m fintwin.research stats >> out/stats.log 2>&1 || true
  stamp "Sobol (v3)"
  for i in $(seq 0 $((N - 1))); do FINTWIN_SPEC=v3 py -m fintwin.research sobol-shard "$i" "$N" > "out/sobol_$i.log" 2>&1 & done
  wait
  FINTWIN_SPEC=v3 py -m fintwin.research sobol-stats > out/sobol_stats.log 2>&1
  stamp "done"
  ;;
esac
tar -cf out/results.tar -C .cache research sobol 2>/dev/null || true
