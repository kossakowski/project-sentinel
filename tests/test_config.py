"""Tests for sentinel.config configuration system."""

import os

import pytest
import yaml

from sentinel.config import ClassificationConfig, ConfigError, SentinelConfig, UrgencyLevel, load_config


def test_load_valid_config(monkeypatch):
    """Load config/config.example.yaml with env vars set, verify key fields accessible."""
    monkeypatch.setenv("ALERT_PHONE_NUMBER", "+48123456789")
    monkeypatch.setenv("TELEGRAM_API_ID", "12345")
    monkeypatch.setenv("TELEGRAM_API_HASH", "abc123")

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
            "gdelt": {"themes": ["A"]},
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
            "gdelt": {"themes": ["A"]},
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
            "gdelt": {"themes": ["A"]},
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
            "gdelt": {"themes": ["A"]},
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
    assert config.database.path == "data/sentinel.db"
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
    # Spec 1.6b: YAML with empty `classification: {}` must populate the new
    # threshold defaults so existing production configs keep working.
    assert config.classification.corroboration_window_minutes == 360
    assert config.classification.summary_similarity_threshold == 50
    assert config.classification.summary_similarity_metric == "token_set_ratio"
    assert config.classification.corroboration_max_age_minutes == 2880
    assert config.classification.syndication_similarity_threshold == 90


def test_corroboration_window_default_is_360():
    """ClassificationConfig built without corroboration_window_minutes defaults to 360."""
    cfg = ClassificationConfig()
    assert cfg.corroboration_window_minutes == 360


def test_summary_threshold_default_is_50():
    """ClassificationConfig built without summary_similarity_threshold defaults to 50
    (raised from 40 alongside the token_set_ratio metric switch)."""
    cfg = ClassificationConfig()
    assert cfg.summary_similarity_threshold == 50


def test_summary_metric_default_is_token_set_ratio():
    """ClassificationConfig defaults to the length-robust token_set_ratio metric,
    and an unknown metric is rejected by validation."""
    import pytest
    from pydantic import ValidationError

    assert ClassificationConfig().summary_similarity_metric == "token_set_ratio"
    assert ClassificationConfig().corroboration_max_age_minutes == 2880
    with pytest.raises(ValidationError):
        ClassificationConfig(summary_similarity_metric="bogus")


def test_all_allowed_summary_metrics_resolve_to_callables():
    """Every metric the validator allows must resolve to a real rapidfuzz.fuzz
    callable so the corroborator's getattr(fuzz, metric) can never fail at runtime
    (guards against allowlist/rapidfuzz API drift)."""
    from rapidfuzz import fuzz

    for metric in ("ratio", "partial_ratio", "token_sort_ratio", "token_set_ratio", "WRatio", "QRatio"):
        cfg = ClassificationConfig(summary_similarity_metric=metric)
        fn = getattr(fuzz, cfg.summary_similarity_metric)
        assert callable(fn)
        assert isinstance(fn("a", "a"), (int, float))


def test_syndication_threshold_default_is_90():
    """ClassificationConfig built without syndication_similarity_threshold defaults to 90."""
    cfg = ClassificationConfig()
    assert cfg.syndication_similarity_threshold == 90


# --------------------------------------------------------------------------
# UrgencyLevel.channel — per-tier delivery channel (Phase 1)
# --------------------------------------------------------------------------


def test_channel_field_defaults_to_both():
    """[1.1] UrgencyLevel without channel defaults to 'both' (SMS-only while push off)."""
    assert UrgencyLevel(min_score=7, action="sms").channel == "both"


def test_channel_accepts_each_valid_value():
    """[1.1] Each allowed channel constructs and round-trips its value."""
    for value in ("sms", "push", "both"):
        level = UrgencyLevel(min_score=7, action="sms", channel=value)
        assert level.channel == value


def test_channel_rejects_invalid_value():
    """[1.1a] An unknown channel raises a pydantic ValidationError mentioning channel."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="channel"):
        UrgencyLevel(min_score=7, action="sms", channel="email")


def test_config_loads_without_channel_keys(tmp_path):
    """[1.1b, 1.6] A config whose urgency_levels omit `channel` (incl. critical/low)
    loads, and the SMS-action tiers default to channel == 'both'."""
    config_dict = {
        "monitoring": {
            "target_countries": [{"code": "PL", "name": "Poland", "name_native": "Polska"}],
            "aggressor_countries": [{"code": "RU", "name": "Russia", "name_native": "Rosja"}],
            "keywords": {"en": {"critical": ["military attack"]}},
        },
        "sources": {
            "rss": [{"name": "T", "url": "https://example.com/rss", "language": "en"}],
            "gdelt": {"themes": ["A"]},
            "google_news": {"queries": [{"query": "test", "language": "en"}]},
            "telegram": {"enabled": False},
        },
        "classification": {},
        "alerts": {
            "phone_number": "+48123456789",
            "urgency_levels": {
                "critical": {"min_score": 9, "action": "phone_call", "corroboration_required": 1},
                "high": {"min_score": 7, "action": "sms", "corroboration_required": 1},
                "medium": {"min_score": 5, "action": "sms", "corroboration_required": 1},
                "low": {"min_score": 1, "action": "log_only"},
            },
            "acknowledgment": {},
        },
        "scheduler": {},
        "database": {},
        "logging": {},
        "testing": {},
        "processing": {"dedup": {}},
    }
    config_path = tmp_path / "no_channel.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config_dict, f)

    config = load_config(str(config_path))
    levels = config.alerts.urgency_levels
    assert levels["high"].channel == "both"
    assert levels["medium"].channel == "both"
    # critical/low load fine even though channel is irrelevant to them.
    assert levels["critical"].channel == "both"
    assert levels["low"].channel == "both"


def test_shipped_configs_set_channel_both():
    """[1.6] The shipped config files route the 5-8 tiers via `channel: both`.

    Parses the raw repo YAML directly (no env credentials / full Settings needed)
    and asserts: in BOTH config.yaml and config.example.yaml the high and medium
    urgency levels set `channel: both`; config.example.yaml keeps its
    alerts.push block disabled; and config.yaml ships NO push block under alerts
    (the PushConfig `enabled=False` default is the production-matching state).
    """
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def _load(relpath):
        with open(os.path.join(repo_root, relpath)) as f:
            return yaml.safe_load(f)

    main_cfg = _load("config/config.yaml")
    example_cfg = _load("config/config.example.yaml")

    for cfg in (main_cfg, example_cfg):
        levels = cfg["alerts"]["urgency_levels"]
        assert levels["high"]["channel"] == "both"
        assert levels["medium"]["channel"] == "both"

    # config.example.yaml ships the push block disabled.
    assert example_cfg["alerts"]["push"]["enabled"] is False

    # config.yaml has NO push block under alerts (relies on the disabled default).
    assert "push" not in main_cfg["alerts"]
