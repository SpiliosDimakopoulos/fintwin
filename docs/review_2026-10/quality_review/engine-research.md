# engine-research review (engine/fintwin/research, engine/fintwin/backtest)

Read in full: stats, transmission, plan2, calibration, distress, experiments, __main__, assumption_sobol, batch, walk_forward, scoring.
Read-only; no tests run.

IMPORTANT for every "changes numbers: no" fix below: `research/__main__._code_digest` hashes every `fintwin/**/*.py`
plus data csv/json into the shard stamp. ANY edit under fintwin/ (even a pure refactor or comment) makes the in-flight run's
shards "stale" (`check_run` refuses to merge). Land all of these only after the run is merged, or accept a re-run.

### R1 Backtests calibrate with the product defaults, not point-in-time ones (look-ahead)
- where: backtest/batch.py:305-316 (company_cases), batch.py:372-384 (covid_row), backtest/walk_forward.py:65-69, 218-222
- severity: bug
- changes numbers: yes (needs owner decision)
- issue: These modules call `stochastic.calibrate.calibrate` directly. `research/experiments.calibrate` exists precisely because the product uses the January-2026 rating-spread table and the revised 5% fixed-cost prior (`FIXED_SHARE_PRIOR`), and swaps in `spreads_asof(cutoff)` and the pre-specified 35% prior. Rolling-origin "out-of-sample" coverage/CRPS skill in calibration.json (origins 2013-2025) and the COVID cross-section therefore use a spread table published after the cutoff and a prior that was revised after seeing 2020. The batch.py header claims "point-in-time".
- fix: either call `experiments.calibrate` here (changes numbers; web calibration.json would then differ from today's), or keep as is and state in the docstring/paper that these product backtests use the shipped parameters and are not the pre-registered design. Do not change silently.
- effort: S

### R2 Holm "secondary" family and the capex-share headline use the leaky winsorization limits
- where: research/stats.py:429-436 (`_secondary_pvalues` reads `hybrid`), research/transmission.py:1021-1022, research/plan2.py:575-585 (`fcf_mechanism` first block), plan2.py:597 (`capex_hypothesis_holds`, no suffix)
- severity: risk
- changes numbers: yes (needs owner decision)
- issue: `hybrid(bounds="full")` and the first `fcf_mechanism` block take the 1st/99th percentile limits from all years including the test year (the code itself calls this revision 2 and added `bounds="train"` for E6). The Holm adjustment still pulls its `hybrid_*` p-values from the "full" variant, and `capex_hypothesis_holds` (unsuffixed) is the full-sample one. Lambda is chosen on earlier years but the loss is winsorized with limits that saw test outcomes.
- fix: point `_secondary_pvalues` at `hybrid_train` (and report `capex_hypothesis_holds_train_bounds` as the headline), keep the "full" ones as labelled comparison only. If the pre-registration names the "full" version, leave it and say so in a comment.
- effort: S

### R3 Four copies of the walk-forward combination-weight search
- where: research/transmission.py:461-535 (`hybrid`), transmission.py:578-650 (`_Losses`, vectorised), research/plan2.py:495-518 (`_combo`), plan2.py:184-212 (`cash_hybrid`), plan2.py:255-325 (`density_combos`), also experiments.py:279-306 (`walk_forward_select`) and transmission.py:199-221 (`add_shrunk`)
- severity: slop
- changes numbers: no (if the shared helper keeps loss, grid and tie-breaking exactly)
- issue: "choose lambda/weight on rows with year <= Y-3, evaluate on year Y" is re-typed with different lags (`LAG`, literal 3, `oy < yr - 1`, `DENSITY_LAG`, `WF_LAG`) and different minimum-train constants (100, 200, 300, 500, `MIN_TRAIN` defined three times with different values: transmission 200, calibration 300, distress 300). A lag changed in one place will silently not change the others.
- fix: one `earlier_years(yrs, y, lag)` / `choose_on_past(...)` helper in stats.py and a single named lag constant per horizon (8-quarter outcomes: 3; 4-quarter forecasts: 2). Leave `_Losses` alone (performance code) but have it use the same constants.
- effort: M

### R4 Three different clustered-DM implementations that can disagree
- where: backtest/batch.py:526-546 (`dm_stat`, one-way, t(G-1)), research/stats.py:332-404 and :407-433 (`cluster_ols`, `two_way_mean`, eigenvalue PSD repair), research/calibration.py:226-262 (`dm_two_way`, falls back to `max(vf, vy)` when V<=0)
- severity: risk
- changes numbers: only where the two-way variance is not PSD (otherwise no)
- issue: `calibration.dm_two_way` and `stats.two_way_mean` compute the same quantity (Cameron-Gelbach-Miller, t(G-1), G = smaller cluster count) with different non-PSD repairs and different minimum n (30 vs 3). Same data can yield different p-values depending on which section reports it. `calibration` also imports `dm_stat` from the backtest package, so research depends on backtest internals.
- fix: have `dm_two_way` call `stats.two_way_mean` (add `p_less` there), move `dm_stat` into stats.py, import from there. Check the density section output for a non-PSD case before/after.
- effort: M

### R5 Duplicated helpers between batch.py and walk_forward.py, and import direction inverted
- where: backtest/walk_forward.py:34-61 (`_realized`, `_baseline`) vs backtest/batch.py:217-257; batch.py:359 imports `research.__main__.stamp`; research/calibration.py:18 imports `backtest.batch`; calibration.py:186 `from ..research.experiments import QLEVELS` inside the research package
- severity: slop
- changes numbers: no
- issue: `_realized` and `_baseline` are near-copies (walk_forward adds a total_debt branch via a two-key dict lookup `{"cash_like": None, "total_debt": "total_debt"}[var]` and a `horizon` arg). Both import `_calendar` from batch, so the shared module already exists. batch (a backtest) imports the research CLI for a stamp, and research imports batch for statistics: a cycle kept alive by function-local imports.
- fix: move `_realized/_baseline/_calendar/rw_empirical/following/usable_prefix/window_ok/seen_by/dm_stat` to `backtest/pit.py` (or `data/`), make walk_forward call them with a `horizon` param; move `stamp` to a small module neither package owns; use `.experiments` instead of `..research.experiments`.
- effort: M

### R6 `realized_min_cum_fcf` is the minimum of the cumulative sum, not floored at zero, and duplicated
- where: backtest/batch.py:386-391 and backtest/walk_forward.py:239-258 (both), vs research/experiments.py:888-895 (`_abnormal_burn` floors at 0)
- severity: risk
- changes numbers: yes (needs owner decision)
- issue: for a firm with positive cash flow every quarter, `fcf.cumsum().min()` is the first quarter's (positive) FCF, so a healthy firm's "realized burn" ranges over positive values and the Spearman/quintile "median burn" in calibration.json mixes burn and non-burn. stats.main notes the same artefact for the paper (and keeps `covid_worst` as robustness) but the web backtest has no note. The whole COVID row (window 2020-01-15..2021-07-15, fcf, rev_ttm, debt raise) is written twice, in `covid_row` and `cross_section`, with the slightly different `realized_burn_ratio` only in the latter.
- fix: make `cross_section` call `covid_row` and read its fields; decide whether to switch to total cumulative FCF (as experiments does for `cum_fcf`) or floor at 0.
- effort: S (dedupe), M (metric change)

### R7 `cross_section` crashes on an empty result and hides failures; hindsight universe
- where: backtest/walk_forward.py:222-266
- severity: bug
- changes numbers: no
- issue: if every ticker fails (`rows == []`), `df[[x, y]]` raises KeyError, so the one-line `except Exception` per ticker is followed by an unguarded crash; with 1-2 survivors `spearmanr` returns NaN with a warning and `float(rho)` goes into JSON. The 30-name `UNIVERSE` (and `UNIVERSE_XL`, "plus the travel/leisure names most exposed to 2020") is chosen with hindsight about 2020, which inflates the spread of the outcome in the "twin ranked vulnerability correctly" test.
- fix: `if len(d) < 5: stats[...] = None`; add one sentence to the docstring that the universe is hand-picked and the test is illustrative, not the census result.
- effort: S

### R8 Failures converted to `{"error": ...}` in the pre-registered merge
- where: research/stats.py:1031-1036 (`_safe`) and research/plan2.py:766-771 (`_safe`, identical copy), stats.py:812-820 and 1019-1022, transmission.py:429-440 (`_lad`), stats.py:493-496 `_industry` (`except Exception: return "Unknown"`)
- severity: risk
- changes numbers: no
- issue: a bug in any evaluation section (renamed column, empty frame) produces an `error` string in research.json and the run still "succeeds"; only a person reading the JSON would notice. `_safe` is typed twice. `stats.main` has no final check that no section carries an `error`.
- fix: one `_safe` in stats.py (plan2 imports it); after assembling `res`, collect all paths with an `"error"` key and print/raise them (raise unless `FINTWIN_ALLOW_SECTION_ERRORS=1`). Narrow the `_industry` except to the lookup error it expects.
- effort: S

### R9 `plan2.calibration` ignores actual filing dates, unlike `calibration.conformal`
- where: research/plan2.py:340-366 (`d["seen"] = target_ts + REPORT_LAG`, `d["seen"] <= o`) vs research/calibration.py:60-61 (`seen_by` with the D10 `filed` date)
- severity: risk
- changes numbers: yes (small; conditional/ACI coverage cells)
- issue: the same "was this error observable at the origin" rule is implemented twice; the plan2 version uses quarter end + 90 days even though `filed` is stored in every forecast row (D10). Not a leak (90 days is conservative for 10-Q/10-K timing) but inconsistent with the stated protocol, and the conformal windows of the two sections cover different past sets.
- fix: use `seen_by(d["target_ts"], d.get("filed"), o, REPORT_LAG.days)` in both loops.
- effort: S

### R10 Online conformal logic re-implemented in `batch.aggregate`
- where: backtest/batch.py:444-470 and `_scores` :408-421 vs research/calibration.py:25-88 (`_norm`, `conformal`)
- severity: slop
- changes numbers: no (same rule: quantile 0.9 of s90 from forecasts reported by 15 Feb of the year; batch additionally requires `year < Y`, which `seen_by` already implies for h>=1 targets)
- issue: second copy of the same scoring (`s90`, `s50`, `hit90`) and the same observability rule, with a hard-coded `len(past) < 40` in both. `aggregate` is 91 lines and untested (no test imports `aggregate`, `company_cases`, `covid_row`, `cross_section`, `forecast_backtest`, `structural_backtest`).
- fix: let `aggregate` build `d = calibration._norm(...)`/`conformal` per variable; add one small synthetic test of `aggregate`'s conformal factors (e.g. targets reported after the origin must not enter).
- effort: M

### R11 Very long functions
- where: research/experiments.py:660 `structural` (179 lines, also nests `pc/tot/med_tot/first`, sensitivity and tau/lambda grid loops), research/stats.py:600 `covid_section` (155 lines), experiments.py:1148 `company` (111), stats.py:818 `panel_section` (88), stats.py:1039 `main` (77), transmission.py:461 `hybrid` (75), backtest/batch.py:426 `aggregate` (91), batch.py:287 `company_cases` (82), walk_forward.py:64 `forecast_backtest` (87)
- severity: slop
- changes numbers: no
- issue: each mixes computation, orientation and JSON assembly; `structural` is the hardest to review for a pre-registered run.
- fix: `structural` -> `_structural_paths`, `_structural_events`, `_static_runway`, `_sensitivity_runs`, `_wf_grid_runs`; `covid_section` -> predictors / composite / regression / ablations / secondary; `panel_section` -> `_oos_models`. Pure moves, same RNG order.
- effort: L

### R12 Two `frame()` builders for the same outcome table
- where: research/transmission.py:108-176 and research/plan2.py:35-104
- severity: slop
- changes numbers: no
- issue: both walk `panel.st` and rebuild `real_*`, `twin_*`, `N3_*`, `S_*` columns with different spellings (`rev.sum()/(len(rev)/4) - 100` vs `rev.sum()/2 - 100`; `T.point` is called from both; `revsum` written inside the per-variable loop). The E1 "point forecast" override is implemented in both; a change to one leaves `T1_cfo` and `twin_cfo` different.
- fix: plan2 should consume `transmission.frame` (it already imports it as `T`) and add only its extra columns (`ebitda`, `capex`, `rc_*`, `tm_*`, `gr_*`).
- effort: M

### R13 Log-loss and logistic fitting defined three ways
- where: research/stats.py:871-888 (inline Brier/log-loss, clip 1e-6) vs research/distress.py:19, 205-228 (`EPS_LOG = 1e-4`, `brier`, `log_score`); research/stats.py:728-742 (`_fit_predict`, statsmodels L1_wt=0 alpha=0.01) vs distress.py:285-307 (`fit_logit`, Newton ridge) vs transmission.py:966-969 (GLM alpha=0.001)
- severity: risk
- changes numbers: yes if unified (log-loss values only; AUC unaffected)
- issue: the same "out-of-sample log loss" in research.json is clipped at 1e-6 in `panel.out_of_sample` and 1e-4 in `liquidity`; three regularised logits with different penalties are all described as "walk-forward logit". Readers comparing numbers across tables cannot tell the difference.
- fix: panel_section should call `distress.log_score/brier`; document which penalty each model uses in one place. Keep numbers unchanged by only re-labelling if the pre-registration fixed 1e-6/alpha values.
- effort: S

### R14 Stale compatibility scaffolding from earlier revisions
- where: research/experiments.py:51-55 (`try: from ..stochastic import spec ... except ImportError: _spec_mod = None`, "until it is merged"), :65-86 and `fix_active`/`spec_name` fallbacks, :259-260 (`TAU_GRID`/`LAMBDA_GRID` `getattr(_cal_mod, ...)` fallbacks), research/__main__.py:33 (`CACHE = ROOT # kept for callers`), research/assumption_sobol.py:42 (`CACHE = CACHE_ROOT # legacy name`), :80 (`FACTORS = FACTORS_V2`)
- severity: slop
- changes numbers: no
- issue: `stochastic/spec.py` and `calibrate.TAU_GRID/LAMBDA_GRID` exist, so the ImportError branch and the fallback grids (0.05..0.50, 0..0.50) are dead; note the real `TAU_GRID` is `(0.05, 0.10, 0.15, 0.25, 0.50, 1.0, inf)`, different from the fallback, so the code reads as if it used another grid. grep finds no importer of the three aliases. Thin wrappers: `stats._data_legacy` (just re-imports `data_legacy`), `experiments._following`, `__main__._stamp_of`.
- fix: import `spec` unconditionally, drop the fallbacks and aliases and the `LOCAL_FIXES`/`hasattr(_spec_mod, "active")` guards; call `data_legacy` directly.
- effort: S

### R15 Stale/contradicting comment and magic constants in plan2.calibration and cash_hybrid
- where: research/plan2.py:370-373 ("gamma = 0.005" then "gamma = 0.05"; code uses 0.05), plan2.py:196 and :222 (`b=300`, ignores `B_PANEL`), plan2.py:25-36 `PRIORS` ("baseline": 0.35 duplicates `SPECIFIED_FIXED_SHARE_PRIOR`), plan2.py:704-712 hard-coded `> 8` pp and `> 2e9`
- severity: slop
- changes numbers: no
- issue: comment says one gamma and the next says another; the bootstrap size is a literal in two functions while the rest of the pipeline reads `FINTWIN_B*`; the 0.35 baseline prior is a second source of truth (and would be wrong under `v2-rev`, where `research_prior()` is 0.05).
- fix: delete the first gamma line; use `S.B_PANEL`; use `calibrate.SPECIFIED_FIXED_SHARE_PRIOR`; name the example thresholds.
- effort: S

### R16 Sobol analysis: silent caps and duplicated bookkeeping
- where: research/assumption_sobol.py:316 (`range(min(n_boot, 200))` while `indices` is given `n_boot` and cycles `boot_f[b % len(boot_f)]`), :121-137 vs :186-195 (same try/except + failed/excluded counting copied), :60-61 `SPECIFIED_V2` literals (0.08, 0.5, 0.5, 1.5, 0.04, 0.85 duplicate calibrate/sd_model defaults), :151 `0.53 * access_hi`
- severity: risk
- changes numbers: yes for the CIs only (needs owner decision)
- issue: the CLI-visible `n_boot=500` silently becomes 200 firm-year resamples reused cyclically across 500 draws, so the reported interval is narrower in effect than documented. `SPECIFIED_V2` can drift from the model defaults it is meant to equal; `0.53` is `0.8/1.5` with no source.
- fix: use `n_boot` for both, or document 200; build `specified()` from `ASSUMPTIONS`/sd_model defaults; write `access_lo = 0.8 / 1.5 * access_hi` with a comment.
- effort: S

### R17 `crps_gaussian` propagates NaN scale silently; `crps_skill` divides unequal samples
- where: backtest/scoring.py:20-24, walk_forward.py:118-124
- severity: risk
- changes numbers: no for finite inputs
- issue: `max(sigma, 1e-12)` with `sigma = nan` returns nan (Python `max` keeps the first argument on a failed comparison), so one bad baseline sd makes `crps_baseline` NaN; the data-frame `.mean()` then skips it while `crps` is averaged over all rows, giving a skill computed on different samples. Not reachable after `usable()` (16 quarters) but `forecast_backtest` does not check `window_ok` at all.
- fix: `sigma = np.nanmax([sigma, 1e-12])` / explicit `np.isfinite` guard returning nan, and in `forecast_backtest` drop the row when `crps_baseline` is not finite so both means use the same rows; call `window_ok(hist.quarters, 16)` like batch does.
- effort: S

### R18 `risk` of selection on the evaluation sample for "best benchmark"
- where: research/stats.py:643-646 (`best = max(bench_avail, key=rho)`), :669-678 (`b_sub`)
- severity: risk
- changes numbers: no
- issue: the comparison "twin minus best benchmark" picks the best benchmark in-sample on the same data it is tested on. This is conservative for the twin (biased against it), so it cannot create a false positive, but the paper text must not describe `baseline_minus_best` as a pre-specified comparison.
- fix: add one comment in `covid_section` and in the paper table note that the best benchmark is chosen ex post.
- effort: S

### R19 Weak tests for the backtest package
- where: engine/tests (test_scoring.py covers scoring only)
- severity: test
- changes numbers: n/a
- issue: no test imports `forecast_backtest`, `structural_backtest`, `cross_section`, `covid_row`, `company_cases`, `aggregate`, `dm_stat`, `skill_by_horizon` except through a mock in test_scripts.py:71. The riskiest paths (gap handling in `structural_backtest` after D4, the conformal observability rule inside `aggregate`) are untested.
- fix: three small synthetic tests: `structural_backtest` with a NaN in the second realized quarter returns exactly one quarter; `aggregate`-style conformal factors exclude forecasts whose `filed` date is after the origin; `dm_stat` against a hand-computed cluster t.
- effort: M

### R20 Minor slop in stats.py
- where: research/stats.py:162 (list comprehension variable `g` shadows the Generator `g` in `boot`), :663-669 (`import statsmodels.api as sm` re-imported in five functions), :867-876 (`auc_by_year` evaluates `(p["year"] == yr).to_numpy() & m` twice per cell), :1012 (`n` and `n_ets_matched` always equal), :1073-1085 `RAW/ABN` upper-case locals, walrus `sp := panel[...]` inside a dict literal (stats.py:1100)
- severity: slop
- changes numbers: no
- issue: shadowing a variable called `g` inside a function whose RNG is also `g` is correct in Python 3 but reads like a bug; the walrus inside the `res` literal relies on evaluation order.
- fix: rename comprehension var to `i`; import statsmodels at module top; compute `sel = (p["year"] == yr).to_numpy() & m` once; hoist `sp` above the dict.
- effort: S
