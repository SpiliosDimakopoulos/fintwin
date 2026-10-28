import os

import pytest

# Small bootstraps in tests: the research defaults (B = 10,000 for the test family) take minutes.
os.environ.setdefault("FINTWIN_B_FAMILY", "200")
os.environ.setdefault("FINTWIN_B_LAD", "20")


def make_params(**over) -> dict:
    """A small synthetic company with round numbers, independent of any network data."""
    p = {
        "ticker": "TEST",
        "name": "Test Co",
        "last_quarter": "2025-12-31",
        "horizon": 12,
        "history_quarters": 40,
        "seasonal": [1.0, 1.0, 1.0, 1.0],
        "season0": 0,
        "base_rev0": 1000.0,
        "mu": 0.01,
        "phi": 0.3,
        "sigma_g": 0.05,
        "g0": 0.01,
        "t_df": 6.0,
        "rho_gm": 0.3,
        "rec_hazard": 0.045,
        "rec_exit": 0.24,
        "rec_drift": -0.015,
        "rec_vol_mult": 1.5,
        "rec_state0": 0.0,
        "beta_gdp": 1.5,
        "F": 300.0,
        "v": 0.5,
        "rho_m": 0.5,
        "sigma_m": 0.01,
        "infl": 0.006,
        "target_margin": 0.1,
        "cut_delay": 2,
        "cut_speed": 0.04,
        "cut_floor": 0.85,
        "dso": 45.0,
        "dio": 60.0,
        "dpo": 50.0,
        "ddays": 20.0,
        "tau_ar": 1.0,
        "tau_inv": 2.0,
        "dep_rate": 0.03,
        "capex_ratio": 0.06,
        "maint_capex": 0.8,
        "sbc_ratio": 0.01,
        "ocf_ratio": 0.0,
        "tax_rate": 0.21,
        "coupon": 0.05,
        "floating": 0.1,
        "refi_ratio": 1.0,
        "sigma_fin": 0.02,
        "cash_target": 300.0,
        "cash_cap": 600.0,
        "div_q": 10.0,
        "bb_ratio": 0.3,
        "revolver_cap": 200.0,
        "cash_floor": 80.0,
        "maturities_q": [50.0] * 12,
        "r0": 0.03,
        "term_premium": 0.01,
        "kappa": 0.1,
        "theta": 0.03,
        "sigma_r": 0.003,
        "cash0": 400.0,
        "ar0": 500.0,
        "inv0": 400.0,
        "ap0": 300.0,
        "def0": 220.0,
        "ppe0": 2000.0,
        "debt0": 1500.0,
        "equity0": 1800.0,
        "other_net0": 300.0,
        "other_liab0": 400.0,
        "wc_other0": 0.0,
        "retained0": 900.0,
        "ebit_ttm0": [100.0] * 4,
        "ebitda_ttm0": [160.0] * 4,
        "interest_ttm0": [19.0] * 4,
        "_sources": {},
    }
    # make the opening balance sheet balance exactly
    p["other_net0"] = p["equity0"] + p["ap0"] + p["def0"] + p["debt0"] - (p["cash0"] + p["ar0"] + p["inv0"] + p["ppe0"])
    p.update(over)
    return p


@pytest.fixture
def params():
    return make_params()
