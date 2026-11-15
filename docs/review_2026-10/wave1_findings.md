# Review round Oct 2026, wave 1: consolidated findings

Sources: researcher replies (`../RESEARCHER_REPLIES_2026-10.md`) and five internal reviewers (econometrics, credit risk, data/EDGAR, reproducibility, handling editor), 28 Oct 2026.

Key:
- `[V]` means verified in the code by the main session.
- IDs are referenced by `IMPROVEMENT_PLAN.md`.

## D: data layer (`engine/fintwin/data`, census)

- **D1** [V] The spine is built only from quarters that have revenue (`facts.py:265`), so missing quarters are dropped rather than kept as NaN. As a result:
  - `_ttm` (`experiments.py:93`) can sum 5 or more calendar quarters.
  - `usable` (16 rows) can span 5 years.
  - `.head(8)` outcomes (`experiments.py:496`) can cover 10 or more quarters.
  - `.rolling(4)` has the same problem.
  - Scale: 643 gaps in 474 firms (`data_audit.json`).
  - Fix: reindex to a full quarterly calendar (keep 52/53-week alignment) and require date contiguity.
- **D2** [V] Flows and balances are zero-filled per quarter (`facts.py:301-310`): receivables, inventory, deferred revenue, short investments, dividends, buybacks, SBC. A single-quarter gap becomes a fake swing. Fix:
  - carry balances forward within a limit;
  - add missing indicators;
  - zero-fill only fields that are never tagged at all, and record a note when that happens.
- **D3** [V] `_total_debt` ends with `.fillna(0.0)` (`facts.py:248`), so an untagged debt becomes 0. Fix:
  - return NaN when no debt tag exists;
  - add tags (SeniorNotes, ConvertibleNotesPayable, NotesPayable, finance lease liabilities);
  - sanity-check against liabilities.
  - Also: `ltd_noncurrent` is forward-filled but `debt_current` is not.
- **D4** [V] The outcome FCF is computed as `(cfo - capex).fillna(0).cumsum()` (`experiments.py:500`), so a missing quarter counts as zero burn. Fix: require finite values.
- **D5** `_latest` (`facts.py:178`) uses an unstable sort, so same-day ties (10-K vs 10-K/A) are broken arbitrarily. `groupby().last()` can also mix columns across rows. Fix: mergesort with accn as a secondary key, then take the last row (not `.last()`).
- **D6** (a data reviewer) Q4 de-cumulation mixes vintages (`facts.py:186-201`): the FY leg and the 9-month YTD leg come from different filings. Fix: require the same filing or an adjacent filing, otherwise flag or drop the quarter.
- **D7** (a data reviewer) Tag fallbacks are merged by priority without an overlap check (`facts.py:213-218`), which can create level breaks at a tag switch. Fix: check the ratio over overlap periods; on a break, splice by ratio or flag the quarter.
- **D8** Bankruptcy case grouping (`stats.py:187`, gap_days=1095) has two problems:
  - Later confirmation or emergence 8-Ks create phantom second cases.
  - Firms still in Chapter 11 after 2 years re-enter the sample as survivors (`bk_event`, `stats.py:199`).
  - Fix: take the first 1.03 filing per case, and exclude firm-years that fall inside a bankruptcy.
- **D9** Fiscal-year-end changes: the 60-day spine dedup keeps the stub period, and 10-KT stubs of 75 days or less are lost. Add a test.
- **D10** The reporting lag is a fixed 90 days (`calibration.py:13`, while the docstring says 75; `batch.py:298`). Fix: use each target's actual `filed` date.
- **D11** Fallback XBRL instance selection (`xbrl_fallback.py:64-73`) may pick a non-instance `.xml`; it does no `decimals` check, and filings partially present in companyfacts are never completed. (Uncertain.)
- **D12** The financial filter uses the current SIC, so bankrupt shells recoded to 6770 are dropped. The 6800-6999 range is also inconsistent with the ff12 classification.
- **D13** Signs of capex, dividends, buybacks and interest are never validated. Fix: count negative values and normalise them.
- **D14** (a data reviewer) The universe is us-gaap USD frames only. All text must say "US-GAAP filers reporting in USD with at least $50M of revenue". Affected places:
  - `fintwin.tex:45,49,263`
  - `distress.py:5`
  - `research/__main__.py:7`
  - `BacktestView.tsx:40`
  - README, site, emails
- **D15** Tests are missing for: `_align` tolerance, `_total_debt`, zero-fill, gaps, `petitions`/`bk_event`, fiscal-year-end changes, same-day amendments, D6 and D7.

## E: econometrics and inference (`research/stats.py`, `transmission.py`, `plan2.py`, `calibration.py`, `experiments.py`)

- **E1** [V] The twin's point forecast is the sum of per-quarter cross-path medians (`experiments.py:363-366`, `transmission.py:84`). Fix: store path-level 8-quarter totals and use their median.
- **E2** The Monte Carlo density is never evaluated for cumulative OCF/FCF. Fix: CRPS and PIT for the twin vs. Gaussian and empirical-residual densities around N3. This is central to the a referee reframing; see E12.
- **E3** The 3.6% combination gain is bootstrapped over firms only, with λ fixed across resamples and about 8 test years. Fix:
  - DM test with firm×year clustering, or a year-block bootstrap;
  - year-by-year gains, with a count of signs;
  - re-estimate λ inside each resample.
- **E4** [V] Bootstrap p-values come from resample counts with B=500 (`stats.py:103`), so "<0.001" is an exact zero. Holm's verdicts therefore rest on 0–1 crossings, and the family of tests is ad hoc. Fix:
  - studentized p-values, or B of at least 10k;
  - a family of tests defined ex ante;
  - Romano–Wolf (see E5).
- **E5** (an econometrician) Add MCS (Hansen, Lunde and Nason 2011) over all forecasters, plus SPA (Hansen 2005) and Romano–Wolf stepM against the 16-quarter margin.
- **E6** [V] Winsorization bounds use the full sample, including test years (`transmission.py:295`, `plan2.py:454`). Fix: compute them on training years only, and also report unwinsorized results.
- **E7** Loss mismatch: encompassing and HLN are MSE-based, while λ is chosen on MAE. Fix: add MAE- or LAD-based encompassing, or an absolute-loss DM test.
- **E8** Liquidity-event probabilities are evaluated by AUC only. Fix: Brier and log scores, Murphy decomposition, reliability curves.
- **E9** Two-way clustering with 11–13 clusters uses normal critical values (`transmission.py:252`, `stats.py:649`). Fix: t(G−1) critical values or a wild cluster bootstrap, and a PSD check.
- **E10** Revenue-forecast benchmark (`batch.py:143-150`):
  - The random-walk standard deviation is constant for h=1–4 and estimated from 20 changes.
  - The DM test is pooled over horizons.
  - Fix: DM by horizon, and an empirical-quantile random-walk density.
- **E11** The cash "hybrid" density shifts the location only, and λ is chosen on MAE but scored on CRPS (`plan2.py:179-224`). Fix: a linear pool or quantile averaging, with λ chosen on CRPS.
- **E12** (a referee) Make liquidity-shortfall vulnerability the second main test: P(cash + undrawn < 0 within N quarters under a named shock) vs. realised stress periods (2015–16, 2020, 2022). Evaluate with E2 and E8 scores. Demote the bankruptcy AUC to a secondary check.
- **E13** Calibration:
  - Only the PIT mean is reported. Fix: PIT histograms, interval score, conditional coverage test.
  - The conformal interval is symmetric about the median, so it cannot fix skew.
- **E14** Text vs. code mismatches:
  - The hybrid table note says "Test years 2015–2024" (`fintwin.tex:180`), which conflicts with the Y−3 rule.
  - The paper says 11 cutoffs; the code has 12 (`PANEL_ORIGINS` from 2013).
  - The Holm wording (around line 171) contradicts the table, and so does the Discussion.
  - 75 vs 90 days.
  - 0.30 vs 0.32 between the abstract and lines 43/155.

## M: model mechanics (credit practitioner; deepened by wave 2 `model_mechanics.md`)

- **M1** No covenants. The revolver is always fully available (`sd_model.py:205-212`) and the only breach is `cash < 0` (L254). Fix:
  - maintenance covenant on net debt/EBITDA or ICR;
  - revolver frozen or cut on breach, and revolver maturity;
  - "first covenant breach quarter" as an output.
- **M2** Floating-rate share is 0.1 for every firm (`calibrate.py:343`). Fix: XBRL floating-rate and derivative tags, otherwise sector defaults.
- **M3** Refinancing:
  - `refi_ratio` comes from the 8-quarter debt trend (`calibrate.py:220`).
  - Access has only 3 ICR steps.
  - A failed refinancing never defaults.
  - The ladder falls back to debt0/24 (`calibrate.py:258-272`). Fix: flag "ladder unknown"; assume bullet maturities.
- **M4** Scenarios are hand-set and uniform across industries (`presets.py`). Fix:
  - sector shock multipliers, using the 2020 industry shocks;
  - named, sourced supervisory-aligned presets;
  - a reverse-stress headline.
- **M5** Working capital, capex and dividends:
  - Payables track costs instantly.
  - `maint_capex` = 0.8·D&A for every firm.
  - The dividend cut ignores the REIT 90% payout rule and utilities.
  - Equity issuance is off.
- **M6** Tax has no NOLs and no 163(j) limit; the revolver margin is fixed at +1.5%.
- **M7** Outputs are not decision-relevant. Add:
  - runway in quarters;
  - funding gap distribution (p95);
  - maturity wall;
  - P(liquidity < X within N).
  - The 0–100 health score uses arbitrary weights.
- **M8** Sector scope: REITs, utilities, biotech, leases, pensions, captive finance. Fix: define in-scope sectors, add leases and pensions to leverage, report results by sector group.
- **M9** Outcome breadth: build a credit-event label from 8-K Item 2.04 (acceleration), Item 3.01 (delisting), going-concern opinions and distressed exchanges. Report results per event type; 1.03 is a subset.

## P: paper and positioning (handling editor)

- **P1** There is no target journal, and at about 11.5k words with about 20 tables the paper reads like a lab notebook. Decision: see the plan.
- **P2** Frame the paper honestly as a benchmark or negative-result paper. Drop "digital twin" from the headline: the framework admits it is a "digital shadow".
- **P3** The 16-quarter base is post hoc. The abstract must say that only H2 was pre-registered, and report the pre-registered base result first.
- **P4** The recommendation at line 393 holds only conditional on a known revenue path. Restrict it.
- **P5** Missing literature:
  - Stein et al. 2001 (CFaR), the closest precedent;
  - Hillegeist et al. 2004;
  - Acharya–Engle–Pierret 2014;
  - MCS, SPA and Romano–Wolf;
  - Gneiting–Raftery.
- **P6** Put the effect size next to every t-statistic; drop "carries information" phrasing.
- **P7** Novelty and dataset claims are overstated (the panel is not tested for completeness).
- **P8** Sobol with 64 base samples is "noisy": rerun it larger or drop it.
- **P9** Format:
  - dense `\scriptsize` 8–9 column tables;
  - AI disclosure placement;
  - document the Internet Archive spreads (line 378).
- **P10** The author email at `fintwin.tex:25` reads `spiliosdimakk@gmail.com`. The user must confirm it.

## R: reproducibility (data editor)

- **R1** Raw data is not frozen: `engine/.cache` is gitignored and reruns fetch live EDGAR. Fix:
  - archive the facts cache with a hash on Zenodo;
  - state the extraction date;
  - add `REPRODUCE.md` and a `make paper` target.
- **R2** `paper_assets.py` builds `numbers.tex` from `web/public/data/*.json`, which the weekly `data.yml` overwrites; merge e908581 changed them. Fix:
  - freeze `paper_data/` with a manifest;
  - build the paper from a tag;
  - stop merging the weekly refresh into `revision`.
- **R3** `uv sync` runs without `--locked`, and Python and library versions are not stated in the paper.
- **R4** Seeds:
  - Seeds and path counts are scattered (3, 5, 11, 41, 7, 1, 20200220).
  - `stats.py` uses a global RNG, so results depend on call order.
  - Fix: a seeds table, and per-function RNGs.
- **R5** Versions: 2.0.0 in CITATION and Zenodo, but 0.1.0 in `pyproject.toml`, `package.json` and `__init__.py`. Check for a `v2.0.0` tag.
- **R6** README:
  - says "39 tests" (there are about 46);
  - "390+ companies" vs 377 and 331, never explained;
  - documents `paper_assets.py` but not `research_assets.py` or the `python -m fintwin.research` commands.
- **R7** Licence: MIT covers code only. Add a DATA-LICENCE note covering SEC, Damodaran and Philadelphia Fed sources.
- **R8** Coverage excludes `research/__main__.py`, `experiments.py` and `plan2.py`. Stray files: `grep.exe.stackdump`, `klein_list.txt`, LaTeX artifacts in `docs/paper`.
- **R9** Small float differences between runs: the pipeline is not bit-reproducible (OpenBLAS threads?).
