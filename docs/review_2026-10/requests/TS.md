# Requests from the TS port (phase 1b)

- `engine/fintwin/export.py` `golden_cases` still writes 12 of 29 keys for the ticker goldens. `engine/scripts/gen_parity_goldens.py`
  re-simulates them from the stored params/eps and adds all keys; if export is re-run, run that script afterwards (or widen the tuple).
- Python `model/ratings.py` / `sd_model._rank`: NaN -> 14 (AAA); TS now returns 0 (SW-9). Not covered by a golden (NaN is not JSON).
- Not ported (no browser use): `loop_r1`/`loop_r2` ablation levers, `spread_scale`/`spreads`/`access_*` research params,
  `scn["revenue_override"]` (conditional backtests), and M4 `sector_knobs`.
