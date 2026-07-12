"""Tests for sentinel.config configuration system."""

import os

import pytest
import yaml
from pydantic import ValidationError

from sentinel.config import (
    AcknowledgmentConfig,
    AlertsConfig,
    ChannelBand,
    ClassificationConfig,
    ConfigError,
    DedupConfig,
    GeographyConfig,
    SentinelConfig,
    UrgencyLevel,
    load_config,
)


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


def test_corroboration_surface_is_gone():
    """No corroboration / source-independence knob survives anywhere in the config models.

    Corroboration is deleted: no source-count gate may suppress or delay an alert,
    and a dead knob implying otherwise is worse than no knob.
    """
    assert not hasattr(ClassificationConfig(), "corroboration_required")
    assert not hasattr(ClassificationConfig(), "syndication_similarity_threshold")
    level = UrgencyLevel(min_score=9, action="phone_call")
    assert not hasattr(level, "corroboration_required")
    # The never-read retry knobs are gone too -- alerts.retry.max_rounds is the only bound.
    assert not hasattr(level, "retry_attempts")
    assert not hasattr(level, "fallback")


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
                "critical": {"min_score": 9, "action": "phone_call"},
                "high": {"min_score": 7, "action": "sms"},
                "medium": {"min_score": 5, "action": "sms"},
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


# --------------------------------------------------------------------------
# Phase 2 config surfaces — geography, channel_bands, dedup
# --------------------------------------------------------------------------


def _alerts(**overrides) -> AlertsConfig:
    """Build a minimal AlertsConfig, overriding one field at a time."""
    kwargs = {
        "phone_number": "+48123456789",
        "urgency_levels": {"critical": UrgencyLevel(min_score=9, action="phone_call")},
        "acknowledgment": AcknowledgmentConfig(),
    }
    kwargs.update(overrides)
    return AlertsConfig(**kwargs)


def test_geography_defaults():
    """GeographyConfig defaults carry the whole Phase 2 geo surface."""
    geo = GeographyConfig()
    assert geo.high_tier_countries == ["PL", "LT", "LV", "EE", "RO"]
    assert geo.floor_countries == ["PL"]
    assert geo.nato_attack_targets == ["RU"]
    # Known-but-LOW countries: only these (or the HIGH set) may demote a 9-10 to SMS.
    assert set(geo.low_tier_countries) == {"UA", "MD", "RU", "BY"}
    # The kinetic set never contains the two meta-event types (debris/reactions are not strikes).
    assert "debris_found" not in geo.kinetic_event_types
    assert "official_statement" not in geo.kinetic_event_types
    assert "missile_strike" in geo.kinetic_event_types


def test_channel_band_rejects_unknown_class():
    """ChannelBand.channel_class is validated against call/notify/none."""
    assert ChannelBand(min_score=9, channel_class="call").channel_class == "call"
    with pytest.raises(ValidationError):
        ChannelBand(min_score=9, channel_class="telegram")


def test_channel_bands_default_is_the_rubric_v2_map():
    """The shipped default band map: >=9 call, 5-8 notify, <=4 none."""
    bands = {b.channel_class: b.min_score for b in _alerts().channel_bands}
    assert bands == {"call": 9, "notify": 5, "none": 1}


@pytest.mark.parametrize(
    "bands,reason",
    [
        ([], "empty"),
        (  # no call band -> no event could ever place a phone call
            [ChannelBand(min_score=5, channel_class="notify"), ChannelBand(min_score=1, channel_class="none")],
            "no call band",
        ),
        (  # urgency 1-4 falls through to no band at all
            [ChannelBand(min_score=9, channel_class="call"), ChannelBand(min_score=5, channel_class="notify")],
            "coverage gap",
        ),
        (  # inverted: notify sits above call
            [
                ChannelBand(min_score=9, channel_class="notify"),
                ChannelBand(min_score=5, channel_class="call"),
                ChannelBand(min_score=1, channel_class="none"),
            ],
            "inverted",
        ),
        (  # duplicate min_score -> ambiguous band
            [
                ChannelBand(min_score=9, channel_class="call"),
                ChannelBand(min_score=9, channel_class="notify"),
                ChannelBand(min_score=1, channel_class="none"),
            ],
            "duplicate min_score",
        ),
        (  # outside the 1-10 urgency scale
            [
                ChannelBand(min_score=11, channel_class="call"),
                ChannelBand(min_score=5, channel_class="notify"),
                ChannelBand(min_score=1, channel_class="none"),
            ],
            "out of range",
        ),
        (  # two call bands -> "the call tier" is ambiguous for the corroborator's guards
            [
                ChannelBand(min_score=10, channel_class="call"),
                ChannelBand(min_score=9, channel_class="call"),
                ChannelBand(min_score=5, channel_class="notify"),
                ChannelBand(min_score=1, channel_class="none"),
            ],
            "duplicate channel_class",
        ),
    ],
)
def test_bad_channel_bands_fail_at_load(bands, reason):
    """A band map that could silence the call tier must fail AT CONFIG LOAD, not in production.

    AlertPolicy reads the whole alert decision out of this map, so one YAML typo
    (empty list, missing call band, uncovered urgency, inverted order) would
    otherwise route an urgency-10 event on Polish soil to NOTIFY or to nothing --
    with every test still green.
    """
    with pytest.raises(ValidationError):
        _alerts(channel_bands=bands)


def test_min_event_urgency_default_and_cross_check(sample_config_dict, tmp_path):
    """dedup.min_event_urgency must not sit above the lowest alerting band.

    The pre-event gate drops a classification BEFORE any event row exists. Set above
    the notify band it would silently kill every urgency-5/6 SMS-tier event with all
    tests green -- so it is cross-checked at load.
    """
    assert DedupConfig().min_event_urgency == 5

    def _load(min_event_urgency):
        cfg = dict(sample_config_dict)
        cfg["dedup"] = {"min_event_urgency": min_event_urgency}
        path = tmp_path / f"cfg-{min_event_urgency}.yaml"
        with open(path, "w") as f:
            yaml.dump(cfg, f)
        return load_config(str(path))

    # At/below the notify band (5): fine.
    assert _load(5).dedup.min_event_urgency == 5
    assert _load(3).dedup.min_event_urgency == 3

    # Above it: rejected at load.
    with pytest.raises(ConfigError):
        _load(7)
