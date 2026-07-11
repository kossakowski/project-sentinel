"""Config-shape + harness-constant tests for Phase 0 geography correctness.

Deterministic and offline: loads the tracked ``config/config.yaml`` (raw YAML for
structural key checks, typed via ``load_config`` for field assertions) and inspects
the eval-harness module. No network / API calls.
"""

import re
from pathlib import Path

import pytest
import yaml

import sentinel.eval.harness as harness_module
from sentinel.config import load_config

CONFIG_PATH = "config/config.yaml"

# Gazetteer-style keys that MUST NOT appear anywhere in the config (0.3): country
# resolution stays LLM-driven and country-level.
FORBIDDEN_GAZETTEER_KEYS = {"gazetteer", "places", "cities", "coordinates", "geocells"}


@pytest.fixture(scope="module")
def raw_config() -> dict:
    """The tracked config parsed as raw YAML (no env substitution, no typing)."""
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture
def loaded_config(monkeypatch):
    """The tracked config loaded + validated through the Pydantic models."""
    monkeypatch.setenv("ALERT_PHONE_NUMBER", "+48123456789")
    monkeypatch.setenv("TELEGRAM_API_ID", "12345")
    monkeypatch.setenv("TELEGRAM_API_HASH", "abc123def456")
    return load_config(CONFIG_PATH)


def _all_keys(node) -> set:
    """Collect every dict key at any depth of a nested dict/list structure."""
    keys: set = set()
    if isinstance(node, dict):
        for k, v in node.items():
            keys.add(k)
            keys |= _all_keys(v)
    elif isinstance(node, list):
        for item in node:
            keys |= _all_keys(item)
    return keys


# ---------------------------------------------------------------------------
# 0.1 — Romania is a monitored target country
# ---------------------------------------------------------------------------


def test_config_ro_target_country(loaded_config):
    """[0.1] An object with code == 'RO' exists in monitoring.target_countries."""
    countries = loaded_config.monitoring.target_countries
    codes = {c["code"] for c in countries}
    assert "RO" in codes
    ro = next(c for c in countries if c["code"] == "RO")
    assert ro["name"] == "Romania"
    assert ro["name_native"] == "Rumunia"


# ---------------------------------------------------------------------------
# 0.2 — Romania is HIGH geo-tier
# ---------------------------------------------------------------------------


def test_config_ro_high_tier(loaded_config):
    """[0.2] 'RO' is in geography.high_tier_countries (with the other monitored states)."""
    high_tier = loaded_config.geography.high_tier_countries
    assert "RO" in high_tier
    for code in ("PL", "LT", "LV", "EE", "RO"):
        assert code in high_tier


# ---------------------------------------------------------------------------
# 0.3 — no gazetteer / place list anywhere
# ---------------------------------------------------------------------------


def test_config_no_gazetteer(raw_config):
    """[0.3] No gazetteer-style key at any depth; countries stay strictly code-level."""
    keys = _all_keys(raw_config)
    intersection = FORBIDDEN_GAZETTEER_KEYS & keys
    assert not intersection, f"forbidden gazetteer-style keys present: {intersection}"
    # Each target-country entry carries ONLY {code, name, name_native}.
    for entry in raw_config["monitoring"]["target_countries"]:
        assert set(entry.keys()) == {"code", "name", "name_native"}, entry


# ---------------------------------------------------------------------------
# 0.4 — Romanian-language ingestion surface
# ---------------------------------------------------------------------------


def test_config_romanian_keywords_present(loaded_config):
    """[0.4] Romanian-language keyword entries exist so events on Romanian soil are ingested."""
    assert "ro" in loaded_config.monitoring.keywords
    ro_keywords = loaded_config.monitoring.keywords["ro"]
    assert ro_keywords.critical, "Romanian critical keywords are empty"
    assert ro_keywords.high, "Romanian high keywords are empty"


def test_config_romanian_source_queries(raw_config):
    """[0.4] At least one Romanian-language ingestion source (Google News query)."""
    queries = raw_config["sources"]["google_news"]["queries"]
    ro_queries = [q for q in queries if q.get("language") == "ro"]
    assert ro_queries, "no Romanian-language Google News query configured"


# ---------------------------------------------------------------------------
# 0.10 / 0.11 — eval gate + regression wiring
# ---------------------------------------------------------------------------


def test_config_eval_gate_human(loaded_config):
    """[0.10] The eval gate points at the human correctness set."""
    assert loaded_config.testing.eval_set_file.endswith("eval_set_human.yaml")


def test_config_regression_eval(loaded_config):
    """[0.11] The regression set points at eval_set.yaml and differs from the gate."""
    regression = loaded_config.testing.regression_eval_set_file
    assert regression.endswith("eval_set.yaml")
    assert regression != loaded_config.testing.eval_set_file


# ---------------------------------------------------------------------------
# 0.13 — harness MONITORED_COUNTRIES includes RO
# ---------------------------------------------------------------------------


def test_harness_monitored_includes_ro():
    """[0.13] harness.MONITORED_COUNTRIES includes 'RO' so RO/9 maps to phone_call."""
    from sentinel.eval.harness import MONITORED_COUNTRIES

    assert "RO" in MONITORED_COUNTRIES


# ---------------------------------------------------------------------------
# 0.12 — harness never writes the labeled fixtures
# ---------------------------------------------------------------------------


def test_harness_does_not_write_fixtures():
    """[0.12] The harness performs no write/open-for-write against tests/fixtures/."""
    src = Path(harness_module.__file__).read_text(encoding="utf-8")
    # No open-for-write/append/exclusive-create against a fixtures path.
    write_to_fixtures = re.findall(r"open\([^)]*fixtures[^)]*,\s*[\"'](?:w|a|x)", src)
    assert write_to_fixtures == [], f"harness opens a fixtures path for writing: {write_to_fixtures}"
    # Belt-and-braces: no line both references a fixtures path and a write mode.
    for line in src.splitlines():
        if "fixtures" not in line:
            continue
        assert not re.search(r"[\"'](?:w|a|x)[\"']", line), f"harness may write a fixtures file: {line.strip()}"


# ---------------------------------------------------------------------------
# 0.4 — Romanian-language Google News fetch actually resolves to a RO edition
# ---------------------------------------------------------------------------


def test_google_news_lang_map_has_romanian():
    """[0.4] The Google News language map resolves 'ro' to a Romanian edition (not the en-US fallback)."""
    from sentinel.fetchers.google_news import LANG_MAP

    assert "ro" in LANG_MAP
    assert LANG_MAP["ro"] == ("ro", "RO")


# ---------------------------------------------------------------------------
# 0.15 — the new event types render in Polish in the alert templates
# ---------------------------------------------------------------------------


def test_event_type_pl_covers_new_types():
    """[0.15] debris_found + official_statement have non-English Polish renderings (alerts are in Polish)."""
    from sentinel.alerts.state_machine import EVENT_TYPE_PL

    for event_type in ("debris_found", "official_statement"):
        assert event_type in EVENT_TYPE_PL, f"{event_type} missing a Polish rendering"
        rendering = EVENT_TYPE_PL[event_type]
        assert rendering and rendering != event_type, f"{event_type} falls back to a raw English token"


# ---------------------------------------------------------------------------
# 0.11 — the report-only regression eval never crashes the gate run
# ---------------------------------------------------------------------------


def _load_sentinel_cli():
    """Load the shadowed sentinel.py CLI script under a distinct module name."""
    import importlib.util
    import os

    script_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "sentinel.py")
    spec = importlib.util.spec_from_file_location("sentinel_cli_entry_cfg", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_regression_eval_survives_broken_set(tmp_path):
    """[0.11] A malformed/empty regression set is non-gating: it must NOT raise out of the runner."""
    import asyncio
    from unittest.mock import MagicMock

    cli = _load_sentinel_cli()

    # An empty YAML file makes load_eval_set raise ValueError BEFORE any classifier
    # call, so this stays fully offline. The runner must swallow it (report-only).
    broken = tmp_path / "broken_regression.yaml"
    broken.write_text("", encoding="utf-8")

    try:
        # Must return normally (no exception) despite the broken set.
        cli._run_regression_eval(str(broken), MagicMock(), MagicMock())
    finally:
        # asyncio.run closes/clears the loop; restore a fresh one for the session.
        asyncio.set_event_loop(asyncio.new_event_loop())
