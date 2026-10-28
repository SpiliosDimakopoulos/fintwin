# Software review (wave 2): engine/fintwin, engine/tests, pyproject

Reviewer role: senior Python engineer. Source was read, not edited. No test was run (static review only). Items marked UNCERTAIN were not reproduced. Not re-reported: data/facts.py issues, bootstrap p-value resolution, seeds/global RNG, uv --locked, version 0.1.0 vs 2.0.0, README test count.

## Verdict on the model duplication (Python vs TypeScript)
I compared engine/fintwin/model/sd_model.py with web/src/engine/model.ts, summary.ts, scenario.ts, ratings.ts and shocks.ts line by line. The core equations, the default access thresholds (1.5/0.8 -> 1/0.6/0.3), the scenario builder, the percentile logic and the summary statistics agree. The only behavioural differences are (a) NaN handling (finding 9), (b) the Python-only research switches (revenue_override, spreads, access_icr, loop_r1/r2), which is by design, and (c) the browser shock generator uses its own PRNG (stated in its header). The residual risk is the parity TEST, not the port (finding 1).

## Ranked findings

### 1. HIGH - Python/TS parity goldens never exercise sector tolerance, a recession start state, or most outputs
- web/src/engine/__golden__/*.json, engine/fintwin/export.py:218-262 (golden_cases), web/src/engine/model.test.ts.
- I loaded all six goldens: every one has `sector_tol = 1.0` and `rec_state0 = 0.0`. The goldens come from AAPL, BA, CCL, INTC, NFLX and TSLA, whose sectors have tolerance 1.0 in sector_norms.json. Utilities (2.0), Materials (1.38) and Staples (1.36) are never tested.
- Untested code: `tol`/`lev_cap`/`_rank(icr*tol)` in the health score, and the in-recession opening state.
- The `expected` block holds only 12 keys. It omits `ebitda`, `ebit`, `cfo`, `capex`, `fcf`, `rating`, `nd_ebitda`, `dividends`, `buybacks`, `fixed_cost_mult`, `liquidity`, `h_liq/h_cov/h_lev/h_solv`. A divergence in capex cuts, payouts, the cost-cut multiplier or any of the four score components can hide behind equal cash and health.
- The tolerance is `|d| / max(|want|, 1) < 1e-6`. For quantities of order 0.01-1 (icr, zscore, rates) this is an absolute 1e-6. Acceptable, but looser than "number for number".
- Failure scenario: someone edits `lev_cap` or the sector tolerance in one engine only. All parity tests stay green and utilities show different health scores in the browser.
- Fix: add goldens with `sector_tol=2.0` and `rec_state0=1.0` (the synthetic `make_params` in conftest.py is enough, no network needed). Export every key in OUTPUTS and compare them all.
- Related: the identity test (test_model.py) only protects the Python engine.

### 2. HIGH (for the rerun) - Resumable research shards reuse stale results with no version stamp
- research/__main__.py:59 (`if out.exists(): continue`); stats.load globs every `*.json` in .cache/research (stats.py, `load`).
- The per-company file records neither a code revision, a model/assumption hash, nor the universe. Changing sd_model.py, calibrate.py or ASSUMPTIONS and re-running "shard" skips every existing company. The paper then mixes old-model and new-model companies in one table.
- `data_vintage()` records the facts hash, but nothing in stats.main checks that all shards share one code version or one facts hash.
- Files for CIKs no longer in universe_edgar.csv are also loaded (`stats.load` does not intersect with `research_tickers()`).
- Fix: write `{"code": hash of fintwin/**/*.py or git rev, "assumptions": hash(ASSUMPTIONS, SENSITIVITY), "schema": n}` into each shard. Make shard() recompute on mismatch. Make stats.main fail on mixed stamps and drop keys outside the universe. The same applies to .cache/batch (backtest/batch.py:395) and .cache/sobol.

### 3. MEDIUM-HIGH - Silent exception swallowing in the research pipeline biases samples without a trace
- experiments.py:557 `forecasts()`: `except Exception: continue`. A failed origin disappears. It is not written to `res["errors"]`, so forecast attrition is missing from the error counts.
- experiments.py:432 (sensitivity variants): `except Exception: continue`. A variant that fails for some companies makes the sensitivity table rely on a different subset. There is no count.
- experiments.py:543 `_ets_samples`: any exception returns None, so `crps_ets` is None. stats.forecast_section then filters `g["crps_ets"].notna()` (stats.py:~641). The twin-vs-RW comparison is silently restricted to rows where the ETS fit succeeded. That is a defensible matched sample, but ETS failures are selective (short or non-positive series) and the n reduction is not reported.
- batch.py:209/213/258 and walk_forward.py:238 follow the same pattern, but they record `skipped` text, which is better. covid_row (batch.py:258) returns None with no reason.
- Fix: record counts per failure class in `errors`, print the failed fraction per class in stats.main, and fail the build above a threshold.

### 4. MEDIUM - Realized quarters are aligned to the forecast horizon by position, with no gap check
- walk_forward.py:33 `_realized`, batch.py:137 `_realized`, experiments.py `structural` (`nxt = full[...].head(n_q)`) and `_forecast_origin`.
- `full[full.index > after + 20d].head(H)` takes the next H rows. If a quarter is missing in `full` (data-layer gaps are a known issue), row h is compared with simulated quarter h but belongs to a later quarter. `target` then carries the wrong date, and nothing flags it. In `structural`, `nxt["revenue"]` is fed as the revenue override for the wrong quarters.
- The check `nxt["revenue"].isna().any()` only catches NaN rows, not skipped quarters.
- Fix: assert the offsets (`(nxt.index - pre.index[-1]).days` should step by roughly 60-125 days) or reindex to the expected quarter-end grid and let missing quarters be NaN. Add a unit test.

### 5. MEDIUM - Weekly pipeline keeps stale company JSONs and can never report removals
- pipeline.py:81-90 `build_index` globs `web/public/data/companies/*.json` instead of using this run's universe.
- If a ticker fails this week (pipeline.py:55-58 records it in .cache/failed), last week's JSON is still indexed with `generated = today`. changes.diff sees an unchanged `last_quarter` and reports nothing. The only trace is build_report.json.
- A ticker dropped from the universe is never deleted, so `removed` in changes.diff (changes.py:76) is dead in this flow.
- .cache/failed/*.json (pipeline.py:134) is never cleared, so fixed failures keep appearing in build_report.
- changes.diff crashes the whole `aggregate` if a health or p_breach is null (NaN becomes null via `_clean`): `h1 - h0` or `round(None, ...)` raises TypeError (changes.py:~54-65). That happens before calibration, backtests and notes run.
- `export.build` (export.py:~318) writes its own index entries without `gics` or `components`; `pipeline.build_index` writes them. Two writers of one schema. If the feed baseline ever comes from export.build, `_drivers` silently returns [].
- Fix: build the index from this run's tickers plus verified-fresh files, delete or flag orphans, clear `failed` at the start of `shard`, null-guard `diff`, and use one index builder.

### 6. MEDIUM - calibration.json can contain NaN literals that break the browser
- backtest/batch.py:358 `OUT.write_text(json.dumps(res, ...))` bypasses `export._clean`. `json.dumps` writes `NaN`, which `JSON.parse` rejects.
- Candidates: `by_year[...]["skill"]` (0/0 when the crps_baseline mean is 0), `cross_section.spearman` when `health_stress` is constant, `rows` with NaN values, and `ci95` percentiles of all-NaN bootstraps (`np.nanpercentile` gives NaN).
- batch.py:395 (the per-company cache) is read back by Python only, which is fine.
- Fix: `json.dumps(_clean(res), allow_nan=False)`.

### 7. MEDIUM - Coverage configuration hides the code that produces the paper's numbers
- pyproject.toml [tool.coverage.run] omits research/experiments.py, research/__main__.py, research/assumption_sobol.py, backtest/walk_forward.py, backtest/batch.py, pipeline.py, api.py and memo.py. There is no `fail_under`.
- Reported coverage therefore looks healthy while these have zero tests: experiments.features (Altman Z'', Ohlson O, Zmijewski; I checked the coefficients and they match the published ones), covid, structural, covid_outcomes, _distress, forecasts, _ets_samples, _cash_rule/_apply_rule, _probs, _spread_scale; walk_forward.forecast_backtest, structural_backtest, cross_section; batch.company_cases, covid_row, aggregate (conformal factors, quintiles, bootstrap CI); export.history_block, build, build_backtests, _clean; pipeline.shard/aggregate/norms; assumption_sobol.design/points/_one/shard/stats.
- Research tests that exist: stats.main on synthetic JSON (planted signal, thresholds like rho > 0.6 and AUC > 0.7 with B=50), `auc`/`rho`/`pct`, harrell_c, holm, boot_two_way, combo, transmission null checks, `indices`. None verifies a number against an independent calculation. The planted-signal test would pass with a wrong CI width or p-value.
- Minimum additions, each a few lines and no network: `features()` against a hand-computed Altman/Ohlson/Zmijewski on a toy balance sheet; `structural()` with revenue override on conftest params (check the override reaches `rev`); `_realized` with a missing quarter; `_apply_rule` and `_cash_rule`; `unverified_numbers`; `history_block`; `_clean` (NaN, inf, numpy types, Timestamp); `batch.aggregate` conformal logic with a hand-made frame.

### 8. MEDIUM - Duplicated logic that can silently diverge
- Health formula and weights (0.3/0.3/0.2/0.2, s_liq/8, 6x leverage cap, Z'' scaling): sd_model.py, model.ts, experiments.health_at_open (hard-codes access 1.5/0.8/0.6/0.3, ignores `access_icr`), changes.WEIGHTS, web/src/charts/Waterfall.tsx:22. The only guard on health_at_open is `abs(sim - h0) < 25` (test_research.py, last test), which cannot detect a wrong coefficient.
- `_realized` and `_baseline`: walk_forward.py vs batch.py. They already differ (batch drops `total_debt` and the `ebitda`/`fcf` columns). `_baseline` in both uses `dropna()` before `shift(4)` and `iloc[-4+...]`, so a missing quarter silently shifts the season.
- The COVID row exists three times: walk_forward.cross_section, batch.covid_row, experiments.covid, with different seeds, path counts and failure handling.
- Index entry builder: export.build vs pipeline.build_index (finding 5).
- Investment-grade threshold: ratings.INVESTMENT_GRADE_MIN_RANK, notes.INVESTMENT_GRADE, and the literal `< 9` in mc.summarize.
- Verdict bands: notes._verdict vs web/src/format.ts healthStatus (70/50/30). The docstring promises they match; nothing enforces it.
- Fix: one module for the health formula and thresholds, exported once into meta (the web already receives ICR_LOWER/SPREADS this way), and one test per consumer.

### 9. LOW-MEDIUM - NaN rating behaviour differs between engines
- Python `_rank`: `np.searchsorted(ICR_LOWER, nan, side="right") - 1` returns 14 (AAA). A NaN coverage would be scored as the best rating. TS `ratingRank(NaN)` returns -1, then `SPREADS[-1]` is undefined and the output becomes NaN. NaN cannot arise today (calibrate rejects non-finite params, interest is floored at 1e-9), but one engine fails safe and the other fails to AAA. Guard `_rank` (`np.where(np.isfinite(icr), ..., 0)`) and test it.

### 10. LOW-MEDIUM - Quintile statistics depend on file order when scores tie
- batch.py:345 `pd.qcut(xs["health_stress"].rank(method="first"), 5)`. `rank(method="first")` breaks ties by row order, and rows come from `sorted(CACHE.glob("*.json"))`, so alphabetical ticker order decides which tied firms land in the "most fragile" quintile. Health scores saturate and many tie, so `quintile_median_burn` and `quintile_share_severe_burn` carry an alphabetical bias. Use a seeded random tie-break or report quintiles on untied scores only.

### 11. LOW-MEDIUM - AI memo number check is weak; notes and memos share a path
- memo.py `unverified_numbers` skips every number with `abs(x) <= 12`, so invented small counts and ratings pass. It accepts any number within max(5.1%, 0.6 absolute) of ANY number in the sheet. The unicode minus written by notes._money (U+2212) is not parsed, so signs are lost for negatives.
- notes.build and memo.build both write web/public/data/memos/{ticker}.json (notes.py:276, memo.py `build`). The weekly aggregate calls notes.build for all tickers (pipeline.py:121) and overwrites any Claude memo. The committed AAPL.json already says "rule-based analyst". The optional LLM path is effectively dead unless pointed elsewhere.
- notes.fact_sheet hard-codes `"simulated_paths": 5000` (notes.py:45) but api.py uses 3000. `rev_ttm` (notes.py:38) sums only non-null quarters, so one missing quarter understates TTM revenue with no flag.

### 12. LOW - plan2.timing compares C-indices on different samples
- plan2.py:~311-336. `harrell_c(twin)` and `harrell_c(no_loops)` each drop rows where their own risk is NaN. If `tm_no_loops_*` is missing for some rows, `twin_minus_no_loops` is a difference between two samples (stats.paired restricts to the common sample; this does not). The bootstrap also runs on a random subsample of 6000 while the point estimates use all rows.

### 13. LOW - Winsorising bounds computed on the full sample
- plan2.py:454 (`fcf_mechanism`), plan2.py:169, transmission.py:176/236/296: `np.nanpercentile(real, [1, 99])` over all years, including test years, then used in a walk-forward MAE. Mild look-ahead in the clipping bounds only, but `_combo` is billed as walk-forward.

### 14. LOW (UNCERTAIN impact) - Two-way clustering with very few origins
- stats.py:650 `forecast_section` and the two-way fits in transmission.encompassing use normal-theory p-values (`cov_type="cluster"`, default `use_t=False`). With about 7 forecast origins (about 12 panel years) the origin-dimension variance is poorly estimated and the sandwich can be non-PSD. Consider `use_t=True` or reporting the firm-only SE alongside.

### 15. LOW - experiments.features raises ZeroDivisionError on zero denominators
- experiments.py:~121-160. `ta, tl, ca, cl` are converted with `float(...)`, giving Python floats. `/ ta`, `/ tl`, `cl / ca`, `ca / cl` raise ZeroDivisionError instead of yielding NaN and a None via `_f`. One zero balance item turns the company's covid block into an error entry (recorded, but the firm is lost). Use numpy floats or guard.

### 16. LOW - API behaviour
- api.py:35 maps every `KeyError` to "not a known SEC ticker" (404). A KeyError raised deep in calibration for a known ticker is reported as unknown.
- `lru_cache` has no TTL, and concurrent first requests for one ticker each build. Local-only tool, so low priority.

### 17. LOW / UNCERTAIN - Recession regime uses the full NBER record available today
- calibrate.py:139 `recession_regime(last_quarter_end)` truncates USREC by date, but NBER dates are announced 6-18 months late and FRED holds the final dating. For 2020-2021 origins the model "knows" the 2020 recession ended in April 2020 (announced July 2021). `rec_state0` and the hazard/exit estimates use hindsight. `asof` is the last quarter-end rather than the cutoff, which is conservative for GDP vintages. Mention in limitations or lag USREC by the announcement delay.

### 18. PERFORMANCE hot spots for the rerun
- Repeated disk and parse work in the inner loop: `macro_quarterly(asof)` re-reads and resamples three FRED CSVs on every call (panel: twice per origin per company, plus covid about 3 times, plus structural). `recession_regime` re-reads USREC and GDP, and `gdp_vintage` re-reads gdp_vintages.csv, per calibrate. `spreads_asof` re-reads rating_spreads.csv per calibrate. `universe.classify` re-reads bankruptcies_2020.csv on every call for "~" tickers; calibrate calls `sector_tolerance -> classify` each time. With about 5,000 CIKs x ~15 origins this is hundreds of thousands of redundant CSV parses. Add `lru_cache` keyed on `asof` (results are immutable).
- `fred_series` re-downloads when the cache file is older than 24 h (fred.py:24). A multi-day rerun spread over runners will fetch FRED at different times, so shards can see different GDP/USREC vintages. Pin the macro inputs in the repo for the rerun.
- `pipeline.shard` calibrates each ticker at horizon 12 three times (company_block, `_vintage(full_data)`, plus the 13 origins re-loading and re-calibrating). Reuse `p` where possible.
- `plan2.harrell_c` is an O(events x n) Python loop (fine at n=6000, noted by the author).
- UNIVERSE_XL lists "DIS" twice (batch.py:60). Harmless because `export.build` dedups, but a direct iteration would run DIS twice.

### 19. Test quality notes
- Good: hypothesis-driven balance-sheet identity (test_model.py:28), CRPS against the closed form (test_scoring.py), point-in-time facts tests, null-predictor checks in test_transmission.py.
- Assert-the-implementation or too loose: `test_health_at_open...` (<25 points); `test_pit_and_intervals` hard-codes the `<=` convention (`51/101`); `test_stats_pipeline_recovers_planted_signal` uses B=50 and thresholds such as `> 0.6` / `> 0.7`, so it proves wiring, not correctness; `test_conformal_scores_and_norms` tests `_scores` on two rows and never the online conformal factors in `aggregate`, which is the claim in the paper.
- No test for: `changes.diff` with null health, `export._clean`, `history_block`, `notes` with missing quarters, or a check that the exported meta ratings table equals ratings.ts constants (ICR_LOWER, SPREADS are duplicated in ratings.ts).

### 20. Config nits (pyproject.toml)
- `lxml` is in the dev group but nothing imports it (xbrl_fallback uses xml.etree). `matplotlib` is used only by scripts/.
- No `--cov-fail-under`, no markers to separate slow tests, no `filterwarnings`. The code does `warnings.simplefilter("ignore")` globally in pipeline.py:144 and batch.py:363, which also hides real numerical warnings during the paper run.
- mypy is configured but lenient (`check_untyped_defs = false`) and not part of the test path.
- assumption_sobol.indices (line ~135) lacks the `var < 1e-12` guard that sensitivity/sobol.py has, so a constant output gives NaN indices (null after `_clean`, silently).

## Checked and found correct (no action)
- crps_samples, crps_gaussian, pit, interval_hit formulas; TS vs Python `percentile`; summarize outputs vs summary.ts; `build_scenario` vs `buildScenario`; Sobol S1 (Saltelli 2010) and ST (Jansen) estimators; loo_median index arithmetic; holm; boot_two_way; HLN one-sided p-value branch; Ohlson/Zmijewski/Altman coefficients; shock generator recipe (t-mixing applied to demand and margin shocks only, in both engines); conformal causality check in batch.aggregate (target + 90 d <= 15 Feb); no mutable default arguments found.
