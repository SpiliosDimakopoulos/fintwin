# Requests from workstream D

## To C2 (research/__main__.py, research/stats.py)
1. R3/OPS-F5: write a `provenance` block into research.json: `python` (sys.version), `platform`, versions of numpy, pandas,
   scipy, statsmodels, `git_sha` (env `GITHUB_SHA` or `git rev-parse HEAD`), sha256 of `engine/uv.lock`, the snapshot
   `manifest.json` digest, `FINTWIN_*` env, `run_id` (env `GITHUB_RUN_ID`). The paper can then state versions from it.
2. R9: at the top of `research/__main__.py`, before numpy is imported, `os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")`
   (same for OMP_NUM_THREADS, MKL_NUM_THREADS), so a bare `python -m fintwin.research` is deterministic outside the
   Makefile/workflows too (D pins them there only).
3. OPS-F5: `stats` should fail unless every one of the N shards and the expected number of companies are present
   (D only gates on all shard jobs succeeding).
4. SW-20: `assumption_sobol.indices` lacks the `var < 1e-12` guard that `sensitivity/sobol.py` has; `warnings.simplefilter("ignore")`
   in pipeline.py:144 and batch.py:363 hides numerical warnings during the paper run.

## To whoever owns data/edgar.py (OPS-F6)
Take the throttling/locking fix from origin/main PR #50 deliberately (main is not merged here); lower the per-shard
request rate for the 16 parallel weekly jobs (about 0.15 s x 16 per shard-request in total), honour `Retry-After`, and
treat HTTP 403 as fatal rather than retryable/cacheable.

## To the integrator
- Create the GitHub release `paper-data` (assets: `fintwin_snapshot_<date>.tar`, `manifest.json`) from
  `freeze_snapshot.py build` before `research.yml` can run in frozen mode. A tag `paper-<name>` triggers paper.yml.
- web/package-lock.json still says version 0.1.0 (not mine; `npm ci` tolerates it; update with `npm install --package-lock-only`).
- .mailmap necessarily contains the old private address (that is what a mailmap maps); GitHub ignores .mailmap, so the 19
  old commits still show that address and possibly the wrong account on GitHub. Only a history rewrite fixes that; not done.
- docs/paper/fintwin.tex:25 prints the double-k address (P10, user to confirm).
- Repo settings (outside the repo): delete stale remote branches (dependabot/*, dependabot-groups, contributor-experience,
  devcontainer, docstring-fixes).
- Coverage now includes research/*; fail_under=85 is in pyproject. I could not run the full suite here, so the first CI run
  may need the omit list or threshold adjusted if research code drags the total under 85.
- SW-7 beyond research/*: walk_forward.py, batch.py, pipeline.py stay omitted (they need tests from other workstreams first).
