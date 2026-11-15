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
# the lock is written on Windows and misses rolldown's linux-arm64 binding (npm/cli#4828): add it on ARM servers
(cd web && npm ci --silent \
  && { [ "$(uname -m)" != aarch64 ] || npm install --no-save --silent \
       "@rolldown/binding-linux-arm64-gnu@$(node -p "require('./node_modules/rolldown/package.json').version")"; } \
  && npm test && npm run build) > ci_out/web.log 2>&1 || rc=$((rc+2))
tail -5 ci_out/engine.log; tail -15 ci_out/web.log; echo "CI rc=$rc"; exit $rc
