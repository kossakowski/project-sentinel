"""The tracked production config loads and keeps its life-safety values.

``config/config.yaml`` is deployed as-is by ``/deploy``. These tests load it
through the real ``load_config()`` (via the ``prod_config`` fixture) and pin
the values that decide whether an urgency 9-10 event places a phone call.
A change to any pinned value must be a deliberate owner decision that also
updates this file.
"""

import os
import re
from pathlib import Path

import pytest
import yaml

from sentinel.config import ConfigError, SentinelConfig, UrgencyLevel, load_config


def _tier_for(config: SentinelConfig, score: int) -> tuple[str, UrgencyLevel]:
    """Return the (name, level) whose band holds ``score``: the highest ``min_score`` <= score."""
    eligible = [(name, level) for name, level in config.alerts.urgency_levels.items() if score >= level.min_score]
    assert eligible, f"no urgency tier holds score {score}"
    return max(eligible, key=lambda item: item[1].min_score)


def test_live_config_loads_and_pins_life_safety_values(prod_config, tmp_path):
    config = prod_config

    # 1.4: the runtime paths live under tmp_path, the env dummies are shape-valid.
    runtime_paths = [
        config.database.path,
        config.logging.file,
        config.classification.budget.ledger_path,
        config.sources.telegram.session_name,
    ]
    for path in runtime_paths:
        assert Path(path).is_relative_to(tmp_path), path
    assert re.fullmatch(r"\+[1-9]\d{7,14}", config.alerts.phone_number)
    assert isinstance(config.sources.telegram.api_id, int)
    assert config.alerts.push.tokens
    assert all(re.fullmatch(r"ExponentPushToken\[.+\]", token) for token in config.alerts.push.tokens)

    # 1.5: urgency 9 and 10 fall in a phone-call tier that one source triggers.
    for score in (9, 10):
        name, level = _tier_for(config, score)
        assert level.action == "phone_call", (score, name)
        assert level.corroboration_required == 1, (score, name)

    # 1.5: one call per round.
    assert config.alerts.acknowledgment.max_call_retries == 1

    # 1.5: urgency 5-8 is delivered by app push only.
    for score in (5, 6, 7, 8):
        name, level = _tier_for(config, score)
        assert level.action == "sms", (score, name)
        assert level.channel == "push", (score, name)
    assert config.alerts.push.enabled is True

    # 1.5: the live classifier and grouping path.
    assert config.classification.provider == "openai"
    assert config.classification.incident_memory.enabled is True


def test_load_config_does_not_read_dotenv(sample_config_dict, tmp_path, monkeypatch):
    """load_config() resolves ${VAR} from the process environment only, never from a .env file."""
    import dotenv.main

    marker = "SENTINEL_DOTENV_PROBE"
    monkeypatch.delenv(marker, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(f"{marker}=+48500999888\n", encoding="utf-8")
    # Any dotenv lookup made during load_config() would find this file.
    monkeypatch.setattr(dotenv.main, "find_dotenv", lambda *args, **kwargs: str(env_file))
    monkeypatch.chdir(tmp_path)

    sample_config_dict["alerts"]["phone_number"] = "${" + marker + "}"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(sample_config_dict), encoding="utf-8")

    try:
        with pytest.raises(ConfigError, match=marker):
            load_config(str(config_path))
        assert marker not in os.environ
    finally:
        os.environ.pop(marker, None)
