# shellcheck shell=bash
# Shared by build_all.sh, resume_build.sh and full_pipeline.sh (sourced, not run).

# Run a command up to three times. A command that still fails is reported on stderr and makes retry return 1,
# so a driver can finish its loop and then exit non-zero instead of silently dropping a company.
retry() {
  for _ in 1 2 3; do
    "$@" && return 0
    sleep "${RETRY_SLEEP:-3}"
  done
  echo "FAILED: $*" >&2
  return 1
}

# Every company a dashboard build covers, one ticker per word.
all_tickers() {
  uv run python -c "from fintwin.export import SHOWCASE; from fintwin.backtest.walk_forward import UNIVERSE; from fintwin.backtest.batch import UNIVERSE_XL; print(' '.join(dict.fromkeys(SHOWCASE + UNIVERSE + UNIVERSE_XL)))"
}
