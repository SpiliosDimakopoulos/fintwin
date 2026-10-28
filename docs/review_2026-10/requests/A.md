# Requests from workstream A (data layer)

Read `interfaces/A.md` first. The short version: `quarters` can now hold **gap rows** (NaN revenue, `gap=True`), and
balances, flows and `total_debt` can be **NaN** where revision 2 put 0. Data fixes apply to all specifications, so code
that reads `quarters` must survive NaN even under `FINTWIN_SPEC=v2-pre`. `FINTWIN_DATA_LEGACY=1` gives the old frame.

## To B1 (`stochastic/calibrate.py`)

1. **Last-row values that can now be NaN** (each one makes the simulation NaN):
   - `ar0, inv0, ap0, def0 = last["receivables"], last["inventory"], last["payables"], last["deferred_revenue"]`
     (`calibrate.py:281-282`): NaN when the field is tagged in the vintage but missing for 3+ quarters at the end.
   - `debt0 = float(last["total_debt"])` (`:208`), and `q["total_debt"].iloc[-1] - q["total_debt"].iloc[-9]` (`:219`).
   - `div_q = float(q["dividends"].tail(2).mean())` (`:230`): NaN if both quarters are missing.
   Suggested: take the last finite value within the last 4 rows, else 0, and record it in `_sources`; this changes
   nothing when the values are finite, so v2-pre stays identical on complete firms.
2. **Windows `tail(n)` now count calendar quarters.** `rev.tail(4).sum()` (`rev_ttm`, `:234`, and `quarterly_costs`
   `:245`) silently sums 3 quarters when one is a gap row (pandas skips NaN). Revision 2 summed 4 *reported* quarters
   that could span 5 calendar quarters. Either `q = q[~q["gap"]]` at the top of `_calibrate` (keeps revision-2
   semantics except for real data fixes) or contiguity-aware windows (`facts.contiguous_mask`). Same for `t4`, `t8`,
   `win.tail(16)` (`:168`, dropna first so fine), `_seasonal` (`rolling(4, center=True)` over NaN gives NaN ratios,
   dropped by the median).
3. **MM-F4.** Use `q["da_missing"]` / `q["da_annual"]`: on firm-years where D&A is missing in the window, either set
   `dep_rate = 0` with a flag (D&A stays inside F + v·rev), or add `da_annual` to EBITDA before the cost regression
   and keep `dep_rate`. Prevalence is in my final report.
4. `explained = NI + da + sbc - ΔNWC` (`:200`) now drops quarters with missing `sbc` or NWC parts instead of
   counting them as 0; `nanmedian` handles that, no change needed, but expect `ocf_ratio` to move on affected firms.

## To C2 (`research/experiments.py`, `backtest/*`, `research/assumption_sobol.py`, `research/distress.py`)

1. `usable` (`experiments.py:90`) and `len(hist.quarters) < 16` (`backtest/batch.py:174, 240`): count of rows now
   includes gap rows. Use `facts.contiguous(hist.quarters, 16)` (or whatever window the spec needs; D1).
2. `_ttm` (`experiments.py:93`) already returns NaN when one of the last 4 rows is NaN, so a gap row makes TTM NaN
   (correct under D1). Same for `nxt["revenue"].isna().any()` (`:326`) on the 8 outcome quarters (`:496`):
   a gap row among them now rejects the firm-year, where revision 2 used quarters up to 10+ calendar quarters ahead.
   Decide whether to reject or to take `contiguous(nxt, 8)`; either way, report the count.
3. `pre["dividends"].tail(4).fillna(0)` and buybacks (`:373, 402, 476`): fine, but note that missing now means
   unknown, not zero.
4. `(win["total_debt"].max() - pre["total_debt"].iloc[-1])` (`:486`): NaN possible.

## To F (`pipeline.py`, `export.py`)

- `pipeline.py:43-44`: `tail(4).sum()` of EBITDA over gap rows, and `total_debt.iloc[-1] - cash - short_investments`
  can be NaN.
- `export.py:168-180` `history_block`: `rolling(4).sum()` TTMs; mask with `facts.contiguous_mask(full, 4)` so the
  site does not show 4-row sums spanning a gap. Gap rows will appear in the history arrays as nulls (`_clean`
  already writes NaN as null).

## To D (`tools/freeze_snapshot.py`) and the integrator

1. **D11 needs new snapshot files.** For non-inline filings the fallback now tries up to 3 candidate files per filing
   and checks each is an XBRL instance. Files beyond the first candidate are not in the current snapshot, so in
   frozen mode those filings are skipped (no regression: revision 2 parsed a non-instance there). Re-run the snapshot
   fetch once after A is merged if those filings should count.
2. **D12 changes the committed universe.** `universe_edgar.csv` must be regenerated on a server (network, about an
   hour of SEC requests): `cd engine && uv run python -m fintwin.data.edgar_universe`. Expected effect: companies
   whose current SIC is 6770 (blank check: post-bankruptcy shells and de-SPAC companies) enter; in the cached
   submissions there are 8 such candidates (e.g. American Apparel, with a 1.03 8-K; Infrastructure & Energy
   Alternatives; Inspirato). No current member has SIC 6800-6999, so the wider Money range removes nobody. The SIC
   is still the *current* one: EDGAR does not expose historical SIC codes, so a firm recoded to another financial
   code is still lost (limitation for the paper).
3. Shard stamping already records `FINTWIN_*` env vars, so `FINTWIN_DATA_LEGACY=1` runs are distinguishable.

## Out of scope, found while working

- `scripts/data_audit.py` (owner unclear) counts gaps from the spine; with D1 it should count `q["gap"]` instead.
- `quality.py` (mine, unchanged): `core_completeness_last20_pct` now counts gap rows as missing, which is correct.
