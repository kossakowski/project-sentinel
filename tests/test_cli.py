"""Tests for sentinel.py CLI entry point."""

import os
import subprocess
import sys


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


def test_dry_run_flag(tmp_path, pg_url):
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
            "gdelt": {"enabled": False, "themes": ["A"], "cameo_codes": ["19"]},
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
        "database": {"url": pg_url},
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


def test_custom_config_path(tmp_path, pg_url):
    """Test that --config accepts a custom path and loads it."""
    import yaml

    # Create a minimal valid config file
    config_dict = {
        "monitoring": {
            "target_countries": [{"code": "PL", "name": "Poland", "name_native": "Polska"}],
            "aggressor_countries": [{"code": "RU", "name": "Russia", "name_native": "Rosja"}],
            "keywords": {"en": {"critical": ["military attack"]}},
        },
        "sources": {
            "rss": [{"name": "T", "url": "https://example.com/rss", "language": "en"}],
            "gdelt": {"themes": ["A"], "cameo_codes": ["19"]},
            "google_news": {"queries": [{"query": "test", "language": "en"}]},
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
        "database": {"url": pg_url},
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
