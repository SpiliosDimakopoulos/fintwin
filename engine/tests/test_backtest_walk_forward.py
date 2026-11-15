"""Backtest orchestration on a small synthetic company: the score table, series and cross-section that become
backtest.json. load_company and macro_quarterly are replaced, so nothing reads the network or the cache."""

import numpy as np
import pandas as pd
import pytest
from test_B1_parity import synthetic_company

from fintwin.backtest import walk_forward as W
from fintwin.data.facts import CompanyData

CUTOFF = "pre_covid"  # 2020-02-20: the history ends 2019-12-31, the realized quarters start 2020-03-31
HORIZON = 4
VARS = {"revenue", "cash_like", "total_debt"}


def quarters(n: int, seed: int = 0) -> pd.DataFrame:
    """n quarters from 2010-03-31; 48 reach 2021-12-31."""
    return synthetic_company(n=n, seed=seed).quarters


def company(q: pd.DataFrame, asof: str | None = None) -> CompanyData:
    return CompanyData(
        "TEST", 1, "Synthetic", asof, q, {}, [200.0, 180.0, 160.0, 150.0, 140.0, 600.0], str(q.index[-1].date())
    )


@pytest.fixture
def serve(monkeypatch, macro):
    """Serve a quarter table (or a dict of them by ticker): with asof the history known then, else everything."""

    def install(full):
        def load(ticker, asof=None):
            q = full[ticker] if isinstance(full, dict) else full
            if asof is None:
                return company(q)
            return company(q[q.index <= pd.Timestamp(asof) - pd.Timedelta(days=45)], asof)

        monkeypatch.setattr(W, "load_company", load)
        monkeypatch.setattr(W, "macro_quarterly", lambda asof=None: macro)

    return install


def _run(**kw):
    return W.forecast_backtest("TEST", CUTOFF, horizon=HORIZON, n_paths=200, **kw)


def test_forecast_backtest_score_table(serve):
    serve(quarters(48))
    res = _run()
    assert res["horizon"] == HORIZON and res["last_quarter_known"] == "2019-12-31"
    assert set(res["scores"]) == VARS and set(res["series"]) == VARS
    for var, sc in res["scores"].items():
        assert sc["n"] == HORIZON, var
        for k in ("coverage50", "coverage90", "stress_coverage90"):
            assert 0.0 <= sc[k] <= 1.0, (var, k)
        assert len(sc["pit"]) == sc["n"] and all(0.0 <= x <= 1.0 for x in sc["pit"])
        assert sc["crps"] >= 0 and np.isfinite(sc["crps_skill"])
        assert len(res["series"][var]["base_bands"]) == 5
    realized = res["series"]["revenue"]["realized"]
    assert realized["dates"][0] == "2020-03-31" and len(realized["values"]) == HORIZON
    assert set(res["pre_shock"]) == {"base", "stress"}


def test_a_realized_quarter_with_unreported_cash_is_skipped_not_scored(serve):
    q = quarters(48)
    q.loc[pd.Timestamp("2020-06-30"), "cash"] = np.nan  # second realized quarter
    serve(q)
    res = _run()
    assert res["scores"]["cash_like"]["n"] == HORIZON - 1
    assert res["scores"]["revenue"]["n"] == HORIZON
    values = res["series"]["cash_like"]["realized"]["values"]
    assert values[1] is None and sum(v is not None for v in values) == HORIZON - 1


def test_realized_window_stops_at_a_missing_revenue_quarter(serve):
    q = quarters(48)
    q.loc[pd.Timestamp("2020-09-30"), "revenue"] = np.nan  # third realized quarter
    serve(q)
    res = _run()
    assert res["horizon"] == 2
    assert all(sc["n"] == 2 for sc in res["scores"].values())


def test_realized_series_shorter_than_the_horizon(serve):
    serve(quarters(42))  # history to 2019-12-31 plus two realized quarters
    res = W.forecast_backtest("TEST", CUTOFF, horizon=8, n_paths=200)
    assert res["horizon"] == 2
    assert all(sc["n"] == 2 for sc in res["scores"].values())
    assert len(res["structural"]["dates"]) == 2


def test_crps_skill_survives_a_perfect_baseline(serve, monkeypatch):
    serve(quarters(48))
    monkeypatch.setattr(W, "crps_gaussian", lambda mu, sd, y: 0.0)
    sc = _run()["scores"]["revenue"]
    assert sc["crps_baseline"] == 0.0 and np.isfinite(sc["crps_skill"]) and sc["crps_skill"] < 0


def test_structural_backtest_stops_at_the_first_missing_cash_flow(serve):
    q = quarters(48)
    q.loc[pd.Timestamp("2020-09-30"), "cfo"] = np.nan
    serve(q)
    s = _run()["structural"]
    assert s["dates"] == ["2020-03-31", "2020-06-30"]
    assert len(s["actual_cum_fcf"]) == 2 and len(s["model_cum_fcf_bands"]) == 5


def test_structural_backtest_is_empty_without_realized_cash_flow(serve):
    q = quarters(48)
    q.loc[q.index > pd.Timestamp("2020-01-15"), "cfo"] = np.nan
    serve(q)
    assert _run()["structural"] == {}


def test_cross_section_ranks_and_reports_failures(serve):
    holed = quarters(48, seed=4)
    holed.loc[pd.Timestamp("2020-09-30"), "cfo"] = np.nan  # a hole in the 2020-21 cash flows
    gap = quarters(48, seed=5).drop(pd.Timestamp("2019-06-30"))  # not four consecutive quarters before the cutoff
    serve(
        {
            "AAA": quarters(48, seed=1),
            "BBB": quarters(48, seed=2),
            "CCC": quarters(48, seed=3),
            "HOLE": holed,
            "GAP": gap,
        }
    )
    res = W.cross_section(["AAA", "BBB", "CCC", "HOLE", "GAP", "NOPE"], n_paths=200)
    assert [r["ticker"] for r in res["rows"]] == ["AAA", "BBB", "CCC"]
    assert res["failed"]["HOLE"].startswith("missing cash-flow quarter")
    assert res["failed"]["GAP"].startswith("no four consecutive quarters")
    assert res["failed"]["NOPE"].startswith("KeyError")
    for r in res["rows"]:
        assert 0 <= r["health_stress"] <= r["health_base"] <= 100
        assert 0 <= r["p_breach_stress"] <= 1
    st = res["stats"]["health_stress__realized_min_cum_fcf_pct_rev"]
    assert st["n"] == 3 and -1 <= st["spearman"] <= 1
