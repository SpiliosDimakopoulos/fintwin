"""Rerun 5, P9: the shard digest covers exactly the code that can change a shard, so a change to a statistic never
makes the shards of a finished run stale (it did: every stats fix forced a full rerun)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import fintwin.research.__main__ as M

ANALYSIS = ("stats", "calibration", "distress", "transmission", "plan2", "cross_spec", "analysis")
TESTS = Path(__file__).resolve().parent


def test_closure_holds_the_shard_code_and_no_analysis_module():
    mods = set(M.shard_modules())
    assert {"fintwin.research.experiments", "fintwin.model.sd_model", "fintwin.stochastic.calibrate"} <= mods
    assert {"fintwin.data.xbrl_fallback", "fintwin.data.edgar_universe", "fintwin.clean"} <= mods  # lazy imports too
    assert not [m for m in mods if m.rsplit(".", 1)[-1] in ANALYSIS] and "fintwin.export" not in mods


def test_running_the_shard_code_loads_only_digested_modules():
    script = f"""
import json, os, sys
sys.path[:0] = [{str(TESTS)!r}, {str(TESTS.parent)!r}]
os.environ["FINTWIN_SPEC"] = "v3"
from _pytest.monkeypatch import MonkeyPatch
import test_C2_spec as T
from test_C2_synth import quarters
import fintwin.research.__main__  # the shard entry point
T._patch_company(MonkeyPatch(), quarters())
T.X.company("CIK0000000001", with_forecasts=True, years={{2018, 2020}})
print(json.dumps(sorted(m for m in sys.modules if m == "fintwin" or m.startswith("fintwin."))))
"""
    out = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=True)
    loaded = set(json.loads(out.stdout.strip().splitlines()[-1]))
    assert loaded and loaded <= set(M.shard_modules()), sorted(loaded - set(M.shard_modules()))


def test_a_statistics_change_leaves_the_shard_digest_alone(monkeypatch, tmp_path):
    import shutil

    root = Path(M.__file__).resolve().parents[1]
    copy = tmp_path / "fintwin"
    shutil.copytree(root, copy, ignore=shutil.ignore_patterns("__pycache__"))
    monkeypatch.setattr(M, "__file__", str(copy / "research" / "__main__.py"))
    monkeypatch.setattr(M, "DATA", copy / "data")
    M._code_digest.cache_clear()
    before, a_before = M._code_digest(), M.analysis_digest()
    (copy / "research" / "stats.py").write_text((copy / "research" / "stats.py").read_text() + "\n# edit\n")
    M._code_digest.cache_clear()
    assert M._code_digest() == before and M.analysis_digest() != a_before
    (copy / "model" / "sd_model.py").write_text((copy / "model" / "sd_model.py").read_text() + "\n# edit\n")
    M._code_digest.cache_clear()
    assert M._code_digest() != before
    M._code_digest.cache_clear()
