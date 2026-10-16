"""Tests for sentinel.py CLI entry point.

The subprocess smoke tests carry ``@pytest.mark.slow``, except
``test_custom_config_path``: it stays in the default (``-m "not slow"``) run so
that run proves a full ``--once`` cycle needs no network (every source is
disabled in its config).
"""

import importlib.util
import os
import subprocess
import sys

import pytest

from sentinel.config import ConfigError

_SCRIPT_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "sentinel.py")


def _load_cli_module():
    """Import the ``sentinel.py`` script (shadowed on sys.path by the ``sentinel`` package)."""
    spec = importlib.util.spec_from_file_location("sentinel_cli_script", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_main_loads_dotenv_before_config(monkeypatch):
    """main() fills the environment from .env first, then loads the config."""
    import dotenv

    cli = _load_cli_module()
    order: list[str] = []

    def fake_load_dotenv(*args, **kwargs):
        order.append("dotenv")
        return False

    def fake_load_config(path):
        order.append(f"config:{path}")
        raise ConfigError("stop after loading")

    monkeypatch.setattr(dotenv, "load_dotenv", fake_load_dotenv)
    monkeypatch.setattr(cli, "load_config", fake_load_config)
    monkeypatch.setattr(sys, "argv", ["sentinel.py", "--config", "custom.yaml"])

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 1
    assert order == ["dotenv", "config:custom.yaml"]


@pytest.mark.slow
def test_help_exits_cleanly():
    """Run python sentinel.py --help, verify exit code 0."""
    result = subprocess.run(
        [sys.executable, "sentinel.py", "--help"],
        capture_output=True,
        text=True,
        cwd=os.path.join(os.path.dirname(__file__), ".."),
    )
    assert result.returncode == 0
    assert "Sentinel" in result.stdout or "sentinel" in result.stdout


@pytest.mark.slow
def test_invalid_config_exits():
    """Run with --config /nonexistent/path, verify exit code 1."""
    result = subprocess.run(
        [sys.executable, "sentinel.py", "--config", "/nonexistent/path/config.yaml"],
        capture_output=True,
        text=True,
        cwd=os.path.join(os.path.dirname(__file__), ".."),
    )
    assert result.returncode == 1
    assert "Error" in result.stderr or "error" in result.stderr.lower()


@pytest.mark.slow
def test_dry_run_flag(tmp_path):
    """Test that --dry-run is recognized and reported."""
    import yaml

    # Use a minimal config with all sources disabled to avoid real network calls
    config_dict = {
        "monitoring": {
            "target_countries": [{"code": "PL", "name": "Poland", "name_native": "Polska"}],
            "aggressor_countries": [{"code": "RU", "name": "Russia", "name_native": "Rosja"}],
            "keywords": {"en": {"critical": ["military attack"]}},
        },
        "sources": {
            "rss": [{"name": "T", "url": "https://example.com/rss", "language": "en", "enabled": False}],
            "gdelt": {"enabled": False, "themes": ["A"]},
            "google_news": {"enabled": False, "queries": [{"query": "test", "language": "en"}]},
            "telegram": {"enabled": False},
        },
        "classification": {},
        "alerts": {
            "phone_number": "+48123456789",
            "urgency_levels": {
                "critical": {"min_score": 9, "action": "phone_call"},
            },
            "acknowledgment": {},
        },
        "scheduler": {},
        "database": {"path": str(tmp_path / "dry_run_test.db")},
        "logging": {"file": str(tmp_path / "dry_run_test.log")},
        "testing": {},
        "processing": {"dedup": {}},
    }
    config_path = tmp_path / "dry_run_config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config_dict, f)

    env = os.environ.copy()
    env["ALERT_PHONE_NUMBER"] = "+48123456789"

    result = subprocess.run(
        [sys.executable, "sentinel.py", "--dry-run", "--once", "--config", str(config_path)],
        capture_output=True,
        text=True,
        cwd=os.path.join(os.path.dirname(__file__), ".."),
        env=env,
    )
    assert result.returncode == 0
    combined = result.stdout + result.stderr
    assert "dry" in combined.lower() or "Dry" in combined


def test_custom_config_path(tmp_path):
    """Test that --config accepts a custom path and loads it.

    Every source is disabled, so the ``--once`` cycle fetches nothing and the
    subprocess (which the in-process socket guard cannot reach) stays offline.
    """
    import yaml

    # Create a minimal valid config file
    config_dict = {
        "monitoring": {
            "target_countries": [{"code": "PL", "name": "Poland", "name_native": "Polska"}],
            "aggressor_countries": [{"code": "RU", "name": "Russia", "name_native": "Rosja"}],
            "keywords": {"en": {"critical": ["military attack"]}},
        },
        "sources": {
            "rss": [{"name": "T", "url": "https://example.com/rss", "language": "en", "enabled": False}],
            "gdelt": {"enabled": False, "themes": ["A"]},
            "google_news": {"enabled": False, "queries": [{"query": "test", "language": "en"}]},
            "telegram": {"enabled": False},
        },
        "classification": {},
        "alerts": {
            "phone_number": "+48123456789",
            "urgency_levels": {
                "critical": {"min_score": 9, "action": "phone_call"},
            },
            "acknowledgment": {},
        },
        "scheduler": {},
        "database": {"path": str(tmp_path / "custom_test.db")},
        "logging": {"file": str(tmp_path / "custom_test.log")},
        "testing": {},
        "processing": {"dedup": {}},
    }
    config_path = tmp_path / "custom_config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config_dict, f)

    result = subprocess.run(
        [sys.executable, "sentinel.py", "--config", str(config_path), "--once"],
        capture_output=True,
        text=True,
        cwd=os.path.join(os.path.dirname(__file__), ".."),
    )
    assert result.returncode == 0
    combined = result.stdout + result.stderr
    assert "initialized" in combined.lower() or "Sentinel" in combined
