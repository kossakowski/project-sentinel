"""Tests for sentinel.config configuration system."""

import os

import pytest
import yaml

from sentinel.config import ConfigError, SentinelConfig, load_config


def test_load_valid_config(monkeypatch):
    """Load config/config.example.yaml with env vars set, verify key fields accessible."""
    monkeypatch.setenv("ALERT_PHONE_NUMBER", "+48123456789")
    monkeypatch.setenv("TELEGRAM_API_ID", "12345")
    monkeypatch.setenv("TELEGRAM_API_HASH", "abc123")
    monkeypatch.setenv("DATABASE_URL", "postgresql://sentinel:sentinel@localhost:5432/sentinel")

    config = load_config("config/config.example.yaml")

    assert isinstance(config, SentinelConfig)
    assert config.alerts.phone_number == "+48123456789"
    assert config.classification.model == "claude-haiku-4-5-20251001"
    assert config.scheduler.interval_minutes == 15
    assert len(config.sources.rss) > 0
    assert config.sources.gdelt.enabled is True
    assert len(config.monitoring.target_countries) > 0


def test_missing_required_field(tmp_path):
    """Config YAML missing 'monitoring' section raises ConfigError (wraps ValidationError)."""
    config_dict = {
        "sources": {
            "rss": [{"name": "T", "url": "https://example.com/rss", "language": "en"}],
            "gdelt": {"themes": ["A"], "cameo_codes": ["19"]},
            "google_news": {"queries": [{"query": "test", "language": "en"}]},
            "telegram": {"enabled": False},
        },
        # monitoring section is missing
        "classification": {},
        "alerts": {
            "phone_number": "+48123456789",
            "urgency_levels": {
                "critical": {"min_score": 9, "action": "phone_call"},
            },
            "acknowledgment": {},
        },
        "scheduler": {},
        "database": {},
        "logging": {},
        "testing": {},
        "processing": {"dedup": {}},
    }
    config_path = tmp_path / "bad_config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config_dict, f)

    with pytest.raises(ConfigError, match="Config validation failed"):
        load_config(str(config_path))


def test_env_var_substitution(monkeypatch, tmp_path):
    """Config with ${TEST_SENTINEL_VAR} gets substituted when env var is set."""
    monkeypatch.setenv("TEST_SENTINEL_VAR", "+48999888777")

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
            "phone_number": "${TEST_SENTINEL_VAR}",
            "urgency_levels": {
                "critical": {"min_score": 9, "action": "phone_call"},
            },
            "acknowledgment": {},
        },
        "scheduler": {},
        "database": {},
        "logging": {},
        "testing": {},
        "processing": {"dedup": {}},
    }
    config_path = tmp_path / "env_config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config_dict, f)

    config = load_config(str(config_path))
    assert config.alerts.phone_number == "+48999888777"


def test_missing_env_var(tmp_path):
    """Config with ${SENTINEL_NONEXISTENT} without env var set raises ConfigError."""
    config_dict = {
        "monitoring": {
            "target_countries": [{"code": "PL", "name": "Poland", "name_native": "Polska"}],
            "aggressor_countries": [{"code": "RU", "name": "Russia", "name_native": "Rosja"}],
            "keywords": {"en": {"critical": ["test"]}},
        },
        "sources": {
            "rss": [{"name": "T", "url": "https://example.com/rss", "language": "en"}],
            "gdelt": {"themes": ["A"], "cameo_codes": ["19"]},
            "google_news": {"queries": [{"query": "test", "language": "en"}]},
            "telegram": {"enabled": False},
        },
        "classification": {},
        "alerts": {
            "phone_number": "${SENTINEL_NONEXISTENT}",
            "urgency_levels": {
                "critical": {"min_score": 9, "action": "phone_call"},
            },
            "acknowledgment": {},
        },
        "scheduler": {},
        "database": {},
        "logging": {},
        "testing": {},
        "processing": {"dedup": {}},
    }
    config_path = tmp_path / "missing_env.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config_dict, f)

    # Make sure the env var doesn't exist
    os.environ.pop("SENTINEL_NONEXISTENT", None)

    with pytest.raises(ConfigError, match="SENTINEL_NONEXISTENT"):
        load_config(str(config_path))


def test_invalid_url(tmp_path):
    """RSS source with invalid URL raises ConfigError (wraps ValidationError)."""
    config_dict = {
        "monitoring": {
            "target_countries": [{"code": "PL", "name": "Poland", "name_native": "Polska"}],
            "aggressor_countries": [{"code": "RU", "name": "Russia", "name_native": "Rosja"}],
            "keywords": {"en": {"critical": ["test"]}},
        },
        "sources": {
            "rss": [{"name": "Bad", "url": "not_a_url", "language": "en"}],
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
        "database": {},
        "logging": {},
        "testing": {},
        "processing": {"dedup": {}},
    }
    config_path = tmp_path / "bad_url.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config_dict, f)

    with pytest.raises(ConfigError, match="Config validation failed"):
        load_config(str(config_path))


def test_defaults_applied(sample_config_yaml):
    """Config without optional fields gets defaults (e.g., scheduler.interval_minutes = 15)."""
    config = load_config(sample_config_yaml)
    assert config.scheduler.interval_minutes == 15
    assert config.scheduler.jitter_seconds == 30
    assert config.database.url.startswith("postgresql://")
    assert config.database.article_retention_days == 30
    assert config.classification.model == "claude-haiku-4-5-20251001"


def test_disabled_source_loadable(tmp_path):
    """Source with enabled: false still loads correctly."""
    config_dict = {
        "monitoring": {
            "target_countries": [{"code": "PL", "name": "Poland", "name_native": "Polska"}],
            "aggressor_countries": [{"code": "RU", "name": "Russia", "name_native": "Rosja"}],
            "keywords": {"en": {"critical": ["test"]}},
        },
        "sources": {
            "rss": [
                {"name": "Active", "url": "https://example.com/active", "language": "en", "enabled": True},
                {"name": "Disabled", "url": "https://example.com/disabled", "language": "en", "enabled": False},
            ],
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
        "database": {},
        "logging": {},
        "testing": {},
        "processing": {"dedup": {}},
    }
    config_path = tmp_path / "disabled.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config_dict, f)

    config = load_config(str(config_path))
    assert len(config.sources.rss) == 2
    disabled = [s for s in config.sources.rss if not s.enabled]
    assert len(disabled) == 1
    assert disabled[0].name == "Disabled"
    assert config.sources.gdelt.enabled is False
