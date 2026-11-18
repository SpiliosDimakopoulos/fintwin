"""Plan 5 statistics corrections S1-S8 (docs/REVISION_PLAN_5.md), on small synthetic frames."""

import numpy as np
import pandas as pd
import pytest

from fintwin.research import distress, plan2
from fintwin.research import stats as S
from fintwin.research import transmission as T


def _frame(n_firms: int = 60, years=range(2010, 2020), seed: int = 0) -> pd.DataFrame:
    """A transmission frame (the output of T.frame) with an informed twin and a few holes in N5."""
    rng = np.random.default_rng(seed)
    recs = []
    for f in range(n_firms):
        mu = rng.normal(0.12, 0.05)
        for y in years:
            info = rng.normal(0, 3)
            n16 = 200 * mu + rng.normal(0, 0.5)
            n1 = 200 * mu + rng.normal(0, 4)
            rec = {"ticker": f"F{f}", "cluster": f"F{f}", "year": y, "industry": "ABC"[f % 3], "revsum": 200.0}
            for var, shift in (("cfo", 0.0), ("fcf", -8.0)):
                real = 200 * mu + info + rng.normal(0, 1) + shift
                rec |= {
                    f"real_{var}": real,
                    f"N1_{var}": n1 + shift,
                    f"N2_{var}": 0.5 * (n1 + n16) + shift,
                    f"N3_{var}": n16 + shift,
                    f"N5_{var}": n16 + rng.normal(0, 1) + shift,
                    f"N6_{var}": n16 + rng.normal(0, 1) + shift,
                    f"T0_{var}": n16 + 0.5 * info + shift,
                    f"T1_{var}": n16 + info + rng.normal(0, 1) + shift,
                    f"m4_{var}": (n1 + shift) / 200,
                }
            recs.append(rec)
    df = pd.DataFrame(recs)
    df.loc[df.index % 17 == 0, "N5_cfo"] = np.nan  # N5 fails on some firm-years: per-model samples differ
    df.loc[3, "real_cfo"] = 5000.0  # one test-year outlier
    return T.add_shrunk(df)


# ---------------------------------------------------------------- S1 common sample
def test_levels_use_one_common_sample_and_keep_per_model_results():
    df = _frame()
    common = T.levels(df, "cfo")
    own = T.levels(df, "cfo", sample="per_model")
    n_common = int(T.common_mask(df, "cfo").sum())
    assert {v["n"] for k, v in common.items() if k in T.MODELS} == {n_common}
    assert own["N1"]["n"] > n_common == own["N5"]["n"]
    m = T.common_mask(df, "cfo")
    e = np.abs(df["N1_cfo"] - df["real_cfo"]).to_numpy()
    assert common["N1"]["median_ae"] == pytest.approx(np.median(e[m]))
    assert own["N1"]["median_ae"] == pytest.approx(np.median(e))
    assert "mae_w_fullwinsor" in own["N1"] and "mae_w_fullwinsor" not in common["N1"]


def test_by_year_errors_on_a_common_sample():
    df = _frame()
    df.loc[df["year"] == 2015, "N6_cfo"] = np.where(np.arange((df["year"] == 2015).sum()) % 2, np.nan, 1.0)
    cell = T.by_year(df, "cfo")[2015]
    assert cell["n_mae"] < cell["n"]
    assert np.isfinite(cell["mae_T1"]) and np.isfinite(cell["mae_T1_own_sample"])


# ---------------------------------------------------------------- S2 Holm with B_HOLM and (1 + k) / (B + 1)
def test_holm_boot_p_is_never_below_one_over_b_plus_one(monkeypatch):
    monkeypatch.setattr(S, "B_HOLM", 99)
    rng = np.random.default_rng(1)
    y = (rng.uniform(size=400) < 0.3).astype(float)
    good = y + rng.normal(0, 0.3, 400)
    bad = rng.normal(size=400)
    firms = np.repeat(np.arange(100), 4)
    old = S.paired(S.auc, good, bad, y, firms, 99)
    new = S.paired_holm(S.auc, good, bad, y, firms)
    assert old["p"] == 0.0  # the share of resamples: zero
    assert new["p"] == pytest.approx(1 / 100) and new["B"] == 99 and new["k"] == 0
    monkeypatch.setattr(S, "B_HOLM", 0)
    assert S.paired_holm(S.auc, good, bad, y, firms) is None


def test_holm_section_keeps_the_reported_family_and_adds_the_corrected_one():
    def cell(p, ph):
        return {"p": p, "holm": {"p": ph}}

    res = {
        "transmission": {
            "panel": {
                "cfo": {
                    "hybrid_train": {"N3+T1_vs_N3+N1": cell(0.0, 1 / (S.B_HOLM + 1)), "N3+T1_vs_N3+N5": cell(0.2, 0.21)}
                },
                "decisions": {"cash_half": {"oos": {"delta_twin": {"p": 0.004}, "delta_twin_holm": {"p": 0.03}}}},
            }
        }
    }
    out = S.holm_section(res)
    assert out["reported"]["m"] == out["corrected"]["m"] == 3
    adj = out["corrected"]["adjusted"]
    assert min(adj.values()) >= 3 / (S.B_HOLM + 1) - 1e-12
    assert out["flips_at_5pct"] == ["decision_cash_half"]  # 3 x 0.004 < 0.05, 2 x 0.03 > 0.05
    assert plan2.holm(S._secondary_pvalues(res))["hybrid_cfo_N3+T1_vs_N3+N1"] == 0.0  # reported family unchanged


def test_holm_bound_prints_the_resolvable_floor():
    assert S.holm_bound(0.0, 17, 500) == ("<", pytest.approx(17 / 501))
    assert S.holm_bound(0.2, 17, 500) == ("=", 0.2)


# ---------------------------------------------------------------- S3 training-year winsorization
def test_levels_and_encompassing_take_limits_from_training_years():
    df = _frame()
    lv = T.levels(df, "cfo")
    assert lv["T1"]["winsor"] == "train" and lv["T1"]["n_mae_w"] < lv["T1"]["n"]  # the first years have no limits
    lo, hi = T.row_bounds(df["real_cfo"].to_numpy(), df["year"].to_numpy())
    assert np.isnan(lo[df["year"].to_numpy() < 2013]).all() and np.isfinite(lo[df["year"].to_numpy() >= 2013]).all()
    # the 2010 outlier sets no limit of its own year (no training years), and is inside every later year's limits
    # only through its training share; with all-year limits it is clipped to the 99th percentile of every year
    full = T.levels(df, "cfo", sample="per_model", bounds="full")
    assert full["T1"]["mae_w"] == pytest.approx(full["T1"]["mae_w_fullwinsor"])
    enc = T.encompassing(df, "cfo", bounds="train", lad=False)
    assert enc["winsor"] == "train" and enc["n_dropped_no_train_limits"] > 0 and "lad_levels" not in enc


def test_hybrid_defaults_to_training_limits():
    df = _frame()
    firms = df["ticker"].to_numpy()
    h = T.hybrid(df, "cfo", firms, 20)
    assert h.get("bounds") == "train"
    assert "bounds" not in T.hybrid(df, "cfo", firms, 20, bounds="full")


# ---------------------------------------------------------------- S4 shrinkage grid and effective rivals
def test_shrinkage_grid_stops_at_09_and_prior_grid_is_kept():
    assert T.SHRINK_GRID.max() == pytest.approx(0.9) and T.SHRINK_GRID_PRIOR.max() == pytest.approx(1.0)
    df = _frame()
    df["m4_cfo"] = df["real_cfo"] / df["revsum"]  # the own margin is perfect: the prior grid picks 1.0
    df = T.add_shrunk(df.drop(columns=["N4_cfo", "N4g10_cfo"]))
    w_new, w_old = df.attrs["N4_weights_cfo"], df.attrs["N4g10_weights_cfo"]
    assert max(w_new.values()) <= 0.9 and max(w_old.values()) == 1.0
    df["N1_cfo"] = df["m4_cfo"] * df["revsum"]
    eff_old = T.effective_rivals(T.prior_grid(df), "cfo")
    eff_new = T.effective_rivals(df, "cfo")
    yr = next(y for y, w in w_old.items() if w == 1.0)
    assert "N4=N1" in eff_old[yr]["duplicates"] and eff_old[yr]["effective"] == eff_new[yr]["effective"] - 1


# ---------------------------------------------------------------- S5 downturn: univariate and one control at a time
def test_exposure_regression_adds_univariate_and_one_control_at_a_time():
    rng = np.random.default_rng(2)
    n = 300
    depth = rng.uniform(0, 0.5, n)
    fcf = rng.normal(size=n)
    twin = depth + fcf + rng.normal(0, 0.3, n)
    sev = depth + 0.5 * fcf + rng.normal(0, 0.5, n)
    reg = distress.exposure_regression(sev, depth, twin, fcf, rng.normal(size=n), np.arange(n) % 12)
    assert set(reg["univariate"]) == {"exp", "twin", "fcf", "formula"}
    assert reg["univariate"]["twin"] == pytest.approx(S.rho(twin, sev))
    lad = reg["one_control_at_a_time"]
    assert {"twin|alone", "twin|exp", "twin|fcf", "twin|formula", "exp|alone", "exp|twin"} <= set(lad)
    assert lad["twin|alone"]["t"] > lad["twin|exp"]["t"]  # the shock takes part of the twin's correlation
    assert reg["pre_specified"]["twin"]["t"] == pytest.approx(reg["pre_specified"]["twin"]["t"])  # unchanged keys


def test_episodes_record_the_missing_16_quarter_outcome():
    assert "abn16_cum8" in plan2.ABN16_NEEDED and plan2.ABN16 == "y_abn16_cum8"


# ---------------------------------------------------------------- S6 the H2 statistics for every rival
def test_h2_rivals_score_every_candidate_like_the_twin():
    df = _frame()
    firms = df["ticker"].to_numpy()
    out = T.h2_rivals(df, firms, 30)
    c = out["candidates"]
    assert set(c) == set(T.MODELS) - {"N1"}
    assert set(c["T1"]["incremental"]) == {"N3", "N4", "N6"} and set(c["N3"]["incremental"]) == {"N4", "N6"}
    assert c["T1"]["passes_h2_rule"] and not c["N2"]["passes_h2_rule"]
    assert out["n"] == int(T.common_mask(df, "cfo").sum())
    # the twin's row is the verdict's statistic on the common sample
    v = T.h2_verdict(
        T.h2_inputs(df[T.common_mask(df, "cfo")].reset_index(drop=True), firms[T.common_mask(df, "cfo")], 30),
        T.encompassing(df[T.common_mask(df, "cfo")].reset_index(drop=True), "cfo", lad=False),
    )
    assert v["twin_vs_each_null_ci_low"]["N3"] == pytest.approx(c["T1"]["incremental"]["N3"]["ci"][0])
    assert v["encompassing_p_twin"] == pytest.approx(c["T1"]["encompassing"]["p"])


# ---------------------------------------------------------------- S7 neighbouring tau values
def test_tau_neighbours_report_the_scores_around_the_choice():
    ev = {
        2017: {"choice": "tau_0.50", "n_past": 900, "median_ae": {"tau_0.25": 3.2, "tau_0.50": 3.0, "tau_inf": 3.05}},
        2018: {"choice": "tau_inf", "n_past": 950, "median_ae": {"tau_0.25": 3.3, "tau_0.50": 3.1, "tau_inf": 3.0}},
        2014: {"choice": None, "n_past": 10, "skipped": True},
    }
    out = S.tau_neighbours(ev)
    a = out["2017"]
    assert a["choice"] == 0.5 and a["below"]["tau"] == 0.25 and a["above"]["tau"] == np.inf
    assert a["above"]["gap"] == pytest.approx(0.05) and a["nearest_gap"] == pytest.approx(0.05)
    assert out["2018"]["at_grid_edge"] and "above" not in out["2018"]
    assert out["2014"]["skipped"]


# ---------------------------------------------------------------- S8
def test_r6_worst_cumulative_is_floored_at_zero():
    assert S.floor_drawdown([3.0, -2.0, np.nan]).tolist()[:2] == [0.0, -2.0]
    rows = pd.DataFrame(
        [
            {
                "ticker": "A",
                "year": 2015,
                "st": {
                    "rev": [25.0] * 8,
                    "real_cfo": [1.0] * 8,
                    "real_fcf": [-1.0] * 8,
                    "m": {"cfo4": 0.04, "fcf4": -0.04},
                },
            }
        ]  # fmt: skip
    )
    f = T.frame(rows)
    assert f["real_cfo_wraw"].iloc[0] == 1.0 and f["real_cfo_w"].iloc[0] == 0.0
    assert f["real_fcf_w"].iloc[0] == f["real_fcf_wraw"].iloc[0] == -8.0


def test_r9_plan2_calibration_uses_filing_dates():
    rng = np.random.default_rng(3)
    rows, feats = [], []
    origins = pd.date_range("2012-02-15", periods=10, freq="365D")
    for i in range(80):
        for o in origins:
            t = o + pd.Timedelta(days=60)
            q = sorted(rng.normal(0, 1, 5))
            rows.append({"ticker": f"F{i}", "var": "revenue", "q": q, "origin": o, "target": t, "y": rng.normal(),
                         "year": o.year, "filed": t + pd.Timedelta(days=400)})  # fmt: skip
            feats.append({"ticker": f"F{i}", "year": o.year, "log_rev": rng.normal(), "rev_vol": rng.uniform()})
    fc, panel = pd.DataFrame(rows), pd.DataFrame(feats)
    a = plan2.calibration(fc, panel, False)
    b = plan2.calibration(fc, panel, True)
    assert a["revenue"]["n"] > b["revenue"]["n"]  # filed a year late: fewer errors seen at each origin


def test_r13_one_log_score():
    p, y = np.array([0.0, 1.0, 0.5]), np.array([1.0, 1.0, 0.0])
    assert distress.log_score is S.log_score and distress.brier is S.brier
    expected = -np.mean([np.log(1e-4), np.log(1 - 1e-4), np.log(0.5)])
    assert S.log_score(p, y) == pytest.approx(expected)


def test_r16_sobol_caps_are_counted():
    sb = {
        "median_ae": {
            "indices": [{"S1": -0.1, "ST": 1.2, "ST_ci": [0.5, 1.4]}, {"S1": 0.2, "ST": 0.3, "ST_ci": [0.1, 0.5]}]
        }
    }
    c = S.sobol_caps(sb)
    assert c["boot_draws"] == 500 and c["firm_year_resamples"] == 200 and c["capped"]
    assert c["clipped_median_ae"] == {"S1_below_0": 1, "ST_below_0": 0, "ST_above_1": 1, "S1_above_ST": 0,
                                      "ST_ci_outside_0_1": 1, "n_indices": 2}  # fmt: skip


def test_tau_section_reads_the_first_pass_table(tmp_path):
    import json

    (tmp_path / "_selection").mkdir()
    ev = {"2017": {"choice": "tau_0.50", "median_ae": {"tau_0.25": 3.2, "tau_0.50": 3.0}}}
    (tmp_path / "_selection" / "v3.json").write_text(json.dumps({"tau_evidence": ev}), encoding="utf-8")
    assert S.tau_section(tmp_path / "v3-wf")["tau"]["2017"]["below"]["median_ae"] == 3.2
    assert "missing" in S.tau_section(tmp_path / "v2-pre")
