# DevOps / security / repo-hygiene review (wave 2), 2026-10-28

Scope: .github/workflows/*, .gitignore, engine/pyproject + uv.lock, web/package.json, scripts, repo root, git history, branches.
No secret values were found or printed. Already-known items (uv sync without --locked, data not frozen, weekly refresh moves paper inputs) are not re-listed except for the proposed fix mechanism (F1).

## Ranked findings

### HIGH

**F1. origin/main is 22 commits ahead of revision and keeps diverging; the paper is not built from an immutable ref.**
- Evidence: `git rev-list --left-right --count origin/main...revision` = 22 0. The 22 include 3 weekly data refreshes (c95c52f, cd53f73, c6d9dbb), contributor PRs that change engine code the paper depends on (edgar.py throttling/locking #50, calibrate.py docstring on the fixed-cost prior #46, api.py, research/stats.py tests #47, a new gfc_2008 preset #31) and Dependabot bumps of every action and all Python/web deps (#22, #27, #28). Local `main` is stale, so `git rev-list main...revision` gives a misleading 0/35. Tag v2.0.0 (ee5ddd0, the merge of PR #1 revision->main) already exists, yet revision keeps being edited, so the tag no longer equals what the paper describes.
- Problem: Zenodo/CITATION say 2.0.0, but the code the revision describes (Y-3 training, 90-day lag, etc.) is not what v2.0.0 contains, and main moves under it. Merging main back into revision (as in e908581) imports data refreshes and dependency bumps into the revision.
- Fix (concrete mechanism):
  1. Freeze the revision with an annotated tag (e.g. `paper-r1`, or v2.0.1 if 2.0.0 is already minted on Zenodo; never move a published tag) on the final revision commit. Cut the Zenodo release from that tag, not a branch tip.
  2. Stop merging main into revision (cherry-pick bug fixes deliberately). Weekly refresh only commits web/public/data/{build_report,calibration,index,changes}.json and feed.xml, so it never needs to enter revision.
  3. Add a `paper-data` GitHub Release (or Zenodo data deposit) holding the EDGAR facts cache tarball, FRED/Philadelphia Fed vintages and universe_edgar.csv with sha256s. research.yml downloads this asset instead of hitting EDGAR live; store hashes in e.g. `engine/fintwin/data/paper_inputs.lock` and verify them at start of `research`.
  4. In data.yml and pages.yml set `ref: main` explicitly on checkout so nothing from the weekly job touches revision or tags. Optionally write weekly data commits to a `data` branch and have pages.yml take site data from it, keeping main (code) reviewable.
  5. CI job `paper` on tag push `paper-*`: build the PDF with a pinned TeX image, run `research-stats` against the frozen asset, diff research.json / numbers.tex against committed, fail on drift.

**F2. Public git history contains the e-mail that must not be public.**
- Evidence: `git log --all` shows 19 commits authored and committed as `SpiliosDmk <[redacted email]>` (from 0901d99 "Scaffold + data layer" through ae561f3, all 2026-10-16). They are ancestors of published main and tag v2.0.0. It is not in the current HEAD tree (git grep on HEAD finds no match).
- Also: 82 commits use `SpiliosDimakopoulos <spiliosdimakk@gmail.com>` (double k, a different address). It is also printed in docs/paper/fintwin.tex:25 and hardcoded at .github/workflows/data.yml:99 as the bot commit identity. Presumably an intentional contact address, but it contradicts the rule to commit with the noreply address `150211937+SpiliosDimakopoulos@users.noreply.github.com`.
- Problem: wrong/linked-account attribution on those 19 commits and permanent exposure; rewriting means force-pushing published history and breaking Zenodo-referenced SHAs.
- Fix: (a) change data.yml:99 now to the noreply address (or github-actions[bot]); (b) add a `.mailmap` mapping both old addresses to the noreply identity; (c) only if exposure outweighs archive stability, `git filter-repo --mailmap` plus force push (invalidates v1.x/v2.0.0 SHAs and Zenodo links); (d) verify on GitHub that those commits show as SpiliosDimakopoulos and not CobeOg; (e) confirm that fintwin.tex:25 should show the double-k mailbox.

### MEDIUM

**F3. Actions pinned by mutable tag only; ci.yml has no `permissions:` block.**
- revision: ci.yml:6-7,19-20 (`checkout@v4`, `setup-uv@v5`, `setup-node@v4`); every workflow uses floating major tags. origin/main already moved to checkout@v7, setup-uv@v7, cache@v6, download-artifact@v8, upload-pages-artifact@v5, deploy-pages@v5, so every workflow file will conflict on the next merge. `astral-sh/setup-uv` is third-party.
- ci.yml runs on every push and pull_request (including forks) with default token permissions (write on older repos).
- Fix: `permissions: { contents: read }` at the top of ci.yml; pin to full commit SHAs with `# vX.Y.Z` comments (Dependabot updates SHA pins). Take main's workflow files wholesale when reconciling.

**F4. data.yml: over-broad permissions and swallowed failures.**
- data.yml:8 gives every job `pages: write, id-token: write`, including the 16 shard jobs that run `uv run` of all dependencies. Only `deploy` needs them (aggregate already overrides to contents: write at line 70). Use top-level `contents: read` and grant pages/id-token only on `deploy`.
- data.yml:100-103: `git push || echo "push skipped"` and `git add ... 2>/dev/null || true` hide failures; the next job still deploys data the repo never recorded.
- aggregate has `if: ${{ !cancelled() }}` and shards are `fail-fast: false`, with output folders wiped first, so a failed shard silently drops about 1/16 of companies from the deployed site. Add a gate (all 16 shard artifacts present, coverage in build_report above a threshold) before deploy.

**F5. research.yml is not reproducible by construction (beyond "data not frozen").**
- research.yml:44-49 and ~92-97: cache key contains `github.run_id` (16 new caches per run, churns the 10 GB budget and can evict the weekly data.yml cache) and `restore-keys: edgar-` falls back to the latest weekly cache, so shards may start from different EDGAR vintages. `FINTWIN_FACTS_MAX_AGE=100000` means whatever is restored is never refreshed, silently.
- `timeout 320m ... || true` turns crashes into green jobs; `stats` aggregates whatever finished with no check that all 16 shards / all companies are present before writing research.json.
- research.json records no git SHA, uv.lock hash or data-vintage hash. research-stats.yml recomputes "with the current code" on a past run's outputs without asserting that the code matches the producing run.
- Artifacts have default 90-day retention (research-results, shard outputs, sobol, data-audit); after that research-stats cannot rerun from a run_id.
- Fix: F1 step 3; static cache key `edgar-paper-<vintage>`; fail stats if shard count != 16 or company count != expected; write `{git_sha, uv_lock_sha256, inputs_sha256, run_id}` into research.json; `retention-days: 400` on research-results, sobol-assumptions, data-audit; attach research-results to the paper tag as a release asset.

**F6. SEC EDGAR compliance: UA is a secret I cannot see; limiter and 16-way parallelism need care.**
- UA comes from `secrets.SEC_USER_AGENT` (data.yml:10, research.yml:12) and gitignored `.env` (never added in history; no .env/key/token/pem in `git log --all --diff-filter=A`). Verify the secret is not `[redacted email]`. The .env.example placeholder is fine. No step echoes the variable.
- edgar.py (revision): `_MIN_INTERVAL = 0.15`, global `_last_request` set in `finally` after the response, no lock. origin/main PR #50 fixes this (lock, monotonic clock, timestamp before request); take it, but note it changes engine code, so apply deliberately given F1.
- 16 shard jobs on separate runners share one UA, each at up to 6.7 req/s, so the UA-level load can be about 100 req/s (SEC's limit is 10 req/s per user/IP; per-IP blocking usually saves it, but it is a compliance risk). Lower per-shard rate (about 0.15 s x 16 = 2.4 s per shard-request, or cap shards), honour `Retry-After`, and treat 403 as fatal, not retryable/cacheable (edgar.py retries only 429 and 5xx).

**F7. Weekly refresh pushes straight to the default branch under the owner's personal identity.**
- data.yml:97-103 commits as SpiliosDimakopoulos with a personal address and pushes to main with no gate; pages.yml then deploys on that push. Use github-actions[bot] or the noreply identity, add a schema/coverage gate before commit, and include the run id in the commit message.

**F8. pages.yml deploys data built from different code than the code deployed; two deploy workflows race.**
- pages.yml:12-20 overlays `site-data` from the latest successful data.yml run of any branch/SHA (`gh run list --workflow data.yml --status success --limit 1`, no `--branch main`) onto the pushed commit's web build. A push that changes the JSON schema ships new UI on old data until Monday; a manual dispatch on revision would feed pages. Add `--branch main`, record the producing SHA in site-data and check a schema version.
- data.yml `deploy` (concurrency group `data`) and pages.yml (group `pages`) both call deploy-pages and can overlap. Use one shared concurrency group.

### LOW

**F9. CI runs tests and the coverage gate (good) but is thin.** ci.yml:15-16 run ruff, mypy, pytest `--cov-fail-under=85`, vitest parity on goldens and the build on every push/PR. Gaps: no Python version pin or matrix (pyproject says >=3.11), no `--locked`, no pip-audit/npm audit, no check that committed docs/paper/fintwin.pdf and numbers.tex match code. uv.lock and web/package-lock.json are committed; web uses `npm ci` with exact versions. tools/package-lock.json is not covered by Dependabot.

**F10. Dependabot only on main; many stale remote branches.** dependabot.yml (monthly, grouped) exists on origin/main, not on revision (fine, default branch). Stale remotes: dependabot/github_actions/* (7), dependabot/npm_and_yarn/web/*, dependabot/uv/engine/*, dependabot-groups, contributor-experience, devcontainer, docstring-fixes. Delete them; add /tools npm ecosystem. Dependabot bumping numpy/scipy/statsmodels on main changes numerics, which reinforces F1 (paper must use the lock at the tagged commit).

**F11. Stray files at repo root (untracked, hidden only by local .git/info/exclude).** grep.exe.stackdump (msys crash dump), klein_list.txt (unrelated NSFW image-model list), Feedback_from_researchers.txt (20 KB private correspondence), docs/MESSAGES_TO_RESEARCHERS.md, docs/OUTREACH.md are excluded only in `.git/info/exclude`, not `.gitignore`: another clone or `git add -A` elsewhere would publish them. Delete the first two, move correspondence out of the repo or into .gitignore. Untracked and not excluded: docs/RESEARCHER_REPLIES_2026-10.md and docs/review_2026-10/ (decide before committing; the replies name reviewers). `.env` is gitignored and absent from history.

**F12. Repo weight and artifacts.** Largest blobs: docs/paper/research.json 2.4 MB (4 older versions 1.5-1.7 MB in history), fintwin.pdf 650 KB, engine/uv.lock 650 KB, screenshots 0.4-0.6 MB. 1,184 tracked files under web/public/data. No blob over 2.4 MB, no credentials. LaTeX artifacts (aux, log, out, bbl, blg, fls, fdb_latexmk, dist/) are correctly ignored. fintwin.pdf is tracked and can drift from the tex; build it in CI on the paper tag.

**F13. Licence and metadata.** MIT LICENSE covers code only; no statement for derived SEC/FRED/Philadelphia Fed data in web/public/data and universe_edgar.csv (FRED series have third-party terms). SECURITY.md, CODEOWNERS, CONTRIBUTING exist on main but not revision. scripts/deploy.sh:9-10 does `git mv .github/workflows/pages.yml.disabled`, a file that no longer exists: dead and misleading, remove. engine/pyproject.toml version is 0.1.0 while CITATION/Zenodo say 2.0.0; align.

**F14. Caching.** data.yml saves cache with the same weekly key; a re-run in the same ISO week cannot refresh it (benign "already exists" warning). `restore-keys: edgar-` trusts any cache of that prefix as data input; a poisoned or stale entry flows into paper numbers (fixed by the hash check in F1.3).

## What is fine
- No secrets, tokens, keys or .env committed anywhere in `git log --all`; the SEC UA is a repository secret.
- research.yml and research-stats.yml have least-privilege `permissions: { contents: read, actions: read }`; pages.yml grants only what Pages needs.
- CI executes ruff, mypy, pytest with an 85% coverage gate, vitest parity and a production build on every push/PR.
- `concurrency` and `timeout-minutes` set on the heavy jobs; `npm ci` with exact versions; uv.lock committed.
