# Interfaces: workstream F

New or changed (all additive):
- `export.dumps(obj, sig=10, **kw)`: `_clean` + `json.dumps(allow_nan=False)`. `_write`, `pipeline._json` and `api._build` use it, so no `NaN`/`Infinity` literal can reach `JSON.parse`.
- `export.index_entry(block)`: the single builder of an `index.json` company entry (now always with `gics` and `components`). Used by `export.build` and `pipeline.build_index`.
- `company_block(...)` output has a new key `n_paths`; `notes.fact_sheet` reads it (default 5000).
- `pipeline.build_index(tickers=None, failed=None)`: indexes only this run's universe (`universe.tickers()` + SHOWCASE) minus tickers in `.cache/failed`; returns the index plus `_stale` and `_orphans` lists (not written to index.json). `build_report.json` gains `stale_excluded` and `orphans`.
- `pipeline.failed_tickers()`: failure records, dropped once the company file is newer than the record. `shard` deletes its own `failed/shard{i}.json` at start.
- `changes.diff`: companies whose base health is null are skipped; null `p_breach` and null components no longer raise.
- `memo.unverified_numbers(memo, sheet, strict=False)`: U+2212 minus is parsed. `strict=True` (used by `memo.main`) also checks |x| <= 12 and enforces the sign of negative figures. Default behaviour is unchanged for `test_helpers.py`.
- `notes.build` never overwrites a `web/public/data/memos/{ticker}.json` whose `generated_by` does not start with `notes.RULE_BASED`. `fact_sheet` shows `"n/a (a quarter is missing)"` for TTM revenue when a quarter in the last four is null.
- `api`: only a `KeyError("Unknown ticker...")` is a 404; other `KeyError`s are logged and returned as 422.

## SW-9: NaN rating behaviour (what the TS side must do)
Intended behaviour (software.md #9): a non-finite coverage ratio fails SAFE, i.e. is scored as the WORST rating (rank 0, highest spread), never AAA. Python (`model/ratings.py:42`, `model/sd_model.py:57`, not owned by F) currently returns 14 (AAA) for NaN: see requests/F.md. The TS side (`web/src/engine/ratings.ts` `ratingRank`) currently returns -1 and then NaN spreads; it must return 0 for a non-finite input (`Number.isFinite(icr) ? searchsorted(...) : 0`), with the same NaN -> rank 0 test in both engines.
