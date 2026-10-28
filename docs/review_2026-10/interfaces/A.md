# Workstream A (data layer): interface changes

All changes are in `engine/fintwin/data/`. Public signatures are unchanged (`load_company`, `CompanyData`,
`duration_quarters`, `instant_values`, `company_facts`); everything below is additive.

## Switch

| Env var | Default | Effect |
|---|---|---|
| `FINTWIN_DATA_LEGACY=1` | `0` | Revision-2 data layer, bit for bit: `load_company` runs `_v2_load_company` (old tag lists, old spine, old zero fills, old `_total_debt`, old `_latest`), `xbrl_fallback` picks instances and dedups facts as before, `edgar_universe.is_financial` uses SIC 6000-6799. Checked on 250 cached firms against the `rev3` code: identical `quarters`, notes, provenance and maturities. Helper: `fintwin.data.edgar.data_legacy()`. |

The data fixes have no `FINTWIN_SPEC` dependence: they apply to v2-pre, v2-rev and v3 alike (REVISION_PLAN_3 §0.3).

## `CompanyData.quarters`: rows

- **D1: full fiscal calendar.** Between the first and last reported revenue quarter, every fiscal quarter is a row. A
  quarter with no revenue fact is a **gap row**: `gap=True`, revenue NaN, flows NaN. Balances may still be present
  (they are read from that quarter's balance sheet, or carried forward). The last row always has revenue.
  Gap-row dates are taken from the company's own balance-sheet dates when available, so 52/53-week calendars stay
  aligned.
- **D9: fiscal-year-end changes.** A quarter that overlaps the previous one by more than 15 days (recast comparatives
  after an FYE change, duplicate definitions) is dropped; revision 2 kept any point at least 60 days away. A stub of
  less than one quarter between two quarters (e.g. a two-month 10-KT) sets `fye_break=True` on the following quarter.
- Consequence: `len(q)` and `q.tail(n)` count calendar quarters, including gap rows. **Use `contiguous` before you
  treat `n` rows as `n` consecutive reported quarters.**

## Contiguity helpers (`fintwin.data.facts`)

```python
contiguous(q, n, col="revenue") -> bool          # last n rows = n consecutive fiscal quarters, all with `col`
contiguous_mask(q, n, col="revenue") -> Series   # per row: does the window of n rows ending here pass?
```

A window fails if it holds a gap row, crosses a `fye_break`, has two rows more than 126 days apart (this also
catches legacy frames, which have no gap rows), or is shorter than `n`. Usage:

```python
ttm = q["revenue"].rolling(4).sum().where(contiguous_mask(q, 4))   # TTM, NaN unless 4 consecutive quarters
usable = contiguous(hist.quarters, 16)                              # "16 quarters of history"
fut = full.loc[full.index > last].head(8); ok = contiguous(fut, 8)  # 8 realised quarters, no hole
```

## `CompanyData.quarters`: new columns

| Column | Type | Meaning |
|---|---|---|
| `gap` | bool | D1 calendar row with no revenue fact |
| `fye_break` | bool | D9: days left uncovered between the previous quarter and this one |
| `vintage_mixed` | bool | D6: a core flow's Q4 had no same-vintage 9-month leg and was dropped (so it is NaN) |
| `splice_break` | bool | D7: a core field (revenue, operating income, net income, CFO, capex, D&A, cash) comes from a fallback tag whose level differs > 10 % from the higher-priority tag on overlapping periods |
| `da_missing` | bool | MM-F4: reported quarter (not a gap row) with no D&A after the extended tag list and the parts fallback |
| `da_annual` | float | MM-F4: where `da_missing`, the fiscal-year D&A / 4 (the fiscal year covering the quarter if its 10-K is in the vintage, else the latest earlier one); NaN elsewhere. Not used by the loader; B1 decides |
| `debt_notes`, `finance_lease` | float | D3: last-resort debt evidence (SeniorNotes, NotesPayable, ConvertibleNotesPayable, LongTermNotesPayable; FinanceLeaseLiability) |

## `CompanyData`: new optional fields

- `imputed: DataFrame | None`: bool, same shape as `quarters` (minus flag columns); True where the value was not
  reported for that quarter but carried forward or zero-filled (D2). `None` in legacy mode.
- `flags: dict`: diagnostics (`splice`, `splice_unchecked`, `vintage_fixed`, `vintage_mixed`, `sign_flipped`,
  `sign_negative`, `debt_untagged`, `debt_over_liabilities`, counts `gaps`, `fye_breaks`, `da_missing`,
  `da_from_parts`). `{}` in legacy mode. In-memory only (holds Timestamps).

## Value semantics that changed (non-legacy)

| Field(s) | Revision 2 | Revision 3 |
|---|---|---|
| receivables, inventory, deferred_revenue, short_investments, payables (balances) | per-quarter NaN -> 0 (payables: ffill 2, then 0) | ffill up to 2 quarters; then NaN. 0 only if the field is never tagged in the vintage (note `"<k>: no data, assumed 0"`) |
| dividends, buybacks, sbc (flows) | per-quarter NaN -> 0 | NaN when missing; 0 only if never tagged (note) |
| `total_debt` | NaN -> 0 | NaN when the quarter has no debt evidence after a 2-quarter ffill of **every** component (revision 2 ffilled `ltd_noncurrent` but not `debt_current`). 0 only if the company never tags any debt field (note `"total_debt: no debt tag in any filing, assumed 0"`, `flags["debt_untagged"]`). Short-term-only debt now counts (revision 2 gave 0). New tags: `ShortTermBankLoansAndNotesPayable`, `LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities`, `DebtAndCapitalLeaseObligations`, plus `debt_notes` / `finance_lease` as last resort. Note when debt > 1.05 x liabilities |
| `debt_current`, `ltd_current`, `short_borrowings`, `commercial_paper` | 0-filled | still 0-filled after the total is built (unchanged for callers) |
| `da` | tags incl. `Depreciation` alone | totals (+ `CostDepreciationAmortizationAndDepletion`, `UtilitiesOperatingExpenseDepreciationAndAmortization`); else `Depreciation` + `AmortizationOfIntangibleAssets` + `FinanceLeaseRightOfUseAssetAmortization`; else NaN with `da_missing` |
| capex, dividends, buybacks, interest_expense | any sign | D13: if most non-zero values are negative the series is flipped (note); remaining negative quarters become NaN (note) |
| Q4 / de-cumulated quarters | later leg minus the latest version of the earlier leg | D6: the earlier leg as it stood when the later leg was filed (same filing if possible); dropped if no such version |
| same-day duplicate facts | unstable sort, column-wise `.last()` | D5: stable sort on (filed, accn), whole last row |

## `xbrl_fallback` (D11)

- `instance_candidates(names, primary) -> list[str]`, `is_instance(content) -> bool`: non-inline filings try up to 3
  candidate files and keep the first whose root is `xbrli:xbrl` (revision 2 could parse `defnref.xml`, as one cached
  filing shows). EDGAR's `*_htm.xml` extractions are used directly.
- Duplicate facts in one instance keep the most precise `decimals`.
- Not done: completing filings that are only partly present in `companyfacts` (would need every filing downloaded).

## `edgar_universe` (D12)

- `is_financial(sic)`: 6000-6999 (the FF12 "Money" range), except 6770 (blank-check code given to post-bankruptcy and
  de-SPAC shells). `ff12(6770) == "Other"`. The committed `universe_edgar.csv` is **not** regenerated (see
  `requests/A.md`).
