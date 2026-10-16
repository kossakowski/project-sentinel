"""Config validation at load time (refactor Phase 2: 2.4, 2.5, 2.6, and the 2.2 key).

A config that would mute or break the 9-10 path must fail ``load_config()``,
so a bad edit stops at deploy time instead of at alert time.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from sentinel.alerts.state_machine import _format_call_message, _format_sms_message, _format_update_sms
from sentinel.config import (
    ALERT_TEMPLATE_FIELDS,
    AlertTemplates,
    ConfigError,
    TwilioConfig,
    load_config,
)
from sentinel.models import Event

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


@pytest.fixture
def load_with(sample_config_dict, tmp_path, monkeypatch):
    """Write ``sample_config_dict`` after ``edit`` changed it, then load it."""
    monkeypatch.setenv("ALERT_PHONE_NUMBER", "+48123456789")

    def load(edit):
        edit(sample_config_dict)
        path = tmp_path / "config.yaml"
        path.write_text(yaml.safe_dump(sample_config_dict, allow_unicode=True), encoding="utf-8")
        return load_config(str(path))

    return load


def test_sample_config_still_loads(load_with):
    config = load_with(lambda cfg: None)
    assert config.alerts.urgency_levels["critical"].action == "phone_call"


# ---------------------------------------------------------------------------
# 2.4: urgency tiers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("action", ["phone-call", "Phone_call", "call", "push", ""])
def test_invalid_action_fails_load(load_with, action):
    def edit(cfg):
        cfg["alerts"]["urgency_levels"]["high"]["action"] = action

    with pytest.raises(ConfigError, match="action"):
        load_with(edit)


def test_no_phone_call_tier_fails_load(load_with):
    def edit(cfg):
        cfg["alerts"]["urgency_levels"]["critical"]["action"] = "sms"

    with pytest.raises(ConfigError, match="phone_call"):
        load_with(edit)


@pytest.mark.parametrize("retries", [0, -1])
def test_zero_call_retries_fails_load(load_with, retries):
    def edit(cfg):
        cfg["alerts"]["acknowledgment"]["max_call_retries"] = retries

    with pytest.raises(ConfigError, match="max_call_retries"):
        load_with(edit)


def test_shared_min_score_fails_load(load_with):
    def edit(cfg):
        cfg["alerts"]["urgency_levels"]["medium"] = {"min_score": 7, "action": "sms", "channel": "push"}

    with pytest.raises(ConfigError, match="min_score 7: high, medium"):
        load_with(edit)


def test_channel_validation_unchanged(load_with):
    def edit(cfg):
        cfg["alerts"]["urgency_levels"]["high"]["channel"] = "email"

    with pytest.raises(ConfigError, match="channel"):
        load_with(edit)


# ---------------------------------------------------------------------------
# 2.5: templates are rendered once at load time
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("template_name", ["call", "sms", "sms_update"])
def test_unknown_template_field_fails_load(load_with, template_name):
    def edit(cfg):
        cfg["alerts"]["templates"] = {template_name: "Alarm: {event_type_pl} {typo_field}"}

    with pytest.raises(ConfigError, match=rf"alerts\.templates\.{template_name}.*typo_field"):
        load_with(edit)


def test_field_of_another_template_fails_load(load_with):
    """``sources_list`` exists only for the SMS; the call formatter does not pass it."""

    def edit(cfg):
        cfg["alerts"]["templates"] = {"call": "{event_type_pl}. Źródła: {sources_list}"}

    with pytest.raises(ConfigError, match="sources_list"):
        load_with(edit)


@pytest.mark.parametrize(
    "template",
    ["Alarm {0}", "Alarm {event_type_pl", "Alarm {summary_pl.missing}", "Alarm {urgency_score:s}"],
    ids=["positional", "unbalanced", "attribute", "bad-format"],
)
def test_malformed_template_fails_load(load_with, template):
    def edit(cfg):
        cfg["alerts"]["templates"] = {"sms": template}

    with pytest.raises(ConfigError, match=r"alerts\.templates\.sms"):
        load_with(edit)


def test_valid_custom_template_loads(load_with):
    def edit(cfg):
        cfg["alerts"]["templates"] = {"call": "{event_type_pl}: pilność {urgency_score:d}, źródeł {source_count}."}

    config = load_with(edit)
    assert config.alerts.templates.call.startswith("{event_type_pl}")


def test_template_field_set_covers_every_template():
    assert set(ALERT_TEMPLATE_FIELDS) == set(AlertTemplates.model_fields)


def _event() -> Event:
    now = datetime.now(UTC)
    return Event(
        event_type="invasion",
        urgency_score=10,
        affected_countries=["PL"],
        aggressor="RU",
        summary_pl="Rosyjskie wojska przekroczyły granicę.",
        first_seen_at=now,
        last_updated_at=now,
        source_count=1,
        article_ids=[],
    )


@pytest.mark.parametrize("template_name", ["call", "sms", "sms_update"])
def test_formatters_accept_every_known_template_field(config, db, template_name):
    """Any template that passes the load-time check also renders when the alert is sent."""
    fields = ALERT_TEMPLATE_FIELDS[template_name]
    template = " | ".join(f"{name}={{{name}}}" for name in fields)
    config.alerts.templates = AlertTemplates(**{template_name: template})
    formatters = {
        "call": lambda event: _format_call_message(event, config),
        "sms": lambda event: _format_sms_message(event, db, config),
        "sms_update": lambda event: _format_update_sms(event, db, config),
    }

    rendered = formatters[template_name](_event())

    assert all(f"{name}=" in rendered for name in fields)
    assert "{" not in rendered


# ---------------------------------------------------------------------------
# 2.6: unknown keys are rejected
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        ("alerts", "acknowledgment", "max_call_retires"),
        ("sources", "gdelt", "update_interval_minutes"),
        ("classification", "incident_memroy"),
        ("alerts", "urgency_levels", "critical", "corroboration_requried"),
        ("alerts", "push", "enable"),
        ("unknown_section",),
    ],
    ids=lambda path: ".".join(path),
)
def test_unknown_config_key_fails_load(load_with, path):
    def edit(cfg):
        node = cfg
        for key in path[:-1]:
            node = node.setdefault(key, {})
        node[path[-1]] = 1

    with pytest.raises(ConfigError, match=path[-1]):
        load_with(edit)


def test_tracked_configs_load_without_dead_gdelt_key(prod_config):
    """Both tracked YAML files pass strict loading; the GDELT key that no code read is gone."""
    assert prod_config.sources.gdelt.lookback_minutes == 60
    for name in ("config.yaml", "config.example.yaml"):
        raw = yaml.safe_load((CONFIG_DIR / name).read_text(encoding="utf-8"))
        assert "update_interval_minutes" not in raw["sources"]["gdelt"]
    assert load_config(str(CONFIG_DIR / "config.example.yaml")).alerts.twilio.http_timeout_seconds == 30


# ---------------------------------------------------------------------------
# 2.2: alerts.twilio.http_timeout_seconds
# ---------------------------------------------------------------------------


def test_twilio_timeout_defaults_to_30_and_live_value_equals_default(prod_config, load_with):
    assert TwilioConfig().http_timeout_seconds == 30
    assert prod_config.alerts.twilio.http_timeout_seconds == TwilioConfig().http_timeout_seconds
    # A config that omits the block gets the default.
    assert load_with(lambda cfg: None).alerts.twilio.http_timeout_seconds == 30


@pytest.mark.parametrize("timeout", [0, -5])
def test_twilio_timeout_must_be_positive(load_with, timeout):
    def edit(cfg):
        cfg["alerts"]["twilio"] = {"http_timeout_seconds": timeout}

    with pytest.raises(ConfigError, match="http_timeout_seconds"):
        load_with(edit)


@pytest.mark.parametrize("interval", [0, -1])
def test_call_poll_interval_must_be_positive(load_with, interval):
    """A poll interval of zero or less would keep the call-wait loop from ever ending."""

    def edit(cfg):
        cfg["alerts"]["acknowledgment"]["call_poll_interval_seconds"] = interval

    with pytest.raises(ConfigError, match="call_poll_interval_seconds"):
        load_with(edit)
