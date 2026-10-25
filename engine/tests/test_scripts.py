"""Tests for engine CLI scripts argument parsing and --help handling."""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
DEFAULT_TICKERS = ["AAPL", "TSLA", "CCL", "BA", "INTC", "NFLX"]


def _load_script(name: str):
    path = SCRIPTS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"engine_scripts_{name}", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def diagnose_mod():
    return _load_script("diagnose")


@pytest.fixture(scope="module")
def backtest_check_mod():
    return _load_script("backtest_check")


@pytest.fixture(scope="module")
def regime_ablation_mod():
    return _load_script("regime_ablation")


@pytest.mark.parametrize("script_name", ["diagnose", "backtest_check", "regime_ablation"])
def test_cli_help_subprocess_exits_zero_without_network(script_name):
    script_path = SCRIPTS_DIR / f"{script_name}.py"
    # Ensure SEC_USER_AGENT is not present to confirm help runs completely offline
    env = {k: v for k, v in os.environ.items() if k != "SEC_USER_AGENT"}
    res = subprocess.run(
        [sys.executable, str(script_path), "--help"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    assert res.returncode == 0
    assert "usage:" in res.stdout
    assert "tickers" in res.stdout
    assert "--help" in res.stdout


def test_diagnose_help_does_not_trigger_data_loading(diagnose_mod):
    with (
        patch.object(diagnose_mod, "load_company") as mock_load,
        patch.object(diagnose_mod, "macro_quarterly") as mock_macro,
    ):
        with pytest.raises(SystemExit) as exc_info:
            diagnose_mod.main(["--help"])
        assert exc_info.value.code == 0
        mock_load.assert_not_called()
        mock_macro.assert_not_called()


def test_backtest_check_help_does_not_trigger_backtest(backtest_check_mod):
    with patch.object(backtest_check_mod, "forecast_backtest") as mock_backtest:
        with pytest.raises(SystemExit) as exc_info:
            backtest_check_mod.main(["--help"])
        assert exc_info.value.code == 0
        mock_backtest.assert_not_called()


def test_regime_ablation_help_does_not_trigger_aggregation(regime_ablation_mod):
    with patch.object(regime_ablation_mod, "aggregate") as mock_agg:
        with pytest.raises(SystemExit) as exc_info:
            regime_ablation_mod.main(["--help"])
        assert exc_info.value.code == 0
        mock_agg.assert_not_called()


def test_diagnose_defaults(diagnose_mod):
    args = diagnose_mod.parse_args([])
    assert args.tickers == DEFAULT_TICKERS
    assert args.asof is None


def test_diagnose_asof_option(diagnose_mod):
    args = diagnose_mod.parse_args(["--asof", "2024-03-31"])
    assert args.asof == "2024-03-31"
    assert args.tickers == DEFAULT_TICKERS

    args2 = diagnose_mod.parse_args(["--asof=2024-03-31", "MSFT", "GOOG"])
    assert args2.asof == "2024-03-31"
    assert args2.tickers == ["MSFT", "GOOG"]


def test_diagnose_custom_tickers(diagnose_mod):
    args = diagnose_mod.parse_args(["NVDA", "AMZN"])
    assert args.tickers == ["NVDA", "AMZN"]
    assert args.asof is None


def test_backtest_check_defaults_and_custom_tickers(backtest_check_mod):
    args_default = backtest_check_mod.parse_args([])
    assert args_default.tickers == DEFAULT_TICKERS

    args_custom = backtest_check_mod.parse_args(["CCL", "AAPL"])
    assert args_custom.tickers == ["CCL", "AAPL"]


def test_regime_ablation_defaults_and_custom_tickers(regime_ablation_mod):
    args_default = regime_ablation_mod.parse_args([])
    assert args_default.tickers == DEFAULT_TICKERS

    args_custom = regime_ablation_mod.parse_args(["TSLA", "INTC"])
    assert args_custom.tickers == ["TSLA", "INTC"]


@pytest.mark.parametrize("mod_fixture", ["diagnose_mod", "backtest_check_mod", "regime_ablation_mod"])
def test_invalid_arguments_raise_error(request, mod_fixture, capsys):
    mod = request.getfixturevalue(mod_fixture)
    with pytest.raises(SystemExit) as exc_info:
        mod.parse_args(["--unrecognized-argument"])
    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "unrecognized arguments" in captured.err
