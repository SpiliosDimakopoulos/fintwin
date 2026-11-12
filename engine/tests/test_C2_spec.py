"""C2: specification switches, the ladder's cache layout, v2-pre identity, dry runs and shard records."""

import json

import numpy as np
import pandas as pd
import pytest
from conftest import make_params
from test_C2_synth import quarters, split

from fintwin.research import experiments as X


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("FINTWIN_SPEC", "FINTWIN_FIXES", "FINTWIN_SELECTION", "FINTWIN_DATA_LEGACY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(X, "_spec_mod", None)  # test the local fallback's semantics


def test_spec_fallback_semantics(monkeypatch):
    monkeypatch.setenv("FINTWIN_SPEC", "v2-pre")
    assert not any(X.fix_active(f) for f in (*X.MODEL_FIXES, "E1"))
    assert X.research_prior() == X.SPECIFIED_FIXED_SHARE_PRIOR
    monkeypatch.setenv("FINTWIN_SPEC", "v3")
    assert all(X.fix_active(f) for f in (*X.MODEL_FIXES, "E1"))
    assert not X.fix_active("SW17")  # opt-in only
    monkeypatch.setenv("FINTWIN_FIXES", "F5, mm-F4")  # FIXES replaces the spec's set
    assert X.fix_active("F5") and X.fix_active("F4") and not X.fix_active("F1") and not X.fix_active("E1")
    monkeypatch.setenv("FINTWIN_SPEC", "v2-rev")
    monkeypatch.delenv("FINTWIN_FIXES")
    assert X.research_prior() == X.FIXED_SHARE_PRIOR == 0.05
    monkeypatch.setenv("FINTWIN_SPEC", "v4")
    with pytest.raises(ValueError):
        X.spec_name()


def test_ladder_rungs_get_distinct_cache_dirs(monkeypatch):
    from fintwin.research.__main__ import ROOT, spec_dir

    names, dirs = [], []
    for _name, env in X.LADDER:
        for k in ("FINTWIN_SPEC", "FINTWIN_FIXES"):
            monkeypatch.delenv(k, raising=False)
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        names.append(X.spec_label())
        dirs.append(spec_dir())
    assert names == [n for n, _ in X.LADDER]  # the directory is the rung's name
    assert len(set(dirs)) == len(dirs) and all(d.parent == ROOT for d in dirs)
    assert names[:6] == ["v2-pre", "v2-pre+F5", "v2-pre+F5+F4", "v2-pre+F5+F4+F1", "v2-pre+F5+F4+F1+F2", "v3"]
    monkeypatch.setenv("FINTWIN_SELECTION", "x.json")
    assert X.spec_label().endswith("-wf")  # the walk-forward pass never overwrites the grid pass
    from fintwin.research.__main__ import run_tag

    assert spec_dir(run_tag(300, {2015, 2020, 2022})).name.endswith("-wf_s300_c2015.2020.2022")
    assert run_tag() == "" and run_tag(1000) == "_s1000" and run_tag(None, {2020}) == "_c2020"


# Outputs of the code before revision 3 on the synthetic firm (structural / _run / _distress on commit 20b2610, before any C2 change).
GOLD_TWIN_CFO = [6.3665, 5.3003, 5.7342, 5.7692, 6.0168, 6.5974, 6.7598, 6.6965]
GOLD_TWIN_FCF = [4.8191, 3.6246, 4.1379, 4.2312, 4.4306, 4.8882, 5.0705, 5.042]
GOLD_NOLOOPS_CFO = [6.3665, 5.299, 5.7315, 5.7664, 6.0133, 6.5941, 6.7567, 6.6936]
GOLD_RUN = {"health": 74.86585333378704, "p_breach": 0.0, "health_p10": 65.65168852225047}
GOLD_RUN_STRESSED = {"health": 64.61431411553643, "p_breach": 0.0, "health_p10": 49.427428991521104}
GOLD_DISTRESS = {
    "burn8": 2.6145428518679257,
    "cum8": 21.53216296977993,
    "abn_cum8": 0.655775625623928,
    "abn_burn8": -0.4097230826850452,
    "icr0": 6.9813193280973875,
    "icr_min": 7.067142529809002,
    "div_payer": True,
    "div_cut": False,
    "rev_drop8": 2.000771590606165,
}


@pytest.mark.parametrize("legacy", [False, True])
def test_v2_pre_outputs_identical_to_pre_revision_code(monkeypatch, legacy):
    from fintwin.scenarios.presets import PRESETS

    monkeypatch.setenv("FINTWIN_SPEC", "v2-pre")
    if legacy:  # the comparison run: v2-pre on the revision-2 data layer
        monkeypatch.setenv("FINTWIN_DATA_LEGACY", "1")
    hist, full = split(quarters(), "2018-02-15")
    p = {**make_params(), "sector_tol": 1.0}
    st = X.structural(hist, p, full, None)
    assert st["twin_cfo"] == GOLD_TWIN_CFO and st["twin_fcf"] == GOLD_TWIN_FCF
    assert st["noloops_cfo"] == GOLD_NOLOOPS_CFO
    assert st["twin_cfo_point"] == st["twin_cfo_sm"] == round(sum(GOLD_TWIN_CFO), 4)  # v2-pre point: sum of medians
    r = X._run(p, {}, {}, 300, 12, 5)
    assert {k: r[k] for k in GOLD_RUN} == GOLD_RUN
    p2 = {**make_params(cash0=60.0, revolver_cap=20.0, cash_floor=10.0), "sector_tol": 1.0}
    r2 = X._run(p2, PRESETS["recession"]["knobs"], {}, 400, 12, 5)
    assert {k: r2[k] for k in GOLD_RUN_STRESSED} == GOLD_RUN_STRESSED
    d = X._distress(hist, full)
    assert {k: d[k] for k in GOLD_DISTRESS} == GOLD_DISTRESS


def _patch_company(monkeypatch, q):
    params = make_params()

    def load(ticker, asof=None, min_year=2010):
        return split(q, asof)[0] if asof else split(q, "2030-01-01")[0]

    monkeypatch.setattr(X, "load_company", load)
    monkeypatch.setattr(X, "data_vintage", lambda cik: {"facts_sha256": None})
    monkeypatch.setattr(X, "first_filed", lambda cik: {"revenue": pd.Series(dtype="datetime64[ns]")})
    monkeypatch.setattr(X, "credit_events", lambda cik: {"1.03": [], "2.04": [], "3.01": ["2019-05-01"]})
    monkeypatch.setattr(
        X, "calibrate", lambda hist, macro, horizon=12, assumptions=None: {**params, "horizon": horizon}
    )
    monkeypatch.setattr(X, "macro_quarterly", lambda asof=None: pd.DataFrame())
    monkeypatch.setattr(X, "SENSITIVITY", {"revolver_low": X.SENSITIVITY["revolver_low"]})


def test_company_records_spec_failures_and_restricts_cutoffs(monkeypatch):
    monkeypatch.setenv("FINTWIN_SPEC", "v3")
    _patch_company(monkeypatch, quarters())
    res = X.company("CIK0000000001", with_forecasts=False, years={2018})
    assert [r["origin"] for r in res["panel"]] == ["2018-02-15"]
    assert "covid" not in res  # 2020 not among the dry-run cutoffs
    assert res["spec"]["name"] == "v3" and "E1" in res["spec"]["fixes"] and res["spec"]["label"] == "v3"
    row = res["panel"][0]
    assert set(row["liquidity"]) == {"grid", "recession", "base"}
    assert len(row["liquidity"]["grid"]) == len(X.DEPTHS)
    assert res["credit_events"]["3.01"] == ["2019-05-01"]
    assert res["failures"]["panel"]["n"] == 1 and not res["failures"]["panel"]["failed"]
    json.dumps(res, default=float)  # serializable


def test_shard_writes_spec_dir_and_dry_dir(monkeypatch, tmp_path):
    import fintwin.research.__main__ as M

    monkeypatch.setenv("FINTWIN_SPEC", "v2-pre")
    monkeypatch.setattr(M, "ROOT", tmp_path)
    monkeypatch.setattr(M, "research_tickers", lambda: [f"CIK{i:010d}" for i in range(1, 11)])
    monkeypatch.setattr(M, "forecast_ciks", lambda: set())
    seen = []

    def fake_company(t, with_forecasts=True, years=None):
        seen.append((t, years))
        return {"ticker": t, "panel": [], "errors": {}, "failures": {}}

    monkeypatch.setattr(X, "company", fake_company)
    d = M.shard(0, 1, limit=3, years={2015, 2020, 2022})
    assert d == tmp_path / "v2-pre_s3_c2015.2020.2022"
    files = sorted(d.glob("*.json"))
    assert len(files) == 3 and all(y == {2015, 2020, 2022} for _, y in seen)
    rec = json.loads(files[0].read_text(encoding="utf-8"))
    assert rec["_run"] == M.run_record(3, {2015, 2020, 2022}) and rec["_run"]["machine"] and rec["_stamp"] == M.stamp()
    assert M.dry_tickers(3) == M.dry_tickers(3)  # same firms in every rung
    seen.clear()
    M.shard(0, 1, limit=3, years={2015, 2020, 2022})
    assert seen == []  # resumable under the same stamp
    # another restricted run (same firms, all cutoffs) has its own directory and does not resume into the first
    d2 = M.shard(0, 1, limit=3)
    assert d2 == tmp_path / "v2-pre_s3" and len(seen) == 3 and all(y is None for _, y in seen)


def test_stats_refuses_mixed_runs_and_incomplete_dirs(monkeypatch, tmp_path):
    import fintwin.research.__main__ as M
    import fintwin.research.analysis as A

    monkeypatch.setenv("FINTWIN_SPEC", "v2-pre")
    monkeypatch.setattr(M, "ROOT", tmp_path)
    monkeypatch.setattr(M, "research_tickers", lambda: [f"CIK{i:010d}" for i in range(1, 11)])
    d = M.spec_dir("_s3")
    d.mkdir(parents=True)
    keys = M.dry_tickers(3)
    for t in keys[:2]:
        (d / f"{t}.json").write_text(json.dumps({"_stamp": M.stamp(), "_run": M.run_record(3)}))
    with pytest.raises(SystemExit, match="incomplete"):
        A.stats(3)
    (d / f"{keys[2]}.json").write_text(json.dumps({"_stamp": M.stamp(), "_run": M.run_record(3, {2020})}))
    with pytest.raises(SystemExit, match="another run"):
        A.stats(3)


def test_select_refuses_an_empty_run(monkeypatch, tmp_path):
    import fintwin.research.__main__ as M

    monkeypatch.setenv("FINTWIN_SPEC", "v3")
    monkeypatch.setattr(M, "ROOT", tmp_path)
    monkeypatch.setattr(M, "research_tickers", lambda: [f"CIK{i:010d}" for i in range(1, 11)])
    with pytest.raises(SystemExit, match="no shards"):
        M.select(3)
    d = M.spec_dir("_s3")
    d.mkdir(parents=True)
    t = M.dry_tickers(3)[0]
    (d / f"{t}.json").write_text(json.dumps({"_stamp": M.stamp(), "_run": M.run_record(3)}))
    with pytest.raises(SystemExit, match="incomplete"):  # a grid pass cut short gives no table
        M.select(3)
    assert M.selection_path("v3", "_s1000").name == "v3_s1000.json"


def test_stamp_ignores_the_selection_path_but_not_its_content(monkeypatch, tmp_path):
    import fintwin.research.__main__ as M

    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text("{}"), b.write_text("{}")
    monkeypatch.setenv("FINTWIN_SELECTION", str(a))
    s1 = M.stamp()
    monkeypatch.setenv("FINTWIN_SELECTION", str(b))
    assert M.stamp() == s1  # same table on another machine / path
    b.write_text('{"tau": 1}')
    assert M.stamp() != s1


def test_cli_options():
    from fintwin.research.__main__ import _opts

    pos, opt = _opts(["shard", "2", "8", "--limit", "300", "--cutoffs", "2015,2020,2022"])
    assert pos == ["shard", "2", "8"] and opt == {"limit": "300", "cutoffs": "2015,2020,2022"}
    assert _opts(["stats", "--limit", "300"])[1] == {"limit": "300"}


def test_stamp_changes_with_selection_content(monkeypatch, tmp_path):
    from fintwin.research.__main__ import stamp

    sel = tmp_path / "sel.json"
    sel.write_text('{"tau": {"2018": 0.1}}', encoding="utf-8")
    monkeypatch.setenv("FINTWIN_SELECTION", str(sel))
    a = stamp()
    sel.write_text('{"tau": {"2018": 0.25}}', encoding="utf-8")
    assert stamp() != a


def test_check_failures_refuses_high_failure_share():
    from fintwin.research.__main__ import check_failures

    ok = [{"failures": {"forecast": {"n": 100, "failed": {"ValueError": 3}, "skipped": {}}}}]
    assert check_failures(ok)["forecast"]["failed_share"] == pytest.approx(0.03)
    bad = [{"failures": {"forecast": {"n": 100, "failed": {"ValueError": 30}, "skipped": {}}}}]
    with pytest.raises(SystemExit):
        check_failures(bad)


def test_realtime_recession_uses_announcement_dates(monkeypatch):
    # the final NBER record says the 2020 recession ended in April 2020; on 15 Feb 2021 that was not yet announced
    assert X.realtime_recession("2021-02-15") is True
    assert X.realtime_recession("2022-02-15") is False
    assert X.realtime_recession("2020-02-15") is False
    assert X.realtime_recession("2009-02-15") is True
    assert X.realtime_recession("2005-02-15") is None
    monkeypatch.setenv("FINTWIN_FIXES", "SW17")
    monkeypatch.setattr(X, "_calibrate", lambda c, m, h, a: {"rec_state0": 0.0})
    monkeypatch.setattr(X, "spreads_asof", lambda asof: None)
    hist, _ = split(quarters(60), "2021-02-15")
    assert X.calibrate(hist, pd.DataFrame())["rec_state0"] == 1.0


def test_macro_and_spreads_read_once_per_cutoff(monkeypatch):
    calls = []
    X._macro_cached.cache_clear()
    monkeypatch.setattr(X, "_macro_quarterly", lambda asof=None: calls.append(asof) or pd.DataFrame({"a": [1.0]}))
    a = X.macro_quarterly("2018-02-15")
    a.loc[0, "a"] = 99.0  # callers get a copy: the cache cannot be altered
    b = X.macro_quarterly("2018-02-15")
    assert calls == ["2018-02-15"] and b.loc[0, "a"] == 1.0
    X._macro_cached.cache_clear()


def test_selection_feeds_calibration(monkeypatch, tmp_path):
    sel = tmp_path / "sel.json"
    sel.write_text(json.dumps({"tau": {"2018": 0.25}, "lambda": {"2018": 0.2}}), encoding="utf-8")
    monkeypatch.setenv("FINTWIN_SELECTION", str(sel))
    X._selection.cache_clear()
    seen = {}
    monkeypatch.setattr(X, "_calibrate", lambda c, m, h, a: seen.update(a) or {})
    monkeypatch.setattr(X, "spreads_asof", lambda asof: None)
    hist, _ = split(quarters(), "2018-02-15")
    X.calibrate(hist, pd.DataFrame())
    assert seen[X.WF_KEYS["tau"]] == 0.25 and seen[X.WF_KEYS["lam"]] == 0.2
    hist19, _ = split(quarters(), "2019-02-15")
    seen.clear()
    X.calibrate(hist19, pd.DataFrame())
    assert X.WF_KEYS["tau"] not in seen  # no selection for that year: B1's default
    X._selection.cache_clear()


def test_walk_forward_selection_uses_only_earlier_years():
    rng = np.random.default_rng(0)
    years = np.repeat(np.arange(2013, 2025), 600)
    real = rng.normal(0, 1, len(years))
    good = real + rng.normal(0, 0.1, len(years))
    bad = real + rng.normal(0, 1.0, len(years))
    sel = X.walk_forward_select(years, real, {"tau_0.05": bad, "tau_0.15": good}, lag=3, min_past=500)
    assert min(sel) == 2016 and all(s["choice"] == "tau_0.15" for s in sel.values())
    # making "bad" perfect in 2020 onwards cannot change the choice for 2022 (uses <= 2019 only)
    bad2 = np.where(years >= 2020, real, bad)
    sel2 = X.walk_forward_select(years, real, {"tau_0.05": bad2, "tau_0.15": good}, lag=3, min_past=500)
    assert sel2[2022]["choice"] == "tau_0.15" and sel2[2024]["choice"] == "tau_0.15"


def test_select_from_panel_builds_tables():
    rows = []
    rng = np.random.default_rng(1)
    for y in range(2013, 2025):
        for _ in range(600):
            r = float(rng.normal())
            rows.append(
                {
                    "origin": f"{y}-02-15",
                    "structural": {
                        "real_cfo": [r],
                        "e1": True,
                        "grid": {
                            "tau_0.05": {"cfo": r + 1.0},
                            "tau_0.25": {"cfo": r + 0.1},
                            "lam_0.00": {"cfo": r + 0.5},
                            "lam_0.20": {"cfo": r + 0.2},
                        },
                    },
                }
            )
    sel = X.select_from_panel(rows)
    assert sel["tau"]["2016"] == 0.25 and sel["lambda"]["2024"] == 0.2 and "2015" not in sel["tau"]


def test_wf_grid_follows_switches(monkeypatch):
    monkeypatch.setenv("FINTWIN_SPEC", "v2-pre")
    assert X.wf_grid() == {}
    monkeypatch.setenv("FINTWIN_FIXES", "F5,F4,F1")
    g = X.wf_grid()
    assert g and all(k.startswith("tau_") for k in g)
    monkeypatch.setenv("FINTWIN_SPEC", "v3")
    monkeypatch.delenv("FINTWIN_FIXES")
    assert any(k.startswith("lam_") for k in X.wf_grid())


def _fake_shard_env(monkeypatch, tmp_path):
    import fintwin.research.__main__ as M

    monkeypatch.setenv("FINTWIN_SPEC", "v2-pre")
    monkeypatch.delenv("FINTWIN_NEW_RUN", raising=False)
    monkeypatch.setattr(M, "ROOT", tmp_path)
    monkeypatch.setattr(M, "research_tickers", lambda: [f"CIK{i:010d}" for i in range(1, 11)])
    monkeypatch.setattr(M, "forecast_ciks", lambda: set())
    monkeypatch.setattr(X, "company", lambda t, with_forecasts=True, years=None: {"ticker": t, "errors": {}})
    return M


def test_shard_refuses_to_overwrite_another_stamp_or_machine(monkeypatch, tmp_path):
    # rerun 5, P2 / P3: a code change between stages, or another platform, must stop the stage, not recompute it
    M = _fake_shard_env(monkeypatch, tmp_path)
    d = M.shard(0, 1, limit=3)
    f = sorted(d.glob("*.json"))[0]
    rec = json.loads(f.read_text(encoding="utf-8"))
    f.write_text(json.dumps(rec | {"_stamp": "old-code"}), encoding="utf-8")
    with pytest.raises(SystemExit, match="another stamp"):
        M.shard(0, 1, limit=3)
    f.write_text(json.dumps(rec | {"_run": rec["_run"] | {"machine": "aarch64"}}), encoding="utf-8")
    with pytest.raises(SystemExit, match="another run"):
        M.shard(0, 1, limit=3)
    monkeypatch.setenv("FINTWIN_NEW_RUN", "1")  # deliberate recompute
    M.shard(0, 1, limit=3)
    assert json.loads(f.read_text(encoding="utf-8"))["_run"] == M.run_record(3)


def test_second_pass_refuses_a_table_from_another_grid_pass(monkeypatch, tmp_path):
    # rerun 5, P6: a table copied from a lost server (or written before a code change) must not drive the "-wf" pass
    M = _fake_shard_env(monkeypatch, tmp_path)
    table = tmp_path / "sel.json"
    table.write_text(json.dumps({"tau": {}, "lambda": {}, "_grid_stamp": "another"}), encoding="utf-8")
    monkeypatch.setenv("FINTWIN_SELECTION", str(table))
    d = M.shard(0, 1, limit=3)  # skipped, not run on a stale table (round 2: raising killed every ladder process)
    assert not list(d.glob("*.json"))
    monkeypatch.delenv("FINTWIN_SELECTION")
    good = M.grid_stamp()
    table.write_text(json.dumps({"tau": {}, "lambda": {}, "_grid_stamp": good}), encoding="utf-8")
    monkeypatch.setenv("FINTWIN_SELECTION", str(table))
    assert M.shard(0, 1, limit=3).name.endswith("_s3")
