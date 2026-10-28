"""Revision 3, workstream C1: multiple comparisons, clustered inference with few clusters, walk-forward combinations
re-estimated inside each resample, bankruptcy cases, seeds. Each test plants a known answer in simulated data."""

import numpy as np
import pandas as pd
import pytest
from scipy.stats import norm
from scipy.stats import t as t_dist

from fintwin.research import plan2
from fintwin.research import stats as S
from fintwin.research import transmission as T


def _mean_boot(x: np.ndarray, b: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    """Column means of x (n x K) and their row-bootstrap distribution (b x K)."""
    g = np.random.default_rng(seed)
    idx = g.integers(0, len(x), (b, len(x)))
    return x.mean(0), x[idx].mean(1)


# ---------------------------------------------------------------- E5: Romano-Wolf stepM
def test_stepm_with_identical_hypotheses_equals_the_single_test():
    x = np.random.default_rng(0).normal(0.12, 1, (400, 1))
    theta, star = _mean_boot(np.repeat(x, 5, axis=1), 4000, 1)
    rw = S.stepm(theta, star)
    # perfectly dependent tests: no multiplicity penalty (Bonferroni would multiply by 5)
    assert np.allclose(rw["p_adj"], rw["p_raw"]) and np.allclose(rw["p_adj"], rw["p_adj"][0])


def test_stepm_with_independent_hypotheses_is_close_to_sidak():
    g = np.random.default_rng(2)
    K, n = 6, 500
    x = g.normal(0, 1, (n, K))
    x[:, 0] += 0.11  # one moderate effect
    theta, star = _mean_boot(x, 8000, 3)
    rw = S.stepm(theta, star)
    top = int(np.argmin(rw["p_raw"]))  # the first step is the single-step max-t test: Sidak for independent tests
    assert rw["p_adj"][top] == pytest.approx(1 - (1 - rw["p_raw"][top]) ** K, abs=0.03)


def test_stepm_rejects_the_real_effects_and_keeps_the_nulls():
    g = np.random.default_rng(4)
    x = g.normal(0, 1, (600, 8))
    x[:, :3] += np.array([0.4, -0.35, 0.3])
    theta, star = _mean_boot(x, 3000, 5)
    rw = S.stepm(theta, star)
    assert rw["reject"][:3].all() and not rw["reject"][3:].any()
    assert (rw["p_adj"] >= rw["p_raw"] - 1e-12).all()
    assert (rw["p_raw"] > 0).all()  # (1 + count) / (B + 1): never an exact zero (E4)


def test_stepm_controls_the_familywise_error_rate():
    g = np.random.default_rng(6)
    hits = 0
    reps = 150
    for r in range(reps):
        common = g.normal(0, 1, (200, 1))
        x = 0.6 * common + 0.8 * g.normal(0, 1, (200, 5))  # correlated, all nulls true
        theta, star = _mean_boot(x, 400, 100 + r)
        hits += bool(S.stepm(theta, star, alpha=0.10)["reject"].any())
    assert hits / reps < 0.17  # nominal 0.10, Monte Carlo error about 0.025


# ---------------------------------------------------------------- E5: Hansen SPA
def test_spa_consistent_p_value_is_not_swamped_by_poor_models():
    g = np.random.default_rng(7)
    n = 500
    z = g.normal(0, 1, (n, 1))
    good = z - z.mean() + 0.125  # t about 2.8 against the benchmark
    bad = g.normal(-1.0, 3, (n, 60))  # many clearly worse, noisy models
    d, star = _mean_boot(np.hstack([good, bad]), 4000, 8)
    sp = S.spa(d, star, n)
    assert sp["p_lower"] <= sp["p_consistent"] <= sp["p_upper"]
    assert sp["p_consistent"] < 0.05 < sp["p_upper"]  # the reality check (upper) loses the good model


def test_spa_does_not_reject_when_no_model_beats_the_benchmark():
    g = np.random.default_rng(9)
    d, star = _mean_boot(g.normal(-0.05, 1, (500, 5)), 2000, 10)
    assert S.spa(d, star, 500)["p_consistent"] > 0.2


# ---------------------------------------------------------------- E5: model confidence set
def test_mcs_keeps_the_equal_best_and_drops_the_worse():
    g = np.random.default_rng(11)
    loss = g.normal(0, 1, (800, 5)) + np.array([0.0, 0.0, 0.0, 0.5, 0.8])
    L, star = _mean_boot(loss, 2000, 12)
    names = list("abcde")
    res = S.mcs(L, star, names, alpha=0.10)
    assert set(res["included"]) == {"a", "b", "c"}
    assert res["p_mcs"]["e"] <= res["p_mcs"]["d"] < 0.10
    assert max(res["p_mcs"].values()) == 1.0


def test_mcs_with_identical_models_keeps_all_of_them():
    x = np.random.default_rng(13).normal(0, 1, (300, 1))
    L, star = _mean_boot(np.repeat(x, 3, axis=1), 500, 14)
    assert S.mcs(L, star, ["a", "b", "c"])["included"] == ["a", "b", "c"]


# ---------------------------------------------------------------- E9, SW-14: few clusters
def test_cluster_ols_matches_statsmodels_one_way_and_uses_t_of_g_minus_one():
    import statsmodels.api as sm

    g = np.random.default_rng(15)
    firms, years = np.repeat(np.arange(60), 12), np.tile(np.arange(12), 60)
    x = g.normal(size=720)
    y = 0.2 * x + g.normal(size=720) + g.normal(size=12)[years]
    X = sm.add_constant(x)
    mine = S.cluster_ols(y, X, [firms])
    ref = sm.OLS(y, X).fit(cov_type="cluster", cov_kwds={"groups": firms})
    assert np.allclose(mine["se"], ref.bse)
    two = S.cluster_ols(y, X, [firms, years])
    ref2 = sm.OLS(y, X).fit(cov_type="cluster", cov_kwds={"groups": np.column_stack([firms, years])}, use_t=True)
    assert np.allclose(two["se"], ref2.bse)
    assert two["G"] == 12 and two["df"] == 11
    assert two["t_crit"] == pytest.approx(t_dist.ppf(0.975, 11)) and two["t_crit"] > 2.15
    assert np.allclose(two["p"], 2 * t_dist.sf(np.abs(two["t"]), 11))
    assert two["p"][1] > 2 * norm.sf(abs(two["t"][1]))  # the normal p-value of revision 2 is too small


def test_two_way_variance_that_is_not_psd_is_flagged_and_repaired():
    # cell effects that cancel within every firm and every year: V_firm = V_year = 0 < V_cell, so V_1 + V_2 - V_12 < 0
    firms = np.repeat([0, 0, 1, 1], 50)
    years = np.repeat([0, 1, 0, 1], 50)
    d = np.repeat([1.0, -1.0, -1.0, 1.0], 50)
    r = S.two_way_mean(d, firms, years)
    assert r["psd"] is False and r["se"] >= 0


def test_forecast_dm_reports_t_of_g_minus_one():
    g = np.random.default_rng(16)
    rows = []
    for f in range(40):
        for o in range(8):
            for h in (1, 2):
                rows.append(
                    {
                        "var": "revenue",
                        "ticker": f"F{f}",
                        "origin": f"{2014 + o}-02-20",
                        "h": h,
                        "scale": 1.0,
                        "crps_twin": abs(g.normal(1, 0.3)),
                        "crps_rw": abs(g.normal(1.1, 0.3)),
                        "crps_ets": abs(g.normal(1.05, 0.3)),
                    }
                )
    res = S.forecast_section(pd.DataFrame(rows))["revenue"]["rw"]
    assert res["dm_tG1"]["G"] == 8 and res["dm_tG1"]["t_crit"] > 2.3
    assert "dm_p" in res  # the revision-2 statistic is kept


# ---------------------------------------------------------------- D8: bankruptcy cases
def test_petitions_chain_from_the_previous_filing_not_the_petition():
    a = pd.Timestamp("2016-01-04")
    raw = [a, a + pd.Timedelta(days=800), a + pd.Timedelta(days=1600)]  # petition, confirmation, emergence
    assert S.petitions(raw) == [a]  # revision 2 opened a phantom second case at a + 1600
    assert S.cases(raw) == [(a, a + pd.Timedelta(days=1600))]


def test_petitions_legacy_switch_restores_revision_2(monkeypatch):
    monkeypatch.setenv("FINTWIN_DATA_LEGACY", "1")
    a = pd.Timestamp("2016-01-04")
    raw = [a, a + pd.Timedelta(days=800), a + pd.Timedelta(days=1600)]
    assert S.petitions(raw) == [a, a + pd.Timedelta(days=1600)]


def test_firm_year_inside_a_running_case_is_excluded():
    a = pd.Timestamp("2016-01-04")
    spans = S.cases([a, a + pd.Timedelta(days=1000)])
    # three years after the petition, still in Chapter 11: revision 2 scored this firm-year as a survivor (0)
    assert S.bk_event([a], "2019-02-20") == 0.0
    assert np.isnan(S.bk_event([a], "2018-09-01", spans=spans))
    assert S.in_bankruptcy(spans, "2018-09-01") and not S.in_bankruptcy(spans, "2019-02-20")
    assert S.bk_event([a], "2019-02-20", spans=spans) == 0.0  # after the case's last filing: a survivor again


def test_spans_match_petitions_only():
    a = pd.Timestamp("2016-01-04")
    raw = [a, a + pd.Timedelta(days=500)]
    assert S._spans([a], raw) == [(a, a + pd.Timedelta(days=500))]
    b = pd.Timestamp("2020-06-01")
    assert S._spans([b], raw) == [(b, b)]  # petitions from another source keep a one-day span


# ---------------------------------------------------------------- R4: seeds
def test_bootstrap_does_not_depend_on_call_order():
    x = np.random.default_rng(17).normal(size=200)
    first = S.boot(np.mean, [x], b=50)
    S.boot(np.median, [x], b=77)  # another statistic computed in between
    assert np.array_equal(first, S.boot(np.mean, [x], b=50))


def test_seeds_table_lists_every_seed_and_bootstrap_size():
    tab = S.seeds_table()
    assert {"boot", "family", "year_block", "boot_two_way", "cv_folds", "lad", "cash_pool"} <= set(tab["seeds"])
    assert tab["B"]["B_FAMILY"] == S.B_FAMILY
    assert not hasattr(S, "RNG")


def test_p_centered_is_never_zero():
    d = np.full(100, 0.5) + np.random.default_rng(18).normal(0, 0.01, 100)
    assert S.p_two_sided(d) == 0.0 and S.p_centered(0.5, d) == pytest.approx(1 / 101)


# ---------------------------------------------------------------- panel for the combination tests
def _panel(
    n_f: int = 120, years=range(2012, 2024), seed: int = 0, info: float = 1.0, nested: bool = False
) -> pd.DataFrame:
    """Realized cash = persistent level + firm-year news + noise. N3 sees the level; T1 sees the level plus `info` of
    the news; N1 is noisier; the rest are noise around the level."""
    g = np.random.default_rng(seed)
    years = list(years)
    f = np.repeat(np.arange(n_f), len(years))
    y = np.tile(years, n_f)
    n = len(f)
    level = g.normal(10, 5, n_f)[f]
    news = g.normal(0, 4, n)
    real = level + news + g.normal(0, 3, n) + g.normal(0, 2, len(years))[y - years[0]]
    d = {"ticker": [f"F{i}" for i in f], "year": y}
    for var in ("cfo", "fcf"):
        d[f"real_{var}"] = real
        d[f"N3_{var}"] = level + g.normal(0, 1, n)
        d[f"N1_{var}"] = level + g.normal(0, 4, n)
        # nested: T1 is N3 plus the news, so N3 adds nothing to T1
        d[f"T1_{var}"] = d[f"N3_{var}"] + info * news if nested else level + info * news + g.normal(0, 2, n)
        for k in ("N2", "N4", "N5", "N6", "T0"):
            d[f"{k}_{var}"] = level + g.normal(0, 2.5, n)
    return pd.DataFrame(d)


def _v2_lambdas(df, var, base, adj, lo, hi):
    """The revision-2 weight choice, written out independently."""
    real, bx, ax, yrs = (df[c].to_numpy(float) for c in (f"real_{var}", f"{base}_{var}", f"{adj}_{var}", "year"))
    out = {}
    for y in sorted(set(yrs)):
        tr = yrs <= y - 3
        if tr.sum() < 200:
            continue
        lo_, hi_ = (lo, hi) if lo is not None else T.train_bounds(real, yrs)[int(y)]
        err = [
            np.mean(np.abs(np.clip(bx[tr] + lam * (ax[tr] - bx[tr]), lo_, hi_) - np.clip(real[tr], lo_, hi_)))
            for lam in T.LAMBDAS
        ]
        out[int(y)] = float(T.LAMBDAS[int(np.argmin(err))])
    return out


# ---------------------------------------------------------------- E6: training-only winsorization
def test_train_bounds_ignore_test_year_outliers():
    df = _panel()
    real, yrs = df["real_cfo"].to_numpy(float).copy(), df["year"].to_numpy()
    before = T.train_bounds(real, yrs)
    real[yrs == 2023] = 1e6  # an extreme last year
    after = T.train_bounds(real, yrs)
    assert all(before[y] == after[y] for y in before)  # a cutoff year's limits use years <= Y-3 only
    full = T.train_bounds(real, yrs, "full")
    assert full[2016][1] > before[2016][1]  # the revision-2 limits see the future


def test_hybrid_train_bounds_lambda_is_not_moved_by_future_outliers():
    df = _panel()
    firms = df["ticker"].to_numpy()
    base = T.hybrid(df, "cfo", firms, 5, bounds="train")["lambda"]["N3+T1"]
    df2 = df.copy()
    df2.loc[df2["year"] == 2023, "real_cfo"] = 1e5
    moved = T.hybrid(df2, "cfo", firms, 5, bounds="train")["lambda"]["N3+T1"]
    assert {y: v for y, v in moved.items() if y < 2023} == {y: v for y, v in base.items() if y < 2023}
    assert "mae" in T.hybrid(df, "cfo", firms, 5, bounds="train")  # unwinsorized errors reported (E6)


def test_hybrid_full_bounds_reproduces_revision_2_lambdas():
    df = _panel()
    lo, hi = np.nanpercentile(df["real_cfo"], [1, 99])
    h = T.hybrid(df, "cfo", df["ticker"].to_numpy(), 5)
    assert h["lambda"]["N3+T1"] == _v2_lambdas(df, "cfo", "N3", "T1", lo, hi)


def test_fcf_mechanism_adds_training_bound_results():
    years = np.repeat(np.arange(2012, 2024), 100)
    g = np.random.default_rng(19)
    real = g.normal(size=len(years))
    df = pd.DataFrame({"year": years})
    for var in ("cfo", "capex", "fcf"):
        df[f"real_{var}"] = real
        df[f"twin_{var}"] = real + g.normal(0, 0.5, len(years))
    df["N3_cfo"] = df["N3_capex"] = df["N3_fcf"] = real + 1.0
    df["ols_cfo"] = df["N5_capex"] = df["ols_fcf"] = real + g.normal(0, 2, len(years))
    out = plan2.fcf_mechanism(df)
    assert "gain" in out["cfo"] and out["cfo"]["train_bounds"]["gain"] > 0
    assert "capex_share_of_fcf_gain_train_bounds" in out


# ---------------------------------------------------------------- E3: the resampling engine
def test_engine_point_losses_match_direct_computation():
    df = _panel()
    names = ["N3", "T1", "N3+T1", "N3+N1"]
    r = T.boot_losses(df, names, 3, "firm", seed=1, variables=("cfo",))["cfo"]
    d = r["_data"]
    real = df["real_cfo"].to_numpy(float)[d.idx]
    yrs = df["year"].to_numpy()[d.idx]
    bnd = T.train_bounds(df["real_cfo"].to_numpy(float), df["year"].to_numpy())
    lo, hi = np.array([bnd[y][0] for y in yrs]), np.array([bnd[y][1] for y in yrs])
    lam = _v2_lambdas(df, "cfo", "N3", "T1", None, None)
    assert r["lambda"]["N3+T1"] == {y: lam[y] for y in r["test_years"]}
    b_, a_ = df["N3_cfo"].to_numpy(float)[d.idx], df["T1_cfo"].to_numpy(float)[d.idx]
    pred = b_ + np.array([lam[y] for y in yrs]) * (a_ - b_)
    assert r["point_mean"][2] == pytest.approx(np.mean(np.abs(np.clip(pred, lo, hi) - np.clip(real, lo, hi))))
    assert r["point_median"][2] == pytest.approx(np.median(np.abs(pred - real)))
    assert r["point_median"][0] == pytest.approx(np.median(np.abs(b_ - real)))


def test_engine_resample_equals_recomputation_on_replicated_data():
    """One firm x year resample: weights w_f * v_t are the same as repeating each firm-year that many times and
    re-running the walk-forward choice of lambda (limits fixed at the sample's own)."""
    df = _panel(n_f=60)
    names = ["N3", "N3+T1"]
    years = sorted(df["year"].unique())
    fcode = pd.factorize(df["ticker"])[0]
    tcode = np.searchsorted(years, df["year"].to_numpy())
    d = T._Losses(df, "cfo", names, "train", fcode, tcode, years)
    W, V = T._draws(fcode.max() + 1, len(years), 1, "firm_year", np.random.default_rng(3))
    mean, med = d.losses(W, V, 1)
    reps = (W[0][fcode] * V[0][tcode]).astype(int)
    rep = df.loc[np.repeat(df.index, reps)].reset_index(drop=True)
    real, yrs = rep["real_cfo"].to_numpy(float), rep["year"].to_numpy()
    bnd = T.train_bounds(df["real_cfo"].to_numpy(float), df["year"].to_numpy())
    bx, ax = rep["N3_cfo"].to_numpy(float), rep["T1_cfo"].to_numpy(float)
    num = den = 0.0
    errs = []
    for j, y in enumerate(d.test_years):
        lo, hi = bnd[y]
        tr = yrs <= y - 3
        if tr.any():
            err = [
                np.sum(np.abs(np.clip(bx[tr] + lam * (ax[tr] - bx[tr]), lo, hi) - np.clip(real[tr], lo, hi)))
                for lam in T.LAMBDAS
            ]
            lam = T.LAMBDAS[int(np.argmin(err))]
        else:
            lam = T.LAMBDAS[d.lam_point["N3+T1"][j]]
        te = yrs == y
        p = bx[te] + lam * (ax[te] - bx[te])
        num += np.sum(np.abs(np.clip(p, lo, hi) - np.clip(real[te], lo, hi)))
        den += te.sum()
        errs.append(np.abs(p - real[te]))
    assert mean[0, 1] == pytest.approx(num / den)
    assert med[0, 1] == pytest.approx(np.median(np.concatenate(errs)))


def test_weighted_median_matches_repetition():
    g = np.random.default_rng(20)
    e = g.normal(size=37)
    w = g.integers(0, 4, (5, 37)).astype(float)
    got = T.wmedian(e, w)
    for r in range(5):
        assert got[r] == pytest.approx(np.median(np.repeat(e, w[r].astype(int))))
    assert T.wmedian(e, np.ones((1, 37)))[0] == np.median(e)


def test_lambda_is_re_estimated_in_each_year_block_resample():
    r = T.boot_losses(_panel(), ["N3", "N3+T1"], 60, "year", seed=2, variables=("cfo",))["cfo"]
    d = r["_data"]
    lam = d.lambdas("N3+T1", None, T._draws(d.F, d.T, 60, "year", np.random.default_rng(4))[1], 60)
    assert len(np.unique(lam, axis=0)) > 1  # not one fixed lambda as in revision 2
    assert np.isfinite(r["boot_mean"]).all()


# ---------------------------------------------------------------- E3, E4, E5: the pre-specified family
def test_inference_family_spa_mcs_and_gains():
    res = T.inference(_panel(n_f=150), 300)
    fam = res["family"]
    assert len(fam) == 16
    t1 = fam["cfo_mean_T1_vs_N3"]
    assert t1["diff"] < 0 and t1["reject_05"]  # the informed twin beats the 16-quarter margin
    assert fam["cfo_median_N3+N1_vs_N3"]["p_romano_wolf"] >= fam["cfo_median_N3+N1_vs_N3"]["p"]
    assert res["spa"]["cfo_mean_family"]["p_consistent"] < 0.05
    mc = res["mcs"]["cfo_mean"]
    assert "N3+T1" in mc["included"] and "N1" not in mc["included"]
    g = res["gains"]["cfo"]["N3+T1_vs_N3"]
    assert g["gain_pct"] > 0 and g["positive_years"] == g["n_years"]
    assert g["dm_abs"]["G"] == len(res["gains"]["cfo"]["test_years"]) and g["dm_abs"]["p"] < 0.05
    assert set(g["by_year"]) == set(res["gains"]["cfo"]["test_years"])


def test_inference_finds_nothing_when_the_twin_knows_nothing():
    res = T.inference(_panel(n_f=150, info=0.0, seed=5), 300)
    assert not res["family"]["cfo_mean_T1_vs_N3"]["reject_05"] or res["family"]["cfo_mean_T1_vs_N3"]["diff"] > 0
    assert res["spa"]["cfo_mean_family"]["p_consistent"] > 0.05


# ---------------------------------------------------------------- E7: absolute loss
def test_abs_loss_encompassing_detects_information_under_mae():
    df = _panel(n_f=150, nested=True)
    d = df[df["year"] >= 2014]
    X = pd.concat(
        [
            pd.DataFrame({k: d[f"{k}_cfo"] - d["N1_cfo"] for k in ("T1", "N3", "N4", "N6")}),
            pd.get_dummies(d["year"], prefix="y", drop_first=True, dtype=float),
        ],
        axis=1,
    )
    lo, hi = np.nanpercentile(d["real_cfo"], [1, 99])
    out = T._encompassing_v3(d, "cfo", X, lo, hi, ["T1", "N3", "N4", "N6"])
    a = out["abs_loss_encompassing"]
    assert a["N3_encompasses_T1"]["p_one_sided"] < 0.01  # N3 misses the news T1 sees
    assert a["T1_encompasses_N3"]["p_one_sided"] > 0.05
    assert out["dm_abs"]["T1_vs_N3"]["mean"] < 0 and out["dm_abs"]["T1_vs_N3"]["p"] < 0.05
    assert out["all_two_way_tG1"]["G"] == d["year"].nunique()
    assert out["lad_levels"]["coef"]["T1"] > 0.3


# ---------------------------------------------------------------- SW-12: concordance on a common sample
def _harrell_brute(r, t, e):
    num = den = 0.0
    for i in range(len(t)):
        if e[i]:
            later = t > t[i]
            den += later.sum()
            num += (r[i] > r[later]).sum() + 0.5 * (r[i] == r[later]).sum()
    return num / den


def test_fast_harrell_c_equals_the_pairwise_definition():
    g = np.random.default_rng(21)
    r = np.round(g.normal(size=400), 1)  # with ties
    t = g.integers(1, 10, 400).astype(float)
    e = g.random(400) < 0.4
    assert plan2.harrell_c(r, t, e.astype(float)) == pytest.approx(_harrell_brute(r, t, e))


def test_timing_difference_uses_the_common_sample():
    g = np.random.default_rng(22)
    n = 600
    t_ev = np.where(g.random(n) < 0.3, g.integers(1, 9, n), np.nan).astype(float)
    risk = -np.nan_to_num(t_ev, nan=12) + g.normal(0, 2, n)
    nl = risk + g.normal(0, 3, n)
    nl[: n // 2] = np.nan  # the ablation is missing for half the firm-years
    df = pd.DataFrame(
        {"rc_t_cash_half": t_ev, "tm_full_cash_half": risk, "tm_no_loops_cash_half": nl, "st_cash_min": -risk}
    )
    res = plan2.timing(df, np.array([f"F{i % 100}" for i in range(n)]), 20)["cash_half"]
    both = np.isfinite(nl)
    time = np.where(np.isfinite(t_ev), t_ev, 9.0)
    ev = np.isfinite(t_ev).astype(float)
    want = plan2.harrell_c(risk[both], time[both], ev[both]) - plan2.harrell_c(nl[both], time[both], ev[both])
    assert res["twin_minus_no_loops"]["est"] == pytest.approx(want) and res["twin_minus_no_loops"]["n"] == both.sum()
    assert res["twin"] - res["no_loops"] != pytest.approx(want)  # the revision-2 keys: different samples


# ---------------------------------------------------------------- E11: density combinations
def test_quantile_grid_recovers_a_normal():
    q = norm.ppf(plan2.TAUS)[None, :] * 2.0 + 1.0
    grid = plan2._quantile_grid(q, 50)
    want = 1.0 + 2.0 * norm.ppf((np.arange(50) + 0.5) / 50)
    assert np.allclose(grid[0, 10:40], want[10:40], atol=0.06)
    assert np.all(np.diff(grid[0]) > 0)


def test_density_combination_learns_weight_on_crps():
    g = np.random.default_rng(23)
    n = 3000
    mu = g.normal(0, 1, n)
    y = mu + g.normal(0, 1, n)
    origin_year = np.repeat(np.arange(2012, 2024), n // 12)
    fc = pd.DataFrame(
        {
            "y": y,
            "rw_mu": mu + 1.5,  # biased random walk
            "rw_sd": np.full(n, 1.0),
            "scale": np.ones(n),
            "ticker": [f"F{i % 300}" for i in range(n)],
            "q": list(mu[:, None] + norm.ppf(plan2.TAUS)[None, :]),  # the twin knows the true density
        }
    )
    out = plan2.density_combos(fc, origin_year, b=30)
    for k in ("linear_pool", "quantile_avg"):
        assert out[k]["skill_vs_rw"] > 0.2 and min(out[k]["lambda"].values()) >= 0.7
    assert out["quantile_avg"]["skill_vs_rw"] >= out["linear_pool"]["skill_vs_rw"] - 0.02
