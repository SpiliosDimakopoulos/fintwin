import os
import socket

import numpy as np
import pandas as pd
import pytest
from hypothesis import settings

import fintwin.stochastic.calibrate as calibrate_mod

# Small bootstraps in tests: the research defaults (B = 10,000 for the test family) take minutes.
os.environ.setdefault("FINTWIN_B_FAMILY", "200")
os.environ.setdefault("FINTWIN_B_LAD", "20")
os.environ.setdefault("FINTWIN_B_HOLM", "200")

# CI runs the property tests on a fixed example sequence (HYPOTHESIS_PROFILE=ci), so a failure reproduces anywhere.
settings.register_profile("ci", derandomize=True)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "default"))

_SWITCHES = (
    "FINTWIN_SPEC",
    "FINTWIN_FIXES",
    "FINTWIN_SELECTION",
    "FINTWIN_MA_HINDSIGHT",
    "FINTWIN_POOL",
    "FINTWIN_TEXT",
    "FINTWIN_CASH_TARGET",
    "FINTWIN_POOL_ONLY",
    "FINTWIN_TEXT_VARIANT",
    "FINTWIN_SELECTION_DIGEST",
    "FINTWIN_TEXT_MIN_TRAIN",
    "FINTWIN_DATA_LEGACY",
    "FINTWIN_FROZEN",
    "FINTWIN_FILL_ONLY",
)
_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "slow: bootstrap, Monte Carlo or stats-pipeline tests (deselect with -m 'not slow')"
    )
    config.addinivalue_line("markers", "network: the test may open a network connection")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """The specification switches come from the test, never from the developer's shell."""
    for k in _SWITCHES:
        monkeypatch.delenv(k, raising=False)


@pytest.fixture(autouse=True)
def _no_network(request, monkeypatch):
    """A test that forgets to patch requests fails here instead of calling SEC or FRED (loopback stays open)."""
    if request.node.get_closest_marker("network"):
        return
    real_connect, real_connect_ex = socket.socket.connect, socket.socket.connect_ex

    def guard(real):
        def wrapper(self, address, *a):
            if self.family in (socket.AF_INET, socket.AF_INET6) and address[0] not in _LOCAL_HOSTS:
                raise RuntimeError(f"test tried to open a network connection to {address!r}")
            return real(self, address, *a)

        return wrapper

    monkeypatch.setattr(socket.socket, "connect", guard(real_connect))
    monkeypatch.setattr(socket.socket, "connect_ex", guard(real_connect_ex))


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


@pytest.fixture
def macro(monkeypatch):
    """Stub the NBER/GDP regime and return a quarterly rate frame, so calibration runs offline."""
    gdp = pd.Series(0.05 + 0.01 * np.sin(np.arange(80) / 3), index=pd.date_range("2005-03-31", periods=80, freq="QE"))
    monkeypatch.setattr(
        calibrate_mod,
        "recession_regime",
        lambda asof=None: {
            "hazard": 0.045,
            "exit": 0.24,
            "gdp_shortfall_q": 0.01,
            "in_recession_now": False,
            "gdp_yoy": gdp,
            "n_recessions": 12,
        },
    )
    idx = pd.date_range("2000-03-31", "2025-12-31", freq="QE")
    return pd.DataFrame(
        {"short_rate": 0.02 + 0.01 * np.sin(np.arange(len(idx)) / 8), "long_rate": 0.035, "credit_spread": 0.02},
        index=idx,
    )
