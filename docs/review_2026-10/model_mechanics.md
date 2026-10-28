# Wave 2: model mechanics, Monte Carlo and calibration review

Reviewer role: system-dynamics and Monte Carlo modeller, calibration.
Scope: `engine/fintwin/model/sd_model.py`, `model/ratings.py`, `stochastic/{calibrate,mc,shocks}.py`, `scenarios/{presets,reverse_stress}.py`, `sensitivity/{sobol,tornado}.py`, `research/assumption_sobol.py` (the paper's Sobol), and `docs/paper/fintwin.tex` with `sections/model.tex`.
Method: I read the code. I ran small single-firm checks (KO, F and HD at 2019/2017 cutoffs, GOOGL at 2019, and synthetic data for the cost estimator) on the local cache. Nothing heavy was run, and no code was edited.
This report does not repeat the items already known (M1–M6, the median-sum issue).

## 0. Diagnosis in one paragraph

The paper's numbers, rescaled, come to this. `rev_change` is the average annual revenue change in %, and the outcome is the 8-quarter CFO in % of TTM revenue. So a slope of 0.62 means **$0.31 of extra CFO per extra $ of revenue in the twin, against $0.135 in reality**. The real figure is about the size of a typical CFO margin: at a two-year horizon, firms' cash flow is close to *proportional* to revenue.

The twin's figure can be explained almost entirely by one equation. CFO/ΔRev ≈ (1−t)(1−v) + sbc + ocf − NWC drag. With a cost ratio of about 0.85 and the estimator's fixed share of about 0.24 (finding 1), this is 0.79 × (1 − 0.85 × 0.76) ≈ 0.28, plus about 0.01–0.03 for sbc and ocf. That gives about 0.30 against the measured 0.31. **Under the specification the paper reports, the overreaction is the cost prior, mechanically. The data barely enter.**

The level inaccuracy against the 16-quarter margin has a different set of causes. The twin rebuilds CFO from components, and the estimators of those components do not match each other (findings 4–6). Each component adds level error that a direct CFO margin does not have.

## 1. Ranked findings

### F1 (critical): the fixed/variable estimator is about 2/3 prior and 1/3 data, regardless of how much revenue varied
`stochastic/calibrate.py:44-62` (`_fixed_variable_split`)

**Problem.** The data term is `SSE / (n·var(costs))`. That is ≈ R²·((v−v̂)/v̂)², which is scale-free and has curvature ≤ 1. The prior term is `2·((v−v_prior)/ratio)²`, with curvature 2. Neither term grows with n or with revenue variation. The mode is therefore ≈ (R²·v̂ + 2·v_prior)/(R² + 2): even a perfect fit (R² = 1) gives the prior 2/3 of the weight.

The docstring and `model.tex:55` both claim the opposite: "the data dominate once revenue has varied enough" / "shrunk ... when revenue has not varied enough". That claim is false.

**Evidence.** Synthetic costs = 0.85·rev exactly, so there are no fixed costs, with revenue coefficient of variation from 4% to 66%:

| Prior | Estimated v | Estimated fixed share | Truth |
|---|---|---|---|
| 0.35 | 0.650 | **0.24** | 0 |
| 0.05 | 0.82 | 0.04 | 0 |

These values are the same at every level of revenue variation.

A second case has a true fixed share of 40% and revenue CV of about 50%. With the 5% prior the estimate is a 25% share. With prior weight 0.2 it is 38%, and with weight 0 it is 40%.

This also explains several of the paper's results:
- `\SobTopST` = 1.00 (Sobol total-effect index) for the prior.
- The selected prior is 5% "in every year": the prior *is* the estimate, so the walk-forward search is choosing the fixed share directly.
- The single-firm runs confirm it. KO's fixed share is 0.27 with the 35% prior and 0.02 with the 5% prior; HD's is 0.25 and 0.08; F's is 0.32 and 0.11.

**Fix.** Use a proper Bayesian/ridge posterior:

`obj = SSE/σ̂² + ((v − v_prior)/τ)²`

where σ̂² is the residual variance and τ is a fixed prior s.d. (for example 0.15·ratio). The data weight is then n·var(rev)/σ̂², which grows with sample size and with revenue variation. Report the posterior s.d. of the fixed share in `_sources`.

**Test.** A recovery test on synthetic firms: at a revenue CV above 20%, the estimate should be within 5 pp of the truth whatever the prior. Also re-run the walk-forward grid over τ instead of over the prior mean.

**Expected effect.** The revised 5% specification already removes most of the overreaction. It does so by assuming costs are almost fully variable, not by estimating them. With a correct estimator, the paper could make the claim it currently makes in words: that the cost structure is *estimated*.

I expect a modest further MAE gain at most. The data-driven split is itself contaminated (F2), which is why "no prior" (9.4) does slightly worse than 5% (9.0). The real gain is the honesty of the claim: the twin's transmission mechanics are currently "16-quarter EBITDA margin × (1−t)" with almost no estimated structure.

**Paper action.** Report the elasticity ratio under the revised specification as well. I predict about 1.0–1.2 from the decomposition above (uncertain). If it comes close to 1, the "overreaction" section can say the bias was the prior, quantified.

### F2 (critical): operating leverage is identified from seasonal and transitory variation, at the wrong horizon
`calibrate.py:165-168`. The regression is on 16 raw quarterly *levels*.

**Problem.** Within a year, costs smooth through seasonal revenue swings: staffing, rent and SG&A are budgeted annually. A levels regression reads that as fixed cost. The transmission test, however, asks how *two-year cumulative* cash responds to persistent revenue changes, and at that horizon capacity costs adjust.

**Evidence.**
- Synthetic seasonal firm: costs track the trend fully but follow only 10% of the ±25% seasonal swing. With no prior, the estimator returns v at the grid floor (0.105) and a **fixed share of 0.88**.
- This mechanism also explains why "no prior" is worse than a 5% prior in the paper.

**Fix (pick one, then test walk-forward).**
- (a) Regress TTM costs on TTM revenue (rolling sums), or use 4-quarter differences Δ₄costs on Δ₄rev. Either removes seasonality and matches the annual horizon.
- (b) Pool the estimate hierarchically by Fama–French industry, with firm deviations shrunk by their standard errors.
- (c) Estimate the cost elasticity in log differences (Δ₄ ln costs on Δ₄ ln rev), and map it to F and v at the cutoff.

**Expected effect.** This removes most of the "no prior does worse" gap. It also gives a data-identified fixed share whose cross-section can be compared with the cost-stickiness literature (Anderson–Banker–Janakiraman 2003). With the 35% specification this source of error is masked by F1. Once F1 is fixed it becomes the main remaining driver of overreaction. Expected elasticity ratio after F1 + F2: about 1 (uncertain).

### F3 (major): "fixed" costs never scale with persistent revenue changes, including M&A
`sd_model.py:137` (`fixed = F(1+π)^(t+1)·cut_mult`). B2 only cuts costs and is close to inert.

**Problem.** Any persistent change in revenue level is treated as pure operating leverage. That includes organic growth, acquisitions (the acquired revenue comes with the acquired cost base), divestitures and refranchising (KO 2017–19), and ASC 606 gross/net changes in 2018. The winsorized slope in `plan2.overreaction` is driven by the largest |rev_change| observations, which are disproportionately inorganic.

**Fix.** Use partial adjustment:

`F_t = F_{t−1} + λ·(f·R̄_t − F_{t−1})`

where R̄_t is the smoothed deseasonalized revenue level and f = F₀/R̄₀. Estimate λ pooled and walk-forward on the panel; a half-life of 2–4 quarters is plausible. Optionally make it asymmetric (λ_down < λ_up, for sticky costs). B2 then becomes a special case.

**Test.**
1. Split the elasticity ratio by the sign of rev_change and by an acquisition flag. This needs `PaymentsToAcquireBusinessesNetOfCashAcquired` and `Goodwill` added to `facts.py`; neither is loaded today.
2. Prediction: the excess concentrates in |rev_change| > 10% and in acquirers.

**Expected effect.** This is the main remaining structural fix for the elasticity if F1 and F2 restore a non-trivial fixed share. It also gives the twin a defensible "managerial response" that B2 lacks. The paper itself finds R1 and B2 inert; partial adjustment would be a loop that matters.

### F4 (critical, data → model): missing D&A double-counts depreciation and zeroes the CFO correction
`calibrate.py:165, 194, 199-200`; `sd_model.py:140, 169`.

**Problem.** When the `da` tag is missing:
1. `ebitda = operating_income + da.fillna(0)` makes EBITDA equal EBIT. Historical D&A is therefore inside the cost base F + v·rev.
2. `dep_rate` falls back to 0.03, so the twin subtracts D&A a second time (0.03·PPE).
3. `explained = NI + da + sbc − ΔNWC` is all-NaN, so `ocf_ratio` falls back to 0 and nothing compensates.

The net bias in twin CFO is ≈ −(DA_real − t·DA_twin) per quarter.

**Evidence.**
- GOOGL at the 2019-02-15 cutoff has no non-null `da` in any of its 18 quarters. The twin's 8-quarter CFO is **71.7 against 87.4** realized (the 16-quarter margin implies about 86), so the twin is about 16 pp of TTM revenue low.
- In the first 60 cached tickers, `da` was all-NaN over the last 8 quarters for CSCO, DOW, LIN, LMT and MAR as well. ABNB and DIS look like loader artifacts at that cutoff, so they don't count.
- The tag list (`facts.py:64-69`) lacks, for example, `DepreciationAmortizationAndAccretionNet` variants and `DepreciationAndAmortizationExcludingAmortizationOfDebtIssuanceCosts`. I did not check the exact tags each of these firms uses (uncertain).

**Fix.**
- Extend the D&A tag list.
- If D&A is still missing, set the twin's D&A to zero *and* keep the cost base as is. That is consistent, because D&A is then inside the costs: set `dep_rate` = 0 and flag it.
- Alternatively, impute D&A from PPE and add it back to EBITDA *before* the cost regression.
- Compute `ocf_ratio` with the same fill rules the model uses.
- Report the share of panel firm-years affected.

**Expected effect.** For affected firm-years the level error is 5–15 pp, which is the same order as the whole median absolute error. If 5–10% of firm-years are affected (uncertain; this needs a panel count), the median error moves by a few tenths of a point. The tail errors and the 16-quarter-margin comparison improve more.

### F5 (major): mismatched estimators for tax and the CFO residual create level bias
`calibrate.py:200` (`ocf_ratio` = *median* of 8 quarters), `:203-204` (tax = 8-quarter *sum ratio*, clipped to [0.05, 0.30]); `sd_model.py:154`.

**Problem.** The book ETR includes one-offs, but the non-cash reversal of those one-offs lands in the CFO residual, which is estimated with a median. The median ignores the reversing quarter. The obvious case is the TCJA transition tax and DTA remeasurement in Q4 2017, which distorts the 2018 and 2019 cutoffs, but large settlements, valuation allowances and intellectual-property migrations do the same.

**Evidence.**
- KO at 2019: the sum-ratio ETR is 0.49, clipped to 0.30. The median quarterly ETR is 0.22. That costs the twin ≈ 0.08 × EBT/rev (0.28) × 2 years ≈ **4.5 pp of TTM revenue of CFO**.
- In the first 60 tickers at the 2019 cutoff, **27** have clipped sum-ratio and median ETRs that differ by more than 5 pp: ABT 0.43 vs 0.11, JNJ 0.53 vs 0.20, LLY 0.55 vs 0.19, CSCO 0.58 vs 0.20, KHC −0.44 vs 0.27, and so on.
- Non-operating income (equity-method income, pension, FX gains) is in historical NI. It is missing from the twin's EBT and absent from `ocf_ratio`, because `explained` uses the *real* NI.

**Fix.**
- Use cash taxes (`IncomeTaxesPaidNet`, available annually) or a median-of-years ETR.
- Better: **anchor the residual**. Set `ocf_ratio` so that the twin's component sum reproduces historical cumulative CFO over the *same 16-quarter window* at historical revenue, using a sum/sum ratio rather than a median. Add an explicit non-operating line equal to the historical mean.

**Expected effect.** Anchoring makes the twin nest the 16-quarter CFO margin at constant revenue, so the departures from it come only from transmission. This is the single change most likely to close the level gap to the 16-quarter margin. Expected median-error reduction: about 0.5–1.5 pp (uncertain). It also makes the "departures carry information" test cleaner, because the level noise from the components disappears.

### F6 (major): the margin-shock process absorbs the prior's misfit, and the current margin deviation is thrown away
`calibrate.py:170-181`; `sd_model.py:89, 135`.

**Problem.**
- `m_resid` is the residual from the *penalized* fit. When the prior is wrong, the residual contains −(v̂−v)·(rev−r̄)/rev, which is persistent and correlated with revenue. That misfit inflates `rho_m`, `sigma_m` and `rho_gm`.
- `m_dev` starts at 0, so the cost-ratio deviation at the cutoff (the most recent residual) is discarded. This happens even when the estimated persistence is high.

**Evidence.** KO at 2019: `rho_m` is 0.70 with the 35% prior and 0.32 with the 5% prior, and `sigma_m` is 0.046 vs 0.044. HD: `rho_gm` is 0.16 vs −0.03.

**Fix.**
- Estimate the shock process on residuals from the consistent fit (F1/F2).
- Initialize `m_dev0` = the last residual, or the mean of the last 2, decaying at `rho_m`.

**Test.** Walk-forward MAE with and without initialization. Since the 16-quarter margin beats the 4-quarter margin, expect a small optimal persistence; estimate it pooled rather than per firm.

**Expected effect.** Small to moderate on the median error. It mainly matters for "departures carry information", because the current-deviation signal is exactly what the 4- and 16-quarter margins disagree on.

### F7 (major): fat tails are scaled wrongly, so central dispersion is understated by 15–35%
`shocks.py:79-83` with `calibrate.py:73, 122-133`.

**Problem.** `sigma_g` is a MAD-robust s.d., which already excludes the tails. The t draws are then rescaled to *unit variance*. Their MAD-implied s.d. becomes `1.4826·t.ppf(.75, df)·sqrt((df−2)/df)·σ`, which is **0.66σ at df = 3, 0.78σ at df = 4, 0.84σ at df = 5 and 0.91σ at df = 8**. The body of the simulated distribution is narrower than the data.

There is a second problem: `stats.t.fit(z, floc=0, fscale=1)` fixes the scale at 1 for data standardized by the MAD s.d., which is misspecified for t data.

df itself is weakly identified. With 31 Gaussian residuals, 39% of fits give df < 30 (median 30, IQR 11–30). With t₄ data the IQR is 3.5–20.

**Evidence.** The three firms I calibrated have df between 5.4 and 6.3, so their dispersion is about 15% too narrow. The paper's raw revenue interval coverage is `\CalRevRaw` = 70% before conformal rescaling. This finding is a plausible part of that gap (uncertain share). Ignored parameter uncertainty is the other part (F9).

**Fix.**
- Draw `σ·t_df·(1/(1.4826·t.ppf(.75, df)))`, so the MAD matches, and do *not* rescale to unit variance.
- Or fit σ and df jointly by MLE.
- Shrink df toward a pooled panel estimate, since per-firm values are noise.

**Expected effect.** Raw coverage rises by several points. The conformal factor moves closer to 1. Transmission medians are unchanged.

### F8 (minor/major): the shared mixing variable couples demand and margin tails; rate and financing shocks stay Gaussian
`shocks.py:82-83`.

**Problem.** A single chi-square per path-quarter for columns 0 and 1 makes them multivariate t. They have tail dependence even when `rho_gm` = 0: in a demand crash quarter the margin shock is also large. Its sign is still symmetric, so the effect is on variance, not direction. The margin tails also use the df fitted on the *growth* residuals.

**Fix.** Use independent mixing variables (or a t-copula with an estimated tail dependence), with df for margins pooled separately.

**Expected effect.** Small. It matters for P(breach) tails in the product, not for the paper's medians.

### F9 (major, uncertain size): no parameter uncertainty, although most parameters are weakly identified from 16 quarters
How well the 16 quarters identify each parameter:

| Parameter | Identification from 16 quarters |
|---|---|
| dso, dpo, dio, ddays, capex/rev, sbc/rev | Good: levels averaged over 4–8 quarters |
| sigma_fin | Moderate (20 observations) |
| mu | Weak. The SE of a 12-quarter median is about 1.25·σ_g/√12 ≈ 0.7 pp/q at σ_g = 0.02, which is about 3 pp/yr, the same size as mu. The 50% shrink is doing real work. |
| phi | Weak. SE ≈ √((1−φ²)/31) ≈ 0.18. Negative estimates are clipped to 0, which overstates level variance for firms with residual seasonality. |
| rho_m, rho_gm | Weak. n ≈ 15, so SE ≈ 0.25. rho_gm also aligns a growth-residual series of up to 31 with a level-ratio series of 15 by tail only (`calibrate.py:178-181`). |
| t_df | Essentially unidentified (above). |
| F/v | Prior-determined (F1). |
| beta_gdp | Weak: 12–40 *overlapping* YoY pairs give about 3–10 independent observations. |
| refi_ratio | One observation: a single 8-quarter debt difference. |
| cash_floor | The 10th percentile of 12 quarters, so 1–2 observations. |
| tax_rate | Dominated by one-offs (F5). |

**Fix.** Use parameter bootstrap paths: resample residuals, re-estimate (mu, phi, σ, F/v, ρ), and draw one parameter vector per path or block of paths. Alternatively, use hierarchical pooling by industry for phi, df, ρ and the cost elasticity.

**Expected effect.** Probabilistic calibration improves (the coverage gap). The transmission medians move little. Do this before claiming interval quality.

### F10 (major): fixed costs are not re-based to the cutoff, and inflation is applied on top of a nominal revenue path
`calibrate.py:168`; `sd_model.py:137`.

**Problem.** F is the regression intercept at the window's mean, about 8 quarters before the cutoff. It is then inflated at 0.6%/q from t = 1, while the realized (nominal) revenue already carries inflation. The two effects partly offset each other, but the net is firm-specific. At a 25% fixed share and flat nominal revenue, the projection drifts by ≈ 1 pp of TTM revenue in CFO over 8 quarters.

**Fix.** Re-base F to the cutoff, for example by fitting with a time trend or deflating costs and revenue by the PPI. Then index F to the revenue deflator, or let F3's partial adjustment handle it.

**Expected effect.** Small at a 5% prior. About 1 pp of level bias at 35%.

### F11 (major for liquidity events, minor for CFO): debt-free loss-makers are "D-rated" and trigger B1
`sd_model.py:146, 173`; `calibrate.py:295`.

**Problem.** With zero debt, `int4` = 0, so `icr_prev = EBIT/1e-9`. Any negative TTM EBIT therefore gives about −10⁹, which means rating D, access 0.3, and `stressed = True`. The result is capex cut to 0.8·D&A and dividends to 0, even for a cash-rich firm with no debt. `s_cov` = 0 as well.

**Fix.** Define coverage only when interest exceeds a materiality threshold (for example 0.1% of revenue). Otherwise use the liquidity test alone, and set rank and spread from net cash.

**Expected effect.** This removes false "capex cut" and "dividend cut" events, and false low health, for cash-rich growth firms. It touches the decisions table (AUC 0.56–0.68) and the bankruptcy ranking only for that segment. No effect on CFO.

### F12 (minor): numerical bounds in the cost split distort extreme firms
`calibrate.py:56` uses a grid of v ∈ [0.10, 1.05]:
- Cost ratio below 0.1/(1−prior) (royalty and asset-light firms): v is forced to 0.10, F clips to 0, and modelled costs exceed actual costs. EBITDA is understated.
- Cost ratio above about 1.6 (loss-making biotech and tech): v caps at 1.05 and F absorbs the rest, so the fixed share is large (about 47% at a ratio of 2.0). That builds strong operating leverage into exactly the firms whose revenue changes most.
- `ratio = median(costs/rev)` is undefined for revenue ≤ 0 or near 0.

**Fix.** Solve in closed form, without a grid, under constraints such as F ≥ 0, 0 ≤ v ≤ 1.5·ratio, and guard revenue ≤ 0.

### F13 (minor): the AR delay is not a delay
`calibrate.py:334`; `sd_model.py:159`.

`tau_ar` = 1.0 makes `ar_new` equal the target in the same quarter. The paper's statement that "receivables ... adjust with first-order delays" (`model.tex:39`) is therefore true only for inventory (τ = 2).

The first-quarter receivables target also uses `dso`, an average over 4 quarters, applied to next-quarter revenue. Seasonal firms therefore get a one-off working-capital swing in t = 0. That is only a level effect.

**Fix.** Estimate τ (or a seasonal DSO) from history, or correct the text.

### F14 (minor): the recession drift is not offset in mu
Product only; not in the transmission test, where revenue is overridden. `mu` is the median of recent growth, which is mostly expansion. On top of it, `rec_hazard·rec_drift` lowers expected baseline growth by about 3%·β·shortfall per quarter, so the baseline is slightly pessimistic. That is acceptable if documented; otherwise use the expansion-conditional mean.

## 2. Monte Carlo: path counts and seeds

**Transmission medians (500 paths).** I measured the s.d. across 20 seeds of the 8-quarter twin CFO (sum of per-quarter medians):

| Firm | Prior 0.35 | Prior 0.05 |
|---|---|---|
| KO | 0.22 pp | 0.18 pp |
| F | 0.07 pp | 0.05 pp |
| HD | 0.03 pp | 0.02 pp |

All values are in pp of TTM revenue, against a median error of 9–12 pp. **500 paths is ample**; even 200 (the Sobol shards) is fine.

**Event probabilities from 500 paths.** The binomial SE is 1.3 pp at p = 0.1 and 2.2 pp at p = 0.5. That is adequate for AUCs, but it is noisy for rare events (cash below half at p < 0.02). Report a firm-level SE, or use 2000 paths for the decision tables.

**Reverse stress.** 2000 paths give about 1.1 pp resolution on P(breach), but the bisection runs 18 iterations (2⁻¹⁸ of the range). Precision is limited by Monte Carlo noise and threshold non-monotonicity, not by iterations; 8 iterations would do.

Common random numbers (CRN) do **not** guarantee monotonicity here: B1, B2, the R2 steps and the cash sweep are discontinuous. Check `prob(mid)` monotonicity on a small grid and report non-monotone cases.

**Seeds.**
- `structural` uses seed = 3 for *every* firm-year (`experiments.py:337`). The MC error is therefore perfectly correlated across the panel and does not average out. It is negligible for medians (above), but it should be documented, or replaced by `SeedSequence(firm_hash, year)`.
- `sensitivity/sobol.py:231-237` seeds both the design RNG and the shock RNG with the same integer (5). Two PCG64 streams with identical state then feed `random()` and `standard_normal()`, so the design points and shocks are deterministic functions of the same bits. The bias is negligible under CRN, but it is poor hygiene; use `SeedSequence(seed).spawn(2)`.
- (Wave-1 R4 covers the scattered seeds in general.)

## 3. Sobol designs

**Paper Sobol (`research/assumption_sobol.py`).**
- N = 64 base points, k = 8 → 640 runs, on **pseudo-random** uniforms (`rng.random`), not a scrambled Sobol sequence.
- At N = 64, S1 estimates typically carry ±0.1–0.2 of noise. ST ≈ 1.0 for the prior is robust *because of F1*: the estimate is the prior.
- The bootstrap resamples design points only. The 317 firm-years are fixed, so the CIs omit sampling uncertainty over firms.
- `prior_weight` ∈ [0, 10] interacts strongly with `fixed_share_prior` (at weight 0 the prior is inert). A 2-D surface (prior × weight → median error and elasticity ratio) would be more informative than indices.

Fixes:
- Use `scipy.stats.qmc.Sobol(d=8, scramble=True)` with N ≥ 256 (2,560 runs; about 4× the current cost on burst servers).
- Bootstrap over firm-years too.
- Add the elasticity ratio as a third output.
- After F1, replace "prior mean/weight" with τ.

**Product Sobol (`sensitivity/sobol.py`).**
- N = 256 pseudo-random, 300 paths with CRN, output = mean health.
- Statistically fine. Minor issues:
  - S1 is clipped to [0, ST] (`:260`), which hides negative or noisy estimates. Report the raw values with CIs.
  - `refi_freeze` is rounded to an integer, which gives a discontinuous response and inflates interaction shares.
  - The ranges are arbitrary, and the indices depend on them. Tie them to an empirical scenario distribution, for example the 2001, 2008, 2020 and 2022 industry shocks.
  - Quasi-random sampling would halve the cost.

**Tornado.** One-at-a-time with CRN. Fine.

## 4. Proposed fix programme, ranked by expected impact on the paper

| Rank | Fix | Findings | Expected effect | Test |
|---|---|---|---|---|
| 1 | Anchor the CFO residual to the 16-quarter window (sum/sum); cash or median ETR; non-operating line | F5 | Twin nests the 16-quarter margin at constant revenue; median error −0.5 to −1.5 pp (uncertain) | Walk-forward MAE, twin vs 16-quarter margin; elasticity ratio |
| 2 | D&A missing-tag handling and tag list | F4 | 5–15 pp error removed on affected firm-years; count prevalence | Panel share with all-NaN `da`; MAE by flag |
| 3 | Correct Bayesian weighting of the cost prior (τ, data weight ∝ n·var(rev)/σ²) | F1 | Estimated rather than assumed structure; the "overreaction" becomes a quantified prior effect | Synthetic recovery; walk-forward over τ |
| 4 | Identify operating leverage at the annual horizon (TTM or Δ₄, pooled by industry) | F2 | Makes the no-prior or weak-prior fit beat the 5% prior | MAE and elasticity ratio; distribution of fixed share vs literature |
| 5 | Partial adjustment of fixed costs (λ, asymmetric) plus an M&A flag | F3 | Elasticity ratio by |Δrev| bin → about 1; a loop that matters | Ratio by bin and by acquirer flag |
| 6 | Shock process: MAD-consistent t scaling; pooled df; margin residuals from the consistent fit; m_dev0 = last residual | F6–F8 | Raw coverage up several points; small MAE gain | PIT, coverage before conformal |
| 7 | Parameter-uncertainty paths | F9 | Calibrated intervals without conformal | Coverage; CRPS |
| 8 | ICR materiality, grid bounds, F re-basing, AR τ | F10–F13 | Removes false events and bias at the edges | Decisions-table AUC by debt-free flag |

**Run plan.** Fixes 1–4 change only the calibration, so they can be evaluated together in one walk-forward panel run on a burst server. Report the median error, the elasticity ratio (CFO, EBITDA) and the bankruptcy AUC for each fix cumulatively.

## 5. Items I could not verify
- How common all-NaN `da` is in the research panel. Checked on 60 cached tickers at one cutoff; DIS and ABNB there are loader artifacts.
- The predicted elasticity ratio under the revised specification (about 1.0–1.2). It comes from the decomposition, not from a run.
- How much of the 70% raw coverage F7 explains, compared with F9.
- Which XBRL D&A tags CSCO, LIN, LMT and MAR use.
