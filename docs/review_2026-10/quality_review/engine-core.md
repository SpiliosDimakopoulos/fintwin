# engine-core review (model/, stochastic/, scenarios/, top-level engine/fintwin/*.py except export.py)

Read-only. Verified by reading; items marked "(ran)" were also reproduced with a tiny script. No full test suite run.
Overall: the numerical core is in good shape (identity holds, switches are cleanly gated, non-finite calibrated params raise).
I found no demonstrable number-changing bug in model/ or stochastic/. Findings are mostly duplicated constants, a diverging
dead fallback, text/number mismatches in notes, mislabelled provenance, and a few weak tests.

### EC-01 Memo number checker flags dates and year ranges as negative figures
- where: engine/fintwin/memo.py:263 (NUM), :293
- severity: bug
- changes numbers: n/a
- issue: `NUM = r"-?\$?\d+..."` reads the hyphen in "2024-25", "Q3-2026" or "2025-03-31" as a minus sign. (ran) `_numbers("2025-03-31")` gives `[2025, -3, -31]`; in strict mode (used at build time) a negative figure must match a negative figure in the sheet, so `unverified_numbers({'x': 'in 2025-03-31 ... a 2024-25 slump'}, sheet, strict=True)` returns `[-31.0, -25.0]`. A valid memo then triggers the one regeneration and can end up flagged in the UI.
- fix: only treat `-` as a sign when not preceded by a word character or digit: `NUM = re.compile(r"(?<![\w.])-?\$?\d+(?:,\d{3})*(?:\.\d+)?")`; add a test with "2024-25" and "Q3-2026" in tests/test_helpers.py.
- effort: S

### EC-02 sd_model keeps a dead ImportError fallback whose defaults silently differ from spec.py
- where: engine/fintwin/model/sd_model.py:25-42
- severity: risk
- changes numbers: no (the fallback never runs)
- issue: `stochastic/spec.py` is in the same package and imports nothing, so `except ImportError` cannot fire. If it ever did, the fallback differs: default spec "v2-pre" (spec.py: "v2-rev") and `_SPEC_FIXES["v3"] = {"F3","F6","F11"}` (spec.py: F1..F14 except F9/M2, plus F11). A second, wrong copy of the "single source of truth" in a pre-registered path is a trap.
- fix: delete the try/except, `_SPEC_FIXES` and the `os` import; `from ..stochastic.spec import active`.
- effort: S

### EC-03 notes.py writes "5,000 simulated futures" as a literal; other figures hard-coded too
- where: engine/fintwin/notes.py:132, :155, :120
- severity: bug
- changes numbers: n/a
- issue: `fact_sheet` uses `c.get("n_paths", 5000)` but `write_note` writes "Across 5,000 simulated ..." regardless; the live API builds twins with n_paths=3000 (api.py:297). "A 30% revenue fall" (l.155) and "95% revenue drop held for three quarters" (l.120) restate sensitivity/tornado.py:9 and `reverse_stress.TARGETS` by copy and drift if those change.
- fix: `n = c.get("n_paths", 5000)` and f"{n:,}"; take 0.3 from a named constant in tornado.py and 0.95/3 from `TARGETS["sales_depth"]`.
- effort: S

### EC-04 write_note understates quarterly revenue when a quarter is missing (fact_sheet handles it, write_note does not)
- where: engine/fintwin/notes.py:108 vs :38-40
- severity: bug
- changes numbers: n/a (notes text only)
- issue: `rev_q = sum(x for x in last4 if x is not None) / 4` divides by 4 even if a quarter is None, biasing `fixed_share` (l.110). `fact_sheet` explicitly refuses an incomplete TTM, with a comment saying why.
- fix: one helper `_ttm_revenue(c)` returning None when incomplete; skip the fixed-share sentence when None.
- effort: S

### EC-05 sales_duration does not mean "quarters at the trough"
- where: engine/fintwin/scenarios/presets.py:11, :244-246 (and preset desc l.28, reverse_stress.py:283, notes.py:120)
- severity: risk
- changes numbers: no for the wording fix; yes for any shape change (TS engine and goldens must follow)
- issue: (ran) depth 0.2, hold 2, recovery 2 gives `[-0.1, -0.2, -0.133, -0.067, 0, 0]`; hold 3 gives `[-0.1, -0.2, -0.2, -0.133, ...]`. The first quarter is always half depth when hold > 1, so a knob described as "Quarters at the trough" gives hold-1 full-depth quarters, and "holds 2 quarters" / "held 3 quarters" overstate by one. hold == 1 skips the half-blow, so hold 1 is deeper in q0 than hold 2.
- fix: reword the knob and preset descriptions ("ramps in over the first quarter, then holds"). Shape change is an owner decision. Also replace `sales[0] = -depth * 0.5 if hold > 1 else sales[0]` with `if hold > 1: sales[0] = -0.5 * depth`.
- effort: S (wording) / L (shape)

### EC-06 Starting cash ignores the stale-balance logic used for every other stock
- where: engine/fintwin/stochastic/calibrate.py:758 vs :522, :839-846
- severity: risk
- changes numbers: yes (only firms whose short investments or cash are NaN in the last row) - needs owner decision
- issue: `last` (from `_last_known`) carries each stock back up to STALE_ROWS and notes it in `_sources["stale"]`, but `cash0` is recomputed from `q`: `q["cash"].ffill()` (any age, no note) plus `q["short_investments"].fillna(0)` (0 even when `last` carried a value). `other_net0` derives from `cash0`, so the identity holds, but cash is inconsistent with debt/AR/etc and `cash` in STOCK_ANY is effectively dead.
- fix: in the new-data path `cash0 = float(last["cash"] + last["short_investments"])` after checking finiteness; keep the ffill for the legacy path.
- effort: S

### EC-07 Duplicated model constants across files (drift risk in the F10/F5 anchor)
- where: calibrate.py:626, 822, 889 (inflation 0.006 three times); calibrate.py:182 and sd_model.py:246 (interest income `* 0.9 / 4`); calibrate.py:23 and sd_model.py:80 (DAYS_Q); calibrate.py:798 (`floating = 0.1` vs FLOATING_DEFAULT); sd_model.py:245 (`0.015` revolver margin, no source)
- severity: slop
- changes numbers: no
- issue: `_anchor_ocf` rebuilds the model's income statement and must match it exactly, using literals copied from simulate. `infl` deflates the cost fit (F10), is used in the anchor, and is `p["infl"]` in the simulator; editing one silently breaks the F10 consistency.
- fix: one constants module (model/constants.py: `INFL_Q`, `CASH_YIELD_SHARE = 0.9`, `REVOLVER_MARGIN = 0.015`, `DAYS_Q`), imported by both. Same values, no number change.
- effort: S

### EC-08 Magic thresholds in simulate() without a name or source; health weights copied in three places
- where: sd_model.py:267 (`1.5 * cash_floor`, `icr_prev < 2.5`), :398 (`/ 8.0` quarters of runway), :402-405 (`/ 14.0`, `6.0 * tol`, `1.1`, `1.5` in the Z scale), :392 (Altman coefficients); changes.py:452 (weights copied); test_model.py:154; mc.py:151 and notes.py:20 (investment-grade rank 9 literal while `ratings.INVESTMENT_GRADE_MIN_RANK` exists and is unused)
- severity: slop
- changes numbers: no
- issue: the health score and the B1 stress trigger carry unexplained constants; 2.5 coincides with `NET_CASH_ICR` and BBB but nothing says so.
- fix: name them at module top with a one-line source or "assumption" tag (`HEALTH_WEIGHTS`, `STRESS_ICR`, `Z_DISTRESS/Z_SAFE`), import `INVESTMENT_GRADE_MIN_RANK` in mc.py and notes.py, import the weights in changes.py.
- effort: S

### EC-09 `median_quarters_to_breach`, runway and first-covenant-breach are 0-based
- where: engine/fintwin/stochastic/mc.py:145-157; engine/fintwin/model/sd_model.py:470-504
- severity: risk
- changes numbers: no if documented; yes if shifted
- issue: `argmax` returns the quarter index, so a breach in the first simulated quarter reports 0 "quarters to breach"; docstrings say "quarters until". `median_quarters_to_breach` appears only as a type in web/src/data.ts (no consumer found), so it may be dead output.
- fix: document "0 = first simulated quarter" or add 1 (check web/src/engine/summary.ts uses the same convention); drop the field if unused.
- effort: S

### EC-10 `_calibrate` is about 670 lines and `simulate` about 330
- where: engine/fintwin/stochastic/calibrate.py:309-982; engine/fintwin/model/sd_model.py:118-449
- severity: slop
- changes numbers: no (pure extraction)
- issue: calibrate mixes revenue, regime, D&A, cost split, working capital, financing, ladder and stock initialisation in one scope with shared locals. Switch-guarded locals (`share` set under `f4`, `m_dev0` under `f6`) are used at :942-944 under a second, separate guard; if the two guards diverge it is a NameError.
- fix: extract per-block helpers returning small dicts (`_revenue_process`, `_cost_structure`, `_working_capital`, `_ladder`, `_initial_stocks`); keep the golden/parity tests as the safety net. In simulate, extract `_health_score(...)` and the output-recording loop.
- effort: L

### EC-11 `src["maturities"].startswith("XBRL")` used as control flow
- where: engine/fintwin/stochastic/calibrate.py:961-962
- severity: slop
- changes numbers: no
- issue: `ladder_unknown` is derived by string-matching a human-readable note written about 180 lines earlier; rewording the note flips the flag.
- fix: set `ladder_known` in the branch that builds the ladder and use it at :962.
- effort: S

### EC-12 `except Exception: pass` around the Student-t fit
- where: engine/fintwin/stochastic/calibrate.py:544-550
- severity: slop
- changes numbers: no
- issue: swallows every error (including a typo or KeyError) and silently leaves df = 30 (normal). The expected failures are scipy fit errors on degenerate residuals.
- fix: `except (RuntimeError, FloatingPointError, ValueError)` and record in `src["t_df"]` that the fit failed and the normal was assumed.
- effort: S

### EC-13 `_sources` claims an estimate that did not happen
- where: engine/fintwin/stochastic/calibrate.py:699-709 and :551
- severity: risk
- changes numbers: no
- issue: with F13 on, `src["tau_ar"]` says "estimated from N quarters" even when `okr.sum() < 8` and tau_ar stays 1.0. `src["t_df"]` says "MLE Student-t fit" even when fewer than 12 residuals left df at 30. The dashboard shows provenance, so an assumption is labelled an estimate.
- fix: set the source string only inside the branch that estimated; otherwise "assumption: ...".
- effort: S

### EC-14 `sd_model._rank` duplicates `ratings.rating_rank` without its NaN guard; `rating_spread` unused
- where: engine/fintwin/model/sd_model.py:114-115; engine/fintwin/model/ratings.py:41-48
- severity: slop
- changes numbers: no for finite inputs
- issue: ratings.py documents SW-9 (NaN ranks worst, as in ratings.ts) but the model uses its own `_rank`, where NaN ranks AAA. Inputs are finite today (calibrate rejects non-finite params), so it is latent. `rating_spread` has no caller; `ICR_LOWER` is imported in sd_model only for `_rank`.
- fix: `from .ratings import rating_rank` in the model; delete `_rank` and `rating_spread`.
- effort: S

### EC-15 reverse_stress redoes work and runs a full `summarize` for one number
- where: engine/fintwin/scenarios/reverse_stress.py:292-329
- severity: slop
- changes numbers: no
- issue: `reverse_stress` calls `breaking_point` twice per knob (p10, p50); each redraws the same shocks (same seed) and re-runs the lo and hi end-points, and each bisection step calls `summarize`, which takes percentiles of ten variables only to read `p_breach`. About 6 x 20 simulations plus summaries per company.
- fix: draw `eps` once in `reverse_stress` and pass it in; evaluate prob(lo)/prob(hi) once per knob and bisect for both targets; use `out["breach"][:, -1].mean()` instead of `summarize`.
- effort: M

### EC-16 `breaking_point` returns the lower bound when baseline already breaches; notes read it as a real shock
- where: engine/fintwin/scenarios/reverse_stress.py:307-308; engine/fintwin/notes.py:117-121
- severity: risk
- changes numbers: no
- issue: when baseline P(breach) >= target, p50 = 0.0 and the note says "breaks (50% breach odds) at a 0% revenue drop"; the headline says "any one of: revenue drop of 0%; interest-rate rise of 0bp". Correct, but it reads as a bug. No test covers the sales_depth or rate_bp knobs or `headline`.
- fix: return a flag or sentinel (`already_breached`) and render "already above 50% at baseline"; test `headline` with p50 == lo.
- effort: S

### EC-17 `classify()` rereads a CSV on each call; `sector_multiplier` reparses JSON each call
- where: engine/fintwin/universe.py:388-391; engine/fintwin/scenarios/presets.py:191-200
- severity: risk
- changes numbers: no
- issue: for "~" tickers `classify` does `pd.read_csv(bankruptcies_2020.csv)` on every call (the EDGAR csv is cached via `_edgar()`); `sector_tolerance`, called from every `calibrate`, goes through it. `sector_multiplier(table=None)` reads and parses the JSON on every call.
- fix: `@lru_cache` a `_bankruptcies()` loader like `_edgar`, and cache `load_sector_shocks`.
- effort: S

### EC-18 pipeline.shard duplicates `expected_tickers()` and rebuilds the universe list inside a comprehension
- where: engine/fintwin/pipeline.py:60-62 vs :84-88; :172-181
- severity: slop
- changes numbers: n/a
- issue: `universe.tickers()` (list built from the DataFrame) is called per element in the `not in` test, and the same list logic exists in `expected_tickers`. `__main__` does `sys.argv[1]` with no usage message (IndexError on a bare call).
- fix: `tickers = [t for k, t in enumerate(expected_tickers()) if k % n == i]`; a usage `SystemExit` or argparse.
- effort: S

### EC-19 changes.py hard-codes "5 points" in the RSS text instead of THRESHOLD
- where: engine/fintwin/changes.py:544 vs :448
- severity: slop
- changes numbers: n/a
- issue: the empty-week message says "moved by 5 points or more" while the filter uses `THRESHOLD`; changing THRESHOLD makes the feed wrong. `_round` (l.456) is a one-use wrapper.
- fix: `f"... {THRESHOLD:g} points or more."`; inline `_round`.
- effort: S

### EC-20 notes.py / memo.py structure oddities
- where: engine/fintwin/notes.py:276; engine/fintwin/memo.py:212, :375
- severity: slop
- changes numbers: n/a
- issue: `RULE_BASED` is used at line 261 and defined at 276 (works only through call-time lookup). Importing `fintwin.memo` (tests/test_helpers.py does) runs `load_dotenv(..., override=True)` at import, mutating `os.environ`, so a test run can replace credentials in the process. `build = main` is never imported anywhere.
- fix: move `RULE_BASED` to the top; call `load_dotenv` inside `main()`; delete the alias.
- effort: S

### EC-21 Small slop in simulate: double dict for `po`, `identity_gap` allocated inside the loop
- where: engine/fintwin/model/sd_model.py:186-187, :446
- severity: slop
- changes numbers: no
- issue: `po = {**PAYOUT_DEFAULTS.get(...)}` is immediately rebuilt by a comprehension over the same dict. `out.setdefault("identity_gap", np.zeros((N, T)))` evaluates `np.zeros` every quarter and keeps only the first; `identity_gap` is also missing from `OUTPUTS`, so it is an undeclared side channel used by tests.
- fix: `po = {k: p.get(k, d) for k, d in PAYOUT_DEFAULTS.get(cls, ZERO_PAYOUT).items()}`; allocate `identity_gap` with the other outputs and add it to `OUTPUTS` (check the TS parity test ignores it).
- effort: S

### EC-22 api.py has no in-flight de-duplication for an expensive endpoint
- where: engine/fintwin/api.py:286-309
- severity: risk
- changes numbers: n/a
- issue: the cache check and fill are locked, but the 3000-path build runs outside the lock, so N concurrent requests for one cold ticker start N builds (the l.300 comment handles overwrite, not duplicate work). Failures are not cached, so a bad ticker rebuilds on every request. Local dev API, low impact.
- fix: a per-ticker lock or Future map, or cache failures for a short TTL.
- effort: M

### EC-23 Health waterfall test asserts an inequality while the comment claims equality
- where: engine/tests/test_model.py:150-156
- severity: test
- changes numbers: n/a
- issue: the comment says "weighted components minus the breach cap equals the mean health exactly", but the assertion is `weighted >= sm["health_mean"] - 1e-9`, which a wrong weight or cap would also satisfy.
- fix: assert `weighted == approx(health_mean)` on a run with `p_breach == 0`, and compute the expected cap reduction for a breached run.
- effort: S

### EC-24 Rating bucket test misses boundaries and NaN
- where: engine/tests/test_model.py:84-87
- severity: test
- changes numbers: n/a
- issue: three interior points only. The edges (exactly 2.5, 0.2, 8.5, inf) and the SW-9 NaN rule are untested, and the model uses a different `_rank` (EC-14).
- fix: parametrize over `ICR_LOWER` (rank i at LOWER[i], i-1 just below), plus nan -> 0, inf -> 14, and run the same cases against the model's ranking.
- effort: S

### EC-25 Untested risky paths
- where: engine/fintwin/stochastic/calibrate.py (`_last_reported`/`_last_known`, `_trailing`, ladder at :774-796, `fit_vasicek` with b >= 0.995); engine/fintwin/scenarios/reverse_stress.py (`headline`, `_fmt`, sales_depth/rate_bp); engine/fintwin/notes.py (`write_note`)
- severity: test
- changes numbers: n/a
- issue: grep of engine/tests found no direct test of `write_note`, `headline`, or the ladder branches. In the ladder, `per_q[elapsed_q:]` goes wrong if `maturities_date` is after the last quarter (negative `elapsed_q` slices from the end). test_reverse_stress exercises only the cost_pp knob.
- fix: a table test per ladder branch (fresh XBRL, stale with M3, stale without), a `write_note` test on a fixture company covering rs p50 None / == 0 and a missing quarter; `elapsed_q = max(elapsed_q, 0)`.
- effort: M
