"""12-11-2026: quarters booked as 0 revenue gave a zero seasonal factor; v3 (MM-F3 divides by it) wrote None health and
forecast quantiles into shards, the stats dropped those units silently and calibration crashed on one NaN quantile."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest
from test_B1_parity import macro, synthetic_company  # noqa: F401  (fixture)

from fintwin.research import calibration
from fintwin.research import experiments as E
from fintwin.research import stats as S
from fintwin.stochastic import calibrate as C
from fintwin.stochastic import spec


@pytest.mark.parametrize("name", ["v2-pre", "v2-rev", "v3"])
def test_zero_revenue_quarters_are_an_error_in_every_spec(macro, name):  # noqa: F811
    c = synthetic_company()
    q = c.quarters
    q.loc[q.index.quarter != 1, "revenue"] = 0.0  # only Q1 reported, the other quarters booked as 0 (as in the data)
    with spec.using(name, None), pytest.raises(ValueError, match="zero revenue|degenerate seasonal"):
        C.calibrate(c, macro, 8)


def test_clean_company_still_calibrates(macro):  # noqa: F811
    with spec.using("v3", None):
        p = C.calibrate(synthetic_company(), macro, 8)
    assert all(s > 0 for s in p["seasonal"])


def test_finite_guard_raises_on_a_diverged_simulation():
    ok = {"cash": np.ones((3, 4)), "health": np.ones((3, 4))}
    assert E._finite(ok) is ok
    bad = {"cash": np.ones((3, 4)), "health": np.array([[1.0, np.nan, 1.0, 1.0]] * 3)}
    with pytest.raises(ValueError, match="non-finite simulation output"):
        E._finite(bad)


def _fc_rows(n_origins=6, per=30, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for k in range(n_origins):
        origin = pd.Timestamp(f"{2014 + k}-02-15")
        for i in range(per):
            y = float(rng.normal(100, 10))
            rows.append(
                {
                    "ticker": f"T{i}",
                    "var": "cash_like",
                    "h": 1,
                    "origin": str(origin.date()),
                    "target": str((origin + pd.Timedelta(days=45)).date()),
                    "y": y,
                    "scale": 25.0,
                    "q": [80.0, 93.0, 100.0, 107.0, 120.0],
                    "pit_twin": 0.5,
                }
            )
    return rows


def test_load_drops_forecasts_with_non_finite_quantiles(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "membership", lambda: {})
    monkeypatch.setattr(S, "bankruptcy_dates", lambda: {})
    monkeypatch.setattr(S, "bankruptcy_filings", lambda: {})
    rows = _fc_rows(1, 3)
    rows[1]["q"] = [80.0, None, None, None, None]
    (tmp_path / "T0.json").write_text(json.dumps({"ticker": "T0", "forecasts": rows}))
    _, _, fc, errors = S.load(tmp_path)
    assert len(fc) == 2 and "non-finite" in errors["T0"]["forecasts"]


def test_calibration_survives_one_nan_quantile():
    fc = pd.DataFrame(_fc_rows())
    fc.at[5, "q"] = [np.nan] * 5
    panel = pd.DataFrame(
        {
            "ticker": [f"T{i}" for i in range(30)] * 6,
            "year": np.repeat(range(2014, 2020), 30),
            "log_rev": 20.0,
            "nd_ebitda": 1.0,
            "rev_vol": 0.1,
            "industry": "X",
        }
    )
    rng = np.random.default_rng(1)
    for col in ("log_rev", "nd_ebitda", "rev_vol"):  # the width regression standardizes them: they must vary
        panel[col] = panel[col] + rng.normal(0, 0.1, len(panel))
    out = calibration.section(fc, panel)
    assert out["cash_like"]["n"] > 0 and np.isfinite(out["cash_like"]["conformal90"])
    assert set(out["cash_like"]["by"]["size"]) <= {"small", "mid", "large"}


def test_tertiles_of_an_all_missing_column_are_missing_not_an_error():
    assert calibration._tertiles(pd.Series([np.nan] * 5), ["a", "b", "c"]).isna().all()


@pytest.mark.parametrize("name", ["v2-pre", "v2-rev", "v3"])
def test_one_zero_revenue_quarter_in_the_window_is_an_error(macro, name):  # noqa: F811
    # one zero quarter leaves every seasonal factor > 0, so the factor check alone
    # passed and v2 / v3 forecast from a broken base (12-11 review: 33 firms in v3)
    c = synthetic_company()
    c.quarters.loc[c.quarters.index[-3], "revenue"] = 0.0
    with spec.using(name, None), pytest.raises(ValueError, match="zero revenue"):
        C.calibrate(c, macro, 8)


def test_realized_cash_like_treats_missing_short_investments_as_zero():
    from fintwin.backtest import batch

    idx = pd.date_range("2020-03-31", periods=12, freq="QE")
    full = pd.DataFrame({"cash": 10.0, "short_investments": np.nan, "revenue": 100.0}, index=idx)
    full.loc[idx[:2], "short_investments"] = 5.0
    r = batch._realized(full, idx[3], {}) if not batch.data_legacy() else None
    assert r is not None and r["cash_like"].notna().all()


def test_extreme_demand_draw_stays_finite(macro):  # noqa: F811
    from fintwin.model.sd_model import simulate
    from fintwin.scenarios.presets import DEFAULT_LEVERS, build_scenario
    from fintwin.stochastic.shocks import draw_shocks

    with spec.using("v3", None):
        p = C.calibrate(synthetic_company(), macro, 8)
    eps = draw_shocks(p, 50, 8, seed=1)
    eps[0, :, 0] = 1e4  # a demand draw far beyond any t tail: overflowed to inf before the floor
    out = simulate(p, build_scenario({}, 8), eps, DEFAULT_LEVERS)
    assert np.isfinite(out["revenue"]).all() and np.isfinite(out["cash"]).all()


def test_research_runs_refuse_an_unset_spec(monkeypatch):
    monkeypatch.setenv("FINTWIN_REQUIRE_SPEC", "1")
    monkeypatch.delenv("FINTWIN_SPEC", raising=False)
    with pytest.raises(RuntimeError, match="FINTWIN_SPEC is not set"):
        spec.spec()
    with pytest.raises(RuntimeError, match="FINTWIN_SPEC is not set"):
        E.spec_name()
    monkeypatch.setenv("FINTWIN_SPEC", "v3")
    assert spec.spec() == "v3" and E.spec_name() == "v3"
    with spec.using("v2-pre", None):  # an explicit override needs no env
        monkeypatch.delenv("FINTWIN_SPEC")
        assert spec.spec() == "v2-pre"
