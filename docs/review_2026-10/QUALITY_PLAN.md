# Code-quality plan (11-11-2026)

Source: eight read-only reviews of branch `rev3` (engine core, engine data, research and backtest, tests, web logic,
web UX, ops, cross-cutting slop), about 180 findings. Full findings with file:line and proposed fixes are kept with
this plan in `quality_review/` (one file per review; IDs below refer to them).

## Ground rules

1. **No change to numerical output** in this pass. A finding marked "changes numbers: yes" is listed under
   *Owner decisions* and is not implemented. Behaviour changes are limited to failure paths (a crash becomes an error
   message, a silent drop becomes a logged warning or a raised error).
2. **The rev3 run is in flight.** `research/__main__._code_digest` hashes every `engine/fintwin/**/*.py` into the shard
   stamps, so any edit under `engine/fintwin/` (even a comment) makes the running shards stale. This work therefore lives
   on branch `quality` and is merged into `rev3` **only after** the rev3 stats stage has been merged and its results
   pulled. Do not edit `engine/scripts/rev3_server.sh` at all.
3. Research and backtest code (`engine/fintwin/research/`, `engine/fintwin/backtest/`) gets only refactors that are
   provably behaviour-preserving (comments, dead code, named constants with the same values, tests). The deduplication
   of numerical helpers (R3, R4, R5, R10, R12, R13) waits until after v3.0.0 and needs a bit-for-bit parity run.
4. One workstream per set of files, so the branches merge without conflicts. Each workstream runs only the tests it
   touches on the PC; the full suite runs once on a burst server after the merge.

## Owner decisions (not implemented)

| ID | Issue | Why it needs you |
|---|---|---|
| data D1 | `recession_regime` uses today's NBER USREC dating cut at the cutoff; NBER announces turning points 6-21 months late | Look-ahead in the regime input; fixing it changes the paper's numbers. Options: lag USREC by the announcement delay, or use a real-time indicator (Sahm rule from ALFRED vintages) |
| research R1 | `backtest/batch.py` and `walk_forward.py` calibrate with today's product defaults (Jan-2026 rating spreads, 5% fixed-cost prior) at past cutoffs | Look-ahead in `calibration.json`'s rolling-origin results; the research pipeline is not affected. Either route these through `experiments.calibrate` or label them as in-sample |
| research R2 | The Holm secondary family and `capex_hypothesis_holds` use winsorisation limits computed on all years including the test year | Leak-free variants exist (`train_bounds`); switching changes reported p-values |
| research R6, R9, R13, R16 | cumulative-FCF minimum not floored; `plan2.calibration` ignores filing dates; three log-loss definitions; silent Sobol caps | Each changes reported numbers |
| core EC-06 | Starting cash skips the stale-balance logic used for every other stock | Changes simulations for firms with stale cash |
| web W6 / core EC-14 | Python `sd_model._rank` maps a NaN coverage ratio to AAA; TS maps it to D | Python and TS disagree on NaN paths; no current golden has one. Recommended: use `ratings.rating_rank` (D) in Python |
| data D22 | `interest_expense` sign rule shared with capex | Changes interest on filers who report it negative |

## Workstreams

| Branch | Scope (files) | Findings |
|---|---|---|
| `q-web-logic` | `web/src/engine/`, `charts/`, `ask/`, `App.tsx`, `hooks.ts`, `data.ts`, `format.ts`, their tests | web-logic W1-W5, W7-W25 (not W6); tests T4, T5, T16, T17, T21; slop S10, S11, S1 (TS side) |
| `q-web-ux` | `web/src/views/`, `ui.tsx`, `CommandPalette.tsx`, `styles.css` | web-ux W1, W2, W4-W25 (W3 is done on `main` in PR #60) |
| `q-data` | `engine/fintwin/data/`, `export.py`, new test files | data D2-D21, D23, D24; S8 (log, do not swallow silently) |
| `q-core` | `model/`, `stochastic/`, `scenarios/`, `sensitivity/`, `notes.py`, `memo.py`, `changes.py`, `api.py`, `pipeline.py`, `universe.py`, new test files | core EC-01-EC-25 except EC-06 and EC-14; S1 and S2 (Python side, same values) |
| `q-research` | `research/`, `backtest/` (behaviour-preserving only) | R7, R8 (failure paths), R14, R15, R17 (guards that only fire on bad input), R19, R20; S7 ticket codes in these modules |
| `q-tests` | `engine/tests/` (existing files) | tests T1-T3, T6-T15, T18-T20; S5; EC-23, EC-24; D21 |
| `q-ops` | `.github/`, `scripts/`, `tools/`, `Makefile`, `engine/pyproject.toml`, `engine/scripts/` except `rev3_server.sh`, `.gitignore`, docs prose | ops O1-O11, O13-O17 (not O12); docs D1, D3 |

Order of merge into `quality`: ops, data, core, research, tests, web-logic, web-ux. Then the full engine suite and
`npm test && npm run build` on a burst server, and a final diff review in the main session.

## Deferred

- Splitting the 670-line `_calibrate` and the 330-line `simulate` (EC-10), and `load_company` (D13): after v3.0.0, with
  the parity tests as the safety net.
- The research deduplication (R3-R5, R10-R13), as in rule 3.
- `data_legacy()` and `FINTWIN_*` switches (S6): they keep the v2 numbers reproducible; remove them once v2 is
  archived on Zenodo.
