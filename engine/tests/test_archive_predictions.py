"""B4 archive and scorer rules: determinism, schema, immutability, hash chain, tree hash, ADR-003 status rules.
Needs pyarrow (skipped when absent)."""

import datetime as dt
import hashlib
import importlib.util
import json
import os
import shutil
import tempfile
from pathlib import Path

import pytest

pa = pytest.importorskip("pyarrow")
import pyarrow.parquet as pq  # noqa: E402

_S = Path(__file__).parents[1] / "scripts"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _S / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


ap = _load("archive_predictions")
sc = _load("score_predictions")

_UNIV = Path(tempfile.mkdtemp()) / "universe.csv"
_UNIV.write_text(
    "\n".join([
        "key,cik,name,ticker,sic,industry,fy_end,first_year,last_year,last_periodic,bankruptcy_8k",
        "A,100,A,,1.0,x,1231,2012.0,2024.0,2026-09-29,",
        "B,200,B,,1.0,x,1231,2012.0,2020.0,2020-04-01,2020-05-12",
    ]) + "\n"
)
KW = dict(built_at="2026-10-26T07:00:00Z", git_sha="abc123", engine_version="3.0.0.dev0", first=True,
          universe_csv=_UNIV)


def _company(cik, ticker, cash=100.0, fcf=-10.0, byq=None):
    return {
        "ticker": ticker, "cik": cik, "params": {"last_quarter": "2026-06-30", "horizon": 12},
        "presets": {"base": {"health_score": 50.0, "p_breach": 0.3, "p_icr_below_1_5": 0.2, "p_downgrade_below_ig": 0.1,
                             "p_breach_by_q": [0.01 * i for i in range(1, 13)] if byq is None else byq}},
        "history": {"series": {"cash": [cash] * 4, "fcf": [fcf] * 4, "icr": [2.0] * 4, "nd_ebitda": [3.0] * 4,
                               "ebitda": [5.0] * 4, "rating": [5.0, 5.0, 0.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0]}},
    }


def _make_data(d, generated="2026-10-26"):
    (d / "companies").mkdir(parents=True)
    (d / "index.json").write_text(json.dumps({"meta": {"generated": generated}}))
    for cik, t in ((300, "CCC"), (100, "AAA"), (200, "BBB")):  # reverse order on purpose
        (d / "companies" / f"{t}.json").write_text(json.dumps(_company(cik, t)))
    return d


@pytest.fixture
def data(tmp_path):
    return _make_data(tmp_path / "data")


def test_schema_sorted_and_values(data, tmp_path):
    p, m = ap.archive(data, tmp_path / "out", **KW)
    assert p.name == "predictions_2026-44.parquet" and m.name == "manifest_2026-44.json"
    t = pq.read_table(p)
    assert t.column_names == [n for n, _ in ap.COLUMNS]
    assert t.column("cik").to_pylist() == [100, 200, 300]
    assert t.column("p_breach_4q").to_pylist()[0] == pytest.approx(0.04)
    assert t.column("bl_runway_risk").to_pylist()[0] == pytest.approx(1 / (1 + 100 / 10))
    mf = json.loads(m.read_text())
    assert mf["rows"] == 3 and mf["data_release"] == "2026.44" and mf["round"] == "2026Q4"
    assert mf["sha256"] == hashlib.sha256(p.read_bytes()).hexdigest()
    assert "liquidity_floor_breach" in mf["targets"]["p_breach_*"]
    br = mf["base_rates"]["stratum"]["4q"]
    assert (br["events"], br["origins"]) == (4, 85) and mf["base_rates"]["t2a_reference"] is None
    assert "icr_d_proxy_rate" in mf["diagnostics"] and "base_rate_t1_4q" in t.column_names
    assert mf["inputs_tree_sha256"] and mf["inputs_zip_sha256"] and mf["prev_sha256"] is None and mf["prev_note"]


def test_deterministic(data, tmp_path):
    p1, m1 = ap.archive(data, tmp_path / "a", **KW)
    p2, m2 = ap.archive(data, tmp_path / "b", **KW)
    assert p1.read_bytes() == p2.read_bytes()
    assert (tmp_path / "a" / "inputs_2026-44.zip").read_bytes() == (tmp_path / "b" / "inputs_2026-44.zip").read_bytes()
    assert m1.read_text() == m2.read_text()


def test_refuses_overwrite(data, tmp_path):
    out = tmp_path / "out"
    ap.archive(data, out, **KW)
    with pytest.raises(SystemExit, match="refusing to overwrite"):
        ap.archive(data, out, **KW)


def test_needs_prev_or_first(data, tmp_path):
    with pytest.raises(SystemExit, match="--prev-manifest"):
        ap.archive(data, tmp_path / "o", built_at="x", git_sha="y", engine_version="z", universe_csv=_UNIV)


def test_tree_hash_deterministic_and_sensitive(data, tmp_path):
    h = ap.tree_sha256(data)
    copy = tmp_path / "copy"
    shutil.copytree(data, copy)
    os.utime(copy / "companies" / "AAA.json", (1, 1))  # mtime must not matter
    assert ap.tree_sha256(copy) == h
    f = copy / "companies" / "BBB.json"
    f.write_text(f.read_text() + " ")  # one byte changes the tree
    assert ap.tree_sha256(copy) != h


def test_hash_chain(tmp_path):
    out = tmp_path / "out"
    d1 = _make_data(tmp_path / "d1", "2026-10-26")
    d2 = _make_data(tmp_path / "d2", "2026-11-02")
    d3 = _make_data(tmp_path / "d3", "2026-11-09")
    _, m1 = ap.archive(d1, out, **KW)
    _, m2 = ap.archive(d2, out, built_at="t", git_sha="g", engine_version="v", prev_manifest=m1, universe_csv=_UNIV)
    _, m3 = ap.archive(d3, out, built_at="t", git_sha="g", engine_version="v", prev_manifest=m2, universe_csv=_UNIV)
    mf2 = json.loads(m2.read_text())
    assert mf2["prev_sha256"] == hashlib.sha256(m1.read_bytes()).hexdigest() and mf2["prev_week"] == "2026-44"
    assert ap.verify_chain([m1, m2, m3]) == []
    assert ap.verify_chain([m1, m3])  # week 45 deleted -> detected
    m2.write_text(m2.read_text().replace("\"rows\": 3", "\"rows\": 4"))  # altered manifest -> detected
    assert any("does not match" in p for p in ap.verify_chain([m1, m2, m3]))


def test_no_fallback_for_12q(tmp_path):
    d = tmp_path / "d"
    _make_data(d)
    (d / "companies" / "AAA.json").write_text(json.dumps(_company(100, "AAA", byq=[0.1] * 6)))  # only 6 quarters
    p, _ = ap.archive(d, tmp_path / "o", **KW)
    t = pq.read_table(p).to_pydict()
    i = t["cik"].index(100)
    assert t["p_breach_12q"][i] is None and t["p_breach_8q"][i] is None and t["p_breach_4q"][i] == pytest.approx(0.1)


# ---- scorer: ADR-003 section 3 rules ----
ASOF = dt.date(2026, 1, 5)
END = ASOF + dt.timedelta(days=91 * 4)


def _ev(cik, days, items):
    return {"cik": cik, "filed": ASOF + dt.timedelta(days=days), "items": set(items)}


def test_status_rules():
    def st(cik, ev, ex=None, target="T1"):
        return sc.row_status(cik, ASOF, END, ev, ex or {}, target)

    assert st(1, [_ev(1, 30, ["1.03"])]) == "event"
    assert st(1, []) == "survived"
    # prior case: a 1.03 within the 730 days before asof excludes the row, even if a new one follows
    assert st(1, [_ev(1, -400, ["1.03"]), _ev(1, 30, ["1.03"])]) == "excluded_prior_case"
    assert st(1, [_ev(1, -800, ["1.03"])]) == "survived"
    # T2a: 2.04 alone counts, 2.04 with 2.01 or 5.01 does not; T1 never counts 2.04
    assert st(1, [_ev(1, 30, ["2.04"])], target="T2a") == "event"
    assert st(1, [_ev(1, 30, ["2.04"])], target="T1") == "survived"
    assert st(1, [_ev(1, 30, ["2.04", "2.01"])], target="T2a") == "survived"
    assert st(1, [_ev(1, 30, ["3.01", "5.01"])], target="T2a") == "survived"
    # exits: acquired is not a negative; unknown is its own status; an event beats an exit
    ex = {1: (ASOF + dt.timedelta(days=60), "acquired"), 2: (ASOF + dt.timedelta(days=60), "unknown")}
    assert st(1, [], ex) == "exited_non_distress"
    assert st(2, [], ex) == "exited_unknown"
    assert st(1, [_ev(1, 30, ["1.03"])], ex) == "event"
    assert st(1, [_ev(1, 400, ["1.03"])]) == "survived"  # outside the window


def test_round_selection_and_metrics():
    ms = [{"round": "2026Q4", "asof": "2026-11-09", "week": "2026-46"},
          {"round": "2026Q4", "asof": "2026-10-05", "week": "2026-41"},
          {"round": "2027Q1", "asof": "2027-01-04", "week": "2027-01"}]
    assert sc.select_first_in_round(ms, "2026Q4")["week"] == "2026-41"
    assert sc.select_first_in_round(ms, "2026Q2") is None
    assert sc.pr_auc([0, 0], [1.0, 2.0]) is None and sc.roc_auc([1, 1], [1.0, 2.0]) is None
    assert sc.roc_auc([0, 1], [0.1, 0.9]) == 1.0


def test_event_rate_derivation_synthetic():
    r = ap.derive_event_rates(_UNIV, {100})
    # firm B (bankrupt 2020-05-12): origins 2012-03-31..2020-03-31 = 33; the four origins 2019-06-30..2020-03-31 see it
    assert r["all_universe"]["4q"] == {"rate": 4 / 85, "events": 4, "origins": 85, "firms": 2}
    assert r["stratum"]["4q"] == {"rate": 0.0, "events": 0, "origins": 52, "firms": 1}
    assert r["all_universe"]["8q"]["events"] == 8  # 728-day window sees it from 8 origins
    assert r["universe_csv_sha256"] == ap.sha256_file(_UNIV)


def test_round_void_without_early_archive():
    ms = [{"round": "2026Q4", "asof": "2026-10-26", "week": "2026-44"},  # 25 days into the quarter: too late
          {"round": "2026Q4", "asof": "2026-11-02", "week": "2026-45"}]
    assert sc.select_first_in_round(ms, "2026Q4") is None  # VOID, no fallback to a later week
    ms.append({"round": "2026Q4", "asof": "2026-10-12", "week": "2026-42"})
    assert sc.select_first_in_round(ms, "2026Q4")["week"] == "2026-42"
    ms.append({"round": "2026Q4", "asof": "2026-10-05", "week": "2026-41"})
    assert sc.select_first_in_round(ms, "2026Q4")["week"] == "2026-41"
