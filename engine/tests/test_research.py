import numpy as np
import pandas as pd
import pytest

from fintwin.data.edgar import ticker_to_cik
from fintwin.model.sd_model import simulate
from fintwin.research.stats import auc, pct, rho
from fintwin.scenarios.presets import DEFAULT_LEVERS, PRESETS, build_scenario
from fintwin.stochastic.shocks import draw_shocks
from fintwin.universe import classify


def test_auc_and_ranks():
    y = np.array([0, 0, 1, 1, 0, 1], float)
    assert auc(np.array([1, 2, 5, 6, 3, 4.0]), y) == 1.0
    assert auc(-np.array([1, 2, 5, 6, 3, 4.0]), y) == 0.0
    assert np.isnan(auc(np.ones(3), np.zeros(3)))
    assert pct(np.array([3.0, np.nan, 1.0]))[1] != pct(np.array([3.0, np.nan, 1.0]))[1]  # NaN preserved
    assert rho(np.arange(10.0), np.arange(10.0) ** 2) > 0.99


def test_loop_switches_default_on_and_bite(params):
    scn = build_scenario(PRESETS["pandemic"]["knobs"], 12)
    eps = draw_shocks(params, 300, 12, seed=1)
    base = simulate(params, scn, eps, DEFAULT_LEVERS)
    same = simulate(params, scn, eps, {**DEFAULT_LEVERS, "loop_r1": True, "loop_r2": True})
    assert np.array_equal(base["cash"], same["cash"])  # the product never changes
    off = simulate(params, scn, eps, {**DEFAULT_LEVERS, "loop_r1": False, "loop_r2": False})
    assert np.abs(off["identity_gap"]).max() < 1e-6


def test_delisted_lookup_is_offline():
    assert ticker_to_cik("HTZ~2020") == (1657853, "Hertz Global Holdings")
    assert classify("CHK~2020")[0] == "Energy"


def _synthetic_research(tmp_path, n=160, bankrupt=12):
    """Research JSONs where a latent fragility drives the twin's score, realized burn and bankruptcy."""
    import json

    rng = np.random.default_rng(0)
    sectors = ["Energy", "Manufacturing", "Shops", "Business Equipment"]
    keys = (
        "z2",
        "o_score",
        "zmijewski",
        "nd_ebitda",
        "icr",
        "cash_rev",
        "current_ratio",
        "static_cover",
        "rev_vol",
        "fixed_share",
        "due_cash",
        "health_t0",
        "fcf_margin",
        "capex_rev",
    )
    bk_dates = {}
    for i in range(n + bankrupt):
        bk = i >= n
        frag = rng.uniform(0.75, 1.0) if bk else rng.uniform()
        if bk:
            bk_dates[1000 + i] = [pd.Timestamp("2020-06-01")]
        h = 80 - 70 * frag + rng.normal(0, 8)
        feats = {k: float(rng.normal()) for k in keys} | {"log_rev": 21.0 + rng.normal()}
        run = {"health": h, "p_breach": float(frag > 0.7), "health_p10": h - 10}
        rev = np.full(8, 25.0)
        real = (0.1 - 0.1 * frag) * rev + rng.normal(0, 0.3, 8)
        st = {
            "rev": rev.tolist(),
            "real_cfo": real.tolist(),
            "real_fcf": (real - 1).tolist(),
            "m": {f"{v}{k}": 0.05 for v in ("cfo", "fcf") for k in (4, 8, 16)},
            **{
                f"{m}_{v}": ((0.1 - 0.1 * frag) * rev + rng.normal(0, 0.3, 8)).tolist()
                for m in ("ols", "dyn", "twin", "noloops")
                for v in ("cfo", "fcf")
            },
            "events": {
                "cash_half": bool(frag > 0.6),
                "debt_raise": bool(rng.uniform() < frag),
                "div_cut": bool(frag > 0.7),
                "capex_cut": bool(rng.uniform() < 0.3),
            },
            "probs": {
                a: {"cash_half": frag, "debt_raise": frag, "div_cut": frag, "capex_cut": 0.3}
                for a in ("full", "no_r1", "no_r2", "no_b1", "no_b2", "no_loops")
            },
            "static": {"cash_min": 1 - frag, "fin_need": frag, "div_pressure": frag, "rev4": 1.0},
            "sens": {
                "revolver_low": {"cfo": real.tolist(), "fcf": real.tolist(), "health": h, "probs": {"cash_half": frag}}
            },
        }
        rec = {
            "ticker": f"CIK{1000 + i:010d}",
            "cik": 1000 + i,
            "bankrupt_2020": False,
            "errors": {},
            "covid": {
                "ticker": f"CIK{1000 + i:010d}",
                "name": f"Firm {i}",
                "sector": sectors[i % 4],
                "scenarios": {
                    k: run for k in ("base", "rates_200", "sales_20", "recession", "pandemic", "credit_crunch")
                },
                "ablations": {k: run for k in ("full", "no_r1", "no_r2", "no_b1", "no_b2", "no_loops")},
                "sector_adjusted": run,
                "features": feats,
                "depth_grid": {f"{d:.2f}": h - 50 * d for d in (0.0, 0.2, 0.5, 0.8)},
                "realized": {}
                if bk
                else {
                    "burn": float(-30 * frag + rng.normal(0, 4)),
                    "abn_burn": float(-10 * frag + rng.normal(0, 4)),
                    "rev_drop": float(-60 * rng.uniform()),
                    "debt_raise": 1.0,
                    "cash_min_ratio": 1.0,
                    "div_payer": True,
                    "div_cut": bool(frag > 0.6),
                },
                "structural": {} if bk else st,
            },
            "panel": [
                {
                    "origin": f"{y}-02-15",
                    "base": run,
                    "recession": run,
                    "base_no_loops": run,
                    "features": feats,
                    "outcome": {
                        "burn8": float(-30 * frag + rng.normal(0, 6)),
                        "abn_burn8": float(-10 * frag + rng.normal(0, 6)),
                        "icr0": 3.0,
                        "icr_min": float(4 - 4 * frag),
                        "div_payer": True,
                        "div_cut": bool(rng.uniform() < frag / 2),
                    },
                    "structural": st,
                }
                for y in range(2013, 2025)
                if not (bk and y > 2020)
            ],
            "forecasts": []
            if bk
            else [
                {
                    "origin": f"{yr}-02-15",
                    "var": v,
                    "h": h_,
                    "scale": 100.0,
                    "crps_twin": float(rng.uniform(1, 2)),
                    "crps_rw": float(rng.uniform(1.5, 2.5)),
                    "crps_ets": float(rng.uniform(1.5, 2.5)),
                    "pit_ets": 0.5,
                    "y": float(100 + rng.normal(0, 10)),
                    "q": [84.0, 93.0, 100.0, 107.0, 116.0],
                    "pit_twin": float(rng.uniform()),
                    "target": f"{yr - 1}-{3 * h_:02d}-28",
                }
                for yr in range(2015, 2022)
                for v in ("revenue", "cash_like")
                for h_ in range(1, 5)
            ],
        }
        (tmp_path / f"CIK{1000 + i:010d}.json").write_text(json.dumps(rec))
    return tmp_path, bk_dates


@pytest.mark.slow
def test_stats_pipeline_recovers_planted_signal(tmp_path, monkeypatch):
    import fintwin.research.stats as st

    monkeypatch.setattr(st, "OUT", tmp_path / "research.json")
    monkeypatch.setattr(st, "B", 50)
    monkeypatch.setattr(st, "B_PANEL", 30)
    cache, bk = _synthetic_research(tmp_path)
    monkeypatch.setattr(st, "bankruptcy_dates", lambda: bk)
    res = st.main(cache)
    c = res["covid"]["edgar"]
    assert c["predictors"]["twin"]["rho"] > 0.6 and abs(c["predictors"]["altman_z2"]["rho"]) < 0.3
    assert c["regression"]["t"]["twin"] > 3
    assert res["bankruptcy_2020"]["all"]["events"] == 12
    assert res["bankruptcy_2020"]["all"]["predictors"]["twin"]["auc"] > 0.7
    sb = res["panel"]["severe_burn"]
    assert sb["univariate"]["twin"]["auc"] > 0.8
    assert sb["out_of_sample"]["benchmarks_plus_twin"]["auc"] > sb["out_of_sample"]["benchmarks"]["auc"]
    tr = res["transmission"]["panel"]
    assert tr["cfo"]["levels"]["T1"]["rho"] > 0.5 and "verdict" in tr
    assert tr["decisions"]["cash_half"]["auc"]["twin"] > 0.9
    assert res["calibration"]["revenue"]["n"] > 0
    assert res["forecasts"]["revenue"]["ets"]["skill_scaled"] > 0
    assert (tmp_path / "research.json").exists()


def test_health_at_open_is_a_valid_score_near_the_first_simulated_quarter(params):
    from fintwin.research.experiments import health_at_open

    h0 = health_at_open({**params, "sector_tol": 1.0})
    assert 0 <= h0 <= 100
    out = simulate(
        {**params, "sigma_g": 0.0, "sigma_m": 0.0, "sigma_r": 0.0, "sigma_fin": 0.0},
        build_scenario({}, 4),
        np.zeros((1, 4, 5)) + [0, 0, 0, 0, 0.99],
        DEFAULT_LEVERS,
    )
    assert abs(out["health"][0, 0] - h0) < 6  # one quarter of steady-state dynamics: 4.5 points for this company
