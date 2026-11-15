# Requests from workstream E (website)

## 1. Images to regenerate after the rerun (not touched by E)
- `web/public/findings.png` (WEB-H1): still the stale mean-error figure with "377 petitions". Generate one file from `research.json` in `research_assets.py`: median errors, correct petition count, labelled "median". Copy it to `docs/findings.png` at build so the two copies cannot diverge. The alt text on the site (BacktestView) now gives no numbers and points to the Findings below the figure, so it stays correct whatever the figure shows.
- `web/public/og.png`: check it carries no stale claim ("validated", 390+, 30,414).

## 2. Changes needed in files E does not own
- **`engine/scripts/research_assets.py` (WEB-M3)**: export `TrEncTwinTTwoWay` (firm x year clustered encompassing t, the one the abstract/README use) into `research_summary.json` as `incremental.encompassing_t_twoway`, plus the rho CI and the AUC-difference p-values (e.g. `bankruptcy.auc_diff_p`). The site currently shows the firm-clustered `encompassing_t` and says so in the footnote; once the new keys exist, switch BacktestView `ResearchFindings` to them and drop the parenthesis.
- **`engine/scripts/research_assets.py` / `export.py` (WEB-H3)**: add a `spec` block to `research_summary.json` and `calibration.json` (`{"name": "...", "fixed_cost_prior": ..., "built": "YYYY-MM-DD"}`) so the stamps (`SpecStamp`) can print the specification from data rather than from text. Today the stamp only prints the build date from `index.meta.generated`.
- **`.github/workflows/ci.yml` (WEB-M8)**: the web job should regenerate the goldens from `sd_model.py` before `vitest`, and the parity test should compare every key in `OUTPUT_KEYS`. E changed only the text in MethodView ("on the output series that the parity test compares", no "every commit").
- **`.github/workflows/pages.yml` (WEB-L9)**: `|| true` on the data artifact download deploys a mixed snapshot silently; fail or stamp the footer instead.
- **`web/public/data/memos/*.json`**: E renamed the UI label "Watch in the next filings" to "To check in the next filings"; memo text itself (written by the engine) may still use "Distressed/Strained" in `verdict` and prose. The data owner should rename the verdict vocabulary to model-stress wording.
- **`engine/**` TypeScript port**: `ratings.ts` uses the Jan-2026 table; if the port gets point-in-time spreads, drop the caveat sentences added in OverviewView, BacktestView lede, TimeMachineView lede and MethodView.
- Not done in E (needs data): WEB-L4 (repo size of `web/public/data`), L5 (mobile test of MachineView, needs a browser), L7 (`quarterLabel` for non-calendar fiscal years needs the fiscal-year-end in the JSON), L8 (the "Junk at horizon" foot now reads "chance of a sub-investment-grade synthetic rating after 3 years" or the breach timing; the two unrelated explanations are still alternates on the same metric).

## 3. Hard-coded numbers and claims in the site (for the integrator after the rerun)
The site reads results from `research_summary.json`, `calibration.json`, `backtest.json`, `index.json`. These are still typed into the text:

| File | Text / number | Depends on |
|---|---|---|
| `OverviewView.tsx` | "revenue down 70% for three quarters, debt markets shut for two" (Feb 2020 shock); "worse than 10% of a year's revenue" (severe burn threshold); "Fifteen years" of filings; "5,000 paths, 12 quarters ahead"; Carnival "fell 99%"; "Six twins"; featured-company blurbs | preset definitions, horizon, universe |
| `BacktestView.tsx` | "2014–2024" (Finding 1); "2,000 paths" and "next {horizon} quarters" (Finding 3); "10% of revenue" burn threshold; "Carnival's revenue fell about 99%"; "Finding 1-4" numbering and which findings come from which sample; `labelIds` lists | research sample span, calibration run |
| `MethodView.tsx` | health score weights 30/30/20/20; "Nine stocks", "four feedback loops"; access factors 1 / 0.6 / 0.3 at 1.5x / 0.8x; "5,000 paths"; "Q4 = full year minus nine months"; Jan-2026 Damodaran table | model spec, T2 changes to the health score |
| `TwinView.tsx` | "Median of 5,000 simulated futures", "within 3 years", "Coverage under 1.5x"; "unluckiest 10%" | simulation settings |
| `CompareView.tsx` | "5,000 paths over 12 quarters", "eight crises" | preset count, simulation settings |
| `StressLab.tsx` | "Global sensitivity is computed for the 30 core companies"; "NBER base rates since 1947"; path-count options | export settings |
| `ask/parse.ts` | `COST_SHARE_OF_REVENUE = 0.6` (converts a % cost increase to pp of revenue; replace by the firm's actual variable-cost share when the ask feature gets company data); named-crisis presets (2020, 2008, stagflation, recession) | model scaling |
| `HeroSim.tsx` | preset scenario list | presets |
| `format.ts` | `healthStatus` cut-offs 70 / 50 / 30 and labels (now "Low/Moderate/Elevated/High stress"); same cut-offs repeated in `ui.tsx` zone ticks and `TimeMachineView.tsx` mini bars and aria labels | health score definition |
| `index.html` | no numbers any more (390+ and 30,414 removed from description/og:description) | |
| `public/data/*.json` | `n_forecasts`, `n_companies`, `cross_section.p_value` etc. are data-driven; nothing to edit by hand |  |

## 4. Interface notes
- New module `web/src/scenarioUrl.ts` (`decode`, `encode`, moved from StressLab). `decode` now clamps to `RANGES` and accepts only own keys.
- `parseScenario(text, names, costShare = 0.6)`: third argument is optional.
- `Columns` gets an optional `ariaLabel`; `StripPlot` and `Scatter` svgs are now `role="group"` and keyboard-operable (arrow keys, Enter).
- New UI components in `ui.tsx`: `ModelNote`, `SpecStamp`, `rowActions`. New helpers in `format.ts`: `signed`, `MODEL_LIMIT_NOTE`, `UNIVERSE_TEXT`. New loader `loadBuildReport` in `data.ts`.
- Status labels changed: Healthy/Watch/Strained/Distressed -> Low/Moderate/Elevated/High stress.

## 5. Findings not fixed
- WEB-M2 second half is done (cash skill shown in the revenue tile foot); a separate cash tile was not added to keep the tile row at four.
- No browser check was possible (no dev server per brief); keyboard behaviour and contrast of the darker `--warning` were reviewed by reading the code only.
