# Review of GROWTH_PLAN workstream B, section 8 and A10 (benchmark designer view)

Scope: GROWTH_PLAN.md (B0-B5, A10, sections 7-8) against REVISION_PLAN_3.md (B2 label, section 4 supplement). No web checks were run. Statements about ForecastBench, TabArena and M5 come from background knowledge and are unverified.

## 1. Blocking problems

**BM-1 (Blocker). Public labels plus CI reruns cannot prevent tuning on test.**
A10 justifies public labels with "the test set already exists in EDGAR". True for raw data, but a benchmark needs a split nobody has tuned on. Rerunning code proves reproducibility, not that hyperparameters, features or seeds were not picked by looking at the 2019-2024 score.
Fix, in layers:
1. Split the test period into a public dev-test (for example 2019-2022) and a sealed final test (2023-2024 row-to-label mapping not in the repo, scored server-side).
2. Make the prospective track (B4) the headline ranking; label the retrospective score "dev".
3. Cap scored submissions per team per quarter, publish every attempt including failures, and show the attempt count next to each score.
4. Roll the sealed test forward yearly (newest label year becomes the new sealed test), as Kaggle and M-competition private holdouts do.

**BM-2 (Blocker). The T2 label in B1 does not match the locked pre-spec label, and the locked label is a proxy.**
REVISION_PLAN_3 section 2 states the target as P(cash + undrawn revolver < 0 within 4/8 quarters). Section 4 (lines 114-121) locks something else: credit event (8-K 1.03, 2.04, 3.01) OR (cash-like < 25% of start AND total debt increase > 5% of TTM revenue). Problems:
- The second clause is a balance-sheet outcome built from the same XBRL fields used as features, so a model can learn the labelling rule rather than distress.
- The label at t+k needs filings that appear 45-90 days after t+k; late filers and exiting firms have a missing second clause, so labels are differentially censored.
- Items 2.04 and 3.01 include routine events (waivers, listing notices). The merger exclusion (2.01/5.01 in the same 8-K) only catches same-filing cases.
Fix: ship T2a (credit-event only) and T2b (balance-sheet rule) as named sub-labels, publish label code plus a label-version hash, state in the task card that T2b is a proxy, and rename T2 so it is not read as "true liquidity shortfall". Align B1 wording with the locked definition.

**BM-3 (Blocker). Censoring and competing risks are undefined for T1.**
Nothing says what happens to firms that leave without a 1.03: mergers, going-private, voluntary delisting, Form 15, Chapter 7 without 8-K, stopped 10-Ks. As negatives they bias the base rate down and reward "will keep filing"; if dropped, selection on the outcome biases it up.
Fix: row-level status at horizon end: event / survived-and-filing / exited-non-distress (M&A, going private, deregistration) / exited-unknown. Primary metric on event + survived rows; exited-unknown as negative only in a published sensitivity variant. Release time_to_event and exit_reason so survival and competing-risk entries are possible. Drop rows whose 8-quarter window is not fully observed (right-censoring at data end). Publish counts per class per year.

## 2. Important problems

**BM-4 (High). 475 events is too few for rank-order leaderboards.**
About 28 events per year; the 2019-2024 test has roughly 150-200 events, strongly clustered (2020 energy and retail, 2023 banks and biotech). AUC CIs are about +/-0.03-0.05 (my estimate), so most baselines will be statistically tied.
Fix: cluster bootstrap CIs (firm, then year blocks), paired bootstrap or DeLong vs the best baseline, rank bands ("tied with") instead of strict ranks (TabArena-style Elo with bootstrap CIs). One primary metric per task fixed in the pre-spec: T1 PR-AUC plus Brier skill vs base rate; AUC secondary; add recall at top-1% of firms.

**BM-5 (High). Calibration is not rewarded by the setup.**
Base rate varies roughly 10x across years. Add reliability/Murphy decomposition (already in the paper B2), ECE with a fixed binning rule, per-year calibration-in-the-large. Clip probabilities in the scorer (for example [1e-6, 1-1e-6]) so one 0.0 does not destroy log loss. Forbid use of the test-year base rate.

**BM-6 (High). Split design.**
"Train <= 2016, val 2017-2018, test 2019-2024" has issues:
- Purge: with 8-quarter labels, a 2016-Q4 training row has its label realized in 2018, overlapping validation. State the rule in horizon terms: a training row is allowed only if its label window ends before the first evaluation cutoff.
- 2020 is the single shock year; one cut gives one number dominated by COVID handling. Use expanding-window walk-forward with several origins (for example test years 2017, 2019, 2021, 2023), per-year tables, and "2020 excluded" / "2020 only" breakdowns.
- Training on 2009-2016 puts the post-crisis wave in train and a milder regime in test; say so in the task card.
- The B1 test window (2019-2024) differs from the paper cutoffs (2015/2020/2022, REVISION_PLAN_3 line 92); B1 says "or exactly the paper cutoffs". Pick one before running anything.

**BM-7 (High). Leakage channels not addressed.**
- Same firm in train and test: normal for temporal splits, but IDs let GBMs memorize firm levels. Drop or hash CIK, name and ticker by default; offer an optional firm-disjoint protocol.
- Feature dates: define the cutoff on the filed date, not period end. The loader must enforce filed <= cutoff; restatements (10-K/A, later comparatives) must not be visible. Late filers (NT 10-K) have features arriving after the nominal cutoff, so eligibility must be by filing availability.
- Macro: after the section 8 license table, macro is either absent or revised series. NBER USREC is announced with a 6-18 month lag, so a contemporaneous recession flag is look-ahead. Ship macro only with available_at stamps, or exclude it from the default track.
- Delisting: any market fields must not be backfilled after delisting.
Fix: a CI leakage audit that checks max(filed) <= cutoff for every row and fails the build; publish the result per release.

**BM-8 (High). Untrusted code in GitHub Actions, and compute caps.**
Risks: secret exfiltration (pull_request_target), crypto mining, network access to fetch sealed labels, hosted runner limits (6 h job, small CPU runners, no GPU on standard runners; not verified for current plans) that cannot host TabPFN or large GBM runs.
Fix:
1. Use unprivileged pull_request, no secrets, read-only token, hash-pinned env, no network after install, hard time and memory caps. Never check out PR code under pull_request_target.
2. Two stages: the untrusted job produces a predictions artifact; a trusted job scores it with the sealed labels.
3. Resource classes: "CPU-small, 30 min" verified in CI; larger entries rerun by the maintainer on the burst server and marked "maintainer-rerun".
4. Alternative: accept prediction files, mark "self-reported", and rerun only the top-N before marking "verified".

**BM-9 (High). The prospective track has almost no power in year one and underspecified rules.**
Roughly 7 events per quarter in the whole universe; the first 4-quarter label for a 2026-Q4 prediction resolves in 2027-Q4, 8-quarter ones in 2028. After year one there are at most about 25-30 events; a 0.05 AUC gap needs hundreds.
Fix:
- Say in B4 that year one is a process pre-registration with no ranking claim; publish expected event count and CI width up front.
- Add tracks that resolve faster: 1-quarter-ahead, the broader credit-event label, and T3 CRPS (resolves every quarter for thousands of firms).
- Commit contents: Parquet of (cik, asof accession, horizon, probability or quantiles), dataset snapshot hash, code commit hash, public timestamp (Zenodo DOI or OpenTimestamps) before any possible resolution.
- Freeze the universe at commit date (all firms with a recent 10-K/10-Q), including firms that later vanish.
- Calendar-fixed cadence and external deadline (ForecastBench-style rounds); commit baselines before the deadline and never change them.
- Fixed resolution rule: what counts as resolved, handling of late filers and exits (BM-3).

**BM-10 (Medium-High). Versioning with weekly revisions.**
Version the benchmark, not the dataset: bench-vX.Y = frozen snapshot (dataset DOI, label hash, split-file hash). Weekly builds are a separate channel. Patch = scorer bug (rescore all), minor = new task, major = new split or label rule. Stamp the snapshot hash in each submission and leaderboard row; keep old leaderboards readable. Prospective predictions are never rescored.

**BM-11 (Medium). Errata policy.** Section 7 says fixes go to "the next weekly build"; for a benchmark a label fix is a rescoring event. Define who may request it, evidence needed, one batch per quarter, diffs published.

**BM-12 (Medium). Baseline set is incomplete.**
B1 has Altman Z-double-prime, Ohlson O, logit, 16q margin, LightGBM, FinTwin. Add: base rate / last-year-event, Shumway discrete-time hazard, CatBoost and XGBoost (default and tuned), random forest, TabPFN (current release), AutoGluon at a fixed budget. For T3: random walk, seasonal naive, ETS/AutoARIMA, a pretrained TS model (Chronos or TimesFM) zero-shot, empirical-quantile residuals. State tuning budgets and that tuning used only pre-test years. A weak GBM baseline invites the "baselines too weak" critique that TabArena was built to avoid.

**BM-13 (Medium). Unit of evaluation.** Define firm-quarter vs firm-year; consecutive overlapping labels are dependent, so cluster by firm (BM-4). Do not release a downsampled test set; weighting is a scorer option, not the default.

## 3. Missing opportunities

**BM-14 (Opportunity). One default task and a one-line evaluation.** Front page: T1-4q, PR-AUC, walk-forward; T2 and T3 as extra tracks. One command (fintwin-bench run model.py, or evaluate(preds)), with Altman, LightGBM and TabPFN scores on the first screen.

**BM-15 (Opportunity). Paper and durable identity.** Short datasets-and-benchmarks paper (pre-spec, label audit, baseline table with CIs, leakage audit), datasheet, Croissant metadata, Zenodo DOI per benchmark version, CITATION.cff. Keep B0 findings phrased as "we did not find".

**BM-16 (Opportunity). Leakage as the hook.** Publish a "first-reported vs restated" ablation: same model, same split, score gap. No other bankruptcy benchmark can show this; it ties workstream R to B.

**BM-17 (Opportunity). Relative scoring for the prospective track.** ForecastBench-style relative Brier vs a committed baseline; Brier skill vs base rate and paired differences vs the best baseline, so quarters with many events do not dominate.

**BM-18 (Opportunity). Decision metrics.** Lift and recall at top-k and an optional cost-ratio utility for practitioners.

## 4. Concrete plan edits (section/item -> change)

- A10 -> "Dev labels public; final test sealed and rolled yearly; prospective track is the headline; scored attempts capped and published" (BM-1, BM-9).
- B1 T1 -> add status taxonomy, time_to_event, exit_reason, right-censoring rule; primary PR-AUC + Brier skill, AUC secondary, cluster-bootstrap CIs (BM-3, BM-4, BM-5).
- B1 T2 -> split into T2a and T2b, state the proxy, reconcile with REVISION_PLAN_3 sections 2 and 4 (BM-2).
- B1 splits -> walk-forward origins, horizon purge, sealed final test, 2020 breakdowns, cutoff on filed date; resolve 2019-2024 vs paper cutoffs now (BM-1, BM-6, BM-7).
- B1 baselines -> add base rate, Shumway, CatBoost/XGBoost, RF, TabPFN, AutoGluon; T3 time-series baselines; state tuning budgets (BM-12).
- B2 fintwin.bench -> enforce filed <= cutoff, leakage-audit command, probability clipping, hashed IDs, snapshot hash in the submission format, one-line evaluate (BM-5, BM-7, BM-10, BM-14).
- B3 leaderboard -> two-stage unprivileged CI, no secrets or network, resource classes, maintainer-rerun label, show attempts, CIs, rank bands (BM-1, BM-4, BM-8).
- B4 prospective -> fixed calendar and deadline, frozen universe, commit contents and timestamp, fast-resolving tracks, no year-one ranking claim, published expected event count (BM-9, BM-17).
- B5 -> cover the extra baselines and record compute time; check whether TabPFN fits cax21 (unverified).
- Section 7 -> add risks: leaderboard overfitting on public labels, untrusted CI code, label errata (BM-1, BM-8, BM-11).
- Section 8 -> add versioning and errata policy (BM-10, BM-11).
- New B6 -> D&B paper, default task, first-reported vs restated ablation, Croissant, datasheet, DOI (BM-14, BM-15, BM-16).

## Verified vs not verified
- Verified by reading: A10, B0-B5, sections 7-8; REVISION_PLAN_3 B2 label (section 4, lines 114-121), the Y-3 walk-forward rule, the cutoffs 2015/2020/2022 (line 92); the B1 vs pre-spec mismatch.
- Not verified: ForecastBench, TabArena and M5 practice; GitHub Actions limits; per-year event counts (derived as 475/17, not from data); TabPFN hardware needs.
