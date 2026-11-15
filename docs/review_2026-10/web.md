# Web review (wave 2): frontend and science communication

Scope: web/src, web/index.html, web/public/data, README.md, .github/workflows/pages.yml. Read-only; no build or tests run.
Already known, not repeated: "all non-financial SEC filers" alt text (BacktestView.tsx:40); "390+ companies" vs 377/331.

## HIGH

H1. web/public/findings.png is stale and contradicts the page text (used at BacktestView.tsx:37-41).
- Panel 1 shows mean-style errors (4q margin 13.9, 16q 12.9, regression 16.0, twin 18.6, blends 12.5/12.4). The page and paper use MEDIAN errors (7.7, 6.9, 9.4, 11.3).
- Panel 2 axis says "377 petitions"; page, README and paper say 420.
- web/public/findings.png and docs/findings.png differ byte-wise, so two copies diverge.
- Fix: generate one file from research.json in research_assets.py, copy it at build; label "median" and "420 petitions".

H2. "Validated" and "point-in-time" wording overstates (index.html:9; BacktestView.tsx:35; OverviewView.tsx:77; MethodView.tsx:4).
- og:description: "Validated on 30,414 point-in-time forecasts". The paper's result is largely negative (cash forecasts lose to a random walk, skill -26%; twin least accurate in levels). "Validated" is a walked-back claim. The number is also wrong: calibration.json n_forecasts = 30,690.
- BacktestView:35 "Every test below is out of sample and point-in-time ... nothing was tuned on the outcomes". Filings are point-in-time, but the Feb-2020 scatter, time machine and calibration.json use the static Jan-2026 Damodaran spread table (web/src/engine/ratings.ts; export.py:299). Point-in-time spreads exist only in research runs (experiments.py:70, spreads_asof, commit bd3f38d). README itself says the 5% fixed-cost prior was chosen after a sensitivity analysis, which conflicts with "nothing was tuned".
- Fix: meta text such as "A stock-and-flow model of company cash and debt, stress-tested in your browser. Research finds it no more accurate than simple rules." Add to the Evidence lede that dashboard backtests use the Jan-2026 rating table.

H3. Dashboard numbers drift from the paper and are not labelled by calibration (BacktestView.tsx:50-60,130-146; OverviewView.tsx:51-62).
- The product moved to a 5% fixed-cost prior on 2026-10-23 (calibrate.py:39, commit 874d465); research_summary.json (Findings 1-2) uses the pre-specified 35%.
- pages.yml deploys the newest weekly data artifact, so calibration.json, backtest.json and the cross-section silently change from the paper's numbers (numbers.tex RevSkill 28%, CashSkill -26%). README says revenue CRPS 26%, the site says +28%; different samples, unlabelled.
- Fix: stamp blocks "Dashboard sample, product calibration (5% prior), built <date>" vs "Research sample, pre-specified 35% prior", or freeze evidence JSON per paper version.

H4. No model-limit disclaimer by the headline risk numbers (TwinView.tsx:59-75,124-140; StressLab.tsx:185-193; CompareView.tsx:83,142; App.tsx:155; format.ts:345-351).
- Named real companies get "Distressed / Strained / Watch" labels, "Runs out of cash 14%" and "chance of junk". The paper says simulation adds nothing to ranking firms (AUC 0.86 vs 0.87) and probabilities are not calibrated against events. Only a small footer says "Research project, not investment advice".
- Fix: one line under these metrics: "Model-implied probability under stated assumptions, not a forecast or credit opinion; research finds it ranks no better than its own formula." Rename status labels (for example "model stress: low/high") rather than "Distressed".

## MEDIUM

M1. Overview contradicts itself (OverviewView.tsx:79-87). Line 79 "the companies line up with what actually happened"; lines 84-86 say no balance-sheet model saw who the shock would hit and trailing FCF margin ranks better; line 86-87 "Where the twin adds value ... every year from 2014 to 2023" (paper: worth little out of sample, FCF edge not significant after Holm; sample is 2014-2024). Lead with the negative result; replace "adds value" with "carries statistical information that does not improve forecasts".

M2. Overview tiles (OverviewView.tsx:51-62): revenue tile hardcodes `+${v.toFixed(0)}` (line 57), so a negative value shows "+-5"; the favourable revenue figure is shown but the cash result (-25%, wins 44%) appears only on Evidence. Use a sign-aware formatter and show cash beside revenue.

M3. Encompassing t shown is not the headline (research_assets.py:858; BacktestView.tsx:105). Site shows 9.9 (firm-clustered only, TrEncLevTwinT); abstract and README use 9.2 (firm x year). Export TrEncTwinTTwoWay and say "two-way clustered". Also show ρ CI [0.19, 0.24] and AUC-difference p-values (0.164 etc.); "0.86 vs 0.87" has no uncertainty on the page.

M4. "Finding 4" appears twice (BacktestView.tsx:177, :215). Findings 1-2 are the research sample and 3-4 the dashboard sample without separation; renumber and label.

M5. Stale text: "Leverage thresholds are not sector-adjusted" (OverviewView.tsx:146; CompareView.tsx:142), but the model has sector_tol (sd_model.py:270, model.ts, shown in VersusView:108).

M6. Ask parser semantics (ask/parse.ts:23,104-108; AskTwin.tsx:5).
- "wages up 5% for two years" (an example chip) becomes cost_pp = 5, i.e. +5 percentage points of revenue; % change and pp of revenue are conflated and the shock is overstated several-fold. Same for inflation.
- The pandemic regex matches any "2020" ("worse than 2020") and silently applies a 70% revenue drop.
- findCompany (127-136): first-word match (>= 4 chars) can hit common words (match, target, block, ross); uppercase tokens like ALL or IT can match tickers; applyAsk then navigates away from the current company.
- Fix: convert cost % to pp through the cost share or ask; require a crisis word with "2020"; confirm before switching company.

M7. Shared-link scenarios are not clamped (StressLab.tsx:47-58). decode() takes any finite URL value (sales_depth:5, rate_bp:1e9) with no RANGES clamp (the Ask path clamps). `name in KNOB_DEFAULTS` / `name in levers` are true for prototype keys ("constructor", "toString"), polluting knobs and breaking isBase. Use Object.hasOwn and clamp via RANGES.

M8. Parity testing (model.test.ts; ci.yml web job).
- model.ts matches sd_model.py line by line on the product path; research-only switches (loop_r1/r2, spread_scale, spreads, access_*) are intentionally absent.
- CI's web job tests the COMMITTED goldens, last regenerated 2026-10-16, while sd_model.py changed on 10-22/10-23. Regeneration plus a fresh parity check happens only in the weekly data.yml, so a PR changing sd_model.py passes both CI jobs without a real comparison.
- 6 cases, about 64 paths, 12 of 27 outputs compared (ebitda, fcf, rating, nd_ebitda, h_* are not). MethodView:58 says "eleven" (it is 12) and "CI runs that check on every commit" overstates.
- The browser RNG is not numpy by design (shocks.ts); only a mean/variance test covers it.
- Fix: engine CI job regenerates goldens then runs vitest; compare all OUTPUT_KEYS; correct the text.

M9. Time machine and Evidence say "only the filings that existed then" (MethodView:4, TimeMachine lede) but the rating table is Jan 2026 (see H2). Say so.

M10. Production fallback to a nonexistent API (data.ts:283). On GitHub Pages an unknown ticker fetches /api/company/..., gets 404 and shows "Start the live API", meaningless there. Gate on import.meta.env.DEV. The hash ticker is also interpolated unencoded into data/companies/${ticker}.json (data.ts:280); same-origin JSON only, low risk, but encode it.

M11. Failed builds are invisible: build_report.json lists FDXF, VYLR, APA as failed; nothing on the site says which companies were excluded or why.

## LOW

L1. Keyboard: clickable rows (`<tr onClick>`: OverviewView:106, CompareView:119, TwinView:130), sortable `<th onClick>` (CompareView:106,110), Scatter/StripPlot dots (pointer events only) are not focusable. Add buttons, aria-sort, tabIndex/onKeyDown.

L2. Charts have generic aria-labels ("Distribution", "Fan chart of simulated outcomes"; Bars.tsx:54, FanChart.tsx:112) and no text alternative of values. Range inputs expose raw 0.4 rather than 40% (StressLab:145); add aria-valuetext.

L3. Contrast: --warning #c98a00 on #fbfaf6 is about 2.9:1 (Watch status, timeline mini bars, TimeMachineView:90 colour-only). Several 11-12px labels.

L4. Performance: index.json 256 KB on every page; calibration 132 KB and backtest 94 KB on Evidence; per company 31 KB + memo 8 KB + timeline 28 KB; fine after gzip. The repo carries about 25 MB of JSON (companies 12, timeline 9.5, memos 3.2), churned weekly, which inflates git history. Google Fonts is a third-party request. WebLLM about 1 GB is opt-in and disclosed.

L5. Mobile: breakpoints at 680/860/980; Machine SVG has minWidth 640 so it scrolls sideways on phones. Not tested in a browser.

L6. Hardcoded "p < 10^-6" (BacktestView:57; real p is 9e-14, use xs.p_value); hardcoded "5,000 paths / 12 quarters / 3 years" strings (CompareView:67, TwinView:61) rather than meta.

L7. quarterLabel (format.ts:330) uses calendar quarters for non-calendar fiscal years.

L8. "Junk at horizon" foot (StressLab:191) swaps between two unrelated explanations.

L9. pages.yml uses `|| true` when fetching the data artifact, so a failed download deploys the older committed snapshot (mixed dates: index 10-23, companies 10-16) with no visible signal; the footer shows only index.meta.generated.

## Ask feature: summary
- Deterministic regex parser (works everywhere) plus an optional on-device WebLLM (Qwen2.5-1.5B, WebGPU, about 1 GB, lazy-loaded). Model output is schema-constrained JSON, then clampScenario to slider ranges; only known keys, finite numbers and booleans pass.
- No API key and no server call; inference is local. Weights/wasm come from third-party hosts (Hugging Face, GitHub) on opt-in; name them in the UI.
- Prompt injection: only the visitor's own text reaches the model, output cannot reach HTML (no dangerouslySetInnerHTML anywhere), worst case is an odd but clamped scenario. No security concern. Input truncated to 600 chars.
- "Understood: ..." readback and "language only chooses the scenario" are good. Interpretation bugs are in M6.
- Analyst notes claim "rule-based, no language model" (TwinView:92). Verified true for all 392 shipped memos (generated_by deterministic, 0 unverified numbers) but the text is hardcoded; bind it to memo.generated_by.

## Checked and fine
- pp, %, bp units in StressLab deltas and reverse-stress formatting are consistent.
- Evidence-page research numbers (medians 6.9 / 11.3, ρ 0.32 / 0.39 / 0.22, blends 3.6% / 2.9%, AUCs 0.86 / 0.87 / 0.86 / 0.81, 420 petitions, universe 5,220) match paper and README.
- Finding titles and the "Limits" sections follow the paper's negative framing.
- No secrets in client code; theme, reduced-motion handling and CSP-free static hosting are fine.
