"""Rerun 5, WP5: statistics findings of the 12-11-2026 review, each with the case that showed it."""

from __future__ import annotations

from fintwin.research import stats as S


def test_holm_family_reads_the_training_limit_combinations():
    cell = {"N3+T1_vs_N3+N1": {"p": 0.9}, "N3+T1_vs_N3+N5": {"p": 0.9}, "N3+T1_vs_N3+N6": {"p": 0.9}}
    train = {k: {"p": 0.01} for k in cell}
    res = {"transmission": {"panel": {"cfo": {"hybrid": cell, "hybrid_train": train}}}}
    p = S._secondary_pvalues(res)
    assert p["hybrid_cfo_N3+T1_vs_N3+N1"] == 0.01 and len(p) == 3


def test_liquidity_frame_drops_firm_years_inside_a_running_chapter_11(tmp_path, monkeypatch):
    # S3: B2 / B3 read `liquidity_frame`, which rebuilt rows without the D8 exclusion that `stats.main` applies
    import json

    from fintwin.research import distress as D

    def shard(cik, origin):
        return {"ticker": f"CIK{cik:010d}", "cik": cik, "credit_events": {"1.03": [], "2.04": [], "3.01": []},
                "covid": {"sector": "Manuf"},
                "panel": [{"origin": origin, "base": {"health": 50.0, "p_breach": 0.1},
                           "features": {"log_rev": 20.0}, "outcome": {},
                           "liquidity": {"grid": {}, "recession": [0.1, 0.2], "base": [0.0, 0.1]}}]}  # fmt: skip

    for cik in (1, 2):
        (tmp_path / f"{cik}.json").write_text(json.dumps(shard(cik, "2018-02-15")), encoding="utf-8")
    ts = __import__("pandas").Timestamp
    monkeypatch.setattr(S, "bankruptcy_dates", lambda: {1: [ts("2017-01-10")]})
    monkeypatch.setattr(
        S, "bankruptcy_filings", lambda: {1: [ts("2017-01-10"), ts("2018-06-01")]}
    )  # case runs past origin
    df = D.liquidity_frame(tmp_path)
    assert df["cik"].tolist() == [2] and df.attrs["in_bankruptcy_excluded"] == 1


def test_b2_gives_no_verdict_from_three_cutoff_years():
    # S2: with three blocks the percentile interval is the min / max of the yearly skills
    import numpy as np
    import pandas as pd

    from fintwin.research import distress as D

    rng = np.random.default_rng(0)
    n = 600
    df = pd.DataFrame({"year": np.repeat([2015, 2020, 2022], n // 3), "ticker": [f"T{i}" for i in range(n)]})
    for c in (*D.LOGIT_COLS, *D.Z_COLS):
        df[c] = rng.normal(size=n)
    df["origin"] = df["year"].astype(str) + "-02-15"
    df["outcome_filed"] = "2000-01-01"
    df["outcome_filed4"] = "2000-01-01"
    y = (rng.random(n) < 0.1).astype(float)
    out = D._versus(df, np.clip(rng.random(n), 0.01, 0.99), y, 8, [2015, 2020, 2022], 50)
    assert "bss_vs_logit" in out, out
    assert out["bss_vs_logit"]["year_block"]["blocks"] <= 3
    assert out["success"] is None and "cutoff years" in out["success_undefined"]
    r = D.block_ci(lambda x: float(np.mean(x)), [np.arange(9.0)], np.repeat([1, 2, 3], 3), 200)
    assert r["blocks"] == 3 < D.MIN_BLOCKS


def test_walk_forward_candidates_are_scored_on_one_common_set():
    # S5: a value that fails on the hard firm-years used to be scored on the easy ones only, and won
    import numpy as np

    from fintwin.research import experiments as X

    years = np.repeat([2014, 2015, 2016, 2017, 2018], 100)
    real = np.zeros(len(years))
    hard = np.tile(np.arange(100) < 60, 5)  # most firm-years are hard
    a = np.where(hard, 5.0, 1.0)  # finite everywhere: median error 5 over all rows, 1 on the easy ones
    b = np.where(hard, np.nan, 1.5)  # fails on every hard row, error 1.5 on the easy ones
    sel = X.walk_forward_select(years, real, {"tau_0.10": a, "tau_0.25": b}, lag=3, min_past=30)
    assert sel[2017]["choice"] == "tau_0.10"  # on the common rows a (1.0) beats b (1.5); per-own-set picked b
    assert sel[2017]["n_past"] == 40 and sel[2017]["n_excluded"] == {"tau_0.10": 0, "tau_0.25": 60}


def test_walk_forward_records_a_year_lost_to_a_failing_grid_value():
    # round 2, N2: with one value failing on most firm-years, the year used to fall back to the defaults silently
    import numpy as np

    from fintwin.research import experiments as X

    years = np.repeat([2014, 2015, 2016, 2017, 2018], 100)
    real = np.zeros(len(years))
    a = np.ones(len(years))
    b = np.where(np.tile(np.arange(100) < 90, 5), np.nan, 1.0)  # fails on 90% of firm-years
    sel = X.walk_forward_select(years, real, {"tau_0.10": a, "tau_0.25": b}, lag=3, min_past=50)
    assert sel[2017]["skipped"] and sel[2017]["choice"] is None and sel[2017]["n_excluded"]["tau_0.25"] == 90
    rows = [{"origin": f"{y}-02-15", "structural": {"real_cfo": [0.0], "e1": True,
             "grid": {"tau_0.10": {"cfo": 1.0}, "tau_0.25": {"cfo": None if i % 10 else 1.0}}}}
            for y in (2014, 2015, 2016, 2017, 2018) for i in range(600)]  # fmt: skip
    tab = X.select_from_panel(rows)
    assert tab["tau_skipped"] == ["2017", "2018"] and "2017" not in tab["tau"]
