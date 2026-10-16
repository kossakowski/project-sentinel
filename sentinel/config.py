import os
import re
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator


class ConfigError(Exception):
    pass


class _StrictModel(BaseModel):
    """Base of every config model: an unknown or misspelled key fails loading.

    Pydantic ignores unknown keys by default. A typo such as
    ``max_call_retires`` would then load cleanly and fall back to the code
    default, which for several life-safety keys is the value the owner moved
    away from on purpose.
    """

    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Source models
# ---------------------------------------------------------------------------


class RSSSource(_StrictModel):
    name: str
    url: HttpUrl
    language: str
    enabled: bool = True
    priority: int = 2
    keyword_bypass: bool = False


class GDELTConfig(_StrictModel):
    enabled: bool = True
    lookback_minutes: int = 60
    themes: list[str]


class GoogleNewsQuery(_StrictModel):
    query: str
    language: str


class GoogleNewsConfig(_StrictModel):
    enabled: bool = True
    queries: list[GoogleNewsQuery]


class TelegramChannel(_StrictModel):
    name: str
    channel_id: str
    language: str
    priority: int = 1
    keyword_bypass: bool = False


class TelegramConfig(_StrictModel):
    enabled: bool = True
    api_id: int | None = None
    api_hash: str | None = None
    session_name: str = "sentinel"
    channels: list[TelegramChannel] = []

    @model_validator(mode="after")
    def _require_credentials_when_enabled(self) -> "TelegramConfig":
        if self.enabled and (self.api_id is None or self.api_hash is None):
            raise ValueError("telegram.api_id and telegram.api_hash are required when telegram is enabled")
        return self


class SourcesConfig(_StrictModel):
    rss: list[RSSSource]
    gdelt: GDELTConfig
    google_news: GoogleNewsConfig
    telegram: TelegramConfig


# ---------------------------------------------------------------------------
# Monitoring models
# ---------------------------------------------------------------------------


class KeywordSet(_StrictModel):
    critical: list[str] = []
    high: list[str] = []


class MonitoringConfig(_StrictModel):
    target_countries: list[dict]
    aggressor_countries: list[dict]
    keywords: dict[str, KeywordSet]
    exclude_keywords: dict[str, list[str]] = {}


# ---------------------------------------------------------------------------
# Alert models
# ---------------------------------------------------------------------------


class UrgencyLevel(_StrictModel):
    min_score: int
    # A misspelled action used to load and then deliver nothing at all, so the
    # allowed values are checked at load time.
    action: Literal["phone_call", "sms", "log_only"]
    corroboration_required: int = 1
    retry_attempts: int = 0
    retry_interval_minutes: int = 5
    fallback: str | None = None
    # Per-tier delivery channel for the SMS-action tiers (5-8). Consulted by
    # AlertStateMachine._determine_action only when action == "sms"; ignored for
    # phone_call (9-10) and log_only (1-4) levels. Default "both" is
    # behavior-preserving while push is disabled (SMS only).
    channel: str = "both"

    @field_validator("channel")
    @classmethod
    def _validate_channel(cls, v: str) -> str:
        allowed = {"sms", "push", "both"}
        if v not in allowed:
            raise ValueError(f"channel must be one of {sorted(allowed)}, got {v!r}")
        return v


class AcknowledgmentConfig(_StrictModel):
    call_duration_threshold_seconds: int = 15
    # Calls per round. Zero would place no call at all for a 9-10 event.
    max_call_retries: int = Field(default=3, ge=1)
    retry_interval_minutes: int = 5
    cooldown_hours: int = 6
    call_poll_timeout_seconds: int = 90
    call_poll_interval_seconds: int = 5
    call_retry_pause_seconds: int = 10


# The fields that the alert formatters in ``sentinel/alerts/state_machine.py``
# pass to each template in ``alerts.templates``, each with a sample value of the
# type the formatter passes. Every template is rendered once with these values
# when the config loads, so an unknown placeholder fails loading instead of the
# alert itself (a broken SMS template used to abort the 9-10 path before the
# call). The set lives here because this module cannot import the state machine;
# tests/test_config_validation.py checks that the formatters accept every field.
ALERT_TEMPLATE_FIELDS: dict[str, dict[str, object]] = {
    "call": {
        "event_type_pl": "Inwazja",
        "summary_pl": "Opis zdarzenia.",
        "source_count": 1,
        "urgency_score": 10,
    },
    "sms": {
        "event_type_pl": "Inwazja",
        "urgency_score": 10,
        "affected_countries_str": "PL",
        "aggressor": "RU",
        "summary_pl": "Opis zdarzenia.",
        "source_count": 1,
        "sources_list": "- Źródło: Tytuł\n  https://example.com/artykul",
        "first_seen_at_local": "2026-01-01 12:00 CET",
    },
    "sms_update": {
        "event_type_pl": "Inwazja",
        "new_source_name": "Źródło",
        "summary_pl": "Opis zdarzenia.",
        "source_count": 2,
        "urgency_score": 10,
    },
}


class AlertTemplates(_StrictModel):
    call: str = (
        "{event_type_pl} wykryte. {summary_pl}. Źródła potwierdzające: {source_count}. Pilność: {urgency_score} na 10."
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

    @model_validator(mode="after")
    def _render_with_known_fields(self) -> "AlertTemplates":
        for name, fields in ALERT_TEMPLATE_FIELDS.items():
            try:
                getattr(self, name).format(**fields)
            except (KeyError, IndexError, AttributeError, TypeError, ValueError) as exc:
                raise ValueError(
                    f"alerts.templates.{name} cannot be rendered ({type(exc).__name__}: {exc}); "
                    f"allowed placeholders: {sorted(fields)}"
                ) from exc
        return self


class PushConfig(_StrictModel):
    enabled: bool = False
    tokens: list[str] = []


class TwilioConfig(_StrictModel):
    # Timeout, in seconds, of every Twilio HTTP request (call, SMS, call status
    # and inbound-SMS checks). The SDK default is no timeout, so one half-open
    # connection could block the alert path and the pipeline cycle for good.
    http_timeout_seconds: float = Field(default=30, gt=0, allow_inf_nan=False)


class AlertsConfig(_StrictModel):
    phone_number: str
    language: str = "pl"
    urgency_levels: dict[str, UrgencyLevel]
    acknowledgment: AcknowledgmentConfig
    templates: AlertTemplates = AlertTemplates()
    push: PushConfig = PushConfig()
    twilio: TwilioConfig = Field(default_factory=TwilioConfig)

    @model_validator(mode="after")
    def _check_urgency_levels(self) -> "AlertsConfig":
        levels = self.urgency_levels
        if not any(level.action == "phone_call" for level in levels.values()):
            raise ValueError("alerts.urgency_levels needs a level with action 'phone_call', or 9-10 is never called")
        names_by_score: dict[int, list[str]] = {}
        for name, level in levels.items():
            names_by_score.setdefault(level.min_score, []).append(name)
        shared = {score: names for score, names in names_by_score.items() if len(names) > 1}
        if shared:
            details = "; ".join(f"min_score {score}: {', '.join(names)}" for score, names in sorted(shared.items()))
            raise ValueError(f"alerts.urgency_levels must not share a min_score ({details})")
        return self


# ---------------------------------------------------------------------------
# Other models
# ---------------------------------------------------------------------------


class IncidentMemoryConfig(_StrictModel):
    enabled: bool = False
    lookback_hours: int = Field(default=168, ge=1, le=2160)
    candidate_pool_size: int = Field(default=100, ge=1, le=1000)
    max_candidates: int = Field(default=5, ge=1, le=20)
    evidence_per_event: int = Field(default=2, ge=1, le=5)
    max_text_chars: int = Field(default=300, ge=100, le=2000)
    min_confidence: float = Field(default=0.85, ge=0.5, le=1.0)
    critical_min_confidence: float = Field(default=0.9, ge=0.5, le=1.0)
    extra_output_tokens: int = Field(default=256, ge=128, le=1024)
    weekday_aliases: dict[str, list[str]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_candidate_limits(self) -> "IncidentMemoryConfig":
        if self.max_candidates > self.candidate_pool_size:
            raise ValueError("max_candidates must not exceed candidate_pool_size")
        if self.critical_min_confidence < self.min_confidence:
            raise ValueError("critical_min_confidence must be at least min_confidence")
        return self


class ModelBudgetConfig(_StrictModel):
    ledger_path: str = "data/model-usage.db"
    monthly_usd: float = Field(default=10, gt=0, le=50, allow_inf_nan=False)
    input_per_million: float = Field(default=0.20, gt=0, allow_inf_nan=False)
    cached_input_per_million: float = Field(default=0.02, ge=0, allow_inf_nan=False)
    output_per_million: float = Field(default=1.20, gt=0, allow_inf_nan=False)
    cache_write_multiplier: float = Field(default=1.25, ge=1, allow_inf_nan=False)


class SummaryLanguageConfig(_StrictModel):
    detector_languages: list[str] = Field(
        default_factory=lambda: ["pl", "en", "uk", "ru", "de", "cs", "sk", "lt", "lv", "et"]
    )
    repair_max_tokens: int = Field(default=512, ge=128, le=1024)
    repair_timeout_seconds: float = Field(default=10, gt=0, le=30)
    fallback_pl: str = Field(
        default="Polskie podsumowanie jest chwilowo niedostępne. Sprawdź źródła dołączone do powiadomienia.",
        min_length=20,
        max_length=500,
    )

    @model_validator(mode="after")
    def _validate_language_guard(self):
        from lingua import IsoCode639_1

        from sentinel.classification.summary_language import is_polish

        languages = self.detector_languages
        if len(set(languages)) != len(languages) or not {"pl", "en", "uk", "ru"} <= set(languages):
            raise ValueError("Summary detector must include pl/en/uk/ru without duplicates")
        if any(not hasattr(IsoCode639_1, code.upper()) for code in languages):
            raise ValueError("Unsupported summary detector language code")
        if not is_polish(self.fallback_pl, tuple(languages)):
            raise ValueError("Summary fallback must be Polish")
        return self


class ClassificationConfig(_StrictModel):
    # Omitted provider preserves existing installations until explicit migration.
    provider: Literal["anthropic", "openai"] = "anthropic"
    api_base_url: Literal["https://api.openai.com/v1"] = "https://api.openai.com/v1"
    policy: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: float = Field(default=30, gt=0, le=120)
    reasoning_effort: Literal["none"] = "none"
    budget: ModelBudgetConfig = Field(default_factory=ModelBudgetConfig)
    retry_delay_seconds: int = Field(default=300, ge=1)
    retry_batch_size: int = Field(default=100, ge=1, le=1000)
    summary_language: SummaryLanguageConfig = Field(default_factory=SummaryLanguageConfig)

    @model_validator(mode="after")
    def _validate_direct_policy(self):
        if self.provider == "openai":
            if not self.model.startswith("gpt-"):
                raise ValueError("OpenAI provider requires an explicit OpenAI model ID")
            from sentinel.classification.policy import system_prompt

            try:
                if self.policy.get("version") != 2 or not self.policy.get("monitored_countries"):
                    raise ValueError("Missing clarified policy version 2")
                for bounds in self.policy["ranges"].values():
                    if (
                        not isinstance(bounds, list)
                        or len(bounds) != 2
                        or any(type(x) is not int for x in bounds)
                        or not 1 <= bounds[0] <= bounds[1] <= 10
                    ):
                        raise ValueError("Invalid policy urgency range")
                system_prompt(self.policy)
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("OpenAI mode requires the complete approved classification.policy") from exc
        return self

    incident_memory: IncidentMemoryConfig = Field(default_factory=IncidentMemoryConfig)
    model: str = "claude-haiku-4-5-20251001"
    max_tokens: int = Field(default=512, ge=128, le=4096)
    temperature: float = 0.0
    corroboration_required: int = 2
    corroboration_window_minutes: int = 360
    # Absolute cap (measured from first_seen_at) on how long one event keeps
    # absorbing articles. With the sliding (last-activity) corroboration window a
    # perpetually-updated event would otherwise live forever and could chain-merge
    # genuinely distinct incidents; this retires it. 0 disables the cap.
    corroboration_max_age_minutes: int = 2880
    summary_similarity_threshold: int = 50
    # rapidfuzz.fuzz metric used to compare two summaries when grouping. token_set_ratio
    # is length-robust (a short wire headline and a long elaboration of the SAME incident
    # still score high), unlike the length-sensitive token_sort_ratio.
    summary_similarity_metric: str = "token_set_ratio"
    syndication_similarity_threshold: int = 90

    @field_validator("summary_similarity_metric")
    @classmethod
    def _validate_summary_metric(cls, v: str) -> str:
        allowed = {"ratio", "partial_ratio", "token_sort_ratio", "token_set_ratio", "WRatio", "QRatio"}
        if v not in allowed:
            raise ValueError(f"summary_similarity_metric must be one of {sorted(allowed)}, got {v!r}")
        return v


class SchedulerConfig(_StrictModel):
    interval_minutes: int = 15
    fast_interval_minutes: int = 3
    jitter_seconds: int = 30


class DatabaseConfig(_StrictModel):
    path: str = "data/sentinel.db"
    article_retention_days: int = 30
    event_retention_days: int = 90


class LoggingConfig(_StrictModel):
    level: str = "INFO"
    file: str = "logs/sentinel.log"
    max_size_mb: int = 50
    backup_count: int = 5


class TestingConfig(_StrictModel):
    dry_run: bool = False
    eval_set_file: str = "tests/fixtures/eval_set.yaml"


class ProcessingDedup(_StrictModel):
    same_source_title_threshold: int = 85
    cross_source_title_threshold: int = 95
    lookback_minutes: int = 60


class ProcessingConfig(_StrictModel):
    dedup: ProcessingDedup


# ---------------------------------------------------------------------------
# Top-level config
# ---------------------------------------------------------------------------


class SentinelConfig(_StrictModel):
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
                    f"Environment variable '{var_name}' is not set (referenced as ${{{var_name}}} in config)"
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
    """Load, substitute and validate the YAML config at ``config_path``.

    ``${VAR}`` placeholders resolve from the current process environment only.
    This function never reads a ``.env`` file; the CLI entry point
    (``sentinel.py main()``) loads ``.env`` before it calls this, so tests and
    other callers see exactly the environment they were given.
    """
    try:
        with open(config_path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except FileNotFoundError as e:
        raise ConfigError(f"Config file not found: {config_path}") from e
    except yaml.YAMLError as e:
        raise ConfigError(f"Invalid YAML in {config_path}: {e}") from e

    if raw is None:
        raise ConfigError(f"Config file is empty: {config_path}")

    substituted = _substitute_env_vars(raw)

    try:
        return SentinelConfig(**substituted)
    except Exception as e:
        raise ConfigError(f"Config validation failed: {e}") from e
