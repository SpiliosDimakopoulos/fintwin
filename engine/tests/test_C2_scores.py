"""C2: probability scores (E8), the liquidity-shortfall test (E12), credit events (M9), calibration tests (E13),
the density test of 8-quarter totals (E2) and the Sobol design (P8)."""

import json

import numpy as np
import pandas as pd
import pytest

from fintwin.research import calibration as C
from fintwin.research import distress as D
from fintwin.research import experiments as X


# ---------------------------------------------------------------- E8
def test_murphy_decomposition_adds_up_and_detects_miscalibration():
    rng = np.random.default_rng(0)
    p = rng.uniform(0, 1, 20000)
    y = (rng.uniform(0, 1, len(p)) < p).astype(float)
    m = D.murphy(p, y)
    assert m["brier"] == pytest.approx(m["reliability"] - m["resolution"] + m["uncertainty"] + m["within"])
    assert m["reliability"] < 0.001 and m["resolution"] > 0.05
    over = D.murphy(np.clip(p + 0.3, 0, 1), y)
    assert over["reliability"] > 0.05  # systematically too high
    assert all(c["y_mean"] == pytest.approx(c["p_mean"], abs=0.03) for c in m["curve"])
    s = D.prob_scores(p, y)
    assert s["n"] == len(y) and s["brier"] == pytest.approx(np.mean((p - y) ** 2))
    want = -(np.log(D.EPS_LOG) + np.log(1 - D.EPS_LOG)) / 2  # an exact 0 is clipped, not an infinite loss
    assert D.log_score(np.array([0.0, 1.0]), np.array([1.0, 1.0])) == pytest.approx(want)


def test_bss_and_block_ci():
    rng = np.random.default_rng(1)
    p = rng.uniform(0, 1, 3000)
    y = (rng.uniform(0, 1, len(p)) < p).astype(float)
    clim = np.full(len(p), y.mean())
    assert D._bss(p, clim, y) > 0.2
    ci = D.block_ci(D._bss, [p, clim, y], np.repeat(np.arange(10), 300), 200)
    assert ci["blocks"] == 10 and 0 < ci["ci"][0] < ci["ci"][1]


def test_event_scores_on_structural_probs():
    rng = np.random.default_rng(2)
    rows = []
    for y in range(2013, 2025):
        for _ in range(60):
            pr = float(rng.uniform())
            ev = bool(rng.uniform() < pr)
            rows.append({"year": y, "st": {"probs": {"full": {"cash_half": pr}}, "events": {"cash_half": ev}}})
    out = D.event_scores(pd.DataFrame(rows))
    assert out["cash_half"]["n"] == 720 and out["cash_half"]["bss_vs_climatology"] > 0
    assert out["debt_raise"]["n"] == 0


# ---------------------------------------------------------------- M9
def test_credit_events_from_submissions():
    f = pd.DataFrame(
        {
            "form": ["8-K", "8-K", "8-K", "8-K", "10-K", "8-K", "8-K"],
            "filingDate": [
                "2016-03-01",
                "2018-01-10",
                "2018-01-20",
                "2019-06-01",
                "2019-06-01",
                "2020-05-01",
                "2021-01-01",
            ],
            "items": ["1.03,9.01", "5.01", "3.01", "2.04", "", "2.01,2.04,3.01", "11.03,1.031"],
        }
    )
    ev = X.credit_events_from(f)
    assert ev["1.03"] == ["2016-03-01"]  # "11.03" / "1.031" are not item 1.03
    assert ev["2.04"] == ["2019-06-01"]  # the 2020 acceleration came with an acquisition (2.01): dropped
    assert ev["3.01"] == []  # 10 days after a change in control, and one in an acquisition 8-K: dropped
    assert ev["3.01_coc_dropped"] == 2 and ev["2.04_coc_dropped"] == 1
    assert X.credit_events_from(pd.DataFrame())["1.03"] == []


def test_credit_labels_and_exclusion_window():
    ev = {"1.03": ["2016-03-01"], "2.04": ["2019-06-01"], "3.01": []}
    lab = D.credit_labels(ev, "2015-02-15")
    assert lab["ce4"] == 0.0 and lab["ce8"] == 1.0 and lab["bk8"] == 1.0 and lab["acc8"] == 0.0
    assert np.isnan(D.credit_labels(ev, "2017-02-15")["ce8"])  # in or just out of a credit event
    assert D.credit_labels(ev, "2018-02-15")["acc8"] == 1.0
    assert all(np.isnan(v) for v in D.credit_labels(None, "2018-02-15").values())


# ---------------------------------------------------------------- E12
def _liq_frame(seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for year in range(2013, 2025):
        for i in range(400):
            cash_rev, debt_assets, fcf = rng.uniform(0, 0.5), rng.uniform(0, 0.8), rng.normal(0.05, 0.1)
            risk = 1 / (1 + np.exp(-(-3 - 6 * cash_rev + 3 * debt_assets - 8 * fcf)))
            y8 = float(rng.uniform() < risk)
            depths = {f"{d:.2f}": [min(risk * (1 + d), 1) * 0.6, min(risk * (1 + d), 1)] for d in X.DEPTHS}
            rows.append(
                {
                    "ticker": f"T{i}",
                    "cik": i,
                    "origin": f"{year}-02-15",
                    "year": year,
                    "industry": f"ind{i % 8}",
                    "h_base": 100 * (1 - risk),
                    "pb_base": risk,
                    "cash_rev": cash_rev,
                    "debt_assets": debt_assets,
                    "fcf_margin": fcf,
                    "z2": 3 - 4 * risk + rng.normal(0, 0.5),
                    "log_rev": 20.0,
                    "rev_drop8": -10.0 * rng.uniform(),
                    "outcome_filed": f"{year + 2}-01-10",
                    "outcome_filed4": f"{year + 1}-01-10",
                    "rec4": risk * 0.6,
                    "rec8": risk,
                    "y_short4": float(y8 and rng.uniform() < 0.6),
                    "y_short8": y8,
                    "ce4": 0.0,
                    "ce8": y8 * float(rng.uniform() < 0.3),
                    **{f"lg4_{d}": v[0] for d, v in depths.items()},
                    **{f"lg8_{d}": v[1] for d, v in depths.items()},
                }
            )
    return pd.DataFrame(rows)


def test_benchmarks_train_only_on_labels_observable_at_the_cutoff():
    df = _liq_frame()
    cut = pd.Timestamp("2016-02-15")
    known = D.known_by(df, cut, 8)
    assert set(df.loc[known, "year"]) == {2013, 2014}  # 2015's window is still open in Feb 2016
    df.loc[df["year"] == 2014, "outcome_filed"] = "2016-03-01"  # filed after the cutoff: not usable
    assert set(df.loc[D.known_by(df, cut, 8), "year"]) == {2013}
    y = df["y_short8"].to_numpy(float)
    a = D.benchmark_probs(df, y, 8, D.LOGIT_COLS, [2016])
    y2 = y.copy()
    y2[df["year"].to_numpy() >= 2014] = 1 - y2[df["year"].to_numpy() >= 2014]  # scramble every later label
    b = D.benchmark_probs(df, y2, 8, D.LOGIT_COLS, [2016])
    assert np.allclose(a[df["year"] == 2016], b[df["year"] == 2016])
    assert np.isnan(a[df["year"] != 2016]).all()


def test_liquidity_section_scores_twin_against_benchmarks():
    out = D.liquidity_section(_liq_frame(), b=50)
    r = out["shortfall"]["8"]["recession"]
    assert r["n"] > 1000 and r["years"][0] == 2015
    assert set(r) >= {"twin", "logit", "altman_z2", "bss_vs_logit", "bss_vs_altman_z2", "by_year", "success"}
    # here the twin's probability is the true risk, so it beats the trained logit, and the realized-shock version
    # (read off the depth grid at each industry's leave-one-out shock) runs on the three episodes only
    assert r["bss_vs_logit"]["bss"] > -0.05
    assert r["twin"]["murphy"]["reliability"] < 0.01
    rs = out["shortfall"]["8"]["realized_shock"]
    assert rs["years"] == [2015, 2020, 2022]
    json.dumps(out)


def test_logit_fit_recovers_coefficients():
    rng = np.random.default_rng(3)
    X_ = rng.normal(size=(20000, 2))
    pr = 1 / (1 + np.exp(-(0.5 + 1.0 * X_[:, 0] - 2.0 * X_[:, 1])))
    y = (rng.uniform(size=len(pr)) < pr).astype(float)
    m = D.fit_logit(X_, y, ridge=0.0)
    assert np.allclose(D.predict_logit(m, X_), pr, atol=0.03)


def test_liquidity_frame_reads_shards(tmp_path):
    shard = {
        "ticker": "CIK0000000001",
        "cik": 1,
        "credit_events": {"1.03": [], "2.04": ["2019-01-10"], "3.01": []},
        "covid": {"sector": "Manuf"},
        "panel": [
            {
                "origin": "2018-02-15",
                "base": {"health": 60.0, "p_breach": 0.1},
                "features": {"cash_rev": 0.1, "debt_assets": 0.3, "fcf_margin": 0.02, "z2": 1.5, "log_rev": 20.0},
                "outcome": {"rev_drop8": -5.0, "cash_min_ratio4": 0.9, "debt_raise4": 0.0, "cash_min_ratio8": 0.2,
                            "debt_raise8": 0.1, "outcome_filed": "2020-01-30", "outcome_filed4": "2019-01-30"},
                "liquidity": {"grid": {"0.00": [0.01, 0.02], "0.80": [0.2, 0.4]}, "recession": [0.05, 0.1],
                              "base": [0.0, 0.01]},
            }
        ],
    }  # fmt: skip
    (tmp_path / "a.json").write_text(json.dumps(shard), encoding="utf-8")
    df = D.liquidity_frame(tmp_path)
    r = df.iloc[0]
    assert r["ce8"] == 1.0 and r["acc8"] == 1.0 and r["y_short8"] == 1.0
    assert r["y_short4"] == 1.0  # the 2.04 filing is within four quarters
    assert r["rec8"] == 0.1 and r["lg8_0.80"] == 0.4


def test_shortfall_label():
    assert D.shortfall_label(1.0, None, None) == 1.0
    assert D.shortfall_label(0.0, 0.2, 0.1) == 1.0
    assert D.shortfall_label(0.0, 0.2, 0.01) == 0.0
    assert np.isnan(D.shortfall_label(np.nan, 0.2, 0.1))


# ---------------------------------------------------------------- E13
def test_interval_score_and_christoffersen():
    assert C.interval_score(np.array([0.0]), np.array([1.0]), np.array([1.5]), 0.1)[0] == pytest.approx(11.0)
    rng = np.random.default_rng(4)
    n_f, n_t = 200, 12
    hits = rng.uniform(size=n_f * n_t) > 0.1
    g = np.repeat(np.arange(n_f), n_t)
    o = np.tile(np.arange(n_t), n_f)
    ok = C.christoffersen(pd.Series(hits), pd.Series(g), pd.Series(o))
    assert ok["p_uc"] > 0.01 and ok["p_cc"] > 0.01
    # misses in runs: independence is rejected even at the right overall rate
    runs = np.tile(np.r_[np.ones(10, bool), np.zeros(2, bool)], n_f)  # two misses in a row per firm
    bad = C.christoffersen(pd.Series(runs), pd.Series(g), pd.Series(o))
    assert bad["p_ind"] < 0.001 and bad["p_miss_after_miss"] > 0.4


def test_pit_hist_and_asymmetric_conformal_fixes_skew():
    from fintwin.research.calibration import _norm, conformal

    rng = np.random.default_rng(5)
    rows = []
    for o in range(2013, 2020):
        for i in range(300):
            e = rng.exponential(1.0) - 0.7  # right-skewed errors around a symmetric interval
            rows.append({"origin": f"{o}-02-15", "target": f"{o - 1}-09-30", "y": e, "q": [-1.0, -0.5, 0.0, 0.5, 1.0],
                         "pit_twin": 0.5, "ticker": f"T{i}", "scale": 1.0})  # fmt: skip
    d = conformal(_norm(pd.DataFrame(rows)))
    below, above = (d["y"] < d["q50"] - d["c_lo"] * 1.0).mean(), (d["y"] > d["q50"] + d["c_hi"] * 1.0).mean()
    assert abs(below - 0.05) < 0.02 and abs(above - 0.05) < 0.02
    assert d["is90_asym"].mean() < d["is90_conf"].mean()  # tighter where the errors are not
    h = C.pit_hist(rng.uniform(size=5000))
    assert len(h["shares"]) == 10 and h["chi2_p"] > 0.001


# ---------------------------------------------------------------- E2
def _density_panel(seed: int = 6) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for y in range(2013, 2025):
        for i in range(150):
            m16 = 0.12
            real = m16 * 800 + rng.normal(0, 3)
            # an over-dispersed twin: correct centre, s.d. 9 instead of 3
            samples = real - rng.normal(0, 3) + rng.normal(0, 9, 500)
            q = np.percentile(samples, X.QLEVELS).tolist()
            dens = X.density(samples, real)
            st = {"rev": [100.0] * 8, "m": {"cfo16": m16, "fcf16": m16}, "real_cfo": [real / 8] * 8,
                  "real_fcf": [real / 8] * 8, "dens": {"cfo": {**dens, "q": q}, "fcf": {**dens, "q": q}}}  # fmt: skip
            rows.append({"ticker": f"T{i}", "year": y, "st": st})
    return pd.DataFrame(rows)


def test_density_section_benchmarks_and_dm():
    out = C.density_section(_density_panel())
    r = out["cfo"]
    assert r["test_years"][0] == 2017  # training needs cutoffs <= Y-3 with 300 firm-years
    assert r["crps"]["gaussian"] < r["crps"]["twin"]  # the benchmark is calibrated, the twin too wide
    assert r["vs_gaussian"]["dm"]["mean"] > 0 and not r["vs_gaussian"]["success"]
    assert r["vs_gaussian"]["dm"]["years"] == 8 and r["vs_gaussian"]["years_twin_better"] == 0
    assert r["pit"]["twin"]["shares"][0] < 0.1  # too wide: PIT piles up in the middle
    json.dumps(out)


def test_dm_two_way_size():
    rng = np.random.default_rng(7)
    firms, years = np.repeat(np.arange(300), 10), np.tile(np.arange(10), 300)
    d = rng.normal(size=3000) + rng.normal(size=10)[years] * 0.0
    r = C.dm_two_way(d, firms, years)
    assert r["p"] > 0.01 and r["firms"] == 300 and r["years"] == 10


# ---------------------------------------------------------------- P8
def test_sobol_design_is_scrambled_and_large(monkeypatch):
    from scipy.stats import qmc

    from fintwin.research import assumption_sobol as A

    monkeypatch.delenv("FINTWIN_SPEC", raising=False)
    monkeypatch.delenv("FINTWIN_FIXES", raising=False)
    monkeypatch.setattr(X, "_spec_mod", None)
    assert A.N_BASE >= 256
    a, b, ab = A.design()
    k = len(A.factors())
    assert a.shape == (A.N_BASE, k) and len(ab) == k
    lo, hi = np.array([f[1] for f in A.factors()]), np.array([f[2] for f in A.factors()])
    u = (a - lo) / (hi - lo)
    pseudo = np.random.default_rng(41).random(u.shape)
    assert qmc.discrepancy(u) < qmc.discrepancy(pseudo)  # quasi-random fills the cube more evenly
    assert [f[0] for f in A.factors()][1] == "prior_tau"  # v3: F1 replaces the prior weight by tau
    monkeypatch.setenv("FINTWIN_SPEC", "v2-pre")
    assert [f[0] for f in A.factors()][1] == "prior_weight" and A.specified()[0] == 0.35


def test_sobol_indices_guard_and_firm_bootstrap(monkeypatch, tmp_path):
    from fintwin.research import assumption_sobol as A

    monkeypatch.setenv("FINTWIN_SPEC", "v2-pre")
    monkeypatch.setattr(X, "_spec_mod", None)
    rng = np.random.default_rng(0)
    k, n = len(A.FACTORS_V2), 32
    flat = A.indices(np.ones(n * (k + 2)), n, k, rng, n_boot=10)
    assert all(np.isnan(r["S1"]) and np.isnan(r["ST"]) for r in flat)  # not inf from a zero variance
    monkeypatch.setattr(A, "N_BASE", n)
    monkeypatch.setattr(A, "CACHE_ROOT", tmp_path)
    monkeypatch.setattr(A, "OUT", tmp_path / "out.json")
    A_, B_, AB = A.design(n)
    P = np.vstack([A_, B_, *AB])
    d = A.cache_dir()
    d.mkdir(parents=True)
    for i in range(60):
        real = float(rng.normal(10, 3))
        dx = float(rng.normal(0, 10))
        twin = (real + P[:, 0] * 5 * rng.normal() + 0.1 * dx).tolist()  # the first factor matters
        row = {
            "key": f"k{i}",
            "year": 2018,
            "real": real,
            "n1": real + 1,
            "rev_change": dx,
            "twin": twin,
            "_stamp": "s",
        }
        (d / f"k{i}_2018.json").write_text(json.dumps(row), encoding="utf-8")
    eligible = {
        "_stamp": "s",
        "n_sample": 60,
        "keys": [[f"k{i}", 2018] for i in range(60)],
        "failed": {},
        "excluded": {},
    }
    (d / "_eligible.json").write_text(json.dumps(eligible), encoding="utf-8")
    out = A.stats(n_boot=40)
    assert out["attrition"]["eligible"] == out["attrition"]["rows"] == 60
    top = max(out["median_ae"]["indices"], key=lambda r: r["ST"])
    assert top["factor"] == "fixed_share_prior"
    assert "elasticity_ratio" in out and out["n_base"] == n
    ci = top["ST_ci"]
    assert ci[0] < top["ST"] < ci[1] or ci[0] <= ci[1]
