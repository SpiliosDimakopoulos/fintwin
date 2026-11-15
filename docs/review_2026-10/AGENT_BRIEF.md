# Brief for revision-3 fix agents (read fully before starting)

You are one of 8 parallel workstreams fixing the FinTwin project. Each workstream works in its own git worktree, off branch `rev3`.

Read these before anything else:
- `docs/review_2026-10/IMPROVEMENT_PLAN.md`: §1 lists the files you own, §2 describes the phases.
- `docs/REVISION_PLAN_3.md`: the pre-specification. It is binding, and it defines the specification switches below.
- The findings files that your IDs point to.

## Hard rules
1. **File ownership.**
   - Edit only the files your workstream owns, plus new test files named `engine/tests/test_<ws>_*.py`.
   - If a fix needs a change in a file you don't own, don't make it. Write the exact change you need in `docs/review_2026-10/requests/<ws>.md`.
2. **Interfaces.**
   - Do not change public signatures used by other modules: `CompanyData`, `company_quarters`, `calibrate`, `simulate`, `company`, the shard JSON keys.
   - Adding optional parameters or new keys is fine.
   - Every new or changed field or switch goes in `docs/review_2026-10/interfaces/<ws>.md`.
3. **Specification switches.** Each model fix must be selectable, so the ladder in REVISION_PLAN_3 §0.2 can run.
   - `FINTWIN_SPEC` takes `v2-pre`, `v2-rev` or `v3`, and decides which fixes are active.
   - `FINTWIN_FIXES` is an optional comma list (e.g. `F5,F4`) that overrides the defaults.
   - B1 creates `engine/fintwin/stochastic/spec.py` with `active(fix_id) -> bool`. Others import it. Until B1 is merged, use a local fallback that reads the same env vars.
   - Data-layer fixes always apply. `FINTWIN_DATA_LEGACY=1` restores the old behaviour, for one comparison run.
   - With `FINTWIN_SPEC=v2-pre`, model outputs must be **identical** to the current code. Prove it with a test on a synthetic or cached firm.
4. **Tests.**
   - Every finding ID you fix gets at least one test that fails before the fix and passes after it.
   - Run only your own test files plus directly affected existing ones: `cd engine && uv run python -m pytest -q <files> -p no:cacheprovider`.
   - **Never** run the full suite or any research shard/stats run on this PC: it is shared with production. The full suite runs later on a server.
5. **Lint.** `uv run ruff check <your files>` and `uv run ruff format <your files>`, with line length 120 as in `pyproject.toml`.
6. **Commits.**
   - Configure in your worktree: `git config user.name SpiliosDimakopoulos` and `git config user.email 150211937+SpiliosDimakopoulos@users.noreply.github.com`.
   - Commit by group of IDs, and name the IDs in the message (e.g. "D1, D4: contiguous quarterly calendar ...").
   - **No AI attribution of any kind**: no Co-Authored-By, no "Generated with".
   - Do not push. Do not merge. Do not touch other branches.
7. **Style.** Match the surrounding code: terse docstrings, comments that explain *why*, no new dependencies unless unavoidable (ask in the requests file instead).
8. **Scope.** Fix what your IDs say. If you find a new bug outside your scope, write it in `requests/<ws>.md` and do not fix it.
9. **If you cannot fix an ID properly**, leave it and explain why. Don't half-fix it silently.

## Final report (your last message; max ~400 words)
A table with columns: ID | status (fixed/partial/not done) | commit | test | note.

Then add:
- the switches and interfaces you added;
- requests to other workstreams;
- anything the integrator must know before the dry run.
