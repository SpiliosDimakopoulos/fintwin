# Requests from workstream F

## Files F does not own
1. SW-9 (owner of `engine/fintwin/model/ratings.py` and `model/sd_model.py`): guard NaN in both rank functions so a non-finite ICR is rank 0 (worst): `np.where(np.isfinite(icr), np.searchsorted(ICR_LOWER, icr, side="right") - 1, 0)` (keep scalar use working). Add a test (NaN -> 0). TS side: see interfaces/F.md. F cannot do this: `metrics/` holds no rating code.
2. SW-6 (owner of `engine/fintwin/backtest/batch.py:358`): replace `OUT.write_text(json.dumps(res, ...))` with `from ..export import dumps` and `OUT.write_text(dumps(res, ...))` (strict JSON, NaN -> null). `calibration.json` may currently contain `NaN` literals.
3. SW-10 (owner of `batch.py:345`): `pd.qcut(xs["health_stress"].rank(method="first"), 5)` breaks ties by alphabetical ticker order. Shuffle rows with a fixed seed before ranking (`xs = xs.sample(frac=1, random_state=0)`), then restore order.
4. SW-19 (owner of `engine/tests/test_helpers.py`): `test_unverified_numbers_ignores_counts_but_not_thirteen` asserts the weak default; a `strict=True` case is in test_F_software.py. The `<25` health check, the `51/101` PIT constants and the planted-signal thresholds are in files F does not own.
5. SW-8 duplicates outside F: `experiments.health_at_open` (hard-coded access 1.5/0.8/0.6/0.3, ignores `access_icr`), `web/src/charts/Waterfall.tsx:22`, `web/src/format.ts healthStatus` (70/50/30 vs `notes._verdict`), literal `< 9` in `mc.summarize` vs `ratings.INVESTMENT_GRADE_MIN_RANK` and `notes.INVESTMENT_GRADE`. Suggest one `model/health.py` with weights and thresholds; then F's `changes.WEIGHTS` and `notes.INVESTMENT_GRADE` can import it. F did not dedup in its own files because no shared module exists yet.

## .tex edits needed for the bibliography
- Key renamed `lyytinen2023` -> `lyytinen2024` (year field was 2024). Update `docs/paper/sections/framework.tex:4` (`\citep{lyytinen2023}` -> `\citep{lyytinen2024}`).
- `docs/paper/fintwin.tex:128`: `\citep{cameron2008}` (two-way clustering) -> `\citep{cameron2011}`. `cameron2008` is kept for any wild-bootstrap use.
- New entries available (all uncited so far): stein2001, hillegeist2004, acharya2014, hansen2011, hansen2005, romano2005, cameron2011, ball2022, chen2022, altman1995 (Z'' primary source; cite next to `altman2006` where Z'' is used).
- C6/C7 not applied (text decisions): borio2014 and duffie2007 at framework.tex:9, smith2009 at framework.tex:37; reverse-stress citation at model.tex:58 (Grundke-Pliszka 2018 unverified, not added).
