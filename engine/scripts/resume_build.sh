#!/usr/bin/env bash
# Rebuild the dashboard data files. One company per Python process keeps peak memory low.
#   resume_build.sh [REF]   only companies whose snapshot is older than REF (default .cache/build_started),
#                           to resume an interrupted build
#   resume_build.sh --all   every company
# Exits 1 if any company still failed after three attempts; the other steps still run.
set -uo pipefail
cd "$(dirname "$0")/.."
. scripts/lib.sh
export OPENBLAS_NUM_THREADS=1 PYTHONWARNINGS=ignore
REF=${1:-.cache/build_started}
failed=()
for t in $(all_tickers); do
  f="../web/public/data/companies/$t.json"
  [ "$REF" != "--all" ] && [ -f "$f" ] && [ "$f" -nt "$REF" ] && continue
  RETRY_SLEEP=5 retry uv run python -m fintwin.export "$t" || failed+=("$t")
done
uv run python -m fintwin.export GOLDEN || failed+=(GOLDEN)
uv run python -m fintwin.export BACKTEST || failed+=(BACKTEST)
uv run python -m fintwin.notes || failed+=(notes)
if [ ${#failed[@]} -gt 0 ]; then
  echo "FAILED steps: ${failed[*]}" >&2
  exit 1
fi
