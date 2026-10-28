# CR (code-review fixes): new functions, keys and formats

No public signature changed; everything below is new or optional.

| Where | What |
|---|---|
| `backtest.batch.usable_prefix(nxt, last, col="revenue") -> int` | leading rows of `nxt` that are consecutive reported quarters after `last`, including the first row's link and its `fye_break` (CR-1). `following` and `walk_forward._realized` both use it. |
| `backtest.batch.data_legacy` | now the same function as `data.edgar.data_legacy` (`FINTWIN_DATA_LEGACY` exactly `"1"`); `research.stats._data_legacy` delegates to it (CR-8). Before, stats also read `true`/`yes` as legacy. |
| `backtest.batch._calendar(hist, s)` | `s` with gap rows blanked; the random-walk baselines take shift/diff on it, then drop NaN (CR-3). Legacy: positional, as before. |
| `research.stats._finite_rows(star, cols=None)` | filters resamples on the columns in use only; `stepm` / `spa` use the hypotheses with a finite statistic, `mcs` the models with a finite loss (CR-2). |
| `stochastic.calibrate._last_known(q, fields, limit, imputed=None)` | with `CompanyData.imputed`, staleness counts from the last genuinely reported value; notes give that date (CR-5). `imputed=None` is the old rule. |
| `p["_sources"]["trailing"]` (new key, revision-3 data layer only) | present when the last 8 quarters are not consecutive: which run the trailing windows use and, if the last 4 are not consecutive, that TTM revenue is annualized (x 4/k) and the covenant history's earlier slots take the run's average (CR-4). |
| `research.experiments` `Failures` | `outcome`, `covid_outcomes`, `structural` now record `n` (attempts); `outcome` also skips with reason `revenue` when the trailing revenue is unusable (CR-6). |
| `assumption_sobol._one` | returns the outputs dict or an exclusion reason string (`not_usable`, `outcome_short`, `outcome_gap`, `outcome_missing`, `small`, `no_margin`). `_failures_<i>_of_<n>.txt` is now `{"failed": {exception type: n}, "excluded": {reason: n}}` (CR-7). |
