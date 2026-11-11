"""Constants shared by the model (`sd_model.simulate`) and the calibration code that rebuilds its income statement
(MM-F5 anchor) or deflates by its cost inflation (MM-F10). Changing one here changes both sides together."""

EPS = 1e-9  # guard against division by zero
DAYS_Q = 91.25
INFL_Q = 0.006  # fixed-cost inflation per quarter (about 2.4% a year); assumption
CASH_YIELD_SHARE = 0.9  # cash earns 90% of the short rate; assumption
REVOLVER_SPREAD = 0.015  # revolver margin over the short rate plus the rating spread (150bp, docs/METHODOLOGY.md)
# Health-score weights (docs/METHODOLOGY.md): liquidity runway, coverage rating, leverage, Altman Z''.
HEALTH_WEIGHTS = {"liq": 0.3, "cov": 0.3, "lev": 0.2, "solv": 0.2}
