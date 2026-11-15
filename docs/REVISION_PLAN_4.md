# Revision plan 4: pre-specified additional analyses (written before any of their statistics)

Status: written 2026-11-16, **before** any code for these analyses exists and before any of their statistics has been
computed. This file is committed, timestamped with OpenTimestamps (`docs/REVISION_PLAN_4.md.ots`), and pushed to the
public repository **before** the first run. After that, it changes only through dated addenda at the end, each
committed and timestamped before the results it governs.

## Why this plan exists

The third mock review of the paper (`docs/paper/peer-review-simulation.md`, round 3) found that:
- almost no forecast in the paper is ex ante: Pillar A and the density test give the models the realized revenue;
- the paper tests a single model;
- several statistics a forecasting referee expects are missing: the mean-loss model confidence set,
  inference robust to 8–11 year clusters, a scale-free error measure, stronger density rivals, a recalibrated
  shortfall probability with a cleaner label, and a quantified NBER look-ahead.

Revision plan 3's (`REVISION_PLAN_3.md`) verdicts are final and are not re-decided here. Every test below is new. It
is labelled **P4-confirmatory** or **P4-descriptive**, it is reported in its own section of the paper, and the paper
says that these tests were specified after the results of plan 3 were known.

## Data and runs

- **Snapshot and code.** The same frozen snapshot (digest `f0f6e091b610da1d`), universe, census and lock file as
  plan 3. v3 runs with its walk-forward hyper-parameters (selection `d20049b4d5b431d8`), unchanged. The known v3.1
  issues are **not** fixed here, because that would make a new model: the F3 bound, R1, R2 (except P4-8) and W6.
- **Existing outputs.** P4-3 to P4-9 reuse the per-firm outputs of the plan-3 full run
  (`engine/out/stats_1114/results_stats.tgz`, specs v2-pre, v2-rev, v3, v3-wf). No re-simulation is needed.
- **New simulations (server only).**
  - P4-1, unconditional run: for every firm-year in the transmission panel, v3-wf is calibrated exactly as in plan 3
    and run under the **baseline scenario with its own simulated revenue**. It uses 1,500 paths, seed 5, 12 quarters
    (the same draws as the panel's `base` run). The run stores 21 quantiles (0, 0.05, …, 1) and the median of the
    path totals of eight-quarter revenue, operating cash flow and FCF, each in % of trailing four-quarter revenue.
  - P4-8, real-time regime run: the cutoff 2021-02-15 only, v3-wf with the existing real-time recession switch
    `SW17`, the same paths and seeds as the transmission run.
- **Outcomes.** Realized outcomes, exclusions (firm-years inside a bankruptcy, the first petition per case, the
  merger exclusion) and the firm-year sets are those of plan 3, unless a test below defines its own.
- **Bootstraps.** B = 2,000. Seeds are fixed in `fintwin/research/plan4.py`, and each is recorded with its result.

## Tests

### P4-1 Unconditional point and density forecasts (P4-confirmatory)
- **Target.** Cumulative operating cash flow over the eight quarters after the cutoff, in % of trailing revenue
  (as in plan 3), on the firm-years that have an outcome. Test years are the cutoffs **2017–2024**; earlier cutoffs
  train the rivals.
- **Forecasts.** None of them sees future revenue.
  - **T1u:** the median of the unconditional simulator's path totals.
  - **R1u:** the 16-quarter cash-flow margin times a random-walk revenue forecast (each of the next eight quarters
    equals the same quarter of the last year, the seasonal random walk). The result is expressed as
    `m16 × (sum of forecast revenue) / trailing revenue × 100`.
  - **R2u:** the 16-quarter margin times the simulator's own median revenue path. This rival isolates the cost
    mechanics from the revenue forecast.
  - **R3u:** the four-quarter cash-flow margin times the seasonal random walk.
- **Confirmatory test A.** The statistic is the difference in median absolute error, T1u − R1u. It uses a t(G−1)
  interval over the G = 8 yearly differences of medians. *Success:* the upper 95% bound is below 0. Reported
  alongside: a Diebold–Mariano test of the mean absolute difference with two-way clustering, the wild-cluster
  bootstrap of P4-5, and the sign test over years.
- **Confirmatory test B (density).**
  - The simulator's predictive distribution is the 21-quantile distribution (CRPS by the quantile approximation,
    as in plan 3).
  - The rival is R1u plus the empirical distribution of R1u's residuals on cutoffs up to Y−3, pooled over firms.
  - The statistic is the mean CRPS difference, with a Diebold–Mariano test under two-way clustering.
  - *Success:* the simulator's CRPS is lower, with one-sided p < 0.05. The PIT histogram and 90% coverage are
    reported.
- **Descriptive.** The combination R1u + w(T1u − R1u), with w chosen each test year on earlier years over the grid
  0, 0.05, …, 1 by winsorized MAE (bounds from training years). The gain is reported under winsorized MAE,
  median AE and raw MAE.

### P4-2 A second model under the same protocol (P4-confirmatory for its own test; descriptive otherwise)
- **Model ML1.** A pooled, walk-forward **median (LAD) regression** of the eight-quarter outcome, in the spirit of
  pooled cross-sectional earnings and cash-flow models (Hou, van Dijk and Zhang 2012). It uses only information the
  transmission rivals also have: the margins m4, m8 and m16 of CFO, the realized eight-quarter revenue relative to
  trailing revenue (as in Pillar A), the FCF margin, capex/revenue, cash/revenue, debt/assets, revenue volatility,
  the fixed-cost share estimate, log revenue, and industry (FF12) dummies.
- **Estimation.**
  - Features are winsorized at the 1st/99th percentiles of the training years.
  - The model is trained for test year Y on cutoffs up to Y−3 (outcomes observable), with statsmodels QuantReg at
    q = 0.5.
  - Quantile regressions at the 21 quantile levels give its predictive distribution, rearranged so the quantiles
    are monotone.
- **Confirmatory test.**
  - The same statistic and rule as P4-1 test A, ML1 against N3, on the test years 2017–2024 and the common
    firm-years of the plan-3 transmission frame.
  - The point is to show whether the protocol can detect a model that beats persistence: *success* means ML1's
    upper bound is below 0.
- **Descriptive.**
  - ML1 enters the levels table and the encompassing regression, together with T1 and N3, on the same firm-years.
  - It enters a combination N3 + w(ML1 − N3).
  - Its CRPS is scored against the plan-3 rivals.
  - The MCS of P4-3 is recomputed with ML1 added, as a 20th forecaster.

### P4-3 Model confidence set under mean loss (P4-descriptive)
- **Forecasters.** The 19 forecasters of plan 3 (`transmission.MODELS` + `COMBOS`), operating cash flow, on common
  firm-years.
- **Method.**
  - Loss is (a) absolute error winsorized at training-year bounds and (b) raw absolute error.
  - The test is the Hansen–Lunde–Nason MCS at α = 0.10, using `stats.mcs` with the existing firm×year bootstrap.
- **Reported.** Every forecaster's MCS p-value is reported.

### P4-4 Wild-cluster and randomization inference by year (P4-descriptive)
- **Statistics.** These are re-tested:
  - S1 (v3 − v2-pre, median AE);
  - T1's encompassing coefficient (levels regression of the plan-3 encompassing test);
  - the winsorized-MAE gain of N3+T1 over N3;
  - P4-1 test A.
- **Methods.**
  - (i) The wild-cluster bootstrap by year with Webb six-point weights, null imposed, B = 9,999. For the
    median-based S1 the bootstrap is applied to the yearly differences.
  - (ii) The randomization (sign-flip) test over years: exact enumeration, 2^G.
- **Reported.** Two-sided p-values.

### P4-5 Scale-free errors (P4-descriptive)
- **Relative error.** For each forecaster F, the relative absolute error |e_F| / |e_N3| per firm-year, on common
  firm-years (rows where |e_N3| < 0.01 pp are dropped and counted).
- **Reported.**
  - The geometric mean (GMRAE) and the median relative absolute error, with firm×year bootstrap CIs.
  - The share of firm-years in which F beats N3.
  - Plan-3 median and mean AE excluding firm-years whose trailing revenue is below 25% of their own 16-quarter mean
    quarterly revenue × 4 ("near-zero base"), with the excluded count.

### P4-6 Stronger density rivals (P4-descriptive)
- **Rival H.** A heteroskedastic empirical distribution: the N3 residual for firm-year (i, Y) is standardized by the
  firm's own volatility s_i. s_i is the standard deviation of the firm's quarterly CFO margin over the 16 quarters
  before the cutoff × √8, floored at the 5th percentile of the training years. The pooled standardized residuals of
  cutoffs ≤ Y−3 are rescaled by s_i.
- **Rival Q.** A linear quantile regression of the N3 residual on log revenue, revenue volatility and s_i, at the
  21 levels, trained on ≤ Y−3 and rearranged.
- **Reported.**
  - Mean CRPS of T1 (conditional, plan 3), H and Q, with Diebold–Mariano tests under two-way clustering.
  - The PIT histogram and 90% coverage.
  - The PIT and coverage of v2-pre and v2-rev on the same firm-years.

### P4-7 Recalibrated shortfall probability and a cleaner label (P4-confirmatory for (a) on label L2; the rest descriptive)
- **Labels.**
  - **L1:** the plan-3 shortfall label.
  - **L2:** a petition (first Item 1.03 of a case), an acceleration (Item 2.04, merger exclusion as in plan 3) or
    the cash criterion of plan 3. Delisting notices (Item 3.01) are excluded.
  - The eight-quarter Recession cell and the eight-quarter baseline cell are both reported.
- **(a) Recalibration.** Isotonic regression of the label on the simulator's probability, fitted on cutoffs ≤ Y−3
  (labels observable at the cutoff, `known_by`), applied to year Y. The rival is the plan-3 logit refitted on the
  same label and the same training years.
  - *Success (L2, eight quarters, Recession cell):* the Brier skill score of the recalibrated simulator against the
    logit is above 0, with a firm-block 95% interval that excludes 0.
- **(b)** The firm-block interval that `RERUN5_SUPPLEMENT.md` S2 promised for the plan-3 decisive cell, reported
  beside the year-block interval.
- **(c)** The Murphy decomposition for every cell.

### P4-8 NBER look-ahead (P4-descriptive)
- **Comparison.** The real-time regime run (2021-02-15 cutoff) against the plan-3 run on the same firm-years.
- **Reported.**
  - The share of firm-years whose opening regime differs.
  - The change in median and mean AE and in mean CRPS of T1.
  - The change in the eight-quarter Recession-cell Brier score.
- **Other cutoffs.** For cutoffs whose stored `rec_state0` equals `rec_realtime`, the look-ahead is zero by
  construction; their count is reported.

### P4-9 Elasticity interval (P4-descriptive)
- **Statistic.** The ratio of the simulator's to the realized slope of eight-quarter cash flow on the revenue
  change (plan-3 definition).
- **Interval.** A 95% interval by the firm-cluster bootstrap and by the year-block bootstrap, for v3 (full sample),
  v3 default and v2-pre.

## Discipline
1. **Sequence.** The order is: plan committed, timestamped and pushed; then code and tests (synthetic data only);
   then the full run. No P4 statistic on real data is computed before the push. A dry run on 50 firms checks only
   that every test runs; its statistics are not looked at beyond non-finite values, counts and units, and they
   change no rule.
2. **Deviations.** Any deviation is recorded in an addendum here before the full results are read, or in the paper
   as a deviation after.
3. **Reporting.** Every test is reported whatever its result, in the paper's P4 section and in `docs/paper/rev4/`.
4. **Compute.** Server only (burst, ARM cax, x86 if that is all there is). Results are pulled before the server is
   deleted.
