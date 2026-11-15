"""Repository hygiene (workstream D): versions, locked installs, workflow identities, 3.11-parsable scripts."""

import ast
import json
import re
import tomllib
from pathlib import Path

import fintwin

ROOT = Path(__file__).resolve().parents[2]


def _normalized(version: str) -> str:
    """PEP 440 `3.0.0.dev0` and the semver-style `3.0.0-dev` name the same release."""
    return re.sub(r"[.-]?dev\d*$", "-dev", version)


def test_versions_agree():
    py = tomllib.loads((ROOT / "engine" / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    assert fintwin.__version__ == py
    want = _normalized(py)
    assert _normalized(json.loads((ROOT / "web" / "package.json").read_text(encoding="utf-8"))["version"]) == want
    assert f"version: {want}" in (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    assert _normalized(json.loads((ROOT / ".zenodo.json").read_text(encoding="utf-8"))["version"]) == want


def test_scripts_parse_on_python_311():
    for p in (ROOT / "engine" / "scripts").glob("*.py"):
        ast.parse(p.read_text(encoding="utf-8"), filename=str(p), feature_version=(3, 11))


def test_workflows_install_locked_and_pin_actions():
    for p in (ROOT / ".github" / "workflows").glob("*.yml"):
        text = p.read_text(encoding="utf-8")
        assert not re.search(r"uv sync(?! --locked)", text), p.name
        for use in re.findall(r"uses: ([\w./-]+@\S+)", text):
            assert re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", use), f"{p.name}: {use}"


def test_weekly_job_uses_bot_identity_and_main():
    text = (ROOT / ".github" / "workflows" / "data.yml").read_text(encoding="utf-8")
    assert "@gmail.com" not in text
    assert "ref: main" in text and "|| echo" not in text


def test_coverage_includes_research_code():
    cfg = tomllib.loads((ROOT / "engine" / "pyproject.toml").read_text(encoding="utf-8"))
    assert not [o for o in cfg["tool"]["coverage"]["run"]["omit"] if "research" in o]
    assert cfg["tool"]["coverage"]["report"]["fail_under"] >= 80


def test_research_runs_pin_blas_threads():
    for name in ("research.yml", "research-stats.yml"):
        assert 'OPENBLAS_NUM_THREADS: "1"' in (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
    assert "OPENBLAS_NUM_THREADS := 1" in (ROOT / "Makefile").read_text(encoding="utf-8")
