# Revision plan 5: corrections from the external review, pooled parameters and filing text 

Status: **approved by the author on 18-11-2026.** None of the new specifications or tests below has
code or results yet.

**Already known when this plan was written.** These are listed so a reader can see what the design could have been
fitted to:
- The plan-3 and plan-4 results, including the 2021 real-time-recession run (P4-8) and the pooled regression ML1.
- The review's univariate downturn correlations.
- A synthetic check of the v3 cost split, which recovers the true fixed share with a cost bias at current revenue
  below 0.4 points of revenue (`engine/tests/test_cost_split_review.py`).
- Code that already exists:
  - the real-time recession switch `SW17` and its table of NBER announcement dates;
  - the `ma_flag` written by the calibration.

After approval, the file is:
- committed;
- timestamped with OpenTimestamps (`docs/REVISION_PLAN_5.md.ots`);
- pushed before any code for it is written.

After that it changes only through dated addenda, each committed and timestamped before the results it governs.

## Why this plan exists

**Sources.**
- **An external technical review of the code and the paper** (14-11-2026). It audited the October revision; its
  findings are mapped to the current code in the author's working notes.
- **The cover note of a senior colleague.** Two of its points are analyses:
  - the per-firm simulations learn nothing from other firms;
  - the filings carry information beyond their numbers.

**The author's decisions (18-11-2026).**
- Every point is addressed in this paper, including pooled parameters and filing text.
- H3 is retested with smoother liquidity mechanics.
- The paper is not submitted before this plan is complete.

**Prior verdicts.** The verdicts of plans 3 and 4 are final and are not re-decided here. The statistics corrections
S1 to S8 below also recompute some statistics behind those verdicts, and S4 changes a rival named in the H2 rule. The
old verdicts stand as reported. If a corrected statistic would give the other verdict, the paper reports both, says
which correction causes the difference, and does not re-label the old verdict.

**What can be confirmatory.** Every specification in this plan is designed after their results and after the
review. **Therefore nothing in this plan is confirmatory on the 2014–2024 history.** The historical results below are
labelled **P5-descriptive**, and each comes with a reading rule fixed here. The only confirmatory test (P5-8) is
prospective.

## Data and runs

**Snapshot.**
- The XBRL snapshot, universe, census and lock file are those of plan 3 (snapshot `f0f6e091b610da1d`).
- Filing text (P5-6) adds a second frozen snapshot, `text_snapshot`. It is built once, recorded by digest in every
  result, and holds:
  - the 10-K and 10-Q documents filed on or before each cutoff;
  - for each document, its accession number and filing date.

**Platform.**
- Every simulation of this plan runs on ARM (Hetzner cax). Earlier runs were on x86, so v3-wf is rerun in the same
  run as the new specifications.
- **Reproduction check.** The ARM v3-wf transmission errors are compared with rerun 5, firm-year by firm-year. A
  median absolute difference above 0.05 points of revenue, or more than 1% of firm-years differing by more than
  0.5 points, stops the run before any new specification is read.

**Paths and seeds.** 1,500 paths, seed 5, 12 quarters, the same draws as plans 3 and 4. Bootstraps use B = 2,000.
The 17-test Holm family uses B = 10,000 (see S2).

**Stamping.** Each specification has its own cache label and digest, as in rerun 5. Analysis-only modules are
outside the shard digest.

## Corrections applied to every specification (outcomes, benchmarks)

Outcomes and benchmarks must be the same for every model compared. These changes therefore apply to all
specifications, including the v3-wf baseline rerun. Each count of what a change removes is reported.

| ID | Change | Review item |
|---|---|---|
| O1 | Dividends, CFO or capex not tagged in an outcome quarter make that outcome missing, not zero. A dividend cut needs four reported quarters on both sides | 4.2.5 |
| O2 | Outcome windows that are not contiguous are excluded (the existing check), and the count is reported by cutoff | 4.2.4 |
| O3 | Ohlson's size term uses total assets deflated to 2014 dollars with the GDP deflator, as in Ohlson (1980) | 4.3 |
| O4 | Calibration failures are reported by type, cutoff and company count as attrition. A Heckman-style check is not attempted. Firm-years that fail are compared with those that pass on size, margin and petition rate | 4.2.6 |

## The specification ladder

Each rung adds to the previous one. All rungs keep v3's walk-forward hyper-parameters (selection `d20049b4d5b431d8`)
unless the rung re-selects them, and say so.

| Rung | Content | Review item |
|---|---|---|
| v3-wf | Baseline, rerun on ARM | — |
| **v4a** | v3 plus model corrections: G2 real-time recession dates, G3 liquidity mechanics, G4 loss carryforward, G5 dividend run-rate | 4.2.7, 4.2.1, 4.3 |
| **v4b** | v4a plus G6 acquisitions and divestitures | 3.2, rec. 5 |
| **v4p** | v4b plus P1 pooled structural parameters | colleague, point 3a |
| **v4t** | v4p plus T1 and T2 filing text | colleague, point 3b |

### Model corrections (v4a)

- **G2: real-time recession dates.**
  - The regime's entry hazard, exit probability and current state use only the turning points NBER had announced by
    the cutoff. For each turning point, its date and announcement date are taken from nber.org/research/business-cycle-dating.
  - Months after the last announced turning point keep the regime that point opened.
  - The existing switch SW17 (current state only) is extended to the hazard and the exit probability.
- **G3: liquidity mechanics.**
  - The treasury's cash target is 40% of opening cash, below the 50% event threshold, and is no longer 60%.
  - Dividends are cut in proportion to the shortfall of interest coverage below 2.5. The paid share is
    min(1, ICR / 2.5), floored at 0, so the cut is not all-or-nothing.
  - The cash-floor condition is smoothed in the same way.
- **G4: loss carryforward.** Losses accumulate in a carryforward balance that offsets later taxable income. There is
  no limit and no expiry. Opening carryforward is 0, because XBRL tagging of deferred tax assets is too sparse to
  calibrate it.
- **G5: dividend run-rate.**
  - The run-rate is the trailing four-quarter sum divided by four.
  - A quarter whose dividend exceeds 3 × the median of the other three is treated as special and replaced by that
    median.
- **G7: bound on the F3 adjustment.** The F3 move of fixed costs toward f × revenue is capped. The fixed cost after
  the move must stay within [0.5, 2] × its calibrated value. This bound was deferred to "v3.1" because it changes the
  model; it is fixed here before any v4 result.
- **G8: rating of a missing coverage ratio.** A missing (NaN) interest-coverage ratio is rated D, not AAA, as in
  `ratings.rating_rank` and the web model (W6).
- **G9: opening cash.** Opening cash uses the same stale-balance rule as every other stock (EC-06).
- **G10: interest-expense sign.** Interest expense reported as a negative number is read as a cost (D22). The current
  code shares the capex sign rule.

**No cost-block rung.** The review's cost-split check was rerun through the full v3 fitting path: TTM basis, inflation
deflator, revenue guard, posterior split, with and without 15% seasonality. The bias at current revenue was at most 0.4
points of revenue at quarterly growth of −2%, 0, 1.2% and 3%. The estimated fixed share was 0.01–0.09 for a true 0, and
0.26–0.46 for a true 0.35. The level bias the review found came from the revision-2 estimator and is absent from v3.
Rebasing F to trend revenue is therefore not added. The check stays as a unit test.

**Reported for every rung.** Two headline failures of plan 3 are reported with their plan-3 statistics:
- the elasticity ratio and its interval, against the pre-specified range 0.8–1.25;
- the count of explosive firm-years, with the plan-3 definition.

### Acquisitions and divestitures (v4b)

**G6: flag.** A firm-year is flagged when any of these holds in the last eight quarters before the cutoff:
- payments to acquire businesses (net of cash acquired) exceed 10% of trailing revenue;
- proceeds from divestitures exceed 10% of trailing revenue;
- revenue and total assets both change by more than 25% quarter on quarter in the same quarter.

The flag is stored for every specification.

**G6: model change in v4b.** In the realized-revenue test, the fixed cost of a flagged firm-year scales with revenue.
The intuition is that revenue bought or sold comes with its cost base. The fixed cost becomes F_t = F × (rev_t / rev_0)
for the quarters after a flagged quarter.

**Which flag the rungs use.** v4b, v4p, v4t and the selection rule of P5-8 use only this ex-ante flag, together with
the T1 acquisition feature in v4t.

**Hindsight variant.** A second flag is computed on the eight outcome quarters with the same rule. It is reported in
one labelled side result: the realized-revenue test with and without flagged firm-years, and v4b with the hindsight
flag. It never enters a rung or the selection.

### P1: pooled structural parameters (v4p)

**Parameters pooled.** These are the calibration's existing parameters, each estimated per firm with a standard
error:
- cost elasticity, `v / median(costs/revenue)`. Its standard error is the posterior s.d. that `_posterior_split`
  already returns.
- `dso`, `dio`, `dpo`. Each is a four-quarter mean, with standard error equal to the quarterly s.d. over √4.
- `capex_ratio` and `ocf_ratio`. Each is an eight-quarter median, with standard error from the window's s.d. over √8.
- the buyback ratio `bb_ratio`, with standard error from the window's s.d.
- the financing response `refi_ratio`. It has no window standard error, so it is pooled with a fixed weight of 0.5.

**Not pooled.** The dividend `div_q` is a policy level, not a response, so it stays firm-specific.

**τ re-selection.** For cost elasticity the pooled prior replaces the fixed 35% prior mean. τ is therefore re-selected
walk-forward under v4p, with the same rule and grid as v3.

**Pooled prior.** For cutoff Y, the prior for industry j is the median of the firm estimates in j at cutoffs
≤ Y − 3, computed with the same walk-forward data rule as the existing selection.
- Industries with fewer than 30 firm-years fall back to the all-firm median.
- The spread of the prior is the cross-firm interquartile range divided by 1.349.

**Posterior.** Each firm's value is the precision-weighted average of its own estimate and the prior (normal–normal
empirical Bayes). The firm's precision comes from its own standard error over its 16-quarter window.

**Rung variants.** v4p uses the shrunk values. A descriptive variant, v4p-pool, uses the prior alone.

**Comparison.** The reduced-form pooled model of plan 4, ML1, is retained as a rival.

### T1 and T2: filing text (v4t)

**Documents.** Only documents filed on or before the cutoff are used: the latest 10-K, and the 10-Qs after it.

**T1, facts stated in the filing.** Each is a binary or count feature from a keyword and pattern extractor with
published patterns:
- going-concern language;
- a covenant breach or waiver;
- an announced or completed acquisition or divestiture not yet in the numbers;
- an announced restructuring plan with its stated cost;
- a dividend suspension or initiation announced.

A held-out set of 200 filings is labelled by the author to measure the extractor's precision and recall. These are
reported, and the extractor is frozen before any outcome is read.

**T2, judgement.** Features are taken from the MD&A and risk-factor sections:
- tone;
- outlook direction;
- liquidity concern.

**Model and vintage.** The features come from a **chronologically consistent language model**: ChronoBERT (He, Lv,
Manela and Wu 2025). Yearly vintages exist from 1999-12-31 to 2024-12-31, about 0.1B parameters, MIT licence.
- For a cutoff on date d, the model is the latest vintage whose training data end **before d**. For the mid-February
  cutoffs of year Y, that is the vintage ending 31 December of Y−1.

**Scoring.** The features are embeddings reduced to three scores by a ridge model trained walk-forward on the existing
outcome labels, using cutoffs ≤ Y−3.
- Embeddings from different vintages are not comparable. For each test year Y, the training filings are therefore
  **re-embedded with Y's vintage**. This means 11 embedding passes over the training filings.
- Size: about 21k firm-years, with up to 4 sections each, which is about 2 million embeddings. On ARM CPUs this is a
  server job whose time is measured in the D4 probe.

**Fallback.** If a vintage cannot be loaded without the flash-attn library, T2 is missing for that year, and the paper
reports the years it covers.

**Use in the twin.**
- T1 acquisition flags feed G6 ex ante.
- The restructuring cost enters the cost path as a one-off.
- The going-concern and covenant features scale the market-access state at the start.
- T2 scores shift the margin-shock mean by a walk-forward-estimated coefficient.

**Use in the pooled model.** ML2 is ML1 plus T1 and T2.

## Statistics corrections (all analyses)

| ID | Change | Review item |
|---|---|---|
| S1 | Every levels and accuracy comparison uses one common firm-year set per table, and the set's size is reported. Per-model samples are shown only in a supplement table | 4.1.3, rec. 2 |
| S2 | The 17-test secondary Holm family uses B = 10,000 and p = (1 + k)/(B + 1). No p-value below m/(B + 1) is printed | 4.1.5, rec. 4 |
| S3 | Winsorization limits come from training years everywhere | 4.3 |
| S4 | The industry-shrunk margin's weight grid is {0, 0.1, …, 0.9}. The effective number of distinct rivals is reported per year | 4.2.2, rec. 9 |
| S5 | The downturn result is reported with univariate correlations per year, with and without each control, and with abnormal burn measured against a 16-quarter run-rate | 4.1.4, rec. 3 |
| S6 | H2 is reported with the same statistic for every rival beside the simulator's | Sec. 5 |
| S7 | The neighbouring prior values (τ) are reported beside the selected one | Sec. 5 |
| S8 | Four corrections deferred to v3.1 are made here: R6 floors the minimum of cumulative FCF; R9 makes `plan2.calibration` respect filing dates; R13 uses one log-loss definition throughout; R16 counts and reports the Sobol caps | QUALITY_PLAN |

The product backtests (`backtest/batch.py`, deferred item R1) are not part of the paper. They are routed through the
research calibration in the same release, and `docs/BACKTEST.md` says so.

## Run size

| Rung | Sample | Reason |
|---|---|---|
| v3-wf | full universe | reproduction check and baseline |
| v4a, v4p | full universe | rungs with a reading rule |
| v4t | full universe | rung with a reading rule |
| v4b | full universe | its reading uses the flagged firm-years only |
| v4p-pool, hindsight G6, text placebo, vintage-difference | 1,000-firm subsample, as for the plan-3 ladder | descriptive side results |

**Estimate.** Five full passes plus four subsample passes. Rerun 5's plan estimated about 18 h for its full set (its
actual hours were not recorded). The new set is about 1.5–2 times that, about 30–40 h on cax31 (8 vCPU, 0.034 €/h),
roughly 1.5 €. The text embeddings are added on top, at the size measured by the D4 probe. Actual hours and EUR are
recorded in each run's metadata.

## Tests

All P5-descriptive tests use cutoffs 2014–2024. Rivals with a training window are tested where it allows (as in
plan 4). Intervals are t(G−1) over yearly statistics, with the firm-block bootstrap beside them.

### P5-1 Corrections (P5-descriptive)
- **Statistic.** Difference in median absolute error of eight-quarter CFO, given realized revenue: v4a − v3-wf, on
  the common set.
- **Reading.** "The corrections lower the typical error" if the 95% upper bound is below 0. "They do not change it"
  if the interval contains 0.

### P5-2 Acquisitions (P5-descriptive)
- **Statistics.**
  - v4b − v4a on flagged firm-years.
  - The share of flagged firm-years.
  - The v3-wf errors with and without flagged firm-years, compared against N3.
- **Reading.** As in P5-1, on the flagged set.

### P5-3 Pooling (P5-descriptive)
- **Statistics.** v4p − v4b and v4p − N3, as in P5-1. ML1 is reported beside them.
- **Reading.**
  - "Pooling helps" if the v4p − v4b upper bound is below 0.
  - "The twin then beats persistence" only if the v4p − N3 upper bound is also below 0.

### P5-4 Text (P5-descriptive)
- **Statistics.** v4t − v4p and ML2 − ML1, as in P5-1. Brier and AUC for the shortfall and petition labels, with
  and without text.
- **Look-ahead controls,** all reported:
  1. The vintage rule.
  2. A masked-identity placebo: the company name, ticker, auditor and city are replaced. A T2 effect that
     disappears under masking is read as memorization.
  3. A vintage-difference test: T2 is recomputed with the 2024 vintage for every year. A gain that appears only with
     the later vintage is read as look-ahead. The Lookahead Propensity test of Gao, Jiang and Yan is not used,
     because it is defined for generative models.
  4. A keyword baseline (Loughran–McDonald word lists) in place of T2.
- **Reading.** "Text adds information" only if the gain survives controls 2 and 4, and control 3 shows no larger gain
  for the later vintage.

### P5-5 H3 with smooth mechanics (P5-descriptive)
- **Comparator.** The loop-free v4a must produce each event in at least 2% of firm-years. Events for which it does
  not are reported but not tested.
- **Statistic.** For each event, the AUC gain of the full v4a over the loop-free v4a, with a firm-block interval.
- **Reading.** H3 is supported for an event if the interval is above 0. If no event meets the comparator rule, H3 is
  dropped from the paper.

### P5-6 Distribution and stress, repeated (P5-descriptive)
The CRPS and shortfall tests of plan 3, repeated for v4a, v4p and v4t on the same rivals.

### P5-7 Unconditional forecasts, repeated (P5-descriptive)
- The P4-1 unconditional test, repeated for the best rung of P5-1 to P5-4, chosen by the rule in P5-8.
- G6 uses only the ex-ante flag here.

### P5-8 Prospective test (confirmatory)
- **Specification.** The rung with the lowest mean of yearly median errors on 2014–2024 in P5-1 to P5-4 (ties go to
  the simpler rung) becomes the "selected specification".
- **Archive.** From the first weekly build after this plan's run, the public archive stores the selected
  specification's forecasts next to v2-rev's and N3's, without realized revenue (as in P4-1).
- **Test.** After eight quarters of outcomes for at least two cutoff years: P4-1's confirmatory test A on those
  cutoffs only.
- **Reporting.** This paper reports the design and the archive. The result belongs to a later note.

## What this plan does not do

- It does not re-decide plans 3 and 4.
- It does not tune any rung on test-year outcomes.
- It does not use language models other than the dated vintages in T2.
- It does not use any information filed after a cutoff, except the realized-revenue flag of G6, which is labelled.

## Choices made by the author at approval (18-11-2026)

1. **G3 constants.** The main rung uses a 40% cash target and a proportional dividend cut. A pre-specified
   sensitivity analysis on the 1,000-firm subsample repeats v4a with cash targets of 30% and 45%. It is reported
   descriptively and does not change any rung.
2. **T1 labelling.** The author labels the 200 validation filings alone. The labels are frozen, committed and
   timestamped before the extractor is run on them.
3. **P5-8 archive.** The archive starts with the first weekly build after this plan's run.
