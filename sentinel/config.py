import os
import re
from typing import Any

import yaml
from pydantic import BaseModel, HttpUrl, model_validator


class ConfigError(Exception):
    pass


# ---------------------------------------------------------------------------
# Source models
# ---------------------------------------------------------------------------

class RSSSource(BaseModel):
    name: str
    url: HttpUrl
    language: str
    enabled: bool = True
    priority: int = 2


class GDELTConfig(BaseModel):
    enabled: bool = True
    update_interval_minutes: int = 15
    themes: list[str]
    cameo_codes: list[str]
    goldstein_threshold: float = -7.0


class GoogleNewsQuery(BaseModel):
    query: str
    language: str


class GoogleNewsConfig(BaseModel):
    enabled: bool = True
    queries: list[GoogleNewsQuery]


class TelegramChannel(BaseModel):
    name: str
    channel_id: str
    language: str
    priority: int = 1


class TelegramConfig(BaseModel):
    enabled: bool = True
    api_id: int | None = None
    api_hash: str | None = None
    session_name: str = "sentinel"
    channels: list[TelegramChannel] = []

    @model_validator(mode="after")
    def _require_credentials_when_enabled(self) -> "TelegramConfig":
        if self.enabled:
            if self.api_id is None or self.api_hash is None:
                raise ValueError(
                    "telegram.api_id and telegram.api_hash are required when telegram is enabled"
                )
        return self


class SourcesConfig(BaseModel):
    rss: list[RSSSource]
    gdelt: GDELTConfig
    google_news: GoogleNewsConfig
    telegram: TelegramConfig


# ---------------------------------------------------------------------------
# Monitoring models
# ---------------------------------------------------------------------------

class KeywordSet(BaseModel):
    critical: list[str] = []
    high: list[str] = []


class MonitoringConfig(BaseModel):
    target_countries: list[dict]
    aggressor_countries: list[dict]
    keywords: dict[str, KeywordSet]
    exclude_keywords: dict[str, list[str]] = {}


# ---------------------------------------------------------------------------
# Alert models
# ---------------------------------------------------------------------------

class UrgencyLevel(BaseModel):
    min_score: int
    action: str
    corroboration_required: int = 1
    retry_attempts: int = 0
    retry_interval_minutes: int = 5
    fallback: str | None = None


class AcknowledgmentConfig(BaseModel):
    call_duration_threshold_seconds: int = 15
    max_call_retries: int = 3
    retry_interval_minutes: int = 5
    cooldown_hours: int = 6


class AlertTemplates(BaseModel):
    call: str = (
        "{event_type_pl} wykryte. {summary_pl}. "
        "Źródła potwierdzające: {source_count}. "
        "Pilność: {urgency_score} na 10."
    )
    sms: str = (
        "\U0001f6a8 PROJECT SENTINEL: {event_type_pl}\n"
        "Pilność: {urgency_score}/10\n"
        "Kraje: {affected_countries_str}\n"
        "Agresor: {aggressor}\n"
        "\n"
        "{summary_pl}\n"
        "\n"
        "Źródła ({source_count}):\n"
        "{sources_list}\n"
        "\n"
        "Wykryto: {first_seen_at_local}"
    )
    sms_update: str = (
        "\u2139\ufe0f PROJECT SENTINEL UPDATE: {event_type_pl}\n"
        "Nowe informacje ({new_source_name}):\n"
        "{summary_pl}\n"
        "\n"
        "Łącznie źródeł: {source_count}\n"
        "Pilność: {urgency_score}/10"
    )


class AlertsConfig(BaseModel):
    phone_number: str
    language: str = "pl"
    urgency_levels: dict[str, UrgencyLevel]
    acknowledgment: AcknowledgmentConfig
    templates: AlertTemplates = AlertTemplates()


# ---------------------------------------------------------------------------
# Other models
# ---------------------------------------------------------------------------

class ClassificationConfig(BaseModel):
    model: str = "claude-haiku-4-5-20251001"
    max_tokens: int = 512
    temperature: float = 0.0
    corroboration_required: int = 2
    corroboration_window_minutes: int = 60


class SchedulerConfig(BaseModel):
    interval_minutes: int = 15
    fast_interval_minutes: int = 3
    jitter_seconds: int = 30


class DatabaseConfig(BaseModel):
    path: str = "data/sentinel.db"
    article_retention_days: int = 30
    event_retention_days: int = 90


class LoggingConfig(BaseModel):
    level: str = "INFO"
    file: str = "logs/sentinel.log"
    max_size_mb: int = 50
    backup_count: int = 5


class TestingConfig(BaseModel):
    dry_run: bool = False
    test_mode: bool = False
    test_headlines_file: str = "tests/fixtures/test_headlines.yaml"


class ProcessingDedup(BaseModel):
    same_source_title_threshold: int = 85
    cross_source_title_threshold: int = 95
    lookback_minutes: int = 60


class ProcessingConfig(BaseModel):
    dedup: ProcessingDedup


# ---------------------------------------------------------------------------
# Top-level config
# ---------------------------------------------------------------------------

class SentinelConfig(BaseModel):
    monitoring: MonitoringConfig
    sources: SourcesConfig
    classification: ClassificationConfig
    alerts: AlertsConfig
    scheduler: SchedulerConfig
    database: DatabaseConfig
    logging: LoggingConfig
    testing: TestingConfig
    processing: ProcessingConfig


# ---------------------------------------------------------------------------
# Environment variable substitution
# ---------------------------------------------------------------------------

_ENV_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}")


def _substitute_env_vars(data: Any) -> Any:
    if isinstance(data, str):
        def _replacer(match: re.Match) -> str:
            var_name = match.group(1)
            value = os.environ.get(var_name)
            if value is None:
                raise ConfigError(
                    f"Environment variable '{var_name}' is not set "
                    f"(referenced as ${{{var_name}}} in config)"
                )
            return value

        return _ENV_VAR_PATTERN.sub(_replacer, data)
    elif isinstance(data, dict):
        return {k: _substitute_env_vars(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [_substitute_env_vars(item) for item in data]
    return data


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------

def load_config(config_path: str) -> SentinelConfig:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except FileNotFoundError:
        raise ConfigError(f"Config file not found: {config_path}")
    except yaml.YAMLError as e:
        raise ConfigError(f"Invalid YAML in {config_path}: {e}")

    if raw is None:
        raise ConfigError(f"Config file is empty: {config_path}")

    substituted = _substitute_env_vars(raw)

    try:
        return SentinelConfig(**substituted)
    except Exception as e:
        raise ConfigError(f"Config validation failed: {e}") from e
