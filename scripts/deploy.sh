#!/usr/bin/env bash
# One-command publish (run only when you decide to go public):
#   1) creates a public GitHub repo from this folder, 2) enables Pages (the pages workflow is already in the repo), 3) pushes.
# Requires: gh auth login. Your .env (SEC contact email) is git-ignored and never pushed.
set -euo pipefail
cd "$(dirname "$0")/.."
NAME="${1:-fintwin}"
gh repo create "$NAME" --public --source=. --remote=origin --push
gh api -X POST "repos/{owner}/$NAME/pages" -f build_type=workflow >/dev/null || true
echo "Live in ~2 minutes at: https://$(gh api user -q .login).github.io/$NAME/"
