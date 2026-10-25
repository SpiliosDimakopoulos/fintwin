# FinTwin: a financial-health digital twin for public companies

[![ci](https://github.com/SpiliosDimakopoulos/fintwin/actions/workflows/ci.yml/badge.svg)](https://github.com/SpiliosDimakopoulos/fintwin/actions/workflows/ci.yml)
[![data](https://github.com/SpiliosDimakopoulos/fintwin/actions/workflows/data.yml/badge.svg)](https://github.com/SpiliosDimakopoulos/fintwin/actions/workflows/data.yml)
![coverage](https://img.shields.io/badge/coverage-88%25-brightgreen)
![ruff](https://img.shields.io/badge/lint-ruff-261230)
![mypy](https://img.shields.io/badge/types-mypy-2a6db2)
![lighthouse](https://img.shields.io/badge/lighthouse-94%20%C2%B7%20100%20%C2%B7%20100%20%C2%B7%20100-brightgreen)
![licence](https://img.shields.io/badge/licence-MIT-lightgrey)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23434606.svg)](https://doi.org/10.5281/zenodo.23434606)
[![good first issues](https://img.shields.io/github/issues/SpiliosDimakopoulos/fintwin/good%20first%20issue?label=good%20first%20issues&color=7057ff)](https://github.com/SpiliosDimakopoulos/fintwin/labels/good%20first%20issue)
[![discussions](https://img.shields.io/github/discussions/SpiliosDimakopoulos/fintwin)](https://github.com/SpiliosDimakopoulos/fintwin/discussions)

**[Live dashboard](https://spiliosdimakopoulos.github.io/fintwin/)** · **[Paper (PDF)](docs/paper/fintwin.pdf)** · [Methodology](docs/METHODOLOGY.md) · [Backtest report](docs/BACKTEST.md) · [Carnival case study](docs/CASE_STUDY_CCL.md)

**FinTwin turns a company's SEC filings into a living model of its finances, then stress-tests it thousands of times.** It doesn't predict a stock price. It simulates how cash, debt, margins and credit quality respond to a pandemic, a rate shock or a closed bond market, and it reports a *distribution* of outcomes rather than a single number.

![Stress lab demo](docs/demo.gif)

> **30-second pitch.** A flight simulator for corporate finance. It reads 15 years of a company's official filings and learns how its finances behave: fixed vs variable costs, how fast customers pay, when its debt matures. Then it replays the future 5,000 times under any crisis you pick, live in the browser. Then I tested it the hard way, on every US non-financial SEC filer with $50M+ revenue, including the ones that went bust, against simple rules that see the same data. Most of what it seemed to know was persistence: a 16-quarter cash-flow margin predicts cash better than the twin, and the twin's score predicts bankruptcy no better than its own formula without simulation. It also over-reacted to revenue because it assumed too much fixed cost; a prior selected walk-forward fixes much of that. What survives is small and specific: given the revenue that happened, the direction of the twin's departures from that margin is informative, and for free cash flow, blending in about 15% of them lowers the error out of sample by more than any simple rule does. It covers 390+ companies on the dashboard and rebuilds itself from the latest filings every week.

## Results

![The paper in one picture: given realized revenue, the twin alone is less accurate than a 16-quarter margin but improves it when combined; in ranking bankruptcies it equals its own formula without simulation](docs/findings.png)

All numbers come from out-of-sample, point-in-time tests on a survivorship-free universe: **5,220 non-financial SEC filers** (every company with $50M+ revenue in some year 2012-2024, including those later acquired, delisted or bankrupt), 21,545 firm-years 2014-2024, and a census of bankruptcy petitions (8-K Item 1.03, first filing of each case: **420 firm-years at 238 companies** followed by one within two years). The decision rule for the main test was committed before it was run; the rules for the other hypotheses were written after the first results and are treated as descriptive ([plan 1](docs/REVISION_PLAN.md), [plan 2](docs/REVISION_PLAN_2.md)).

| Test | Result |
|---|---|
| **Transmission** (main test): realized revenue given to the twin and to six simple rules, 16,973 firm-years | Alone, the twin is less accurate than every simple rule (median error 11.3 pp of revenue vs **6.9** for a 16-quarter margin). The old headline statistic (0.32 against a 4-quarter margin) is exceeded by the 16-quarter margin alone (**0.39**): it measured mean reversion. The twin's departures still carry information no rule has (encompassing *t* = 9.2 with firm × year clustering; ρ 0.22 [0.19, 0.24] against the 16-quarter margin's residual). Out of sample it is worth little: margin + 10-15% of the twin cuts error by 3.6%, but a simple regression combined the same way gets 2.9%; for **free cash flow** the twin's edge over the best such combination (0.22 pp) does not survive a Holm correction. |
| **Why it misses, and a fix** | The twin's cash flow reacts to revenue **2.3×** as much as firms' does (EBITDA 2.1×, capex 1.0×): too much assumed operating leverage. A fixed-cost prior selected walk-forward (5% instead of 35%) cuts its median error from 12.0 to 9.7 on the 2018-2024 test years with no loss in bankruptcy ranking; it is now the default. The prior was chosen at the edge of the grid, after a sensitivity analysis had pointed that way. |
| **Bankruptcy**: petition within 8 quarters | AUC **0.86** for the twin, **0.87** for its scoring formula without simulation, 0.86 Ohlson, 0.81 Altman Z″ (within 4 quarters: 0.88, 0.89, 0.88, 0.85). Among already-weak firms (82% of petitions): 0.77 vs 0.77. Simulation adds nothing to ranking. |
| **Downturns** (2015-16, 2020, 2022) | Under a uniform scenario nothing ranks the burn a shock causes. Given each industry's realized shock, the twin's fragility is associated with it in all three downturns (*t* = 4.3, 6.8, 5.7, industry-clustered, controlling for the FCF margin and the no-simulation formula). The shock is realized, so this is a decomposition, not a forecast. |
| **Liquidity decisions and loops** | Given realized revenue, event probabilities add +0.01 to +0.04 AUC to a static runway rule + scores. Two of the four loops are necessary for the model to produce cash depletion and payout cuts at all, so their "gain" over a loop-free twin is mechanical; the other two are close to inert. |
| **Forecasts and calibration** | Revenue CRPS 26% better than a seasonal random walk, 19% better than ETS. For cash the best forecast is the random walk. Conformal intervals with group scaling reach 90% coverage in every group for cash; for revenue they fail only in the 2020 stress quarters (77%). |
| **Data** | 52/53-week fiscal calendars are read correctly; filings missing from the SEC's companyfacts API are read from their own XBRL; rating spreads and GDP are point-in-time. |

Where it fails, in the paper's own words ([docs/paper/fintwin.pdf](docs/paper/fintwin.pdf)):
- It is not an early-warning system: its ranking of firms is that of its own scoring formula, and fragility rankings mostly measure persistent cash-flow habits.
- Even corrected, it is less accurate in levels than a long-window cash-flow margin; its value is in the direction of its departures from that margin.
- Its cash forecasts do not beat a random walk, and its revenue intervals are not calibrated in a regime break.
- Two of its four feedback loops have no measurable effect.
- Its transmission test conditions on eight reported quarters, which only 21% of the firm-years followed by a bankruptcy achieve.

## What it does

| | |
|---|---|
| **Point-in-time SEC data** | XBRL `companyfacts` with tag fallbacks, year-to-date de-cumulation, impairment-adjusted EBIT, and *filed-date* vintages that make backtests free of look-ahead bias. Every number links to its source filing. |
| **System-dynamics model** | 9 balance-sheet stocks, quarterly flows, first-order delays and 4 feedback loops: a leverage–spread spiral, a market-access cliff, cash conservation and delayed restructuring. |
| **Calibrated Monte Carlo** | Robust (MAD) volatilities, Student-t tails, demand–margin correlation, a Vasicek short rate, and a Markov recession regime with NBER base rates and company-specific GDP sensitivity. |
| **Stress tools** | 8 crisis presets, free sliders and 6 CFO levers. Reverse stress testing answers "how big a shock breaks it?". Tornado charts and Sobol global sensitivity (with bootstrap CIs) show what matters. |
| **Analyst notes** | A rule-based analyst turns each company's simulation into a credit-memo-style note: verdict, evidenced risks, buffers, scenario commentary, watch list. It is deterministic, so every figure is correct by construction. An optional LLM module writes freer prose from the same fact sheet and machine-checks its figures, if you supply your own key. |
| **Sector-adjusted health** | Leverage that would alarm a software company is normal for a utility. Coverage and leverage are scored against each GICS sector's own norms, which are estimated from the data, and a waterfall shows how each component moves the score. |
| **Time machine** | Rewind any company to what its twin said at every February since 2013, using only the filings that existed then, and see what actually happened next (`#time/CCL`). |
| **Compare** | Put two companies side by side (`#versus/CCL/RCL`), or scan the whole universe × 8 crises, filtered by sector. |
| **Dashboard** | Editorial research-terminal design, light and dark. The landing page runs a live Monte Carlo you can steer. There is a Ctrl K / ⌘K company switcher, a stress lab whose scenarios are shareable as links, peer context on every company, and keyboard shortcuts (press `?`). Everything runs client-side in a Web Worker, so no server is needed. |
| **Ask the twin** | Describe a crisis in plain English ("revenue falls 40% for a year and banks stop lending", "another 2008 for Carnival") and the stress lab sets it up and simulates it. Built-in rules work everywhere; an optional on-device language model (Qwen2.5 1.5B via WebLLM, no API key, nothing leaves the browser) handles free-form text. Language only chooses the scenario: model output is validated and clamped, and every number comes from the simulation. |
| **What changed this week** | Each Monday's rebuild is compared with the previous one: which companies' health moved by 5+ points, after which filing, and which part of the score (runway, coverage, leverage, solvency) drove it. Also as an RSS feed. |
| **Always current, at zero cost** | Every Monday a GitHub Actions workflow pulls the newest SEC filings and FRED data, rebuilds all twins across 16 parallel runners, re-runs the validation and the time machine, checks Python–TypeScript parity, and redeploys. |

| | |
|---|---|
| ![Overview](docs/screenshots/overview-light-1400.png) | ![Company twin](docs/screenshots/twin-light-1400.png) |
| ![Stress matrix, dark theme](docs/screenshots/compare-dark-1400.png) | ![Evidence](docs/screenshots/backtest-light-1400.png) |

## Run it

```bash
cp .env.example .env                       # SEC_USER_AGENT (required by SEC)
cd engine && uv sync && uv run pytest -q   # tests: balance-sheet identity (Hypothesis), offline XBRL end-to-end, 52/53-week calendars, point-in-time, the transmission nulls, CRPS...
bash scripts/full_pipeline.sh              # validation (~30k forecasts) + all snapshots + backtests (hours; CI shards it)
cd ../web && npm ci && npm test && npm run dev    # includes Python <-> TypeScript parity
```

Optional extras:
- `uv run python -m fintwin.notes` regenerates the analyst notes. The optional LLM memos need your own API key: `uv run --extra ai python -m fintwin.memo CCL`.
- `uv run --extra api python -m fintwin.api` lets you twin any ticker live.
- `uv run python scripts/paper_assets.py` regenerates the paper's figures and numbers.

## Repository map

```
engine/fintwin/   data/ (EDGAR, facts, FRED) · model/ (stock-and-flow core, ratings) · stochastic/ (calibrate, shocks, MC)
                  scenarios/ (presets, reverse stress) · sensitivity/ (tornado, Sobol) · backtest/ (walk-forward, batch, scoring)
                  universe.py (S&P 500, sector norms) · pipeline.py (sharded weekly build) · export.py · notes.py · memo.py · api.py
web/src/          engine/ (TS port + parity tests) · views/ · charts/
docs/             paper/ (LaTeX + figures, numbers generated from data) · METHODOLOGY · BACKTEST · CASE_STUDY_CCL · CV_KIT
```

## Contributing

Contributions are welcome, from a typo fix to a new stress scenario or a better test of the method.

- Start with an issue labelled [`good first issue`](https://github.com/SpiliosDimakopoulos/fintwin/labels/good%20first%20issue) or [`help wanted`](https://github.com/SpiliosDimakopoulos/fintwin/labels/help%20wanted).
- See [ROADMAP.md](ROADMAP.md) for the open research questions and [CONTRIBUTING.md](CONTRIBUTING.md) for setup and PR guidelines.
- One-click dev environment: [![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/SpiliosDimakopoulos/fintwin)
- Questions and ideas: [Discussions](https://github.com/SpiliosDimakopoulos/fintwin/discussions).

If you find FinTwin useful, a ⭐ helps others find it. To cite it, use [CITATION.cff](CITATION.cff) or the [Zenodo DOI](https://doi.org/10.5281/zenodo.23434606).

*Data: SEC EDGAR XBRL, FRED. Rating table: A. Damodaran (Jan 2026). MIT licence. Not investment advice.*
