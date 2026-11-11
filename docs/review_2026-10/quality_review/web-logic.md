# web-logic review (web/src/engine, charts, ask, top-level *.ts/tsx)

Paths are relative to D:\Projects\products\comp_project. Parity was checked by reading web/src/engine/model.ts against
engine/fintwin/model/sd_model.py line by line; apart from W6 and W9 the two agree. There is no `any`, `@ts-ignore` or
`as any` in scope (only 4 eslint-disable lines, all in hooks/views).

### W1 Malformed URL hash crashes the whole app
- where: web/src/hooks.ts:65-72 (useHashState)
- severity: bug
- changes numbers: n/a
- issue: `decodeURIComponent(location.hash.slice(1))` throws URIError on any hash with a stray `%` (e.g. `#stress/%`, a truncated pasted share link). It runs in the useState initializer and in the hashchange handler, so the root component throws and there is no error boundary.
- fix: wrap in a small `safeDecode(s)` (try/catch returning the raw string) used in both places.
- effort: S

### W2 A worker failure leaves the UI "busy" forever
- where: web/src/hooks.ts:25-37, 46-60; web/src/engine/worker.ts:15-25
- severity: bug
- changes numbers: n/a
- issue: the worker has no try/catch and the main thread no `worker.onerror`/`onmessageerror`. Any exception inside simulate/summarize (bad or short params, see W8) kills the request silently: the `runSimulation` promise never settles, `pending` leaks, and `useSimulation` stays `busy: true` with the old summary. HeroSim shares the same worker, so one bad run stalls it too.
- fix: wrap the handler body in try/catch and post `{id, error: String(e)}`; in getWorker add `onerror` that rejects all pending; make runSimulation reject, and have useSimulation `.catch` set `busy:false` plus an error field.
- effort: S

### W3 Stale slider requests are still computed, queued behind each other
- where: web/src/hooks.ts:46-60 (latest ticket), web/src/engine/worker.ts:15
- severity: risk
- changes numbers: no
- issue: latest-wins only discards the result. Every posted request is still run in full (5,000 paths, 11 variables x T sorts) in one single worker, strictly in order. Dragging a slider or switching presets queues several complete runs, so the result for the final position arrives late; HeroSim's runs queue behind them too.
- fix: in the worker keep only the newest request: store `latest = e.data` and `setTimeout(run, 0)` so already-queued messages overwrite it first; reply `{id, superseded:true}` for dropped ids so their promises settle (the hook ignores them).
- effort: M

### W4 StripPlot crashes when the active company misses a scenario value
- where: web/src/charts/StripPlot.tsx:73-80
- severity: bug
- changes numbers: n/a
- issue: the dots loop guards `if (v == null) return null`, but the highlight for `activeItem` indexes `activeItem.values[r.key]` unguarded: `undefined.toFixed(0)` throws (TypeError, blanks the page on hover) and the polyline gets `NaN` coordinates. `StripItem.values` is typed `Record<string, number>`, so the type does not warn; the data comes from index.json.
- fix: build `const pts = rows.map((r,i)=>({r,i,v:activeItem.values[r.key]})).filter(p=>p.v!=null)` and render polyline/labels from that.
- effort: S

### W5 App can show the wrong company or stay on a skeleton (no cancel on load)
- where: web/src/App.tsx:56-61; same pattern web/src/views/VersusView.tsx:21-22
- severity: risk
- changes numbers: n/a
- issue: `loadCompany(ticker).then(setCompany).catch(setError)` has no cancelled flag. If the user switches A -> B quickly and A resolves last, `company` is A while `ticker` is B: the view shows a skeleton and nothing re-triggers a load. A late failure for A also sets an error banner while B is displayed.
- fix: `let live = true; ... .then(c => live && setCompany(c)) ...; return () => { live = false; }`.
- effort: S

### W6 Python `_rank` has no NaN guard, TS `ratingRank` does: engines disagree on NaN coverage
- where: engine/fintwin/model/sd_model.py:114 vs engine/fintwin/model/ratings.py:41-44 vs web/src/engine/ratings.ts:10
- severity: bug
- changes numbers: yes (only on paths where ICR is NaN; none in the current goldens)
- issue: sd_model.simulate uses its own local `_rank` (plain searchsorted: NaN -> AAA, rank 14). The SW-9 fix ("an undefined coverage ranks worst, as in ratings.ts") was applied to `ratings.rating_rank`, which sd_model does not call. TS returns 0 (D). The claimed parity does not hold exactly where the fix matters, and there are two copies of the helper. The parity test cannot catch it (no NaN golden).
- fix: needs owner decision (touches the pre-registered model): replace `_rank` in sd_model.py by `rating_rank` (call sites lines 241, 383, 402) and add a golden with NaN EBIT; zero effect where ICR is finite. If numbers must stay frozen, instead correct the comment in ratings.py and document the divergence.
- effort: S

### W7 JSON data is cast, never validated; load failures are swallowed
- where: web/src/data.ts:92-100 (getJson), 104, 117, 135 (`.catch(() => null)`)
- severity: risk
- changes numbers: n/a
- issue: `r.json()` (any) is returned as `Promise<T>` for Index/Company/Backtest/Calibration etc., so every field in the ~150 lines of types is trust-me. The `.catch(() => null)` loaders turn a 404, a network error and a JSON syntax error into the same "no data", hiding a broken deploy. A rejected promise stays cached for index/backtest (only loadCompany evicts), so one transient failure needs a page reload. `loadMemo`/`loadTimeline` interpolate the ticker unencoded while `loadCompany` uses encodeURIComponent.
- fix: evict failed entries inside getJson (`.catch(e => { cache.delete(path); throw e; })`); return null only on HTTP 404 and rethrow/log otherwise; add a minimal shape check for what the engine needs (`horizon`, `maturities_q.length >= horizon`, `seasonal.length === 4`, `*_ttm0.length === 4`); encode tickers uniformly.
- effort: M

### W8 simulate() has no input guards: short ladder or short eps gives silent NaN
- where: web/src/engine/model.ts:25, 64, 138, 230
- severity: risk
- changes numbers: no
- issue: `ladder[t]` and `eps[o]` are read unchecked. If `maturities_q` is shorter than `horizon`, or `eps` shorter than N*T*5, every downstream value turns into NaN (Math.min/Math.max propagate it) and the UI shows "–" or zeros instead of failing; the Python engine raises there. `maturityWall` in summary.ts pads with `?? 0` while the simulation does not, so the two disagree on the same input. Current snapshot data is fine (A.json: horizon 12, ladder 12).
- fix: at the top of simulate: `if (ladder.length < T || eps.length < N*T*SHOCK_COLS) throw new Error(...)`. It then surfaces through the W2 error path.
- effort: S

### W9 decisionOutputs.revolver_due diverges from Python for fractional maturities
- where: web/src/engine/summary.ts:174-178 vs engine/fintwin/model/sd_model.py:497-498
- severity: bug
- changes numbers: no (web only; the Python value is the reference)
- issue: Python tests `0 < int(mq) < T`; TS tests `mq > 0 && mq < T` before truncating. For mq in (0,1) TS passes, `q = 0`, and reads `out.revolver[i*T + q - 1]`, the previous path's last quarter (index -1 = undefined for path 0), giving a wrong or NaN median.
- fix: `const q = Math.trunc(mq ?? 0); if (q > 0 && q < T)`.
- effort: S

### W10 FanChart sample paths are not part of the y-domain and are not clipped
- where: web/src/charts/FanChart.tsx:56-62, 156-159
- severity: bug
- changes numbers: n/a
- issue: the domain is built from history, p5/p95 bands, realized and refLine, but `samplePaths` (40 individual paths, which routinely leave the 5-95% band) are drawn without a clipPath, so lines can run over the axis labels, the x tick row or outside the SVG.
- fix: add a `<clipPath>` for the plot rectangle around the sample paths (cheapest), or include the paths' min/max in `vals`.
- effort: S

### W11 Shock generator: unvalidated t_df / rho, undocumented 32-bit resolution
- where: web/src/engine/shocks.ts:12, 35-52 (gamma), 49-70 (drawShocks)
- severity: risk
- changes numbers: no
- issue: (a) `df <= 2`: `tScale = sqrt((df-2)/df)` is 0 or NaN (all-zero or NaN shocks), and for `df/2 < 1` `gamma()` can return 0 when `uniform()` is 0, so `kG = Infinity`. Calibrated t_df is 3.0 in the snapshot, so not reachable today, but Params.t_df is unchecked JSON. (b) `rho_gm` outside [-1,1] gives NaN margin shocks. (c) the uniform has 32-bit resolution, so Box-Muller caps normals near +-6.2 sigma; harmless for the 5-95% bands but not mentioned next to the "same distributional recipe" claim in the file header.
- fix: guard `t_df > 2` (clamp or fall back to normal) in drawShocks; one line in the header on the resolution limit.
- effort: S

### W12 Output allocation duplicated; casts and non-null assertions around Outputs
- where: web/src/engine/model.ts:27-28, 49, 249, 265-266, 274-279; web/src/engine/types.ts (Outputs)
- severity: slop
- changes numbers: no
- issue: `Object.fromEntries(OUTPUT_KEYS.map(...)) as unknown as Outputs` is copy-pasted in simulate and simulateBlocks, then `.N`/`.T` are patched on. The M1 arrays are optional on the type, which forces `out.cov_breach![i]` and `out[k]!` in the hot loop and the merge code.
- fix: add `allocOutputs(N, T, withM1)` returning a fully typed object; use it in both functions and drop the lazy creation in simulateBlocks.
- effort: S

### W13 Magic numbers in simulate(); health weights triplicated
- where: web/src/engine/model.ts:102-104, 124, 139, 226, 234-238; web/src/charts/Waterfall.tsx:9-14, 22-23
- severity: slop
- changes numbers: no
- issue: `0.015` (revolver spread), `0.9` (interest-income share), `1.5`/`2.5` (stress triggers), the access ladder `1.5/0.8` and `0.6/0.3`, `6` (leverage cap), the Altman coefficients and the health weights `0.3/0.3/0.2/0.2` are bare literals. The weights are repeated in Waterfall (PARTS and again in capBase/capScen), so a change in one place silently breaks the "adds up exactly" claim. Python exposes the access thresholds as params (`access_icr`, `access_levels`); TS hard-codes them.
- fix: hoist named consts at the top of model.ts (`REVOLVER_MARGIN`, `CASH_INTEREST_SHARE`, `HEALTH_WEIGHTS`), import HEALTH_WEIGHTS in Waterfall. Values unchanged.
- effort: S

### W14 parse.ts: dead/misleading code, a regex precedence slip, prototype-key hole
- where: web/src/ask/parse.ts:35, 83, 174
- severity: slop
- changes numbers: no
- issue: (1) `Object.assign(knobs, preset, knobs)`: `knobs` is empty there and the loop `break`s after the first match, so the third argument and the comment "earlier (more specific) matches win" mean nothing. (2) `/\bstagflation|1970s\b/` is `(\bstagflation)|(1970s\b)`; the second branch has no leading boundary; should be `/\b(?:stagflation|1970s)\b/`. (3) `clampScenario` uses `k in RANGES`, the prototype-key class that scenarioUrl.ts already fixed with `own()`: `"toString" in RANGES` is true and would yield `knobs.toString = NaN`. Unreachable today (callers pre-filter) but it is documented as "the guardrail".
- fix: `Object.assign(knobs, preset)`; fix the regex; use hasOwnProperty in clampScenario and drop the redundant double `own(...)` check in scenarioUrl.ts:500.
- effort: S

### W15 AskTwin duplicates llm.ts constants; Scenario type name collides with the engine's
- where: web/src/ask/AskTwin.tsx:20, 80, 98; web/src/ask/llm.ts:12, 15; web/src/ask/parse.ts:11
- severity: slop
- changes numbers: n/a
- issue: `gpu` state re-implements `webgpuAvailable()`; the text `({"about 1 GB"}, ...)` (a string literal inside braces) duplicates `MODEL_SIZE`; "Qwen2.5 1.5B" is hard-coded and duplicates `MODEL`. parse.ts exports `Scenario` (knobs + levers) while engine/types.ts exports a different `Scenario` (per-quarter arrays). `run()` sets `busy` and resets it without try/finally, so a throw in parseScenario leaves the button on "Thinking...".
- fix: import `webgpuAvailable`/`MODEL_SIZE` from llm.ts (it has only a type import of web-llm, so it does not pull the chunk); rename the parse.ts type to `ScenarioSpec`; try/finally in run().
- effort: S

### W16 Waterfall: no-op ternary, width mismatch
- where: web/src/charts/Waterfall.tsx:61 and the slot/width lines (~36-38)
- severity: slop
- changes numbers: n/a
- issue: `y(b.kind === "total" ? b.y1 : b.y1)` (both branches identical, written twice). Slots are laid out with `Math.max(width, 300)` but the svg is `width` wide, so below 300 px the bars overflow the svg.
- fix: `const yl = y(b.y1)`; use the same floor for the svg width, or drop it.
- effort: S

### W17 ShockPreview builds its label parts twice
- where: web/src/charts/ShockPreview.tsx:15-16, 28
- severity: slop
- changes numbers: n/a
- issue: the same three-element `[... && "markets shut", ...].filter(Boolean)` array is built at line 15 and again inline at line 28 with a different separator.
- fix: reuse `shockParts.join(" · ")`.
- effort: S

### W18 useTween jumps when interrupted mid-animation
- where: web/src/ui.tsx:22
- severity: bug
- changes numbers: n/a
- issue: the effect cleanup sets `from.current = value` (the old target) instead of the value currently shown. When a new value arrives during a tween (slider drag), the next tween starts from the old target, so the number snaps before animating.
- fix: keep a `shownRef` updated in `step` and in cleanup do `from.current = shownRef.current`.
- effort: S

### W19 format.ts: leftover no-op and edge cases
- where: web/src/format.ts:38-39 (quarterLabel), 18-19 (pct), 1-8 (money)
- severity: slop
- changes numbers: n/a
- issue: `(d.getUTCMonth() + 12 - 0) % 12` is a no-op (`+12 -0`); `Math.floor(d.getUTCMonth() / 3) + 1` as in futureQuarters is enough. `pct`/`fixed` print "-0%"/"-0.0" for tiny negatives (`signed` handles this, these do not). `money()` ignores `digits` for the M tier and shows "$1000.0B" / "$1000M" at rounding boundaries (999.96e9, 999.5e6).
- fix: simplify quarterLabel; normalise -0 in pct/fixed (`+x.toFixed(d)` trick as in `signed`); choose the tier after rounding.
- effort: S

### W20 summary.ts: duplicated helpers, long mixed-purpose function
- where: web/src/engine/summary.ts:41-106 (summarize), 61, 65, 91, 109-110
- severity: slop
- changes numbers: no
- issue: `med` (line 91), `median` + `sortedCopy` (109-110) and the local `mean` overlap; `eqSum`/`debtSum` are `let` arrays that are never reassigned (could be Float64Array(N)). `summarize` mixes bands, per-path scans, histogram and sample picking in one 65-line body.
- fix: hoist sortedCopy/median above summarize and use them everywhere; `const`; optionally split a `perPath()` helper. Output identical.
- effort: S

### W21 Hot-path churn in simulate and per-hover re-render in StripPlot
- where: web/src/engine/model.ts:55, 193-195; web/src/charts/StripPlot.tsx:31, 60-70
- severity: risk
- changes numbers: no
- issue: each of N=5,000 paths allocates 3 history arrays and does shift()/push() every quarter. It runs in a worker so the main thread is not blocked, but ring buffers would cut GC. StripPlot re-renders every dot (rows x items circles) on each pointer-enter and re-sorts `order` each render; with hundreds of companies x 9 scenarios that is thousands of SVG nodes per hover.
- fix: measure first. If needed: ring indices in simulate (keep the oldest-first summation order so output stays bit-identical) and `useMemo` for `order` and the dot layer in StripPlot.
- effort: M

### W22 App.tsx structure
- where: web/src/App.tsx:18, 37, 63-75, 81-85
- severity: slop
- changes numbers: n/a
- issue: `import { TwinView }` sits after the lazy() consts (and is eager while the other seven views are lazy, with no comment why). `navRef`/`toggleThemeRef` are declared below the `useEffect` that closes over them (works only because the effect runs later). `dark` is read via `matchMedia` on every render and does not react to an OS theme change.
- fix: move the import up; declare the refs before the effect; subscribe to the media query once if live tracking matters.
- effort: S

### W23 Tests: wall-clock assertion and near-tautological checks
- where: web/src/engine/model.test.ts:69-79 (and 58-68)
- severity: test
- changes numbers: n/a
- issue: "runs 5,000 paths fast" asserts `ms < 2000`, which is flaky on a loaded runner or this shared PC, and `expect(s.healthScore).toBeGreaterThanOrEqual(0)` holds for any clamped score, so it checks nothing about correctness. The parity goldens contain no NaN / zero-interest / negative-EBITDA edge (W6), no fractional `revolver_maturity_q` (W9), and `_param_draws` is only tested TS-against-TS, not against a Python golden.
- fix: drop the timing (or move it to a benchmark); assert real properties (pBreach in [0,1], bands monotone p5<=p25<=...); add goldens exported from Python for NaN ICR and `_param_draws`.
- effort: M

### W24 Untested top-level logic that is easy to get wrong
- where: web/src/format.ts (futureQuarters, quarterLabel, money, prettyName), web/src/hooks.ts (useHashState), web/src/engine/scenario.ts
- severity: test
- changes numbers: n/a
- issue: only `signed` and `healthStatus` are tested. `futureQuarters` (date arithmetic over year boundaries; 52/53-week fiscal dates such as 2025-01-03 are labelled Q1 although they close Q4), `prettyName`, `money` tiers and `buildScenario` (the Python mirror, incl. the hold>1 half-blow rule) have no direct test.
- fix: small table tests for these; a golden-style test comparing `buildScenario` with Python output for the 10 presets.
- effort: S

### W25 CommandPalette accessibility wiring is partial
- where: web/src/CommandPalette.tsx:199, 222
- severity: slop
- changes numbers: n/a
- issue: `role="combobox" aria-expanded` is constant, with no `aria-activedescendant` or option ids, so screen readers cannot follow the selection; the focus `setTimeout` is never cleared on close.
- fix: give options ids, set `aria-activedescendant`, clear the timeout in the effect cleanup.
- effort: S
