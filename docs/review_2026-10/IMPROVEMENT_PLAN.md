# FinTwin improvement plan: revision 3 (written 28 Oct 2026)

Findings are collected in this folder:

| File | Finding IDs | Content |
|---|---|---|
| `wave1_findings.md` | D / E / M / P / R | Researchers and 5 reviewers |
| `model_mechanics.md` | MM-F1..F14 | Model mechanics |
| `software.md` | SW-1..20 | Software |
| `web.md` | WEB-HIGH / MEDIUM / LOW | Web |
| `devops.md` | OPS-F1..F14 | DevOps |
| `citations.md` | C1..C8 | Citations, plus missing references |

## 0. What changes in the story

The most important finding is **MM-F1** (verified by the main session in `stochastic/calibrate.py:44-62`). The fixed/variable cost split is about 2/3 prior and 1/3 data, however much revenue varied. The SSE term is normalised by n·var(costs) and can never outweigh `PRIOR_WEIGHT=2`. The docstring says the opposite.

Together with:
- MM-F4: depreciation is counted twice when the D&A tag is missing;
- MM-F5: the tax and CFO-residual estimators do not match;
- MM-F2: operating leverage is identified from seasonal variation;

this means the paper's headline (the twin is less accurate than simple rules and overreacts about 2.3×) is **partly an implementation artifact, not a property of simulation**.

This is the most valuable result of the review, and also the most dangerous for credibility. Fixing it after seeing the results looks like tuning. The rule is therefore:

1. **Pre-specification before any code change.** Write `docs/REVISION_PLAN_3.md`: which fixes are made, which metrics decide, and what counts as success. Commit it and record its hash in the paper. The fixes count as *bug fixes* because the code did not do what the documentation said.
2. **Report both versions.** Report the frozen specification of the previous round (v2) and the corrected one (v3), plus the ladder of fixes cumulatively (MM §4: fix 1 → 1+2 → … → 1–5). Make no new selection on test years.

**Framing (decision of the main session; the user can override).**
- The paper becomes a *pre-registered benchmark of filing-based simulation against persistence*, with two pillars:
  - (i) point transmission (H2, encompassing, combinations, MCS/SPA);
  - (ii) distribution and stress (a referee): density scores (CRPS/PIT) and liquidity shortfall under named shocks against realised stress periods (Brier and reliability).
- The bankruptcy AUC becomes a secondary check.
- Sobol, conformal, S&P forecast evaluation and the episode tables move to an online appendix.
- "Digital twin" is mentioned once; the title speaks of "filing-based cash-flow simulation".
- Target: **International Journal of Forecasting** (forecast evaluation, density scoring, it welcomes well-documented negative results), about 10k words plus appendix. Backup: Journal of Forecasting.

## 1. Organisation

### Principles
- **Each workstream owns files and only those.** No two agents write the same file at the same time, so merges have no conflicts.
- **Each agent works in its own git worktree** (`isolation: worktree`), on branch `rev3/<ws>` off `rev3`.
- **Tests with every fix.** Each ID gets a test that fails before the fix and passes after it. Locally an agent runs only its own test files. The full suite runs on a server (heavy-compute rule).
- **Commits** are authored `SpiliosDimakopoulos <150211937+SpiliosDimakopoulos@users.noreply.github.com>`, with **no AI attribution**, and one commit per ID group whose message names the IDs.
- **Every agent returns a change log** as a table: ID → commit → test → "fixed / partial / not done, and why".
- **What is not fixed is documented.** Out-of-scope items (e.g. M6 NOL/163(j), M8 pensions) go to the paper's limitations, not left silent.

### Models
| Work | Model | Why |
|---|---|---|
| Data layer, model calibration, inference, evaluation (subtle changes with consequences for the numbers) | **Opus** | Subtle errors here cost a full rerun and credibility |
| Repro/infra, web, software cleanup, bibliography, TS port to a fixed spec | **Sonnet** | Clear specs, judgement needed, little risk |
| Mechanical work (renames, wording replacements, counts on files) | **Haiku** (`bulk-reader`/`Explore`) | Cheap |
| Integration, merge, review of diffs, writing the paper | **Main session (Opus)** | Needs the whole picture |
| Verification after the fixes (wave 3) | Fresh Opus and Sonnet reviewers without access to this plan | Unanchored review |

## 2. Phases

### Phase 0: preparation (main session, before any agent)
1. **Git.**
   - Merge `origin/main` (22 commits, including contributor changes to `edgar.py`, `calibrate.py` and `presets.py`) into `revision`, then create `rev3`.
   - From then on, **no** merge from main until the release (OPS-F1).
   - The weekly data refresh stays only on main.
2. **Data snapshot.**
   - A single fetch of the EDGAR facts and census on a server (`burst-server`, cax21).
   - Save it as a tar with SHA256, then use it for every subsequent run (R1).
   - Store the extraction date.
3. **Write and commit `REVISION_PLAN_3.md`** (pre-specification, §0).
4. **Shard stamping first (SW-2).** Every shard file carries the hash of code, assumptions and snapshot; a mismatch means a rerun. Without this the rerun mixes old and new results.
5. **Baseline.** Keep the current `research.json` and `numbers.tex` as `baseline_v2/` for comparison.

### Phase 1: parallel fixes (8 agents in worktrees)

| WS | Model | Files it owns | IDs |
|---|---|---|---|
| **A: data** | Opus | `engine/fintwin/data/*`, `tests/test_facts*.py`, new `tests/test_data_*.py` | D1 (full quarterly calendar + contiguity), D2, D3, D5, D6, D7, D9, D11, D12, D13, D15; detection and flag of missing D&A (data side of MM-F4) |
| **B1: model calibration** | Opus | `stochastic/calibrate.py`, `stochastic/shocks.py`, `stochastic/mc.py` | MM-F1 (Bayesian weighting), F2 (TTM/Δ4 identification), F3 (partial adjustment + M&A flag), F4 (D&A handling), F5 (16q-anchored CFO residual, consistent tax), F6, F7, F9 (parameter-uncertainty paths), F10, F12, F13, F14; M2 (floating by sector/XBRL); M3 (ladder unknown → flag, bullet). Every fix behind a switch, so the ladder of §0 runs |
| **B2: model mechanics** | Opus | `model/sd_model.py`, `model/ratings.py`, `scenarios/*` | M1 (maintenance covenant, revolver availability/maturity, first-breach output), MM-F11 (debt-free loss-makers ≠ D), M4 (sector shock multipliers, named sourced presets), M5 (REIT/utility payout floor, equity issuance switch), M7 (runway, funding gap p95, maturity wall, P(liq<X)). Switches default OFF in research v2 compatibility |
| **C1: inference** | Opus | `research/stats.py`, `research/transmission.py`, `research/plan2.py` | E3, E4, E5 (MCS, SPA, Romano–Wolf), E6, E7, E9, E11, D8 (first petition per case, exclude in-bankruptcy firm-years), R4 (per-function RNG, seeds table), SW-12, SW-13, SW-14 |
| **C2: evaluation pipeline** | Opus | `research/experiments.py`, `research/distress.py`, `research/calibration.py`, `research/assumption_sobol.py`, `research/__main__.py`, `backtest/*` | E1 (median of path totals), E2 (CRPS/PIT of cumulative OCF/FCF), E8 (Brier, log, Murphy, reliability), E10, E12 (liquidity-shortfall test against stress periods), E13, D4, D10 (actual `filed`), M9 (credit-event label 1.03/2.04/3.01/going-concern), SW-2 (if not done in phase 0), SW-3, SW-4, SW-15, SW-17, SW-18 (performance), P8 (Sobol: scrambled, N≥256, resample firm-years) |
| **D: repro/infra** | Sonnet | `.github/*`, `pyproject.toml`, `uv.lock`, `Makefile`, `REPRODUCE.md`, `CITATION.cff`, `.zenodo.json`, `.mailmap`, `.gitignore`, `LICENSE-DATA`, version files, `tools/freeze_snapshot.py` | R1–R3, R5, R7, R8 (coverage includes research), R9 (thread pinning), OPS-F3..F14, SW-20; data.yml with noreply identity (OPS-F2/F7) |
| **E: web** | Sonnet | `web/src/**` except `web/src/engine/**`, `web/index.html`, `web/public/*.png` | All WEB-HIGH/MEDIUM/LOW: disclaimers, "validated" overclaim, product-vs-paper spec label, ask parser, URL clamp, accessibility, D14 wording. Numbers and the figure are finalised in phase 4 |
| **F: software + bibliography** | Sonnet | `pipeline.py`, `changes.py`, `memo.py`, `notes.py`, `export.py`, `api.py`, `metrics/*`, `docs/paper/references.bib` | SW-5, SW-6, SW-9, SW-10, SW-11, SW-16, SW-19; health-formula dedup only in its own files; C1–C8 and the BibTeX additions in `citations.md` (bib only, not the text) |

**Dependencies within phase 1.**
- B1 and B2 must not change the public signature of `calibrate()` / `simulate()` without telling the main session. The same applies to A for `CompanyData`.
- Interface changes are posted in `docs/review_2026-10/interfaces.md`. The workstream owner writes them and the others read.

### Phase 1b: TS port (Sonnet, after B1 and B2 are merged)
- `web/src/engine/**` and the parity goldens: port the changes of B1 and B2.
- Extend the goldens to sector_tol ≠ 1, rec_state0 = 1, and all 29 outputs (SW-1).

### Phase 2: integration (main session)
1. Merge into `rev3` in this order: A → B1 → B2 → C1 → C2 → D → F → E → TS port.
2. Run `/code-review high` on each merge.
3. Full test suite and coverage on a server (cax21, a few minutes).
4. **Dry run.** 300 firms × 3 cutoffs, v2 vs v3 specification, on a server. It checks that nothing broke and that the numbers move in the expected direction before we pay for the full rerun. Abnormal deviations go back to the owning workstream.

### Phase 3: full rerun (a single server session)
- **Machines:** cax31 (or 2× cax31 if the 20-vCPU limit allows). It runs on the frozen snapshot and produces:
  - v2-frozen and v3;
  - the cumulative ladder of MM fixes 1–5;
  - Sobol N≥256;
  - MCS/SPA/RW;
  - density and Brier;
  - liquidity shortfall.
- **Server lifecycle:** delete the server immediately after the pull, and report the server type and cost in EUR.
- **Output:** `research.json` + `numbers.tex` + a diff report against `baseline_v2/`.

### Phase 4: paper and public material (main session, with help)
1. Restructure according to §0, using the IJF template (main session, Opus). Fix E14, P3, P4, P6, P7, P9, D14, and add the citations (C1, missing references).
2. Regenerate figures and tables from the numbers. Never type numbers by hand.
3. README, site, `findings.png`, Zenodo metadata (WS-E and WS-D, Sonnet, small follow-ups).
4. Limitations paragraph listing everything not fixed (M6, M8, the market-based inputs suggested by a referee).

### Phase 5: verification and release
1. **Wave 3: three fresh reviewers** who do not see this plan (Opus econometrician, Sonnet editor, Sonnet replication) on the new PDF and the diff. Fix what they find.
2. Release:
   - tag `v3.0.0` on `rev3`;
   - Zenodo with the data snapshot;
   - PDF build from the tag (OPS-F1).
3. Draft replies to a referee, a data reviewer and an econometrician explaining what changed and thanking them. The user sends them.

## 3. Decisions for the user
1. **Framing and journal** (§0): proceed with IJF and the two-pillar story unless the user objects.
2. **Public email in git history** (OPS-F2):
   - Recommendation: **no** history rewrite (it would change the SHAs that Zenodo and the tags cite). Add `.mailmap` and set noreply from now on.
   - The alternative is `git filter-repo` plus a force-push; that is the user's call.
3. **Contact email in the paper:** `spiliosdimakk@gmail.com` (`fintwin.tex:25`). Is that the right one?
4. **Merge of the 22 commits from main** into revision before the fixes start. Recommendation: yes.

## 4. Rough cost
- **Agents:** 8 (phase 1) + 1 (TS) + 3 (wave 3) plus integration. Most of the cost is the Opus workstreams A, B1, B2, C1 and C2.
- **Hetzner:**
  - snapshot fetch: cax21, about 1 h;
  - tests and dry run: cax21, about 1 h;
  - full rerun: cax31, a few hours;
  - in total roughly 0.5–1.5 EUR net.
