# Rerun 5: findings and fixes before the one clean rerun (12-11-2026)

Gate: no rerun until every BLOCKER and MAJOR below is fixed or explicitly waived by the owner, a second review round
finds nothing new, and the dry run passes. Reviews: 4 independent Fable reviewers (engine/data, pipeline,
statistics vs pre-spec, shard data audit). Design under review: a reader's points (families, age, base rate,
filing behaviour) and the stamp split. Verdicts: V = verified by the main session, R = reviewer only.

## Statistics vs pre-spec
| # | Sev | Finding | V/R | Fix |
|---|---|---|---|---|
| S1 | BLOCKER | Pre-specified confirmatory test v3 vs v2-pre (REVISION_PLAN_3 lines 142-148: median abs CFO error difference on the firm-year intersection, t(G-1) on yearly median differences, year-block bootstrap B=2000, DM firm x year, drop counts) is implemented nowhere | V | implement + test before the run |
| S2 | MAJOR | B2 year-block CI has 2-3 blocks (= min/max of yearly BSS); 8 "success" flags for one uncorrected test, no primary cell | R | name the primary cell, state block count, add firm-block CI |
| S3 | MAJOR | D8 in-bankruptcy exclusion missing in `liquidity_frame` (B2/B3) and `bk_2020` (no `spans`) | R | one `in_bankruptcy` frame, merged; pass spans |
| S4 | MAJOR | Holm secondary p-values read `hybrid` (test-year winsor limits) instead of `hybrid_train` | R | read hybrid_train |
| S5 | MAJOR | Non-common support: walk-forward candidates scored on own finite sets; confirmatory stats within spec (units failing in v3 only leave silently); univariate AUCs on own sets | R | common masks; report on the v2-pre/v2-rev/v3-wf intersection |
| S6 | MAJOR | DESIGN D base rate with origin <= Y-2 leaks (outcome filed after origin); use Y-3 / known_by, EB prior from closed windows | R | in design |
| S7 | MINOR | NaN resamples uncounted; auc_table min 3 events; test_years ignores filters; block_ci seed outside SEEDS; tau/lambda never jointly scored; best_benchmark winner's curse; B1 one-sided p; seasonal-guard sample change needs supplement line; family design notes (successor co-filings, cluster switch in boot_losses), EDGAR age left-censoring | R | triage |

## Pipeline and reproducibility
| # | Sev | Finding | V/R | Fix |
|---|---|---|---|---|
| P1 | BLOCKER | At the cost cap the partial pull looks for `out/results_<stage>.tgz`, written only by the EXIT trap -> nothing pulled, server hold expires, shards lost (universe 7.9 h vs default cap 9 h) | V | background packer every 20 min (`.part` + mv); explicit `--max-hours` per stage |
| P2 | BLOCKER | Code digest drift between stages not refused: a merge after `universe` makes `select` recompute every universe shard silently | R | refuse when an existing `run_meta_*.json` has another code_digest unless FINTWIN_NEW_RUN=1 |
| P3 | BLOCKER | Platform not enforced (ARM vs x86 shards could mix; header command and plan say ARM) | R | `machine` in run_record (check_run refuses); header and plan fixed |
| P4 | MAJOR | Sobol attrition uncounted (`_failures_*` never read, rows vs 320 keys never compared) | R | assert and report |
| P5 | MAJOR | stats silently runs grid-only when a walk-forward table is missing | R | require the table for rungs with a wf grid |
| P6 | MAJOR | Resume copies a stale `_selection/` (existence check only) | R | stamp the table; exclude `_selection`/`_results` from resume |
| P7 | MAJOR | Memory/time: stats loads shards twice; Sobol `eligible()` single-threaded and untimed | R | measure in dry run |
| P8 | MINOR | sobol stats() writes without mkdir; set -e stops stats at first failing group; logs overwritten on pull/resume; SOURCE.json dirty allowed; run_meta lacks library versions; 8 concurrent `uv run`; research.json overwritten per pass | R | triage |
| P9 | DESIGN | Stamp split: shard path = experiments + __main__ + export._clean (pulls 7 extra modules) + lazy xbrl_fallback, edgar_universe; all data csv/json stay in the shard digest. Move `_clean` to a leaf module, explicit SHARD_FILES list, analysis_digest separately; test by executing `company()` and `_one()` and checking sys.modules; shards record `_modules` | R | implement |

## Engine and data (two reviewers agree)
| # | Sev | Finding | V/R | Fix |
|---|---|---|---|---|
| D1 | BLOCKER | Zero revenue = tag-merge bug: `_merge_tags` (facts.py:351) is first-tag-wins and keeps a reported 0 (`Revenues`=0 beside non-zero `SalesRevenueNet`, e.g. Alaska Air, Dentsply); D7 splice check skips level 0 (`rel = 0.0`). 27 firms pick a zero over a non-zero lower tag, 63 have zero quarters inside history. Our seasonal guard only catches a fully zeroed season; `_seasonal` (calibrate.py:133) maps 0/0 to 1.0, so v3 writes finite garbage (log_rev 0, p_breach 1): 33 firms / 52 rows, v2 22 / 23 | V | non-zero lower tag overrides a merged 0; flag splice when level 0; calibrate raises if any reported revenue in the 32-quarter window is <= 0 while history max > 0; `rev_ttm > 0` in `usable()`; count the dropped units |
| D2 | MAJOR | Realized values mix vintages: FY latest minus 9M YTD as first filed -> negative quarters (HP 2014Q4 -26.4bn); 16 firms forecast y < 0, 107 firms structural rev < 0 | R | difference within one vintage |
| D3 | MAJOR | `short_investments` without fillna(0) in `_realized` and `_baseline` (batch.py:227, 245, 350): 23% of revenue keys have no cash row (silent `continue`), rw_sd NaN -> DM vs RW NaN | V | fillna(0) as at batch.py:267 |
| D4 | MAJOR | Student-t tails at df=3: revenue paths up to 3,800bn vs 1.3bn median; crps_twin and density mean/sd distorted (medians robust) | R | owner decision: truncate draws at +-8..10 or flag |
| D5 | MAJOR | Depth grid non-monotone (health rises with a deeper shock): v3 12.4% of rows; feeds plan2.py:490 | R | investigate mechanism (WC release + debt sweep) |
| D6 | MAJOR | DEFAULT_SPEC = "v2-rev" while rev3_server.sh strips FINTWIN_SPEC: any pass relying on the default runs v2-rev under another label | R | set spec explicitly on every line; fail if unset |
| D7 | MINOR | Health ceiling ties (1,862 rows at 100.0), degenerate cash quantiles, literal 0 kept for other tags, sentinels (nd_ebitda 20, icr 100), 1,771 `usable()` skips unrecorded, sobol `simulate` sites without finite check (assumption_sobol.py:183), local companyfacts copy partial | R | triage |

Server count (12-11, all 5,309 firms, origins 2014-2024, `_seasonal` on the data at each origin): 104 firms / 277
firm-years have a seasonal factor of exactly 0 (list: engine/out/zero_rev_1112.txt). These are caught by the current
guard; D1's other cases (zero quarters that leave every factor > 0) are not, so the true count is higher.

## Run state (12-11)
Last run complete except sobol: universe, sample, select, stats (exit 0, `stats_finite.py` wrapper) pulled to
engine/out/; server burst-rev3-1111-2225 (cpx42 x86) deleted, ~16 h, ~1.9 EUR. These numbers are superseded by the
clean rerun.

## Status (updated as packages land; worktree .claude/worktrees/nonfinite)
| # | Status |
|---|---|
| S1 | fixed: `research/cross_spec.py`, `cross-spec` command, stats writes `_results/<run>_cfo_errors.csv`, rev3_server.sh stats stage; tests/test_cross_spec.py |
| D1 | fixed: `_merge_tags` revenue 0 yields to a non-zero lower tag (flag `zero_override`), splice flagged at level 0; calibrate raises on a revenue of exactly 0 in the 32-quarter window (negative quarters stay allowed: MM-F12 handles them, test_F12) |
| D2 | fixed: `_duration_table` pairs the YTD leg as last filed with the first annual filed after it (HP case test); pre-existing D6 tests pass |
| D3 | fixed: fillna(0) on short_investments in `_realized`, `_baseline`, timeline |
| D4 | owner decision A1 revised: no truncation (v2-pre must stay the paper 2.0.0 model); numerical floor `G_LOG_MAX` = 50 on quarterly log growth prevents overflow -> NaN; tails reported as a model property |
| D5 | not a bug: reproduced on CIK0000005981 v3 2024: a deeper shock releases working capital, the cash sweep repays debt (213 -> 0 by q4), the liquidity component rises (34.8 -> 52.8) while coverage falls. Model behaviour; affects only `plan2.episodes` (secondary); reported as is |
| D6 | partly reproduced: labels and applied spec share one default, so no mislabelling; risk of an unintended default remains -> `FINTWIN_REQUIRE_SPEC=1` in rev3_server.sh makes an unset spec an error (tests run without it) |
| D7 | Sobol design point raises on non-finite cfo (counted as a failure) |
| S2 | fixed: primary B2 cell named by rule (shortfall / 8 / Recession); no verdict below 5 year blocks (`MIN_BLOCKS`) |
| S3 | fixed: D8 exclusion in `liquidity_frame` (count reported) and `bk_2020` spans |
| S4 | fixed: Holm family reads `hybrid_train` |
| S5 | (a) fixed: walk-forward candidates on one common set (`n_excluded` reported); (b) firm-year sets across specs: audit RED above 0.1% (WP7) instead of recomputing every test on the intersection; S1 already on the intersection; (c) univariate AUCs on own sets: report n (exists) |
| S6 | fixed in design: base rate from cutoffs <= Y-3, prior from the same years (`rivals.py`) |
| S7 | open MINOR (documented, unchanged): NaN resamples uncounted, auc_table min 3 events, block_ci seed outside SEEDS, tau/lambda not jointly scored, best_benchmark winner's curse, B1 one-sided p (declare in paper) |
| P1-P3, P5, P6 | fixed (WP3), tests in test_C2_spec / bash simulation |
| P4 | fixed: Sobol `_attrition` (every eligible firm-year a row or a recorded failure) |
| P7 | to measure in the dry run |
| P8 | fixed: mkdir, stats groups all run, logs appended, dirty tree refused, library versions; open: research.json overwritten per pass (the per-run copies in `_results/` are the record) |
| P9 | fixed: shard digest = static import closure of the shard entry points; analysis commands in `research/analysis.py`; tests incl. a runtime check |
| WP6 | done: families (82 multi-member, 11 of 488 petitions double counted), family pass, rivals |
| WP7 | done: `scripts/audit_shards.py`; on the 11/12-11 shards it flags all known faults (30 None panel rows, 3 forecasts, 3 covid, 63 firm-years missing in v2, negative revenue 0.11%) |
| WP8 | `RERUN5_SUPPLEMENT.md` on the branch; rev3 wrapper edit reverted; `scripts/stats_finite.py` (untracked) to delete |
