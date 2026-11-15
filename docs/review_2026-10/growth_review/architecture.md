# Architecture review of GROWTH_PLAN.md (28-10-2026)

Reviewer: skeptical software architect. Scope: whether the plan can be built on the code as it stands on `rev3`, and whether it is in the right order. Read-only, except for this file.

Severity scale: **Blocker** (the plan as written will fail or publish something wrong), **High** (large rework or schedule slip), **Medium** (has to be designed in, but is contained), **Low**.

## What I measured

Measured on this PC: one firm, with `FINTWIN_FROZEN=1` and the local cache. No shard or suite was run.

| Step (CCL, asof 2020-02-15) | Time |
|---|---|
| Cold `import fintwin.export` (pandas, scipy, statsmodels) | ~11 s, first run on Windows |
| `load_company` (gzip JSON parse plus XBRL fallback check) | 1.8–2.8 s cold, 0.9–1.6 s warm per extra `asof` |
| `calibrate` | 1.1 s |
| `mc.run`, one preset, 5,000 paths | 0.12 s |
| `reverse_stress` (2 knobs × 2 levels × 18 bisection steps × 2,000 paths) | 2.1 s |
| `tornado` | 0.3 s |
| Full `company_block` (11 presets, reverse stress, tornado) | 5.4 s |
| Payload | 30.9 KB |

Other figures:
- The local cache holds 701 MB of gzipped EDGAR data for 3,890 companyfacts files, about 180 KB per firm.
- One firm has ~5,100–5,600 USD rows over the 97 tags the loader uses, out of ~18–25k rows in total. At 5,300 firms that is about **27 M rows**.
- `web/public/data`:
  - `index.json` is 268 KB for 392 firms, about 0.7 KB per firm;
  - the companies folder averages 30 KB per file, timelines ~24 KB, memos ~8 KB.

---

## 1. Blocking problems

### AR-1 (Blocker): `twin(asof=…)` built as a wrapper over `stochastic.calibrate` is not the paper's point-in-time twin
L2 says to wrap `stochastic/calibrate.calibrate`. But the point-in-time discipline lives in a **second** `calibrate`, at `research/experiments.py:350-363`. That one:
- uses the research prior (`research_prior()`, `experiments.py:116`);
- takes τ/λ from the walk-forward table (`selected_assumptions`, `experiments.py:321-330`, read through `FINTWIN_SELECTION`);
- uses the rating-spread table published at the cutoff (`spreads_asof`, `experiments.py:356`, `model/ratings.py:18-31`);
- uses the real-time NBER state (`realtime_recession`, SW17).

The product path does none of that:
- `stochastic/calibrate.py:974-976` sets `sector_tol` from today's `sector_norms.json`. The research code overrides it with 1.0 because "those are estimated from later data" (`experiments.py:525`).
- `SPREADS` defaults to January 2026 (`sd_model.py:162`).
- `macro` is whatever the caller passes. `api.py:41` and `export.py:336` pass `macro_quarterly()` with no `asof`.
- `spec.py:20` gives `DEFAULT_SPEC = "v2-rev"`. So the library would default to the revision-2 model that the paper is retracting (MM-F1).

The result: `ft.twin("CCL", asof="2020-02-15")` would carry look-ahead, and would not match the numbers in the paper. For a project whose launch message is "here is how much look-ahead naive backtests have", that is fatal.

**Fix.**
- Move the point-in-time calibrate into a non-research module, e.g. `fintwin/twin.py::calibrate_pit`, which both the research code and the public API call.
- When `asof` is set, force `sector_tol=1` (or point-in-time norms), PIT spreads, PIT macro and PIT GDP.
- Make `spec` an explicit parameter whose default is decided in ADR-001.
- Add a test: `ft.twin(t, asof=cutoff).params == research calibrate(t, cutoff)` on the dry-run sample.

### AR-2 (Blocker): Hub mode cannot run the twin from the H1 tables as specified
`load_company` (`data/facts.py:525-641`) works on the raw companyfacts structure `gaap[tag]["units"]["USD"] = [{start,end,val,accn,fy,fp,form,filed,frame}]`. It needs, per **tag** (not per concept):
- the priority-ordered tag merge with a level check at each switch (D7, `_merge_tags`, `facts.py:351`);
- YTD de-cumulation within one vintage (`_duration_table`, `facts.py:296-333`, which needs `start`);
- D&A built from depreciation and amortisation parts (`facts.py:543-547`);
- the `_annual_da` estimate (`facts.py:499`);
- the maturity ladder from `MATURITY_TAGS` (`facts.py:644`).

H1's `facts_vintages` table is keyed by *concept* and carries a `derived` flag. That is the loader's **output** vocabulary, so the loader cannot be fed from it. `quarterly_first` and `quarterly_latest` are not enough either. `calibrate` also needs `CompanyData.imputed`, `maturities`, `maturities_date`, `flags` and `notes` (`facts.py:221-234`), and none of these is a column in H1.

**Fix (minimal schema that runs fully offline).** Store the loader's *input*, not only its output, and run the unchanged loader on it. See §4, H1. A thin `hub.company_facts(cik)` then rebuilds the `gaap` dict from Parquet rows, `xbrl_fallback` is bypassed, and the results are byte-identical to frozen mode. Make that a CI test.

### AR-3 (Blocker): H1's partition by year breaks hub mode and the 60-second first run
The core table is ~27 M rows. With dictionary-encoded tag/accession/form and int32 dates that is roughly 300–400 MB of Parquet. If it is partitioned **by year**, `ft.facts("CCL")` has to download every year partition, i.e. the whole table, before it can build one firm. That breaks L6 (< 60 s) and makes the MCP server unusable.

**Fix.**
- Partition the raw facts by CIK bucket (e.g. `cik % 64`), sorted by `(cik, tag, end, filed)`, with row groups aligned to firms. `pyarrow.dataset` over `hf://` (HfFileSystem) can then read one firm with range requests (a few MB).
- Keep year partitions only for the cross-sectional panel tables.

### AR-4 (Blocker): The silent XBRL fallback in hub or no-UA mode gives different data per user
`xbrl_fallback.augment` (`xbrl_fallback.py:215-238`) catches **every** exception and returns `raw` unchanged. That includes the `RuntimeError` from `_user_agent()` when `SEC_USER_AGENT` is missing (`edgar.py:28-31`). So a user without a UA, or in hub mode with only the companyfacts rows, silently gets a different panel from the CI build. For HCA/KO-type filers whose 10-Qs are missing from companyfacts, that means missing quarters. Nothing warns.

**Fix.**
- In hub mode, the fallback rows must be in the dataset (tagged `source=xbrl_fallback`), and `augment` must be off.
- In live mode, a missing UA must raise, not degrade.
- Record `raw["_fallback"]` (`xbrl_fallback.py:235`) and a `fallback_status` in `CompanyData.flags`.

### AR-5 (Blocker): L1 underestimates how much global state is hard-coded
The plan lists 4 places. There are at least **15** module-level paths or side effects, and several of them write *inside the package*:

- `data/edgar.py:19-21`:
  - `ROOT = parents[3]`; installed, that resolves to `…/lib/python3.x`;
  - `CACHE_DIR = parents[2]/.cache`; installed, that is `site-packages/.cache`;
  - `load_dotenv(ROOT/".env")` at import time.
- `data/fred.py:14,16`.
- `pipeline.py:26-28`.
- `backtest/batch.py:35-36`, which writes to `…/web/public/data`.
- `export.py:37`.
- `memo.py:31-33`: `load_dotenv(..., override=True)` at import, which **overrides** the user's environment.
- `notes.py:19`.
- `universe.py:22-23`, and `universe.py:98`: `compute_norms` writes `sector_norms.json` into the package directory. `data.yml:43` uploads it from there.
- `research/stats.py:20-21`.
- `research/__main__.py:33-35`.
- `research/assumption_sobol.py:41-43`.
- `model/ratings.py:27`.
- `scenarios/presets.py:195`.

In-process caches also ignore mode:
- `facts.company_facts` is `lru_cache(maxsize=2)` keyed by CIK only (`facts.py:29`);
- `universe._norms` and `universe._edgar` are cached;
- the research `_macro_cached` (`experiments.py:182`).

Switching `hub`/`live`/`frozen` in one process therefore returns stale data.

**Fix.** L1 must:
- (a) route every one of these through `fintwin.config`;
- (b) make outputs (`web/public/data`, `docs/paper`) explicit `out_dir` arguments of the build commands, never package-relative;
- (c) have `config.set_mode()` call `cache_clear()` on every cache;
- (d) remove import-time `load_dotenv` from library modules and call it only from the CLI or pipeline entry points.

Effort: 3–4 days, not part of a 1-week G1.

---

## 2. Important problems

### AR-6 (High): Ticker vs CIK keying changes the model output for the same firm
- `ticker_to_cik` (`edgar.py:96-121`) resolves plain tickers through **today's** `company_tickers.json`. A delisted firm has no ticker, and a reused ticker resolves to the wrong firm for historical `asof`.
- `universe.classify` (`universe.py:49-63`) depends on the *key string*:
  - `"AIR"` gets the GICS sector from the S&P CSV, or `""`;
  - `"CIK0000001750"` gets the FF12 industry.
- Both `FLOATING_BY_SECTOR` (`calibrate.py:809-810`) and `sector_tol` (`calibrate.py:974-976`) read that sector. So `twin("AIR")` ≠ `twin("CIK0000001750")`, and every non-S&P firm gets `sector_tol=1.0` (FF12 names never match the GICS keys in the norms).
- `edgar_universe.py:182` stores only `tickers[0]` (current).

**Fix.**
- The CIK is the only internal key.
- Add a resolver `resolve(ticker_or_cik, asof)` backed by a `tickers` table with `valid_from`/`valid_to`. It cannot be derived from the current code; build it from historical snapshots of `company_tickers.json` plus the submissions `formerNames`/tickers, and flag the uncertainty.
- Use one industry scheme (SIC → FF12 for everyone) in the library.
- Keep GICS for the S&P dashboard only, as display metadata.

### AR-7 (High): `quarterly_first` / `quarterly_latest` do not give `panel(asof=d)`. A bitemporal table is needed.
`ft.panel(asof=d)` means "each firm's quarters as known on `d`". That is neither the first-reported value (a restatement *before* `d` must win) nor the latest. The faithful object is the loader output for every distinct filing date: `panel_vintages(cik, period_end, known_from, known_to, fields…, flags…)`. Store only the rows that change between consecutive vintages. `quarterly_first` and `quarterly_latest` are then views of it.

Compute: each extra vintage costs ~1.2 s of loader time (measured). That is ~68 filing dates × 5,300 firms ≈ 130 CPU-hours ≈ 16 h on one cax31 (~0.6 EUR), or ~8 h on 2×cax31 within the 20-vCPU limit. This is affordable once, but it **must be incremental** in the weekly build: only new filings produce new vintages. Otherwise it does not fit Actions.

### AR-8 (High): The H1 universe and event tables are only partly derivable
What exists (`edgar_universe.py`):
- CIK, current name, current SIC/FF12, `fy_end`;
- `first_year`/`last_year` from **calendar-year frames** (`edgar_universe.py:132-142`), not filing dates;
- `last_periodic`;
- 8-K **1.03 only** (`edgar_universe.py:173-175`).

Missing:
- status and exit reason (acquired / delisted / deregistered / bankrupt). This needs Forms 25-NSE and 15-12B, 8-K items 2.01/3.01/5.01, and successor CIKs. That is new logic: about 1 week including validation.
- Entry and exit by filing date.
- Historical SIC (`meta.sic` is today's value).
- Historical tickers (AR-6).

Two claims in the plan also need wording changes:
- The universe is selected on "≥ $50M revenue in **any** year 2012–2024" (`edgar_universe.py:6-10,34-35`). Membership is decided with future information. So "without survivorship" is true, but "selection on later size" is not point-in-time. Add an `eligible_asof` rule, or document it plainly.
- It excludes SIC 6000–6999 (`edgar_universe.py:104-110`). So it is "~5,200 non-financial filers", not "the whole universe of SEC filers" (§0).

The good news: the 9,359 cached `submissions_*.json` files already hold `items`, `form`, `filingDate` and `acceptanceDateTime`, so the events table is cheap to derive.

### AR-9 (High): Columns of H1 `facts_vintages` that are wrong or missing
- `fiscal_year/quarter`: companyfacts' `fy`/`fp` describe the **filing**, not the period. For fallback rows they are `None` (`xbrl_fallback.py:180`). Either keep them as `filing_fy`/`filing_fp`, or derive the period's fiscal quarter from the loader's spine.
- `concept` vs `tag`: keep the raw `tag`, plus a `field` mapping table (from `DURATION`/`INSTANT`/`DA_PARTS`).
- `derived` belongs on panel rows, not raw facts.
- Missing columns:
  - `frame`;
  - `acceptance_datetime`, from the submissions cache. `filed` is a date, the loader filters `filed <= asof` inclusively (`facts.py:275-276`), and 10-Qs filed after the close are otherwise "known" a day early;
  - `decimals`, which D11 uses;
  - `source`.
- Coverage: the fallback only parses the 97 loader tags (`xbrl_fallback.py:164`). A raw table that ships *all* tags from companyfacts would be internally inconsistent: other tags would have no fallback rows. Either ship only the 97 tags, or document the gap.

### AR-10 (High): Licensing conflicts inside the wheel and the dataset
L4 says to ship "only the small reference CSVs", but those are the encumbered ones:
- `data/gdp_vintages.csv` (138 KB, Philly Fed RTDSM, used by `fred.gdp_vintage`, `fred.py:14,50`). §8 says no redistribution without written permission, yet the wheel and the repo ship it today (`pyproject.toml:37-38` packages the whole `fintwin/`).
- `sp500_*.csv` and `universe_sp500.csv`: from Wikipedia, so CC-BY-SA, with GICS labels that MSCI/S&P own. They cannot go into a CC-BY-4.0 dataset.
- `rating_spreads.csv` (Damodaran via Wayback): terms unstated.

There is a functional knock-on as well. If RTDSM is dropped in hub mode, `recession_regime` silently falls back to today's revised GDP (`fred.py:76-78`), and the hub twin drifts away from the paper.

**Fix.**
- Replace RTDSM with BEA/ALFRED GDP vintages. BEA data is public domain; check whether ALFRED's redistribution terms differ from BEA's.
- Or fetch RTDSM at runtime with a cache.
- Keep the S&P, GICS and Damodaran tables out of the wheel and the dataset, and fetch them at runtime.

### AR-11 (High): Removing BAA10Y touches the frame shape
`macro_quarterly` builds DGS3MO, DGS10 and BAA10Y, then `.dropna()` (`fred.py:42-47`). `credit_spread` is never read by the model (grep: the only reference is `fred.py:20`). Dropping BAA10Y is therefore safe, but it changes which rows survive `dropna`. It must be done in the `lib` branch with a test that `fit_vasicek` and `term_premium` are unchanged (`calibrate.py:817-819`). A6 should also say "the model does not use BAA10Y", which is better news than "users download it locally".

### AR-12 (High): Leaving `twin`, `bench` and `R` without a decision on which spec is the product
- The paper reports v2-pre, v3 and the ladder.
- The dashboard and the goldens use whatever `FINTWIN_SPEC` the weekly build has. That is `v2-rev` by default (`spec.py:20`); `golden_cases` (`export.py:273-316`) does not stamp the spec.
- If the library and dashboard move to v3, the TS port must implement every v3 mechanic (Phase 1b). The goldens must also carry `spec`, otherwise parity can pass while Python and TS run different specs.

ADR-001 must fix: the product spec, the library default, and that `twin.params["spec"]` is always reported.

### AR-13 (High): Freezing rev3 and then branching `lib` gives a three-way divergence
"Freeze when the full run starts" is safe for the *numbers* only if the full run's code is never touched again. But rev3 keeps changing after the freeze:
- Phase 4: README, site, `findings.png`, Zenodo metadata, WS-E web numbers;
- Phase 5: wave-3 reviewer fixes, possibly code and a partial rerun.

`main` keeps getting:
- the weekly bot commits to `web/public/data/index.json` (`data.yml:113-118`);
- contributor PRs, with no merge into rev3 until release.

`lib` would rewrite exactly the hot files:
- `data/edgar.py`, `data/fred.py`, `xbrl_fallback.py`, `universe.py`, `pipeline.py`, `export.py`, `batch.py`, `memo.py`, `notes.py`, `research/*` (paths), `pyproject.toml`/`uv.lock` (L4 versus WS-D's R items), `__init__.py`/version, `.github/workflows/*` (L5/H5 versus OPS fixes), and `README.md`.

Also, shard stamping (SW-2) hashes the code. Any lib refactor invalidates every rev3 shard, so a wave-3 partial rerun cannot run from `lib`.

**Fix (order).**
1. Until `v3.0.0`, `lib` is **additive only**. New files: `config.py`, `twin.py`, `hub.py`, `cli.py`, `data/export_parquet.py`, `bench/`. There are no edits to existing modules, and the new modules read the existing constants.
2. Tag `v3.0.0`, merge rev3 into main, and *then* make one mechanical "L1 path rewrite" commit on `lib`, forked from main.
3. Add a **paper-parity test** on `lib`: 30 firms × 1 cutoff must reproduce the `v3.0.0` shard outputs bit for bit.

Merge pain otherwise: about 2–3 days of conflict resolution in `data/*` and `calibrate.py`.

### AR-14 (High): Dashboard at 5,300 firms. What breaks.
- **`index.json`**: 268 KB × 5,300/392 ≈ **3.7 MB** raw, ~0.8–1 MB gzip. It is loaded on every route (`data.ts:102`). Values carry 10 significant digits (`export.py:142,160`).
  - Fix: round to 3 significant digits (about −50%).
  - Split into `index_min.json` (ticker, name, sector, base health) plus a lazily loaded `matrix.json`.
- **Search / switcher**: `CommandPalette.tsx:15-31` maps every company and, with an empty query, renders **all** of them as DOM rows (`:61-64`). That is 5,300 rows on every open. Cap it at ~50 or virtualise.
- **Other full-universe renders**:
  - `CompareView.tsx:41` renders the full matrix: 5,300 × 11 presets ≈ 58k cells;
  - `TwinView.tsx:86` plots every company;
  - `VersusView.tsx:26` builds a `<select>` with 5,300 options.
  - All need pagination, sampling or virtualisation.
- **Memory**:
  - The worker is fine. It holds one shock array per firm (`worker.ts:12-21`, 5,000×12×k doubles), independent of universe size.
  - The risk is `data.ts:91-100`: an unbounded `Map` of promises for every fetched company JSON. A screener built by fetching company files would pin ~160 MB of parsed objects. The screener must use only index fields, and the cache needs an LRU.
- **Universe meaning**: the 5,300 include firms that stopped filing years ago. A "latest" twin for a firm whose last 10-Q was in 2015 is noise. W2 must filter on `last_periodic` within ~6 months.
- **Size**: A9's 250 MB counts only company JSON. Add timeline (~24 KB), prerendered HTML (15–45 KB) and memos. That is ≈ 70–100 KB per firm → **370–530 MB**, still under 1 GB. Also:
  - the `site-data` artifact (`data.yml:110-111`, 90-day retention) becomes ~0.4 GB a week;
  - committing `index.json` weekly to `main` adds a ~4 MB file with poor deltas to git history. Stop committing it; `pages.yml` already reads the artifact.
- **SEC fair access in the weekly build**: the `norms` job warms the cache only for `universe.tickers()` (S&P, `pipeline.py:40`). At 5,300 firms the shards would fetch the rest themselves. That is 20 concurrent runners each throttled to ~6.7 req/s, so **~130 req/s under one User-Agent**, more than 10× the SEC limit.
  - Fix: warm all firms in one job (~13–16k requests ≈ 35–45 min; the timeout is 90), then run the shards with `FINTWIN_FILL_ONLY=1`, or better a strict frozen mode that never fetches.
- **Prerender (W3)**: the app is client-only and data-fetching (`data.ts`). `renderToString` does not await fetches, so the views must take data as props, plus a hydration path. That is ~1–1.5 weeks, not a build script. 5,300 near-identical generated pages also risk being classed as thin content.

### AR-15 (Medium): Leaderboard re-runs untrusted code (B3)
- Run submission code only on `pull_request` (never `pull_request_target`), with:
  - `permissions: {}` and no secrets;
  - repo setting "require approval for fork PRs from all outside contributors";
  - `timeout-minutes`;
  - a container with `--network none`.
- The `env.lock` install is itself arbitrary code. Install in a separate step, then cut the network.
- Mount a **features-only** bundle without labels. Score in a second job that sees only the predictions artifact.
- A third `workflow_run` job with `contents: write` reads only the validated scores JSON (schema check, numeric bounds) and updates the table. It never checks out PR code.
- Honesty limit: labels are public (A10), so reproducible code cannot prevent fitting to the test years. Say so on the page. The **prospective track** is the only uncheatable score.

### AR-16 (Medium): Notebook execution in CI (A8, D)
- Six notebooks. Notebooks 1 and 2 need the panel tables, at least tens of MB even when sampled.
  - Pin the dataset revision.
  - Use a `fixtures/` subset of ~50 firms published as its own HF config.
  - Cache the HF hub folder with `actions/cache`.
- Expected run time: ~5–8 min a run with sampling.
  - Run on changes under `docs/` and `notebooks/`, and nightly. Not on every PR.
- Notebook 6 (MCP plus LLM) cannot run in CI without a key. Execute it with recorded tool transcripts, or mark it non-executed.
- Colab badges must pin the `fintwin` version and the dataset revision, or old notebooks break with every weekly push.

### AR-17 (Medium): H5's `super_squash_history` contradicts H6's pinned revisions
Squashing the HF branch every quarter removes the commits that pinned revisions point to. That breaks "results are reproducible".

**Fix.**
- Weekly pushes go to a `weekly` branch, which is squashed.
- Quarterly snapshots are immutable tags on `main` that are never squashed. Check whether tags survive a squash on HF. If not, use Zenodo as the pin.
- The library resolves `revision="2026Q4"` names to those tags.

### AR-18 (Medium): Runtime per call, and the 60-second first-run test
- Live or frozen: `twin("CCL")` ≈ 2–3 s load + 1.1 s calibrate + 0.12 s per preset, plus 5–30 s of SEC requests on the first fetch of a firm (companyfacts, submissions, fallback instances).
- `tw.reverse_stress()` adds ~2 s. Sobol (`with_sobol`) adds much more.
- The cold import is ~5–10 s because `scipy`/`statsmodels` load eagerly through `calibrate`.
- So < 60 s is realistic **only** if:
  - (a) `import fintwin` is lazy (the L2 facade must not import `export`/`research`);
  - (b) hub reads one firm (AR-3), not the table.
- `ft.panel()` over 5,300 firms in live mode is 2–4 CPU-hours. It must be served from `panel_vintages` (AR-7), never by looping the loader.
- `lru_cache(maxsize=2)` (`facts.py:29`) and the per-process throttle (`edgar.py:56-63`) mean a user's `multiprocessing` loop multiplies the SEC request rate. L1 should add a cross-process limiter, or document "use hub mode for bulk work".

### AR-19 (Medium): B5 underestimates the FinTwin baseline
Altman, Ohlson, logit and LightGBM really are minutes. The **FinTwin** baseline over ~5,200 firms × ~12 cutoffs is ≈ 1.3 s load + 1.1 s calibrate + MC ≈ 3 s per case ≈ 50 CPU-hours ≈ 6–7 h on cax31.

**Fix.** Set the bench splits to *exactly* the paper's cutoffs, so that the FinTwin baseline is the paper's full-run output and is not recomputed.

### AR-20 (Medium): The TS/Python parity burden of new features
- None of L, H, B, R or M touches `sd_model`/`shocks`/`scenario`/`summary`/`ratings`, so they add no TS burden.
- The goldens (`export.py:273-316`) test only `simulate` with given params, and the browser consumes the params from JSON.
- Burden arises from:
  - (a) new presets or knobs (W4 "your own scenario", `tw.stress(custom)`);
  - (b) switching the product spec to v3 (AR-12);
  - (c) any rev3 B1/B2 mechanic merged after the TS port.
- Rule for ADR-001: the `lib` branch may not change model mechanics. New knobs land in Python and TS together, with a golden for each. The goldens add `spec`, `sector_tol ≠ 1` and `_param_draws` (SW-1 already asks for part of this).

### AR-21 (Low): Packaging details
- `python-dotenv` is a core dependency (`pyproject.toml:11`), and `pyarrow`/`platformdirs` are missing.
- There are two version sources: `pyproject.toml:3` and `__init__.py:3`.
- `fintwin.api` already names the FastAPI app, and it imports `fastapi` at the top (`api.py:15-16`). Rename it to `fintwin.server`, so that "public API" docs and `import fintwin.api` don't collide.
- `research/` (~4,500 lines) ships in the wheel. That is acceptable, but keep it out of the public namespace.

---

## 3. Missing opportunities

- **AR-22 (High value): make "frozen mode" the hub mode.** The frozen-snapshot reader already exists (`edgar.frozen()`, `FrozenMiss`). If the hub stores the raw facts in loader-input format (AR-2), hub mode becomes "frozen mode with a remote, Parquet-backed store". The code is roughly 150 lines, and paper, dataset and library become identical by construction, which is what H2 wants.
- **AR-23: data diffs as a product.** The weekly build already computes `changes.json`/RSS. With `panel_vintages`, a "restatements this week" feed (which firms revised which quarter, by how much) is a cheap artefact that keeps the R story alive after launch.
- **AR-24: an `eligible(cik, asof)` function.** It is a reproducible, point-in-time universe rule (≥ 16 quarters on the cutoff, revenue threshold measured point in time). It fixes AR-8's selection-on-future-size and is reused by the bench, R and the dashboard.
- **AR-25: a small fixtures config on HF** (50 firms, all tables). It serves CI, notebooks, docs examples and L6 at once, and keeps CI off the full dataset.
- **AR-26: cross-checks between ingestion paths in H3.** Take a sample of facts from companyfacts and the same facts from the XBRL instances (the existing fallback parser) and compare them. This is a stronger quality check than A = L + E, and the code already exists.

---

## 4. Concrete plan edits ("section/item → change")

1. **§2 L, findings → change.**
   - Replace "cache hard-coded in 3 places" with the list in AR-5 (≥ 15 sites, including package-relative writes at `universe.py:98` and an import-time `load_dotenv(override=True)` at `memo.py:31`).
   - Add "invalidate all `lru_cache`s on mode change (`facts.py:29`, `universe.py:35,65,70`)".
2. **L2 → change.** "Wrappers over `stochastic/calibrate.calibrate`" becomes "a point-in-time calibrate extracted from `research/experiments.py:350-363` into `fintwin/twin.py`, which both research and the public API use". With `asof` set it must:
   - take macro, spreads and GDP vintage as of `asof`;
   - set `sector_tol=1` (or use PIT norms).
   Add explicit `spec=` (ADR-001 decides the default; `spec.py:20` is `v2-rev` today) and a parity test against the research calibrate (AR-1, AR-12).
3. **L2 → add.** One key: CIK. `resolve(ticker, asof)` backed by a `tickers` table with validity dates. One industry scheme (FF12 from SIC) in the library (AR-6; `universe.py:49-63`, `calibrate.py:809,976`).
4. **L4 → change.** "Wheel without data (only small reference CSVs)" becomes: no `gdp_vintages.csv`, `sp500_*.csv`, `universe_sp500.csv` or `rating_spreads.csv` in the wheel (licences, AR-10). Core dependencies add `pyarrow`, `platformdirs` and `huggingface_hub`; `python-dotenv` moves to an extra.
5. **L6 → add.** Make `import fintwin` lazy. The 60-second target assumes per-firm hub reads (AR-3, AR-18).
6. **H1 → replace the schema** (ADR-002):
   - `facts_raw`: cik, tag, unit, start, end, val, accn, form, filed, acceptance_datetime, filing_fy, filing_fp, frame, decimals, source ∈ {companyfacts, xbrl_fallback}. Only the loader's 97 tags plus `DA_PARTS`/`MATURITY_TAGS`. Partitioned by `cik % 64` and sorted by (cik, tag, end, filed). This is the loader's input; the loader runs unchanged on it.
   - `panel_vintages`: cik, period_end, known_from, known_to, every `quarters` column, the `FLAG_COLUMNS`, `da_annual`, the imputed mask as bit flags, and the provenance accession per field. `quarterly_first`/`quarterly_latest` become views of it.
   - `company_meta`: per cik × vintage, with `maturities` and `maturities_date`.
   - `companies`, `tickers` (with validity dates), `events` (from the cached submissions, with item codes and acceptance time), `macro` (licensed series only), `reference` (sector norms by date, if kept) and `manifest` (snapshot SHA256, loader git SHA, spec).
   (AR-2, AR-3, AR-7, AR-9.)
7. **H1 universe → add.** The status and exit reason are new logic (Forms 25/15, 8-K 2.01/3.01/5.01), about 1 week. State that selection uses revenue "in any year 2012–2024" (`edgar_universe.py:6-10,34`), add `eligible_asof`, and say "non-financial" in §0 (AR-8, AR-24).
8. **H2 → add.** `panel_vintages` costs ~130 CPU-hours once (2×cax31, ~8 h, under 1 EUR) and must be **incremental** in the weekly build (AR-7).
9. **H5/H6 → change.** No `super_squash_history` on the branch the pins refer to. Squash a `weekly` branch; quarterly immutable tags (AR-17).
10. **H6 → add.** Hub mode disables `xbrl_fallback.augment`. Live mode without a UA raises instead of degrading silently (`xbrl_fallback.py:236`). Hub == frozen output is a CI test (AR-4, AR-22).
11. **A6/§8 → add.** "BAA10Y is not used by the model (only `fred.py:20`); drop it, and test that `dropna` leaves the rates unchanged." Replace Philly Fed RTDSM with BEA/ALFRED GDP vintages, or the hub twin loses point-in-time GDP (`fred.py:50-66,76-78`) (AR-10, AR-11).
12. **B1 → change.** Splits equal the paper's cutoffs, so the FinTwin baseline is the paper's output (AR-19).
13. **B3 → add a security design.**
    - Use `pull_request` only, with `permissions: {}`.
    - Require approval for fork PRs.
    - Install the dependencies, then run with `--network none` on features only.
    - Score in a separate job.
    - Write the scores through `workflow_run` with schema validation.
    - Add a public note that the historical tracks are not leakage-proof (AR-15).
14. **B5 → change.** "cax21, a few minutes" becomes "minutes for the classical baselines; the FinTwin baseline comes from the paper run (otherwise ~6–7 h on cax31)".
15. **W1/W2 → add.**
    - Warm the cache for all firms in a single job.
    - Shards never touch SEC (`FINTWIN_FILL_ONLY=1`), otherwise ~130 req/s under one UA.
    - Filter the universe to firms with `last_periodic` within 6 months.
    - Stop committing `index.json` to main (`data.yml:113-118`) (AR-14).
16. **W3 → change.** "Prerender with `renderToString` in a build script" becomes "SSR-ready views with data passed as props, plus hydration": 1–1.5 weeks.
17. **W4/W5 → add.**
    - `index.json` rounded and split (`index_min` plus lazy matrix).
    - Virtualised palette and compare table (`CommandPalette.tsx:15-31,61-64`, `CompareView.tsx:41`, `TwinView.tsx:86`, `VersusView.tsx:26`).
    - An LRU in `data.ts:91-100`.
    - The size estimate becomes 370–530 MB, not 250 MB (AR-14).
18. **D → add.** Notebooks run against a 50-firm fixtures config with a pinned revision, on docs changes and nightly. The MCP notebook replays transcripts (AR-16, AR-25).
19. **§3 rule → change.** "The library starts on `lib` from the freeze commit" becomes:
    - until `v3.0.0`, `lib` is additive only (new files);
    - after the tag, merge rev3 into main, then fork `lib` from main and make one mechanical path rewrite;
    - add a paper-parity test (30 firms × 1 cutoff, bit for bit against the `v3.0.0` shards) (AR-13).
20. **§3 G1 gate → add.**
    - The point-in-time twin matches the research calibrate (AR-1).
    - Hub == frozen (AR-22).
    - Installing into read-only site-packages works (AR-5).
21. **§3 estimates → change.** Here is my estimate per workstream (one agent; calendar time assumes the parallelism in §4):

| Workstream | Plan | My estimate | Main driver |
|---|---|---|---|
| L1–L6 | ~1 wk (G1) | **2.5–3 wk** | AR-1, AR-5, AR-6 |
| H1–H6 | 1–2 wk (G2, with B) | **3–4 wk** + ~8 h of server time | `panel_vintages`, universe status, tickers, validation |
| B0–B5 | (in G2) | **2–2.5 wk** + quarterly upkeep | secure leaderboard, prospective track |
| R study | (in G2) | **1 wk** after H | needs `panel_vintages` |
| W1–W5 | ~2 wk (G3, with D, M) | **3–4 wk** | SSR, routing migration, 5,300-scale UI |
| M1–M2 | (in G3) | **1 wk** | |
| D docs and notebooks | (in G3) | **1.5–2 wk** | fixtures, CI |
| G1–G3 repo hygiene | (in G3) | 3–4 days | |

   The critical path is L1 → AR-1 twin → H `facts_raw` + `panel_vintages` → hub mode → R → launch. That is ≈ **7–9 weeks after `v3.0.0`**, not ~4.5. With rev3 ending mid-November and the 20/12–6/1 blackout, a realistic launch is **late January to mid-February 2027**. Remove "early-to-mid December".
22. **§4 → change.** H6 (hub mode) and the H1 schema need Opus review, not just "Sonnet, schema by Opus". They decide whether the library reproduces the paper (AR-2, AR-4). Move `L2 twin.py` (the PIT calibrate extraction) to the same Opus agent as L1, and do it before H2 starts.
