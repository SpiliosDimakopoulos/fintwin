# ops review (workflows, scripts, tools, Makefile, packaging)

Workflows are in good shape: every action is pinned by SHA with a version comment, `permissions` are least-privilege
at top level, `welcome.yml` uses `pull_request_target` without checking out PR code, the snapshot action passes its
input through `env`. Findings below are what is left.

### O1 Silent give-up after 3 retries in the build/validate scripts
- where: engine/scripts/build_all.sh:8, resume_build.sh:11, full_pipeline.sh:9, validate_all.sh:9
- severity: bug
- changes numbers: n/a
- issue: `for attempt in 1 2 3; do cmd && break; sleep N; done` falls through with no error when all three attempts fail,
  so build_all.sh (which has `set -e`) still ends "successfully" and exports GOLDEN/BACKTEST/notes with a company
  missing. The other three do not even have `-e`. A failed company is only visible in a log nobody greps.
- fix: a shared helper `retry() { for a in 1 2 3; do "$@" && return 0; sleep 3; done; echo "FAILED: $*" >&2; return 1; }`
  that records failures and exits non-zero at the end. Put it in one `scripts/lib.sh` sourced by all four.
- effort: S

### O2 Four near-identical bash drivers, two of them dead
- where: engine/scripts/build_all.sh, resume_build.sh, validate_all.sh, full_pipeline.sh
- severity: slop
- changes numbers: n/a
- issue: the same ticker one-liner (SHOWCASE + UNIVERSE + UNIVERSE_XL) is pasted in build_all and resume_build;
  full_pipeline.sh = validate_all.sh + resume_build.sh with a 2-worker split. validate_all.sh is referenced nowhere;
  resume_build.sh only by full_pipeline.sh. full_pipeline.sh also has unquoted `$L`, `echo $L | tr | tac`, and
  `set -uo pipefail` without `-e`. validate_all's "~100 companies" docstring is stale.
- fix: delete validate_all.sh; make resume_build the single path (build_all = resume_build with a `--all` flag); get the
  ticker list from one `python -m fintwin.export --list` call.
- effort: M

### O3 Build artefacts tracked or not ignored
- where: web/tsconfig.tsbuildinfo (tracked), .gitignore (no engine/out/, engine/*.log)
- severity: slop
- changes numbers: n/a
- issue: `web/tsconfig.tsbuildinfo` is committed (a tsc incremental cache that changes on every build: noisy diffs).
  `git status` shows `engine/out/`, `engine/snapshot_build.log`, `engine/universe_build.log` untracked because
  .gitignore lacks them (rev3_server.sh writes to engine/out by design).
- fix: `git rm --cached web/tsconfig.tsbuildinfo`; add `*.tsbuildinfo`, `engine/out/`, `engine/*.log` to .gitignore.
- effort: S

### O4 pyproject has no PyPI-grade metadata; install-from-git is undocumented
- where: engine/pyproject.toml:1-18
- severity: risk
- changes numbers: n/a
- issue: no `readme`, `license` (root LICENSE is outside engine/, so sdist/wheel carry none), `authors`, `[project.urls]`,
  `keywords`, `classifiers`, no `[project.scripts]` (CLIs are `python -m fintwin.pipeline|research|export`). The package
  is in a subfolder, so `pip install git+https://github.com/SpiliosDimakopoulos/fintwin` fails (no pyproject at root);
  it needs `#subdirectory=engine`, and no doc mentions pip install at all (git grep README/CONTRIBUTING/REPRODUCE).
  Version 3.0.0.dev0 is not tied to a tag.
- fix: add engine/README.md (short) + `readme = "README.md"`, `license = "MIT"`, `license-files` (copy LICENSE into
  engine/), `authors`, `[project.urls]`, classifiers (Python 3.11-3.13, Science/Research, Financial), a
  `[project.scripts]` entry; document the `#subdirectory=engine` install; check `uv build && unzip -l` that
  fintwin/data/*.csv and sector_norms.json are in the wheel.
- effort: S

### O5 Free-text workflow input inlined into a shell step
- where: .github/workflows/research-stats.yml:33,36
- severity: risk
- changes numbers: n/a
- issue: `gh run download "${{ inputs.run_id }}"` interpolates a workflow_dispatch input straight into the script
  (template-injection pattern). Only writers can dispatch, so exposure is low, but the same step already uses the safe
  `env:` form for GH_TOKEN. (`${{ matrix.i }}` in research.yml is a fixed list and fine.)
- fix: `env: { RUN_ID: "${{ inputs.run_id }}" }`, use `"$RUN_ID"`, and check `[[ $RUN_ID =~ ^[0-9]+$ ]] || exit 2`.
- effort: S

### O6 Weekly data job loses its refresh if main moved during the run
- where: .github/workflows/data.yml:112-120
- severity: risk
- changes numbers: n/a
- issue: aggregate checks out `main` at start, runs up to 90 min after the 120-min shard wave, then
  `git push origin HEAD:main` with no rebase. Any commit to main in between makes the push non-fast-forward: the job
  goes red, `deploy` is skipped, and the whole refresh is lost though the site artifact was already built.
- fix: `git pull --rebase origin main` before the push (only summary JSON files change), or retry once.
- effort: S

### O7 ci.yml runs everything twice on same-repo PRs and does not lint scripts
- where: .github/workflows/ci.yml:2, 20-24
- severity: risk
- changes numbers: n/a
- issue: `on: [push, pull_request]` runs two full matrices per PR-branch commit; the concurrency group
  `ci-${{ github.ref }}` differs (refs/heads vs refs/pull) so they never cancel each other. Ruff covers `fintwin tests`
  only, so engine/scripts/*.py (rating_vintages.py has a different line style) and all six .sh files are unchecked
  beyond `compileall`; no shellcheck, which is where O1/O2 hide.
- fix: `on: { push: { branches: [main] }, pull_request: {}, workflow_dispatch: {} }` (add rev3 if wanted); add `scripts` to
  ruff; add `shellcheck engine/scripts/*.sh scripts/*.sh` (preinstalled on ubuntu-latest).
- effort: S

### O8 Dead / orphan scripts
- where: engine/scripts/rating_vintages.py, scripts/dev.sh, scripts/deploy.sh, tools/live.mjs, live2.mjs, hero.mjs, og.mjs
- severity: slop
- changes numbers: n/a
- issue: git grep finds no reference to rating_vintages (it produced the committed rating_spreads.csv: keep, but say so
  in REPRODUCE.md), dev.sh (CONTRIBUTING documents manual commands), live.mjs, live2.mjs, hero.mjs, og.mjs.
  live/live2 are one-off debug probes (hard-coded ticker HD, localhost:5173) that duplicate each other. deploy.sh is the
  one-shot "go public" script, already used (repo is public); it appears only in an old review note.
- fix: delete deploy.sh, live.mjs, live2.mjs; document or delete dev.sh, hero.mjs, og.mjs; list kept tools in a short
  tools/README.md.
- effort: S

### O9 tools/: Windows-only Chrome path copy-pasted, npm-init placeholder package.json
- where: tools/*.mjs (executablePath "C:/Program Files/Google/Chrome/Application/chrome.exe" in 8 files), tools/package.json
- severity: slop
- changes numbers: n/a
- issue: the same path and the same launch + error-collector prologue appear in 8 scripts, so none run on Linux/macOS.
  package.json is the `npm init` default (`"main": "index.js"` that does not exist, `"license": "ISC"` while the repo is
  MIT, empty author/description, a `test` script that exits 1, `"type": "commonjs"` though all files are ESM .mjs).
  palette.mjs writes `shots/palette.png` without creating `shots/`.
- fix: one `tools/lib.mjs` exporting `launch()` honouring `CHROME_PATH`; replace package.json with
  `{"name":"fintwin-tools","private":true,"type":"module","dependencies":{...}}`; `mkdirSync("shots")` in palette.mjs.
- effort: S

### O10 Personal address as the default SEC User-Agent; local path in a comment
- where: engine/scripts/rev3_server.sh:27 and :13
- severity: risk
- changes numbers: n/a
- issue: the fallback `FinTwin research spiliosdimakk@gmail.com` is baked into a public script, so any run by someone else
  silently identifies the owner's mailbox to the SEC instead of failing when the variable is unset. (The address is
  already printed in the paper, so not a leak.) The header comment also carries `C:/Users/USER/claude_shared/burst/burst.py`.
- fix: `: "${SEC_USER_AGENT:?set SEC_USER_AGENT to a contact address}"`; replace the local path with `B=<path to burst.py>`.
  The server push must then export the variable; the owner's burst call can pass it.
- effort: S

### O11 uv is installed and used unpinned
- where: engine/scripts/rev3_server.sh:23, .github/workflows/*.yml (astral-sh/setup-uv without `version:`)
- severity: risk
- changes numbers: no
- issue: `curl -LsSf https://astral.sh/uv/install.sh | sh` and setup-uv both take the latest uv, so stages of one run or a
  rerun months later may resolve/install with different uv versions. uv.lock pins packages, not the tool, and the
  script pipes an unverified download to sh.
- fix: pin one version (`curl ... https://astral.sh/uv/0.x.y/install.sh`, setup-uv `with: { version: "0.x.y" }`).
- effort: S

### O12 rev3_server.sh: 50+ lines of Python in heredocs, outside lint and CI
- where: engine/scripts/rev3_server.sh:57-112
- severity: slop
- changes numbers: no
- issue: three Python programs (run_meta, rung_env, stats_runs) are inlined as heredocs, so ruff, mypy, `compileall` and
  tests never see them; stats_runs re-derives run tag and selection path via private imports (`_opts`, `_code_digest`).
  A typo shows up only on a billed server hour. In `probe`, the B1 parity run ends `|| true` and is never stamped, so a
  parity failure is invisible while the main suite failure is at least stamped.
- fix: move them to engine/scripts/rev3_helpers.py (subcommands run_meta / rung_env / stats_runs); stamp the B1 result
  like the main suite.
- effort: M

### O13 freeze_snapshot.py restore ignores the tarball checksum; raw tracebacks on bad CLI input
- where: engine/scripts/freeze_snapshot.py:99-107
- severity: risk
- changes numbers: no
- issue: manifest.json stores `tarball.sha256`, but `restore()` extracts first and only compares per-file hashes after
  (missing/changed fail, extras pass). A truncated download extracts partially and fails with a less clear message.
  `sys.argv[1]` with no argument gives IndexError, an unknown command KeyError.
- fix: in `restore`, compare `_sha(Path(tar))` with the manifest's `tarball.sha256` before extracting; argparse
  subcommands or print the module docstring on bad input.
- effort: S

### O14 Makefile exports FINTWIN_FROZEN=1 globally, including `make test`
- where: Makefile:15-19, test target
- severity: risk
- changes numbers: n/a
- issue: rev3_server.sh runs pytest under `env -u FINTWIN_FROZEN` ("unit tests use their own fixtures"), while the
  documented `make test` runs them with FINTWIN_FROZEN=1 and CI runs them without. (I did not run the suite, so which
  tests, if any, differ is unverified.) Local and CI semantics diverge.
- fix: set FINTWIN_FROZEN only on research / snapshot recipes (`research: export FINTWIN_FROZEN := 1`), keep `test`
  and `paper-assets` clean.
- effort: S

### O15 Boilerplate argparse wrappers and a test that tests nothing real
- where: engine/scripts/backtest_check.py:6-27, diagnose.py:34-44, engine/tests/test_scripts.py
- severity: test
- changes numbers: no
- issue: both scripts wrap argparse in `build_parser()` + a one-line pass-through `parse_args()` + `main()` and duplicate
  DEFAULT_TICKERS (third copy in test_scripts.py:13). The test only checks that `--help` exits 0 and that the parser
  default equals the constant the test re-declares; it never calls forecast_backtest / run, so a break against the
  current API would not be noticed. diagnose hardcodes `n_paths=5000`.
- fix: drop `parse_args`; import DEFAULT_TICKERS from the module in the test; add one smoke test calling
  `main([...])` on a fixture company with a `--paths 200` option.
- effort: S

### O16 Dependency policy is inconsistent across the three manifests
- where: engine/pyproject.toml:6-13, web/package.json, tools/package.json
- severity: slop
- changes numbers: n/a
- issue: engine uses `>=` floors with no upper bound (fine with uv.lock, but a plain `pip install` resolves different
  numpy/pandas/scipy than the paper's), web pins exact versions, tools uses `^`. REPRODUCE.md should state that only
  `uv sync --locked` is the reproducible path.
- fix: one sentence in REPRODUCE.md and README install section; pin tools exactly like web.
- effort: S

### O17 pages.yml / data.yml skip the npm cache; deploy has no test gate
- where: .github/workflows/pages.yml:27-29, data.yml:102-107
- severity: slop
- changes numbers: n/a
- issue: ci.yml caches npm through setup-node, pages.yml does not, so each deploy re-downloads node_modules. pages.yml
  runs on every push to main independently of ci.yml, so a push that breaks the Python<->TS parity still deploys.
- fix: add `cache: npm, cache-dependency-path: web/package-lock.json` to setup-node in pages.yml; run `npm test` before
  `npm run build` there.
- effort: S
