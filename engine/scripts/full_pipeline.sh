#!/usr/bin/env bash
# Everything, memory-friendly: rolling validation (2 workers) -> aggregate -> all company snapshots -> goldens -> backtests.
set -uo pipefail
cd "$(dirname "$0")/.."
. scripts/lib.sh
export OPENBLAS_NUM_THREADS=1 PYTHONWARNINGS=ignore
mkdir -p .cache/batch   # resumable: existing results are kept
L=$(uv run python -c "from fintwin.backtest.batch import UNIVERSE_XL; print(' '.join(dict.fromkeys(UNIVERSE_XL)))")
R=$(printf '%s\n' $L | tac | tr '\n' ' ')
# returns 1 if a company still fails after three attempts
work() {
  local t rc=0
  for t in $1; do
    [ -f ".cache/batch/$t.json" ] && continue
    RETRY_SLEEP=5 retry uv run python -m fintwin.backtest.batch "$t" || rc=1
  done
  return $rc
}
work "$L" > .cache/validate.log 2>&1 &
work "$R" > .cache/validate2.log 2>&1
wait
# a second pass picks up anything a worker dropped; what still fails here is a real failure
work "$L" >> .cache/validate.log 2>&1 || { echo "validation failed for some companies, see .cache/validate.log" >&2; exit 1; }
echo "== validation aggregate"; uv run python -m fintwin.backtest.batch --aggregate
touch .cache/build_started
echo "== company snapshots"; bash scripts/resume_build.sh .cache/build_started > .cache/build.log 2>&1 || build_rc=1
grep -c "health" .cache/build.log; grep -E "FAILED|Traceback" .cache/build.log | tail -5
echo "== pipeline done"
exit "${build_rc:-0}"
