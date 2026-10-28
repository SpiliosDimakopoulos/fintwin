"""CR: code-review fixes in the backtests, the research statistics and the calibration's trailing windows."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest
from test_B1_parity import macro, synthetic_company  # noqa: F401  (fixture)
from test_C2_synth import quarters, split

from fintwin.backtest import batch as B
from fintwin.backtest import walk_forward as W
from fintwin.research import assumption_sobol as AS
from fintwin.research import experiments as X
from fintwin.research import stats as S
from fintwin.stochastic import calibrate as C
from fintwin.stochastic import spec


@pytest.fixture(autouse=True)
def _new_data(monkeypatch):
    monkeypatch.delenv("FINTWIN_DATA_LEGACY", raising=False)


def _flags(q: pd.DataFrame) -> pd.DataFrame:
    q = q.copy()
    q["gap"] = False
    q["fye_break"] = False
    return q


# ---------------------------------------------------------------- 1: fye_break on the first outcome quarter
def test_following_rejects_a_fiscal_year_break_on_the_first_outcome_quarter():
    full = _flags(quarters())
    last = full.index[30]
    assert B.following(full, last, 4)[1] is None
    full.loc[full.index[31], "fye_break"] = True  # days uncovered between `last` and the first outcome quarter
    nxt, why = B.following(full, last, 4)
    assert why == "gap" and nxt.empty
    assert len(W._realized(full, last, 4)) == 0
    full.loc[full.index[31], "fye_break"] = False
    full.loc[full.index[33], "fye_break"] = True  # a break later in the window: walk_forward keeps the run before it
    assert B.following(full, last, 4)[1] == "gap"
    assert list(W._realized(full, last, 4).index) == list(full.index[31:33])


def test_usable_prefix_matches_the_following_loop():
    full = _flags(quarters())
    full.loc[full.index[34], ["revenue"]] = np.nan
    last = full.index[30]
    k = B.usable_prefix(full[full.index > last + pd.Timedelta(days=20)].head(8), last)
    loop = 8
    while loop and B.following(full, last, loop)[1] is not None:
        loop -= 1
    assert k == loop == 3


# ---------------------------------------------------------------- 2: one all-NaN forecaster
def _boot(loss: np.ndarray, b: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    g = np.random.default_rng(seed)
    n = len(loss)
    star = np.array([loss[g.integers(0, n, n)].mean(axis=0) for _ in range(b)])
    return loss.mean(axis=0), star


def test_mcs_stepm_spa_survive_an_all_nan_column():
    g = np.random.default_rng(3)
    loss = g.normal(0, 1, (600, 4)) + np.array([0.0, 0.0, 0.6, 0.0])
    loss[:, 3] = np.nan  # a forecaster that never produced a forecast
    L, star = _boot(loss, 800, 4)
    assert np.isnan(L[3]) and np.isnan(star[:, 3]).all()
    res = S.mcs(L, star, list("abcd"))
    assert res["B"] == 800 and "c" not in res["included"] and {"a", "b"} <= set(res["included"])
    assert "d" not in res["p_mcs"]
    rw = S.stepm(L[:3] - L[0], star[:, :3] - star[:, [0]], side="greater")  # reference without the NaN column
    rw_nan = S.stepm(L - L[0], star - star[:, [0]], side="greater")
    assert rw_nan["B"] == 800 and np.isnan(rw_nan["p_adj"][3])
    np.testing.assert_allclose(rw_nan["p_adj"][:3], rw["p_adj"], equal_nan=True)
    sp = S.spa(L[2] - L, star[:, [2]] - star, 600)
    assert sp["B"] == 800 and sp["p_consistent"] < 0.05  # a and b beat c


# ---------------------------------------------------------------- 3: lags on the calendar, not across gap rows
def _gapped(n: int = 40, gap_at: int = 30) -> pd.DataFrame:
    t = np.arange(n)
    q = pd.DataFrame(
        {
            "revenue": 1000.0 * np.exp(0.02 * t) * (1 + 0.1 * np.sin(t * np.pi / 2)),
            "cash": 500.0 + 10.0 * t + 15.0 * (t % 3),
            "short_investments": np.zeros(n),
        },
        index=pd.date_range("2012-03-31", periods=n, freq="QE"),
    )
    q["gap"] = False
    q.loc[q.index[gap_at], "gap"] = True
    q.loc[q.index[gap_at], "revenue"] = np.nan
    q.loc[q.index[gap_at], "cash"] = q["cash"].iloc[gap_at - 1]  # carried forward by the data layer
    return q


def test_random_walk_baselines_lag_by_calendar_quarter(monkeypatch):
    q = _gapped()
    r = q["revenue"]
    yoy = np.log(r / r.shift(4)).dropna().tail(20).to_numpy()  # never pairs quarters 5 calendar quarters apart
    same = float(r.dropna().iloc[-4])
    np.testing.assert_allclose(B.rw_empirical(q, "revenue", 1), same * np.exp(yoy))
    assert B._baseline(q, "revenue", 1)[1] == pytest.approx(same * float(pd.Series(yoy).std()))
    c = q["cash"].where(~q["gap"])
    d = c.diff(2).dropna().tail(20).to_numpy()
    np.testing.assert_allclose(B.rw_empirical(q, "cash", 2), c.iloc[-1] + d)
    assert B._baseline(q, "cash", 1)[1] == pytest.approx(float(c.diff().dropna().tail(20).std()))
    assert W._baseline(q, "cash_like", 1)[1] == pytest.approx(float(c.diff().dropna().tail(20).std()))
    # legacy: positional, as in revision 2
    monkeypatch.setenv("FINTWIN_DATA_LEGACY", "1")
    s = q["revenue"].dropna()
    old = np.log(s / s.shift(4)).dropna().tail(20).to_numpy()
    np.testing.assert_allclose(B.rw_empirical(q, "revenue", 1), same * np.exp(old))
    assert not np.allclose(old, yoy)


# ---------------------------------------------------------------- 4, 5: calibration on the revision-3 data layer
def _layer(c, gap_back: int):
    q = c.quarters
    q["gap"] = False
    q["da_missing"] = False
    q["da_annual"] = np.nan
    g = q.index[-gap_back]
    flows = ["revenue", "operating_income", "da", "net_income", "tax", "cfo", "capex", "sbc", "dividends", "buybacks"]
    q.loc[g, flows] = np.nan
    q.loc[g, "gap"] = True
    c.imputed = pd.DataFrame(False, index=q.index, columns=q.columns)
    return c


def _cal(c, macro):  # noqa: F811
    with spec.using("v2-pre"):
        return C.calibrate(c, macro, 8)


def test_trailing_windows_are_contiguous_and_annualized(macro):  # noqa: F811
    c = _layer(synthetic_company(seed=21), gap_back=3)  # gap 3 rows back: a 2-quarter run ends at the cutoff
    q = c.quarters
    p = _cal(c, macro)
    run = q.tail(2)
    for key, col in (("ebit_ttm0", "operating_income"), ("interest_ttm0", "interest_expense")):
        x = run[col].to_numpy()
        assert p[key] == pytest.approx([x.mean(), x.mean(), *x])
    assert "x 4/2" in p["_sources"]["trailing"]
    assert p["revolver_cap"] == pytest.approx(C.ASSUMPTIONS["revolver_share"] * 2 * run["revenue"].sum())
    ok = _cal(_layer(synthetic_company(seed=21), gap_back=10), macro)  # the last 8 are consecutive: unchanged
    assert "trailing" not in ok["_sources"]
    assert ok["ebit_ttm0"] == pytest.approx(synthetic_company(seed=21).quarters["operating_income"].tail(4).tolist())
    for v in p.values():
        if isinstance(v, float):
            assert np.isfinite(v)


def test_staleness_counts_from_the_last_reported_value(macro):  # noqa: F811
    c = _layer(synthetic_company(seed=22), gap_back=12)
    q = c.quarters
    # inventory reported last 5 rows back, carried forward by the data layer into the next two rows
    q.loc[q.index[-4:], "inventory"] = np.nan
    q.loc[q.index[-5:-3], "inventory"] = q["inventory"].iloc[-6]
    c.imputed.loc[q.index[-5:], "inventory"] = True
    when = q.index[-6].date()
    last, notes = C._last_known(q, ("inventory",), C.STALE_ROWS, c.imputed)
    assert last["inventory"] == 0.0 and any(f"last reported {when}" in n for n in notes)
    old, _ = C._last_known(q, ("inventory",), C.STALE_ROWS)
    assert old["inventory"] == pytest.approx(q["inventory"].iloc[-4])  # the old rule counted from the carried row
    # within the limit: same value, the note gives the genuine report date
    c.imputed.loc[q.index[-5:-3], "inventory"] = False
    last, notes = C._last_known(q, ("inventory",), C.STALE_ROWS, c.imputed)
    assert last["inventory"] == pytest.approx(q["inventory"].iloc[-4]) and f"from {q.index[-4].date()}" in notes[0]
    assert "inventory" in _cal(c, macro)["_sources"]["stale"]


# ---------------------------------------------------------------- 6, 7, 8: attempts, exclusion reasons, one switch
def test_outcome_stages_count_attempts():
    hist, full = split(quarters(), "2018-02-15")
    fails = X.Failures()
    X._distress(hist, full, fails=fails)
    X.covid_outcomes(hist, full, fails)
    X.structural(hist, {}, full.iloc[:1], None, fails=fails)  # no outcome quarters: excluded as "short"
    for where in ("outcome", "covid_outcomes", "structural"):
        assert fails.d[where]["n"] == 1
    assert fails.d["structural"]["skipped"] == {"short": 1}
    assert X.failure_summary([{"failures": fails.d}])["structural"]["n"] == 1


def test_sobol_shard_separates_exclusions_from_exceptions(monkeypatch, tmp_path):
    monkeypatch.setattr(AS, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(AS, "points", lambda: np.zeros((1, 1)))
    monkeypatch.setattr(AS, "sample", lambda: [("A", 2018), ("B", 2018), ("C", 2018)])
    monkeypatch.setattr(AS, "N_SAMPLE", 3)

    def one(key, year, X):
        if key == "C":
            raise KeyError("no such firm")
        return "outcome_gap" if key == "A" else "small"

    monkeypatch.setattr(AS, "_one", one)
    AS.shard(0, 1)
    rep = json.loads((tmp_path / "_failures_0_of_1.txt").read_text(encoding="utf-8"))
    assert rep == {"failed": {"KeyError": 1}, "excluded": {"outcome_gap": 1, "small": 1}}


@pytest.mark.parametrize("value,legacy", [("1", True), ("0", False), ("true", False), ("yes", False)])
def test_one_legacy_switch(monkeypatch, value, legacy):
    from fintwin.data import edgar

    monkeypatch.setenv("FINTWIN_DATA_LEGACY", value)
    assert B.data_legacy() is edgar.data_legacy() is S._data_legacy() is legacy
    assert B.data_legacy is edgar.data_legacy
