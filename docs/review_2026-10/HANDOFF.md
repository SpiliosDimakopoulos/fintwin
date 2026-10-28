# Handoff (28-10-2026, end of session)

Read this first, then `GROWTH_PLAN.md` (v2) and `IMPROVEMENT_PLAN.md`.

## Git state
- Work is on the local branch `rev3` (126 commits ahead of `main`). **Nothing has been pushed.**
- Local identity: `SpiliosDimakopoulos <150211937+SpiliosDimakopoulos@users.noreply.github.com>`. Check it before
  every commit. No AI or Co-Authored-By lines.
- **Before the first push of rev3:** commit 34865ea added `docs/RESEARCHER_REPLIES_2026-10.md`. It was later untracked
  and gitignored (fcc9b15). Remove it from rev3 history with a local rewrite before any push (filter-repo or an
  interactive-free rebase). Private files never go into git: `Feedback_from_researchers.txt`,
  `docs/MESSAGES_TO_RESEARCHERS.md`, `docs/OUTREACH.md`, `docs/RESEARCHER_REPLIES_*.md`.
- Ask the user before any push, any PyPI/HF/Zenodo publication or any `paper-data` release.

## Server job in flight (the "shell")
- Server `burst-fintwin-snapshot-1028-2115` is a cax21 with a 14 h TTL, so it self-destructs around 12:00 on 29-10.
  It runs two steps:
  1. the universe rebuild (D12). This is **done**: 5,308 non-financial companies, 475 with an Item 1.03 8-K;
  2. `freeze_snapshot build`, which was still running at handoff.
- A background waiter in the old session may die with the clear. Do it by hand:
  ```
  B=C:/Users/USER/claude_shared/burst/burst.py
  python $B job engine            # RUNNING / DONE + log tail
  python $B pull engine snapshot snapshot_build.log universe_build.log fintwin/data/universe_edgar.csv
  python $B down && python $B status   # status must say nothing is billing
  ```
- Then:
  1. Verify the snapshot: `py scripts/freeze_snapshot.py verify` on the pulled tar plus `manifest.json`. Do this only
     as a light check; anything heavy goes to the server.
  2. Commit the new `engine/fintwin/data/universe_edgar.csv`.
  3. Report the server type and EUR. About 0.04 EUR had been spent at 1.4 h.

## Next steps: the rev3 paper (IMPROVEMENT_PLAN, phases 3–5)
1. Run the dry run on a server. The snapshot (~1 GB) uploads at ~0.5 MB/s. Use `--keep` so the full run reuses the
   same server:
   `python $B do engine "bash scripts/rev3_server.sh dry" --pull out --ram 8 --hours 6 --keep`
   It restores and tops up the snapshot, runs the full test suite and the dry ladder (300 firms × 2015/2020/2022),
   then dry stats. Check the timings and results in `engine/out/`.
2. Run `bash scripts/rev3_server.sh full` on the same server. It does the ladder grid, select, walk-forward, legacy
   v2-pre, stats and Sobol. Then run `down`.
3. Phase 4: rewrite the paper in the IJF two-axis framing (pre-spec `docs/REVISION_PLAN_3.md`), regenerate the numbers,
   then update the web numbers, `findings.png` and README.
4. Phase 5: three fresh reviewers, tag `v3.0.0`, Zenodo, and draft replies to the researchers. The drafts stay private.
5. Open small items:
   - the M4 sector table;
   - two-way encompassing t plus a spec block in the web JSON;
   - edgar 403 / Retry-After handling (OPS-F6; also needed by growth plan H5);
   - C1 seeds;
   - D8 emergence dates;
   - the `web/package-lock.json` version;
   - stale remote branches.

## Next steps: the growth plan (GROWTH_PLAN.md v2)
- **G0, can start now, in parallel with rev3, and touches no rev3 code:**
  - ADR-001 (API), ADR-002 (dataset schema, H1), ADR-003 (benchmark pre-spec, B1), written by the main session and
    approved by the user;
  - the R0 pre-spec, then a run on the snapshot (cax21, about 1 h) for a go/no-go decision;
  - a new README (G1), plus G2 hygiene and templates;
  - a new `LICENSE-DATA` and `THIRD_PARTY.md` (A5/A6);
  - the B4 weekly prediction archive and the GitHub-traffic snapshot workflow (these need a push to main, so ask).
- **Branch rule (AR-13):** until `v3.0.0`, branch `lib` takes only new files. After the tag: merge rev3 into main, cut
  `lib` from main, and add the paper-parity test.
- **Then:** G1 (loader and dataset) → beta → launch 1 → G2 (twin and bench) → launch 2 → G3 (web and MCP) → launch 3.
  Section 5 of the plan says which agent or model does each task.
- **Waiting on the user:**
  - approval of A1–A14;
  - review hours per week;
  - PyPI/TestPyPI trusted publisher setup;
  - an HF account and an `HF_TOKEN` environment secret;
  - asking the researchers who replied to be beta testers, and whether any of them has WRDS.

## Standing rules
- Heavy compute (full test suites, research runs, data builds) runs only on the Hetzner burst server, never on the PC.
  Use ARM cax only. Delete servers ASAP and report the type and EUR.
- Delegate mechanical work to Haiku and judgement-based research to Sonnet. Design, merges and final texts stay in the
  main session (Opus).
- Agents follow `AGENT_BRIEF.md`: one worktree per workstream, no push, interface notes in `interfaces/`, requests in
  `requests/`.
