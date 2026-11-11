# slop-crosscut findings

Overall: the repo is far less "AI-slop" than typical. No hype words in code (grep for seamless, powerful, comprehensive etc. found none; "robust" is used in its statistical sense), no console.log, no TODO/FIXME, no comments narrating the obvious (grep for "# Return/Loop/Set/Get..." found 0). What remains:

### S1 Health-score weights hard-coded in 5 places, in two languages
- where: engine/fintwin/model/sd_model.py:406; engine/fintwin/research/experiments.py:425; web/src/engine/model.ts:238; web/src/charts/Waterfall.tsx:22-23; engine/fintwin/changes.py:19 (WEIGHTS dict, the only named one)
- severity: risk
- changes numbers: no
- issue: `0.3*liq + 0.3*cov + 0.2*lev + 0.2*solv` is written out five times. experiments.py:425 is a hand-copy of the model block (its docstring says "Mirrors the scoring block"), so a change in sd_model silently diverges from the research score. Waterfall.tsx shows a decomposition that must equal model.ts.
- fix: define `HEALTH_WEIGHTS` once per language (sd_model.py exports it; experiments.py and changes.py import it; a const in web/src/engine/model.ts imported by Waterfall.tsx). Add a parity assertion that the Python weights equal the TS ones.
- effort: S

### S2 Epsilon `1e-9` inlined ~14 times in the core model, plus other unnamed constants
- where: engine/fintwin/model/sd_model.py:165,238,307,318,347,361,364,377,390,393,397; engine/fintwin/stochastic/calibrate.py:218,223,235,274,276,292
- severity: slop
- changes numbers: no (if the value is kept)
- issue: the same divide-by-zero guard is a bare literal everywhere. Also unexplained in code: `99.0` sentinel for nd/EBITDA when EBITDA<=0 (sd_model.py:364); `0.015` revolver spread (245; METHODOLOGY calls it 150bp); `8.0` quarters, `6.0` leverage cap, `1.1`/`1.5` Altman scale (398-404; only METHODOLOGY explains them); `0.5 * cut_speed` recovery (354); `1.5 * cash_floor` and `2.5` ICR stress trigger (267; the 2.5 also appears as `cov_min_icr` at line 57, same number, different meaning).
- fix: `EPS = 1e-9` at module top; name `RUNWAY_FULL_Q = 8`, `LEV_CAP = 6.0`, `ND_EBITDA_NO_EBITDA = 99.0`, `REVOLVER_SPREAD = 0.015`, `STRESS_CASH_MULT = 1.5`, `STRESS_ICR = 2.5`, each with a one-line source comment. Pure rename, no numeric change (TS port must be renamed in step).
- effort: S

### S3 Duplicated backtest helpers `_realized` and `_baseline`, already diverged
- where: engine/fintwin/backtest/batch.py:217 and :237 vs engine/fintwin/backtest/walk_forward.py:34 and :44
- severity: risk
- changes numbers: no if merged carefully (touches pre-registered code; verify by equality test)
- issue: same names, same purpose, different bodies. batch._realized uses `following()` and records a reason; walk_forward._realized uses `usable_prefix()` and adds ebitda/fcf columns. The two `_baseline` copies share the `_calendar` trick but differ in naming (`same`/`yoy.std()` inline vs `same_season`/`sd`) and docstring. Two sources of truth for the naive benchmark the paper's skill scores are measured against.
- fix: keep one `_baseline` in walk_forward.py and import it in batch.py; rename the two `_realized` to say what differs (`_realized_with_reason`, `_realized_prefix`) or have one call the other. Check with an equality test on one company before and after.
- effort: M

### S4 `_safe` written twice; `_write`, `_ttm`, `_norm`, `_rank` also duplicated by name
- where: `_safe` identical in engine/fintwin/research/plan2.py:766 and research/stats.py:1031. `_write` (JSON writer) in engine/fintwin/export.py:165 and engine/scripts/gen_parity_goldens.py:49 (different details: sig digits vs allow_nan). `_ttm` with different semantics in stochastic/calibrate.py:305 (DataFrame) and research/experiments.py:386 (column). `_norm` with unrelated meanings in research/calibration.py:25 and stochastic/spec.py:48. `_rank` in model/sd_model.py:114 and engine/tests/test_B2_identity.py:54 (a test that re-implements production code, so it cannot catch a bug in it).
- severity: slop
- changes numbers: no
- issue: `_safe` is a 5-line catch-all (`except Exception  # noqa: BLE001`) copied verbatim; same-name different-meaning helpers hurt grep and reading.
- fix: put `_safe` in one place (research/stats.py) and import in plan2.py; rename `_ttm` in experiments.py to `_ttm_sum` and `_norm` in calibration.py to `_with_bands`; make the identity test import `sd_model._rank`.
- effort: S

### S5 Test fixture `_clean_env` copy-pasted in 4 test files
- where: engine/tests/test_B2_f3_f6.py:23; test_B2_mechanics.py:31; test_C2_outcomes.py:21; test_C2_spec.py:15
- severity: test
- changes numbers: n/a
- issue: two variants (2 env vars vs 4 env vars plus `monkeypatch.setattr(X, "_spec_mod", None)`). The shorter ones do not clear FINTWIN_SELECTION / FINTWIN_DATA_LEGACY, so those tests depend on the developer's shell environment.
- fix: one autouse fixture in engine/tests/conftest.py clearing all four variables.
- effort: S

### S6 Legacy/flag branches threaded through production code (about 37 `data_legacy()` sites, 5+ env switches)
- where: engine/fintwin/backtest/batch.py (8 uses, e.g. :217-226, :237-255); backtest/walk_forward.py (4); research/experiments.py (10); research/stats.py (6); data/facts.py (4); data/xbrl_fallback.py:204 (`if E.data_legacy() or ...`)
- severity: slop
- changes numbers: no for the default path
- issue: `FINTWIN_DATA_LEGACY`, `FINTWIN_FIXES`, `FINTWIN_SPEC`, `FINTWIN_SELECTION` (11-17 reads each) make functions like `_baseline`, `_realized`, `_ttm` two functions in one (`if legacy: ... else: ...`). Reads as accreted toggles rather than a designed switch.
- fix: once the paper run is frozen, delete the legacy branches and env switches, keeping the v3 path; until then, document each variable in one place (spec.py docstring) and say they exist only to reproduce v2.
- effort: L

### S7 Opaque internal ticket codes in comments and docstrings (78 occurrences)
- where: engine/fintwin/backtest/batch.py:150,179,208,254,373,443 ("SW-4, D1", "D10", "E10", "SW-3"); data/edgar_universe.py:96 ("D12"); stochastic/calibrate.py:306 ("MM-F2"); data/xbrl_fallback.py:203,207 ("D11"); research/assumption_sobol.py:124,220 ("SW-3")
- severity: slop
- changes numbers: no
- issue: the codes are defined only in docs/REVISION_PLAN_3.md and docs/review_2026-10/*; a reader of the .py file cannot decode "D10" or "MM-F2". Reads like work-ticket ids pasted from a plan.
- fix: keep an id only where it adds a pointer, and always with the plain reason beside it (several already do). Delete the id where the sentence stands alone; add a one-line key at the top of spec.py pointing to REVISION_PLAN_3.md.
- effort: M

### S8 Broad `except Exception` that swallows in the data path
- where: engine/fintwin/data/xbrl_fallback.py:236-238 (`except Exception: return raw`, no log); :208 and :227 (`continue`); research/stats.py:595 (no log); api.py:64 and :69 (the two branches raise the same 422 with the same log line)
- severity: risk
- changes numbers: possibly (xbrl_fallback.py:236: a swallowed error silently drops fallback filings from the data). Needs owner decision.
- issue: 36 `except Exception` in engine/fintwin. Most record the reason (good: batch.py:342, experiments.py:817 count by type), but xbrl_fallback.py:236 and stats.py:595 leave no trace, so a broken fallback looks like "no fallback needed". `noqa: BLE001` appears on some and not others.
- fix: at least log a warning with the ticker/accession and narrow to `(OSError, ValueError, KeyError)`; merge the duplicate 422 branches in api.py.
- effort: S

### S9 Inconsistent output and logging style
- where: logging module used only in engine/fintwin/api.py; everything else uses bare `print(`: pipeline.py (8), research/__main__.py (8), data/edgar_universe.py (5), backtest/batch.py (4), export.py (3), research/assumption_sobol.py (3), plus about 15 scripts
- severity: slop
- changes numbers: n/a
- issue: progress, warnings and failures are all `print` to stdout, mixed with results, so server logs cannot be filtered.
- fix: warnings and failures to `print(..., file=sys.stderr)` or one `logging.getLogger("fintwin")` set up in the `__main__` entry points; keep results on stdout.
- effort: M

### S10 Long logic-packed lines and unexplained lint suppressions in TSX
- where: web/src/views/BacktestView.tsx:46 (632 chars), :119,:147,:162 (214-224); OverviewView.tsx:54,57,103,130 (207-244); TwinView.tsx (12 lines >170), TimeMachineView.tsx (12); StressLab.tsx:68 (effect plus `eslint-disable-line` on one line); VersusView.tsx:21-22 (three statements each plus a suppression); other suppressions hooks.ts:60, CompareView.tsx:47
- severity: slop
- changes numbers: no
- issue: most >170-char lines are prose `info=`/`alt=` strings (fine), but BacktestView.tsx:46 is a 632-char JSX attribute and VersusView/StressLab pack `onPair(a, b); setCa(null); loadCompany(a).then(setCa)` plus a silenced rule on one line. Six `react-hooks/exhaustive-deps` suppressions have no reason given. VersusView.tsx:21 also calls `onPair(a, b)` from an effect keyed on `[a]` only: the stale `b` is the reason for the suppression and may be a bug if `b` changes first.
- fix: move long alt/info prose to a copy.ts constants file; split effects across lines with a one-line reason beside each disable; in VersusView check whether `onPair` needs `b` and either add it or comment why not.
- effort: M

### S11 Small TS helper duplication and unnamed bounds
- where: web/src/ask/parse.ts:45 `clamp(k, v)` (range lookup) vs web/src/views/StressLab.tsx:45 `clampIcr` (literal 30 / -10, unexplained) vs parse.ts:171 `clampScenario`
- severity: slop
- changes numbers: no
- issue: `Math.max(Math.min(v, 30), -10)` re-implements clamp with magic bounds.
- fix: one `clamp(v, lo, hi)` in format.ts; name the bounds (`ICR_AXIS_MIN = -10`, `ICR_AXIS_MAX = 30`).
- effort: S

### D1 Docs disagree with code and each other
- where: docs/METHODOLOGY.md section 4 "Shocks are drawn as [N, T, 4]" vs engine/fintwin/model/sd_model.py:10 "`eps` [N, T, 5] (... regime uniform)"; README.md feature table "9 balance-sheet stocks" vs METHODOLOGY section 2 listing 10 stocks vs sd_model.py:3 docstring listing 9 (omits customer deposits)
- severity: slop
- changes numbers: n/a
- issue: counts disagree across three places, which is what unreviewed generated text looks like.
- fix: use one count (10, if deposits are a stock in code) in all three, and "[N, T, 5] (demand, margin, rate, financing, regime uniform)" in METHODOLOGY. Also README "Optional extras" mixes in "Version: 3.0.0-dev"; move it to the end as a plain line.
- effort: S

### D2 README.md prose: AI-ish tone, with rewrites
- where: README.md lead paragraph, "30-second pitch", feature table, closing lines
- severity: slop
- changes numbers: n/a
- issue and rewrites (the results section is concrete and honest; the weak spots are the marketing lines):
  - "FinTwin turns a company's SEC filings into a living model of its finances, then stress-tests it thousands of times." -> "FinTwin builds a quarterly cash-and-debt model of a US public company from its SEC filings and runs Monte Carlo stress tests on it." ("living model" is filler.)
  - "30-second pitch. A flight simulator for corporate finance." and "Then I tested it the hard way" -> cut the block or move it out of the README top; a metaphor-and-pitch block sits oddly above a table that reports the model losing to a 16-quarter margin.
  - "Editorial research-terminal design, light and dark." -> "Light and dark themes." (design adjectives are not a feature.)
  - "Always current, at zero cost" -> "Weekly rebuild" (the row's text already says what runs; "zero cost" is the free GitHub tier, not a guarantee).
  - "It is deterministic, so every figure is correct by construction." -> "Every figure is taken from the simulation output, not generated as text." ("correct by construction" overclaims.)
  - "If you find FinTwin useful, a star helps others find it." -> cut (template text).
  - "Contributions are welcome, from a typo fix to ..." duplicates CONTRIBUTING.md's opener; keep the links, drop the sentence.
  - The Run-it shell block has a 300+ char trailing comment on the pytest line ("CI badge above = current status; tests: balance-sheet identity ..."); move it to a sentence below the block.
  - Em-dash use is not an issue: zero U+2014 in README, CONTRIBUTING and METHODOLOGY, 5 en-dashes used for ranges.
- effort: S

### D3 CONTRIBUTING.md and METHODOLOGY.md tone
- where: CONTRIBUTING.md:3; docs/METHODOLOGY.md ("Four problems, four fixes." heading; section 5 "line-for-line port")
- severity: slop
- changes numbers: n/a
- issue: both are clean and specific. Nits only: "Four problems, four fixes." is slogan-like; "line-for-line port" is not literally true (TS uses its own helpers such as `sum4`).
- fix: "Four data problems and how each is handled."; "a port that follows the Python step by step".
- effort: S
