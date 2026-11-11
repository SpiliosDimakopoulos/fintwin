# Review: tests (engine/tests, web/src tests, __golden__ usage)

### T1 Backtest orchestration has no test at all
- where: engine/fintwin/backtest/walk_forward.py:64 (forecast_backtest), :157 (structural_backtest), :219 (cross_section)
- severity: test
- changes numbers: n/a
- issue: Only helpers (_baseline, trailing windows) are covered, in test_CR_review.py. The functions that build the published backtest.json (score table, PIT, CRPS skill with `max(...,1e-9)` at :124, realized series shorter than horizon, NaN realized values skipped at :105) have no test. scripts/backtest_check.py is only tested for argparse.
- fix: one offline test using the synthetic company from the `offline` fixture in test_pipeline_offline.py: monkeypatch load_company/macro_quarterly, run forecast_backtest with a short horizon, assert keys, n equals the finite realized count, coverage in [0,1], and a NaN realized quarter is skipped.
- effort: M

### T2 recession_regime and gdp_vintage are only ever mocked
- where: engine/fintwin/data/fred.py:50 (gdp_vintage), :68 (recession_regime); mocked at engine/tests/test_pipeline_offline.py:148 and engine/tests/test_B1_parity.py:108
- severity: test
- changes numbers: n/a
- issue: The hazard/exit formulas (`starts / max(len(rec)-in_rec, 1)`, `starts / max(in_rec, 1)`), the vintage-date rule (20th of the quarter's 2nd month, :57) and the asof truncation feed every calibration, yet both callers replace them with constants. A look-ahead bug here (the repo's headline claim) passes every test. gdp_vintage reads a committed CSV, so it is testable offline.
- fix: test gdp_vintage on gdp_vintages.csv (asof a day before/after a vintage date picks the older/newer column; asof before the first vintage returns None). Test recession_regime by monkeypatching fred_series with a tiny USREC/GDP series with two known recessions and assert hazard/exit/n_recessions by hand.
- effort: M

### T3 fred_series cache/stale/frozen branches untested
- where: engine/fintwin/data/fred.py:24-39
- severity: test
- changes numbers: n/a
- issue: frozen-miss, fill_only and max-age refetch logic (:28-31, a nested `not (...) and ...`) has no test; test_frozen.py covers only edgar.company_facts.
- fix: three small tests with monkeypatched CACHE_DIR and requests.get, as test_frozen.py does: stale file refetches; frozen + missing raises FrozenMiss; fill_only keeps a stale file.
- effort: S

### T4 TS summarize() is checked only for `healthScore >= 0`
- where: web/src/engine/model.test.ts (test "runs 5,000 paths fast and summarizes"); web/src/engine/summary.ts:41-112
- severity: test
- changes numbers: n/a
- issue: Goldens compare raw Outputs arrays and decisionOutputs, not summarize(): bands, pBreachByQ, healthHist, healthP10 are never compared to Python or to hand values. `healthScore >= 0` holds for nearly any output. pLiquidityBelow, maturityWall, firstCovenantBreach (summary.ts:113-137) have no direct test.
- fix: build a 3-path x 2-quarter Outputs by hand in summary.test.ts and assert bands, pBreachByQ and firstCovenantBreach exactly; or add Python summarize output to the goldens and diff it.
- effort: M

### T5 Wall-clock assertion in a unit test
- where: web/src/engine/model.test.ts (`expect(ms).toBeLessThan(2000)`)
- severity: test
- changes numbers: n/a
- issue: A 5,000-path run timed against 2 s fails on a loaded CI runner or cold JIT and passes trivially on a fast machine; it tests the machine, not the code.
- fix: drop the timing assert (or move it to a benchmark script) and replace it with the summarize assertions from T4.
- effort: S

### T6 Real-time, thread-based rate-limit test
- where: engine/tests/test_edgar_rate_limit.py:18-47
- severity: test
- changes numbers: n/a
- issue: Measures real `monotonic()` gaps across 4 threads against `_MIN_INTERVAL - 0.02` (_MIN_INTERVAL = 0.15, edgar.py:23). It performs real sleeps and a 20 ms margin is thin on a loaded box.
- fix: patch the clock and sleep with a fake monotonic that advances on sleep and assert recorded request times are at least _MIN_INTERVAL apart; keep threads only to exercise the lock.
- effort: M

### T7 Vacuous assertion in the throttle-clock test
- where: engine/tests/test_frozen.py:45 (`assert all(s <= edgar._MIN_INTERVAL for s in slept)`)
- severity: test
- changes numbers: n/a
- issue: Passes when `slept` is empty, so it cannot fail if no throttle happens. It also depends on module-global `_last_request` left by earlier tests (order dependent).
- fix: set `_last_request` explicitly via monkeypatch with a fake clock, assert `slept` is non-empty and `sum(slept) <= _MIN_INTERVAL`.
- effort: S

### T8 Health-waterfall test comment says "exactly" but asserts `>=`
- where: engine/tests/test_model.py:150-157
- severity: test
- changes numbers: n/a
- issue: The comment says weighted components minus the breach cap equal the mean health exactly; the assert is `weighted >= health_mean - 1e-9`, true for any cap size. The weights 0.3/0.3/0.2/0.2 are retyped in the test, a second copy that can drift from the model.
- fix: expose the cap and assert `weighted - cap == approx(health_mean)`; import the weights from the model instead of retyping them.
- effort: S

### T9 Loose sanity bounds that few plausible bugs break
- where: engine/tests/test_model.py:92-95 (test_rating_buckets), :98-102 (test_all_presets_run); engine/tests/test_research.py:205 (`abs(h - h0) < 25`); engine/tests/test_pipeline_offline.py:185 (`0.0 < mu < 0.03`)
- severity: test
- changes numbers: n/a
- issue: `0 <= p_breach <= 1` per preset, a 25-point health tolerance and a 3% mu band accept wide ranges of wrong values. test_rating_buckets checks 3 of 15 buckets while the web ratings.test.ts checks every boundary.
- fix: parametrize rating_rank over the full threshold table; for presets assert health <= base health; tighten or drop the h0 check.
- effort: S

### T10 test_d_repo asserts a hard-coded version and a config value
- where: engine/tests/test_d_repo.py:15-21 (`== "3.0.0.dev0"`), :45-47 (`fail_under == 85`)
- severity: test
- changes numbers: n/a
- issue: The literal fails on every legitimate version bump even when all five files agree, and `fail_under == 85` just restates pyproject. The cross-file agreement idea is good; the literals are the brittle/tautological part.
- fix: derive the expected version from pyproject, compare the other files to it (normalizing `.dev0` vs `-dev`); assert `fail_under >= 80` or drop.
- effort: S

### T11 Script tests mock away the thing they claim to protect
- where: engine/tests/test_scripts.py:60-87 (three `*_help_does_not_trigger_*` tests); :46-57 (subprocess `--help`, timeout=10)
- severity: test
- changes numbers: n/a
- issue: `main(["--help"])` raises SystemExit inside argparse before any patched function can run, so "mock not called" holds for any implementation and duplicates the subprocess test. The subprocess test imports numpy/pandas cold under a 10 s timeout, a flake source on Windows. No test runs a script's real main on a fake company.
- fix: delete the three mock tests; raise the timeout to 60; optionally add one `diagnose.main(["SYN"])` run on the offline fixture.
- effort: S

### T12 Duplicated offline fixtures across test files
- where: engine/tests/test_B1_parity.py:104-120 and engine/tests/test_pipeline_offline.py:139-165 (identical recession_regime stub dict and macro frame); synthetic company builders also in test_A_data.py, test_B1_parity.py:23-100, test_C2_synth.py
- severity: slop
- changes numbers: n/a
- issue: The same stub (`hazard 0.045, exit 0.24, gdp_shortfall_q 0.01, ...`) is copy-pasted under different fixture names (`macro`, `offline`); test_B1_calibration.py:303 re-imports one with `# noqa: F811`. A change to recession_regime's return shape must be made in several places.
- fix: move `macro` and a `synthetic_company` factory into conftest.py; delete the copies and the F811 re-imports.
- effort: M

### T13 tornado has only a length assertion
- where: engine/fintwin/sensitivity/tornado.py:18; test engine/tests/test_pipeline_offline.py:203 (`len(tornado(...)) == 6`)
- severity: test
- changes numbers: n/a
- issue: Nothing checks row ordering (the UI relies on it), that low/high differ in the expected direction, or that the base is shared.
- fix: assert rows are sorted by swing and that a rate-up knob lowers health.
- effort: S

### T14 Memo retry-on-unverified-number flow untested
- where: engine/fintwin/memo.py:123 (write_memo), :153 (main)
- severity: test
- changes numbers: n/a
- issue: unverified_numbers is well tested (test_helpers.py) but write_memo's feedback/retry loop, the guard against invented numbers, is never run even with a fake client.
- fix: fake `anthropic.Anthropic` whose `messages.create` returns a memo with a bad number then a good one; assert feedback is sent on the second call and a persistently bad memo is rejected.
- effort: M

### T15 Parity golden has no provenance; regeneration silently turns the test into a tautology
- where: engine/tests/test_B1_parity.py:136-139 (`_golden`), engine/tests/test_B1_v2_golden.json
- severity: risk
- changes numbers: n/a
- issue: The golden was "written once on the pre-change code" but the JSON records neither commit nor generator; anyone re-running `_golden` on new code makes the test compare code with itself and the diff is a big JSON blob.
- fix: write `"_generated_by": "<commit> <date>"` into the JSON and assert it exists in the test so a regeneration is a visible one-line change.
- effort: S

### T16 Web goldens: `files[0]` ordering dependency and a partly vacuous decisions check
- where: web/src/engine/model.test.ts:56 and web/src/engine/shocks.test.ts:9 (params from `goldenFiles[0]`); model.test.ts decisions loop (lines ~41-47)
- severity: test
- changes numbers: n/a
- issue: Shock tests take params from the first golden by readdir order; adding a file that sorts earlier silently changes the params under test. In the decisions loop `flat(want)` is empty for null or non-numeric entries, so those keys are checked only with `expect.anything()`, and a shorter `flat(d[k])` is not detected unless a number is missing.
- fix: name the params file explicitly (`INTC_base.json`); assert `flat(want).length === flat(d[k]).length` before the element compare.
- effort: S

### T17 toScenario (LLM output to knobs) is untested
- where: web/src/ask/llm.ts:62-76
- severity: test
- changes numbers: n/a
- issue: Pure unit conversion (`revenue_drop_pct / 100`, lever inversion, clamping) has no test; a wrong unit would produce a 100x shock silently. parse.test.ts covers only the regex parser.
- fix: add llm.test.ts: `{revenue_drop_pct:40}` -> sales_depth 0.4; `{revenue_drop_pct:140}` -> clamped 0.95; `keep_paying_dividends:true` -> cut_payouts false; `{}` -> empty. The web-llm import is dynamic, so importing the module is safe.
- effort: S

### T18 Sobol test: loose bounds, tiny sample, one seed
- where: engine/tests/test_model.py:127-134; engine/fintwin/sensitivity/sobol.py:39
- severity: test
- changes numbers: n/a
- issue: `0 <= S1 <= 1.2`, `0 <= ST <= 1.5` with n_base=48 accept noisy estimates; the `sales_depth > dio_days` ordering holds for default seed=5 only and breaks on any factor-range edit. No check against a known analytic function.
- fix: factor the estimator so it can be tested on an additive toy function (S1 sums to 1, ST == S1) and keep the model test as a smoke test.
- effort: M

### T19 Hypothesis identity test is not derandomized in CI
- where: engine/tests/test_model.py:13-39
- severity: risk
- changes numbers: n/a
- issue: `max_examples=40, deadline=None`, no profile: each CI run draws new inputs, so a rare failure is hard to reproduce on another machine.
- fix: register a `ci` profile in conftest.py with `derandomize=True` (select by env var), keep random locally.
- effort: S

### T20 No markers, no network guard
- where: engine/pyproject.toml:40-41; heavy tests: engine/tests/test_C1_inference.py, test_research.py:169, test_B2_identity.py
- severity: risk
- changes numbers: n/a
- issue: There are no `slow`/`network` markers, so the suite cannot be run selectively on the shared PC. I found no test that hits the network (requests.get is always patched), but nothing enforces it: one missed patch would call SEC/FRED and pass or fail depending on connectivity.
- fix: register a `slow` marker and tag the stats-pipeline, Sobol and bootstrap tests; add an autouse conftest fixture that patches `requests.get` to raise unless the test opts in.
- effort: S

### T21 Quarter-label date arithmetic untested in web
- where: web/src/format.ts:38-55 (quarterLabel, futureQuarters); web/src/format.test.ts has no case for either (grep verified)
- severity: test
- changes numbers: n/a
- issue: Year rollover (Q4 to Q1), 52/53-week period ends and non-quarter-end `lastIso` are the usual place for off-by-one and timezone (UTC vs local) bugs, and these labels head every chart axis.
- fix: add cases: `futureQuarters("2025-12-31", 3)` crosses the year; `quarterLabel("2025-12-28")` (52-week FY end) and `"2025-01-01"` in a negative-UTC timezone (TZ env in vitest config).
- effort: S
