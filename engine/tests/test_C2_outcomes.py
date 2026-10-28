"""C2: point forecast (E1), stored densities (E2), outcome gaps (D4, SW-4), features (SW-15), failure counts (SW-3),
filing dates (D10), the empirical random walk (E10) and the shortfall probability (E12)."""

import json

import numpy as np
import pandas as pd
import pytest
from conftest import make_params
from test_C2_synth import company, quarters, split

from fintwin.backtest import batch as B
from fintwin.backtest.scoring import crps_samples
from fintwin.model.sd_model import simulate
from fintwin.research import experiments as X
from fintwin.scenarios.presets import DEFAULT_LEVERS, build_scenario
from fintwin.stochastic.shocks import draw_shocks


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("FINTWIN_SPEC", "FINTWIN_FIXES", "FINTWIN_SELECTION", "FINTWIN_DATA_LEGACY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(X, "_spec_mod", None)


def _sim_totals(p, full, hist, var):
    """The structural design's paths, rebuilt independently: realized revenue fed in, 500 paths, seed 3."""
    nxt = full[full.index > hist.quarters.index[-1] + pd.Timedelta(days=20)].head(8)
    T = int(p["horizon"])
    scn = build_scenario({}, T)
    ov = np.full(T, np.nan)
    ov[:8] = nxt["revenue"].to_numpy(float)
    scn["revenue_override"] = ov
    sim = simulate(p, scn, draw_shocks(p, 500, T, seed=3), DEFAULT_LEVERS)
    rev_ttm = float(hist.quarters["revenue"].tail(4).sum())
    return sim[var][:, :8].sum(1) / rev_ttm * 100, nxt, rev_ttm


def test_e1_point_is_median_of_path_totals(monkeypatch):
    monkeypatch.setenv("FINTWIN_SPEC", "v3")
    hist, full = split(quarters(), "2018-02-15")
    p = {**make_params(sigma_m=0.05), "sector_tol": 1.0}
    st = X.structural(hist, p, full, None)
    tot, _, _ = _sim_totals(p, full, hist, "cfo")
    assert st["twin_cfo_tot"] == round(float(np.median(tot)), 4)
    assert st["e1"] and st["twin_cfo_point"] == st["twin_cfo_tot"]
    # the old estimator is kept as an extra key; it is a different number
    assert st["twin_cfo_sm"] == round(float(np.sum(st["twin_cfo"])), 4)
    assert st["twin_cfo_sm"] != st["twin_cfo_tot"]
    assert "twin_fcf_tot" in st and "noloops_cfo_tot" in st


def test_e2_density_of_totals_is_stored_compactly(monkeypatch):
    monkeypatch.setenv("FINTWIN_SPEC", "v3")
    hist, full = split(quarters(), "2018-02-15")
    p = {**make_params(sigma_m=0.05), "sector_tol": 1.0}
    st = X.structural(hist, p, full, None)
    tot, nxt, rev_ttm = _sim_totals(p, full, hist, "cfo")
    real = float(nxt["cfo"].sum()) / rev_ttm * 100
    d = st["dens"]["cfo"]
    assert len(d["q"]) == len(X.QLEVELS) == 21 and d["q"] == sorted(d["q"])
    assert d["crps"] == pytest.approx(crps_samples(tot, real), abs=1e-5)
    assert d["pit"] == pytest.approx(float(np.mean(tot <= real)), abs=1e-5)
    assert len(json.dumps(st["dens"])) < 800  # ~0.4 kB per firm-year for both variables


def test_d4_missing_outcome_quarter_is_not_zero_burn(monkeypatch):
    q = quarters()
    hist, full = split(q, "2018-02-15")
    full = full.copy()
    full.loc[full.index[34], "cfo"] = np.nan  # inside the eight outcome quarters
    d = X._distress(hist, full)
    assert d["burn8"] is None and d["cum8"] is None and d["abn_cum8"] is None and d["abn_burn8"] is None
    monkeypatch.setenv("FINTWIN_DATA_LEGACY", "1")
    legacy = X._distress(hist, full)
    assert legacy["burn8"] is not None and np.isfinite(legacy["cum8"])  # the old code counted it as zero


def test_sw4_dropped_quarter_breaks_positional_alignment(monkeypatch):
    q = quarters(drop=(35,))  # a quarter missing from the spine inside the outcome window
    hist, full = split(q, "2018-02-15")
    p = {**make_params(), "sector_tol": 1.0}
    fails = X.Failures()
    assert X.structural(hist, p, full, None, fails=fails) == {}
    assert fails.d["structural"]["skipped"] == {"gap_or_short": 1}
    assert X._distress(hist, full) == {}
    assert len(B._realized(full, pd.Timestamp("2018-09-30"))) == 0  # gap right after the cutoff's last quarter
    monkeypatch.setenv("FINTWIN_DATA_LEGACY", "1")
    assert X.structural(hist, p, full, None) != {}  # the old code silently compared the wrong quarters


def test_contiguous_prefix():
    idx = pd.DatetimeIndex(["2018-03-31", "2018-06-30", "2018-12-31", "2019-03-31"])
    assert B.contiguous_prefix(pd.Timestamp("2017-12-31"), idx) == 2
    assert B.contiguous_prefix(pd.Timestamp("2017-09-30"), idx) == 0
    # 52/53-week calendars drift a few days but stay one quarter apart
    wk = pd.DatetimeIndex(["2018-03-31", "2018-06-30", "2018-09-29", "2018-12-29"])
    assert B.contiguous_prefix(pd.Timestamp("2017-12-30"), wk) == 4


def test_ttm_and_usable_require_consecutive_quarters():
    q = quarters(drop=(44,))
    assert np.isnan(X._ttm(q.iloc[:46], "revenue"))  # 4 rows spanning 5 calendar quarters
    assert np.isfinite(X._ttm(q.iloc[:40], "revenue"))


def test_sw15_features_survive_zero_balance_items():
    q = quarters()
    q.loc[q.index[-1], ["current_liabilities", "assets"]] = 0.0
    f = X.features(company(q, "2022-02-15"), make_params())
    assert f["current_ratio"] is None and f["z2"] is None and f["debt_assets"] is None
    assert f["fcf_margin"] is not None


def test_sw3_forecast_failures_are_counted(monkeypatch):
    q = quarters(60)
    full = company(q)
    hists = {o: split(q, o)[0] for o in X.FORECAST_ORIGINS[2:5]}  # 16+ quarters of history from 2015

    def boom(*a, **k):
        raise ValueError("bad vintage")

    monkeypatch.setattr(X, "_forecast_origin", boom)
    fails = X.Failures()
    assert X.forecasts("T", full, hists, fails) == []
    assert fails.d["forecast"] == {"n": 3, "failed": {"ValueError": 3}, "skipped": {}}
    s = X.failure_summary([{"failures": fails.to_dict()}, {"failures": fails.to_dict()}])
    assert s["forecast"]["n"] == 6 and s["forecast"]["failed_share"] == 1.0


def test_sw3_ets_failures_and_skips_are_counted():
    fails = X.Failures()
    assert X._ets_samples(np.array([1.0, -1.0] * 10), 4, log=True, seasonal=True, fails=fails) is None
    assert X._ets_samples(np.ones(5), 4, log=False, seasonal=False, fails=fails) is None
    assert fails.d["ets"]["skipped"] == {"non_positive": 1, "short_series": 1} and fails.d["ets"]["n"] == 2


def test_e12_shortfall_counts_cash_plus_undrawn_below_zero():
    p = {"revolver_cap": 100.0}
    cash = np.array([[50.0, -10.0, 20.0, 5.0], [10.0, 10.0, 10.0, -1.0], [-5.0, 10.0, 10.0, 10.0]])
    rev = np.array([[0.0, 100.0, 0.0, 0.0], [100.0, 100.0, 100.0, 100.0], [100.0, 100.0, 100.0, 100.0]])
    sim = {"cash": cash, "revolver": rev}
    # path 1: -10 with the line fully drawn (undrawn 0) -> short; path 2 short in q4; path 3 short in q1
    assert X.shortfall(sim, p, 4) == 1.0
    assert X.shortfall(sim, p, 1) == pytest.approx(1 / 3)
    # a capacity path (e.g. a facility cut on breach) overrides the opening capacity
    sim["revolver_cap"] = np.full((3, 4), 200.0)
    assert X.shortfall(sim, p, 4) == 0.0


def test_e12_run_reports_shortfall_probabilities():
    p = {**make_params(cash0=30.0, revolver_cap=10.0, cash_floor=5.0, F=500.0), "sector_tol": 1.0}
    r = X._run(p, {"sales_depth": 0.5, "sales_duration": 4}, {}, 300, 12, 5)
    assert 0.0 <= r["short4"] <= r["short8"] <= 1.0
    assert r["short8"] > 0


def test_d10_filed_dates_and_seen_by(monkeypatch):
    facts = {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {"end": "2019-12-31", "filed": "2020-02-25", "form": "10-K", "val": 1, "accn": "a"},
                            {"end": "2019-12-31", "filed": "2021-02-20", "form": "10-K", "val": 1, "accn": "b"},
                            {"end": "2020-03-31", "filed": "2020-05-02", "form": "10-Q", "val": 1, "accn": "c"},
                            {"end": "2020-03-31", "filed": "2020-04-01", "form": "8-K", "val": 1, "accn": "d"},
                        ]
                    }
                }
            }
        }
    }
    import fintwin.data.facts as F

    monkeypatch.setattr(F, "company_facts", lambda cik: facts)
    filed = B.first_filed(1)["revenue"]
    assert B.filed_for(filed, pd.Timestamp("2019-12-28")) == "2020-02-25"  # first filing, not the restatement
    assert B.filed_for(filed, pd.Timestamp("2020-03-31")) == "2020-05-02"  # 8-K values do not count
    assert B.filed_for(filed, pd.Timestamp("2020-06-30")) is None
    target = pd.Series(pd.to_datetime(["2019-12-31", "2020-03-31", "2020-06-30"]))
    filed_s = pd.Series(["2020-04-10", "2020-05-02", None])
    # a 10-K filed 101 days after year end is not seen 95 days after it, which the fixed 90-day lag would assume
    seen = B.seen_by(target, filed_s, pd.Timestamp("2020-04-05"))
    assert seen.tolist() == [False, False, False]
    assert B.seen_by(target, None, pd.Timestamp("2020-04-05")).tolist() == [True, False, False]
    monkeypatch.setenv("FINTWIN_DATA_LEGACY", "1")
    assert B.seen_by(target, filed_s, pd.Timestamp("2020-04-05")).tolist() == [True, False, False]


def test_d10_conformal_uses_actual_filing_dates():
    from fintwin.research.calibration import _norm, conformal

    rows = []
    for o in range(2014, 2017):
        for i in range(50):
            rows.append(
                {
                    "origin": f"{o}-02-15",
                    "target": f"{o}-06-30",
                    "filed": f"{o + 1}-03-01",  # reported late: not usable at the next origin's 15 Feb
                    "y": 1.0 + i,
                    "q": [0.0, 1.0, 2.0, 3.0, 4.0],
                    "pit_twin": 0.5,
                    "ticker": f"T{i}",
                    "scale": 1.0,
                }
            )
    d = conformal(_norm(pd.DataFrame(rows)))
    assert sorted(d["year"].unique()) == [2016]  # 2015 has no past target reported by 15 Feb 2015
    no_filed = conformal(_norm(pd.DataFrame(rows).drop(columns="filed")))
    assert sorted(no_filed["year"].unique()) == [2015, 2016]  # the 90-day rule thinks they were reported


def test_e10_empirical_random_walk_density():
    q = quarters(40)
    emp = B.rw_empirical(q, "revenue", 2)
    s = q["revenue"]
    yoy = np.log(s / s.shift(4)).dropna().tail(20).to_numpy()
    assert np.allclose(np.sort(emp), np.sort(s.iloc[-3] * np.exp(yoy)))
    cash = B.rw_empirical(q, "cash_like", 3)
    assert np.allclose(cash, 400 + 5.0 * 39 + 15.0)
    assert B.rw_empirical(q.iloc[:6], "revenue", 1) is None


def test_e10_skill_and_dm_by_horizon():
    rng = np.random.default_rng(0)
    rows = []
    for h in (1, 2):
        for i in range(200):
            rows.append(
                {
                    "h": h,
                    "ticker": f"T{i % 40}",
                    "crps_reg": 1.0 + (0.3 if h == 2 else -0.3) + 0.1 * rng.standard_normal(),
                    "crps_baseline": 1.0,
                    "crps_baseline_emp": 1.0,
                }
            )
    s = B.skill_by_horizon(pd.DataFrame(rows))
    assert s[1]["crps_baseline"]["skill"] > 0 > s[2]["crps_baseline"]["skill"]  # pooled they would cancel out
    assert s[1]["crps_baseline"]["dm"]["p"] < 0.01 and s[1]["crps_baseline"]["dm"]["clusters"] == 40
