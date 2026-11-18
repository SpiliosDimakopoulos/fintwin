"""REVISION_PLAN_5: outcome corrections O1-O4 (every spec), real-time recession dates G2 and the G6 hindsight flag."""

import numpy as np
import pandas as pd
import pytest
from conftest import make_params
from test_C2_synth import quarters, split

from fintwin.data import fred
from fintwin.research import experiments as X

CUT = "2018-02-15"


# ------------------------------------------------------------------------------------------------ O1 dividends
def _untag(q: pd.DataFrame, cols: tuple[str, ...], idx: list[int]) -> pd.DataFrame:
    q = q.copy()
    q.loc[q.index[idx], list(cols)] = np.nan
    return q


def _first_outcome(full: pd.DataFrame, hist) -> int:
    return int(full.index.get_loc(hist.quarters.index[-1])) + 1


def test_o1_untagged_outcome_dividend_is_missing_not_a_cut(monkeypatch):
    q = quarters()
    hist, full = split(q, CUT)
    k = _first_outcome(full, hist)
    full = _untag(full, ("dividends",), [k, k + 1, k + 2])  # three of the four post quarters untagged
    fails = X.Failures()
    d = X._distress(hist, full, fails=fails)
    assert d["div_payer"] is True and d["div_cut"] is None
    assert fails.d["outcome"]["skipped"] == {"div_post_untagged": 1}
    assert fails.by_cutoff()["outcome"][CUT]["skipped"] == {"div_post_untagged": 1}
    st = X.structural(hist, {**make_params(), "sector_tol": 1.0}, full, None, fails=fails)
    assert st["events"]["div_cut"] is None and st["realized_cont"]["div_ratio"] is None
    assert fails.d["structural"]["skipped"]["div_post_untagged"] == 1
    monkeypatch.setenv("FINTWIN_DATA_LEGACY", "1")
    assert X._distress(hist, full)["div_cut"] is True  # the zero-fill read three untagged quarters as a cut


def test_o1_untagged_pre_dividend_leaves_run_rate_unknown():
    q = quarters()
    hist, full = split(q, CUT)
    hist.quarters.loc[hist.quarters.index[-2], "dividends"] = np.nan
    fails = X.Failures()
    d = X._distress(hist, full, fails=fails)
    assert d["div_payer"] is None and d["div_cut"] is None
    st = X.structural(hist, {**make_params(), "sector_tol": 1.0}, full, None, fails=fails)
    assert "static" not in st and st["events"]["div_cut"] is None
    assert fails.d["static"]["skipped"] == {"div_pre_untagged": 1}
    assert fails.d["outcome"]["skipped"] == {"div_pre_untagged": 1}


def test_o1_never_tagged_dividends_mean_a_non_payer():
    q = _untag(quarters(), ("dividends",), list(range(48)))
    hist, full = split(q, CUT)
    fails = X.Failures()
    d = X._distress(hist, full, fails=fails)
    assert d["div_payer"] is False and d["div_cut"] is False
    st = X.structural(hist, {**make_params(), "sector_tol": 1.0}, full, None, fails=fails)
    assert st["events"]["div_cut"] is None and st["static"]["div_pressure"] == 0.0  # payout run-rate 0, not unknown
    assert "outcome" not in fails.d or not fails.d["outcome"]["skipped"]


def test_o1_identical_across_specs(monkeypatch):
    hist, full = split(quarters(), CUT)
    k = _first_outcome(full, hist)
    full = _untag(full, ("dividends",), [k])
    out = {}
    for s in ("v3", "v4a", "v4t"):
        monkeypatch.setenv("FINTWIN_SPEC", s)
        out[s] = X._distress(hist, full)
    assert out["v3"] == out["v4a"] == out["v4t"] and out["v3"]["div_cut"] is None


# ------------------------------------------------------------------------------------------------ O2 / O4 counts
def test_o2_o4_counts_by_cutoff_and_company():
    a, b = X.Failures(), X.Failures()
    a.tried("calibrate", "2018-02-15")
    a.fail("calibrate", ValueError("x"), "2018-02-15")
    a.skip("outcome", "gap", "2018-02-15")
    b.tried("calibrate", "2019-02-15")
    b.skip("outcome", "gap", "2019-02-15")
    s = X.failure_summary(
        [
            {"cik": 1, "failures": a.to_dict(), "failures_by_cutoff": a.by_cutoff()},
            {"cik": 2, "failures": b.to_dict(), "failures_by_cutoff": b.by_cutoff()},
        ]
    )
    assert s["calibrate"]["n"] == 2 and s["calibrate"]["failed"] == {"ValueError": 1}
    assert s["calibrate"]["companies"] == 1
    assert s["calibrate"]["by_cutoff"]["2018-02-15"]["failed"] == {"ValueError": 1}
    assert s["outcome"]["by_cutoff"] == {
        "2018-02-15": {"n": 0, "failed": {}, "skipped": {"gap": 1}},
        "2019-02-15": {"n": 0, "failed": {}, "skipped": {"gap": 1}},
    }
    assert a.d["calibrate"] == {"n": 1, "failed": {"ValueError": 1}, "skipped": {}}  # stage shape unchanged


# ------------------------------------------------------------------------------------------------ O3 deflator
def test_o3_deflator_is_monotone_and_rebased_to_2014():
    early, base, late = (fred.deflator_to_2014(a) for a in ("2013-02-15", "2015-03-15", "2025-02-15"))
    assert early > 1.0 > late and base == pytest.approx(1.0, abs=0.02)
    cuts = [fred.deflator_to_2014(f"{y}-02-15") for y in range(2013, 2026)]
    assert all(x >= y for x, y in zip(cuts, cuts[1:], strict=False))  # prices only rose over 2012-2024
    with pytest.raises(ValueError):
        fred.deflator_to_2014("1940-01-01")


def test_o3_deflator_respects_publication_lag():
    # 2018Q4 (quarter end 2018-12-31) is published 60 days later: not yet usable on 15 Feb 2019
    d = fred._deflator()
    assert fred.deflator_to_2014("2019-02-15") == pytest.approx(
        float(d[d.index.year == 2014].mean()) / float(d[pd.Timestamp("2018-09-30")])
    )


def test_o3_ohlson_size_uses_deflated_assets(monkeypatch):
    hist, _ = split(quarters(), CUT)
    p = make_params()
    monkeypatch.setattr(X, "deflator_to_2014", lambda asof: 1.0)
    o_nominal = X.features(hist, p)["o_score"]
    monkeypatch.setattr(X, "deflator_to_2014", lambda asof: 0.5)
    o_half = X.features(hist, p)["o_score"]
    assert o_half - o_nominal == pytest.approx(-0.407 * np.log(0.5))  # smaller real size, higher O-score
    monkeypatch.setenv("FINTWIN_DATA_LEGACY", "1")
    assert X.features(hist, p)["o_score"] == pytest.approx(o_nominal)


# ------------------------------------------------------------------------------------------------ G2
@pytest.fixture
def nber(monkeypatch):
    """Monthly USREC 2000-2022 with the final NBER dating (2001-04..11, 2008-01..2009-06, 2020-03..04)."""
    months = pd.date_range("2000-01-01", "2022-12-01", freq="MS")
    rec = pd.Series(0.0, index=months)
    for a, b in (("2001-04-01", "2001-11-01"), ("2008-01-01", "2009-06-01"), ("2020-03-01", "2020-04-01")):
        rec[a:b] = 1.0
    qs = pd.date_range("2000-01-01", "2022-10-01", freq="QS")
    gdp = pd.Series(100 * np.exp(0.01 * np.arange(len(qs))), index=qs)
    series = {"USREC": rec / 100.0, "GDP": gdp / 100.0}
    monkeypatch.setattr(fred, "fred_series", lambda sid, max_age_hours=24: series[sid])
    monkeypatch.setattr(fred, "gdp_vintage", lambda asof: None)


def test_g2_realtime_recession_at_2021_cutoff(nber, monkeypatch):
    monkeypatch.setenv("FINTWIN_SPEC", "v4a")
    g2 = fred.recession_regime("2021-02-15")
    # the April 2020 trough was announced on 2021-07-19: on 15 Feb 2021 the recession is still running
    assert g2["in_recession_now"] is True
    # 84 quarters 2000Q1-2020Q4; recession quarters 3 (2001) + 6 (2008-09) + 4 (2020Q1-Q4 in real time)
    assert g2["n_recessions"] == 3
    assert g2["hazard"] == pytest.approx(3 / (84 - 13)) and g2["exit"] == pytest.approx(3 / 13)
    monkeypatch.setenv("FINTWIN_SPEC", "v3")
    v3 = fred.recession_regime("2021-02-15")
    assert v3["in_recession_now"] is False  # today's series, cut at the cutoff (unchanged)
    assert v3["hazard"] == pytest.approx(3 / (84 - 11)) and v3["exit"] == pytest.approx(3 / 11)
    assert v3["gdp_shortfall_q"] != g2["gdp_shortfall_q"]  # the shortfall also uses the real-time quarters
    assert fred.recession_regime("2021-02-15", realtime=False)["hazard"] == v3["hazard"]


def test_g2_after_the_trough_announcement_matches_the_final_dating(nber, monkeypatch):
    monkeypatch.setenv("FINTWIN_SPEC", "v4a")
    g2 = fred.recession_regime("2022-02-15")
    v3 = fred.recession_regime("2022-02-15", realtime=False)
    assert g2["in_recession_now"] is False and g2["hazard"] == v3["hazard"] and g2["exit"] == v3["exit"]
    # between the 2007-12 peak and its announcement (2008-12-01) the economy is still in expansion in real time
    assert fred.recession_regime("2008-10-15")["in_recession_now"] is False
    assert fred.recession_regime("2008-10-15", realtime=False)["in_recession_now"] is True
    # between the 2009-06 trough and its announcement (2010-09-20) the recession is still running
    assert fred.recession_regime("2010-02-15")["in_recession_now"] is True


def test_g2_turning_point_table_has_one_source():
    assert X.NBER_ANNOUNCED is fred.NBER_ANNOUNCED
    known = {(d, k): a for d, k, a in fred.NBER_ANNOUNCED}
    assert known[("2007-12-01", "peak")] == "2008-12-01" and known[("2009-06-01", "trough")] == "2010-09-20"
    assert known[("2020-02-01", "peak")] == "2020-06-08" and known[("2020-04-01", "trough")] == "2021-07-19"
    assert [d for d, _, _ in fred.NBER_ANNOUNCED] == sorted(d for d, _, _ in fred.NBER_ANNOUNCED)


# ------------------------------------------------------------------------------------------------ G6 hindsight
def _frame(n: int = 12) -> pd.DataFrame:
    idx = pd.date_range("2016-03-31", periods=n, freq="QE")
    return pd.DataFrame({"revenue": np.full(n, 100.0), "assets": np.full(n, 1000.0)}, index=idx)


def test_g6_hindsight_rule_on_outcome_quarters():
    f = _frame()
    pre, nxt = f.iloc[:4], f.iloc[4:]
    assert X.ma_hindsight_flag(pre, nxt) == {"flag": 0.0, "legs": ["size_jump"]}
    f2 = f.copy()
    f2.loc[f2.index[6:], ["revenue", "assets"]] *= 1.3  # both jump 30% in the same quarter
    assert X.ma_hindsight_flag(f2.iloc[:4], f2.iloc[4:])["flag"] == 1.0
    f3 = f.copy()
    f3.loc[f3.index[6:], "revenue"] *= 1.3  # revenue alone: no flag
    assert X.ma_hindsight_flag(f3.iloc[:4], f3.iloc[4:])["flag"] == 0.0
    f4 = f.assign(acquisitions=np.nan, divestitures=np.nan)
    f4.loc[f4.index[7], "acquisitions"] = 41.0  # > 10% of trailing revenue 400
    r = X.ma_hindsight_flag(f4.iloc[:4], f4.iloc[4:])
    assert r["flag"] == 1.0 and r["legs"] == ["acquisitions", "divestitures", "size_jump"]
    f4.loc[f4.index[7], "acquisitions"] = 39.0
    assert X.ma_hindsight_flag(f4.iloc[:4], f4.iloc[4:])["flag"] == 0.0
    f4.loc[f4.index[2], "acquisitions"] = 500.0  # before the cutoff: the ex-ante flag's business, not this one
    assert X.ma_hindsight_flag(f4.iloc[:4], f4.iloc[4:])["flag"] == 0.0
    f4.loc[f4.index[9], "divestitures"] = 60.0
    assert X.ma_hindsight_flag(f4.iloc[:4], f4.iloc[4:])["flag"] == 1.0
    assert X.ma_hindsight_flag(pre, nxt.iloc[:0]) == {"flag": None, "legs": []}


def test_g6_hindsight_side_result_is_labelled_and_passes_ma_scale(monkeypatch):
    monkeypatch.setenv("FINTWIN_SPEC", "v4b")
    assert "-mahindsight" not in X.spec_label() and X.spec_record()["ma_hindsight"] is False
    monkeypatch.setenv("FINTWIN_MA_HINDSIGHT", "1")
    assert X.spec_label().endswith("-mahindsight") and X.spec_record()["ma_hindsight"] is True
    seen = []
    monkeypatch.setattr(X, "_calibrate", lambda c, m, h, a: seen.append(a) or {})
    monkeypatch.setattr(X, "spreads_asof", lambda asof: None)
    hist, _ = split(quarters(), CUT)
    with X._assume({"ma_scale": True}):
        X.calibrate(hist, pd.DataFrame())
    X.calibrate(hist, pd.DataFrame())
    assert seen[0]["ma_scale"] is True and "ma_scale" not in seen[1]


# ------------------------------------------------------------------------------------------------ shard records
def _patch_company(monkeypatch, q, calibrate):
    def load(ticker, asof=None, min_year=2010):
        return split(q, asof)[0] if asof else split(q, "2030-01-01")[0]

    monkeypatch.setattr(X, "load_company", load)
    monkeypatch.setattr(X, "data_vintage", lambda cik: {"facts_sha256": None})
    monkeypatch.setattr(X, "first_filed", lambda cik: {"revenue": pd.Series(dtype="datetime64[ns]")})
    monkeypatch.setattr(X, "credit_events", lambda cik: {"1.03": [], "2.04": [], "3.01": []})
    monkeypatch.setattr(X, "calibrate", calibrate)
    monkeypatch.setattr(X, "macro_quarterly", lambda asof=None: pd.DataFrame())
    monkeypatch.setattr(X, "SENSITIVITY", {})


def test_o4_calibration_failure_is_recorded_with_cutoff_and_company(monkeypatch):
    monkeypatch.setenv("FINTWIN_SPEC", "v4b")

    def boom(hist, macro, horizon=12, assumptions=None):
        raise ValueError("non-finite calibrated parameters")

    _patch_company(monkeypatch, quarters(), boom)
    res = X.company("CIK0000000001", with_forecasts=False, years={2018, 2019})
    assert res["panel"] == []
    assert res["calib_failures"] == [
        {"origin": o, "cik": 1, "type": "ValueError", "msg": "non-finite calibrated parameters"}
        for o in ("2018-02-15", "2019-02-15")
    ]
    assert res["failures"]["calibrate"] == {"n": 2, "failed": {"ValueError": 2}, "skipped": {}}
    assert res["failures"]["panel"]["failed"] == {"ValueError": 2}  # the panel stage counts it as before
    assert res["failures_by_cutoff"]["calibrate"]["2019-02-15"]["failed"] == {"ValueError": 1}


def test_g6_flags_are_stored_in_the_panel_row(monkeypatch):
    monkeypatch.setenv("FINTWIN_SPEC", "v4b")
    q = quarters()
    seen = []

    def cal(hist, macro, horizon=12, assumptions=None):
        seen.append(dict(X._EXTRA_ASSUMPTIONS.get() or {}))
        return {**make_params(), "horizon": horizon, "g6_flag": 0.0}

    k = int(q.index.get_loc(split(q, CUT)[0].quarters.index[-1])) + 3
    q.loc[q.index[k:], ["revenue", "assets"]] *= 1.4  # an acquisition-sized jump inside the outcome quarters
    _patch_company(monkeypatch, q, cal)
    row = X.company("CIK0000000001", with_forecasts=False, years={2018})["panel"][0]
    assert row["ma_flag"] == 0.0 and row["ma_flag_hindsight"] == 1.0 and row["ma_scale_hindsight"] is False
    assert seen[-1] == {}
    monkeypatch.setenv("FINTWIN_MA_HINDSIGHT", "1")
    row = X.company("CIK0000000001", with_forecasts=False, years={2018})["panel"][0]
    assert row["ma_scale_hindsight"] is True and seen[-1] == {"ma_scale": True}
