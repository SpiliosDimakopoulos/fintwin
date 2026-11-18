"""REVISION_PLAN_5 T1/T2 in the twin (v4t): the calibration maps the filing-text inputs to model keys, and the model
uses them only under T1/T2."""

from __future__ import annotations

import numpy as np
import pytest
from test_B1_parity import synthetic_company
from test_plan5_model import cal, flat_run

from fintwin.research import text_stage as TS


def test_ridge_recovers_a_linear_signal():
    rng = np.random.default_rng(0)
    X = rng.normal(size=(500, 6))
    y = 2.0 * X[:, 0] - X[:, 3] + rng.normal(0, 0.1, 500)
    m = TS.ridge(X, y, alpha=1.0)
    x = np.array([1.0, 0, 0, 0, 0, 0])
    assert TS.predict(m, x) == pytest.approx(2.0 + float(np.mean(y)) - 2.0 * float(np.mean(X[:, 0])), abs=0.2)


def test_text_inputs_reads_features_and_table(tmp_path, monkeypatch):
    monkeypatch.setenv("FINTWIN_TEXT", str(tmp_path))
    TS.write_features(tmp_path, 42, "2020-02-15", {"t1u_going_concern": 1})
    vint = "manelalab/chrono-bert-v1-20191231"
    TS.write_embedding(tmp_path, vint, 42, "2020-02-15", np.ones(4), "2020-02-15")
    model = {"mu": [0.0] * 4, "sd": [1.0] * 4, "w": [0.5] * 4, "b": 1.0}
    (tmp_path / "table.json").write_text(
        '{"years": {"2020": {"vintage": "%s", "t2_margin": %s}}}' % (vint, str(model).replace("'", '"'))
    )
    TS._table.cache_clear()
    out = TS.text_inputs("2020-02-15", "CIK0000000042")
    assert out["t1u_going_concern"] == 1 and out["t2_margin"] == pytest.approx(3.0)


def test_write_embedding_refuses_a_later_vintage(tmp_path):
    with pytest.raises(Exception):
        TS.write_embedding(tmp_path, "manelalab/chrono-bert-v1-20201231", 42, "2020-02-15", np.ones(4), "2020-02-15")


def test_write_embedding_allows_reembedding_for_a_later_test_year(tmp_path):
    # a 2015 firm-year as training data for the 2018 test year, under the 2017 vintage: allowed
    TS.write_embedding(tmp_path, "manelalab/chrono-bert-v1-20171231", 42, "2015-02-15", np.ones(4), "2018-02-15")
    with pytest.raises(Exception):  # but never as training data for an earlier year
        TS.write_embedding(tmp_path, "manelalab/chrono-bert-v1-20131231", 42, "2015-02-15", np.ones(4), "2014-02-15")


def test_calibration_maps_text_only_under_t1_t2(macro):
    c = synthetic_company()
    text = {"t1u_going_concern": 1, "t1_restructuring_cost_usd": 5e6, "t2_margin": -2.0}
    p = cal(c, macro, "v4t", text=text)
    assert p["text_access0"] == 0.5
    assert p["text_oneoff"] == pytest.approx(min(5e6, 0.10 * 4 * p["base_rev0"]))  # capped at 10% of TTM revenue
    assert p["text_vshift"] == pytest.approx(0.02)
    q = cal(c, macro, "v4p", text=text)
    assert "text_access0" not in q and "text_vshift" not in q


def test_model_uses_text_inputs_only_under_t1_t2(macro):
    c = synthetic_company()
    p = cal(c, macro, "v4p")
    rev = [p["base_rev0"]] * 8
    base = flat_run(p, rev, "v4t")
    hit = flat_run({**p, "text_oneoff": 0.1 * p["base_rev0"], "text_vshift": 0.02}, rev, "v4t")
    off = flat_run({**p, "text_oneoff": 0.1 * p["base_rev0"], "text_vshift": 0.02}, rev, "v4p")
    assert float(np.sum(hit["cfo"])) < float(np.sum(base["cfo"]))
    assert float(np.sum(off["cfo"])) == pytest.approx(float(np.sum(base["cfo"])))
