"""Standardized shock generation: correlated, fat-tailed draws (unit variance, or unit MAD s.d. under MM-F7).

Columns: 0 = demand (revenue growth), 1 = variable-cost margin, 2 = short rate, 3 = discretionary financing,
4 = uniform(0,1) draw driving recession-regime transitions.
Kept separate from the model core so both engines can be fed identical shocks in parity tests.
"""

from __future__ import annotations

import numpy as np


def draw_shocks(p: dict, n_paths: int, horizon: int, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    z = np.empty((n_paths, horizon, 5))
    z[:, :, :4] = rng.standard_normal((n_paths, horizon, 4))
    rho = p["rho_gm"]
    z[:, :, 1] = rho * z[:, :, 0] + np.sqrt(1 - rho**2) * z[:, :, 1]
    df = p["t_df"]
    if df < 30:
        # Student-t via a chi-square mixing variable per path-quarter. Revision 2: one variable shared by demand and
        # margin, draws rescaled to unit variance. MM-F8 (`t_mix_indep`): one per column, so demand and margin have no
        # tail dependence beyond rho_gm. MM-F7 (`t_scale`): rescaled so the draws' MAD s.d. is 1, because sigma_g and
        # sigma_m are MAD estimates (unit variance made the body 15-35% too narrow at df 3-8).
        k = 2 if p.get("t_mix_indep") else 1
        w = rng.chisquare(df, (n_paths, horizon, k)) / df
        scale = p["t_scale"] if "t_scale" in p else np.sqrt((df - 2) / df)
        z[:, :, :2] = z[:, :, :2] / np.sqrt(w) * scale
    z[:, :, 4] = rng.random((n_paths, horizon))
    return z
