"""WP7: the per-stage shard audit stops a stage on the faults of the 12-11-2026 review."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "audit_shards", Path(__file__).parents[1] / "scripts" / "audit_shards.py"
)
A = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(A)


def _shard(t, health=50.0, q=(1.0, 2.0, 3.0, 4.0, 5.0), origins=("2018-02-15",)):
    row = {"base": {"health": health, "p_breach": 0.1}, "recession": {"health": 40.0, "p_breach": 0.2}}
    return {"ticker": t, "panel": [{"origin": o, **row} for o in origins],
            "forecasts": [{"var": "revenue", "q": list(q), "y": 3.0, "crps_twin": 1.0, "crps_rw": 1.0}]}  # fmt: skip


def _run(tmp_path, runs: dict[str, list[dict]]) -> int:
    for run, shards in runs.items():
        (tmp_path / run).mkdir()
        for s in shards:
            (tmp_path / run / f"{s['ticker']}.json").write_text(json.dumps(s), encoding="utf-8")
    return A.main(["--root", str(tmp_path), "--runs", *runs, "--group", *runs, "--out", str(tmp_path / "rep.json")])


def test_clean_runs_pass(tmp_path):
    shards = [_shard(f"T{i}") for i in range(20)]
    assert _run(tmp_path, {"v2-pre": shards, "v3": shards}) == 0


def test_none_health_or_quantile_stops_the_stage(tmp_path):
    bad = [_shard("T0", health=None)] + [_shard(f"T{i}") for i in range(1, 20)]
    assert _run(tmp_path, {"v3": bad}) == 1
    rep = json.loads((tmp_path / "rep.json").read_text(encoding="utf-8"))
    assert "panel.base health/p_breach missing or non-finite" in rep["red"]["v3"]


def test_firm_years_missing_in_one_spec_stop_the_stage(tmp_path):
    full = [_shard(f"T{i}", origins=("2018-02-15", "2019-02-15")) for i in range(20)]
    short = [_shard("T0")] + full[1:]  # one firm-year fewer in v2-pre
    assert _run(tmp_path, {"v2-pre": short, "v3": full}) == 1
