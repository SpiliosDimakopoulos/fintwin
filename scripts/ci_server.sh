#!/usr/bin/env bash
# Full CI (engine pytest + web npm test/build) on a burst server; logs to ci_out/.
set -u
mkdir -p ci_out
command -v uv >/dev/null || { curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1; export PATH="$HOME/.local/bin:$PATH"; }
if ! command -v node >/dev/null || [ "$(node -v | cut -c2- | cut -d. -f1)" -lt 22 ]; then
  arch=$(uname -m); [ "$arch" = aarch64 ] && a=arm64 || a=x64
  curl -fsSL "https://nodejs.org/dist/v22.11.0/node-v22.11.0-linux-$a.tar.xz" | tar -xJ -C /opt && export PATH="/opt/node-v22.11.0-linux-$a/bin:$PATH"
fi
rc=0
(cd engine && uv sync --quiet && uv run --quiet python -m pytest -q -p no:cacheprovider) > ci_out/engine.log 2>&1 || rc=1
(cd web && npm ci --silent && npm test && npm run build) > ci_out/web.log 2>&1 || rc=$((rc+2))
tail -5 ci_out/engine.log; tail -15 ci_out/web.log; echo "CI rc=$rc"; exit $rc
