import os
import re
from typing import Any

import yaml
from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator


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
    keyword_bypass: bool = False


class GDELTConfig(BaseModel):
    enabled: bool = True
    lookback_minutes: int = 60
    themes: list[str]


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
    keyword_bypass: bool = False


class TelegramConfig(BaseModel):
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
# Geography models
# ---------------------------------------------------------------------------


class GeographyConfig(BaseModel):
    """Country-level geography tiers.

    Country resolution stays LLM-driven and country-level; this block carries
    NO city/town/place list or gazetteer -- only whole-country codes.
    """

    # Whole countries whose soil is HIGH geo-tier (call-tier-eligible for a strike
    # anywhere on their territory, including the capital).
    high_tier_countries: list[str] = ["PL", "LT", "LV", "EE", "RO"]
    # Classifier event_type values that count as a kinetic strike. Consumed by
    # GeoWeighter (the Poland floor) and the Phase 3 kinetic separator. Excludes
    # debris_found / official_statement -- inert-debris recovery and reaction
    # stories are not kinetic strikes (owner labels PL debris = 8/sms).
    kinetic_event_types: list[str] = [
        "invasion",
        "airstrike",
        "missile_strike",
        "artillery_shelling",
        "drone_attack",
    ]
    # Countries whose soil, when a kinetic strike lands on it, floors the event to
    # the call tier (>= 9) regardless of the LLM's number. Poland only by default:
    # every kinetic strike on Polish soil in the ground truth is 9-10/call, while
    # Baltic/Romanian strikes are scenario-conditional (carried by the prompt and
    # the eval gates, not a universal floor).
    floor_countries: list[str] = ["PL"]
    # Countries the classifier may name that are KNOWN but not HIGH: their soil is
    # LOW geo tier (routine inside-Ukraine / interior-Moldova / inside-Russia
    # warfare). Membership matters because an UNRECOGNIZED country token is treated
    # as UNKNOWN and fails OPEN to a call at call urgency (2.5a), while a LOW tier
    # demotes that call to an SMS -- so only countries listed here (or above) may
    # demote a 9-10.
    low_tier_countries: list[str] = ["UA", "MD", "RU", "BY"]
    # Countries whose soil, when attacked BY a NATO member, is HIGH geo tier (the
    # R11 "NATO attacks Russia" case: the alliance is now kinetically engaged).
    nato_attack_targets: list[str] = ["RU"]
    # Name aliases for the countries named in the tier lists above, in the same
    # {code, name, name_native} shape monitoring.target_countries uses. The tier
    # lists carry bare ISO codes, so without this a classifier that emits the
    # country NAME ("Ukraine"/"Ukraina") instead of the code would not resolve, the
    # tier would be UNKNOWN, and the LOW demotion this block exists for would not
    # happen (it fails OPEN to a call -- safe, but it defeats the demotion). The
    # monitored PL/LT/LV/EE/RO and RU/BY names come from monitoring.*_countries;
    # these cover the rest of the tier lists.
    country_names: list[dict] = [
        {"code": "UA", "name": "Ukraine", "name_native": "Ukraina"},
        {"code": "MD", "name": "Moldova", "name_native": "Mołdawia"},
    ]


# The classifier's urgency scale (classifier.py clamps to this range). The band
# map must cover it end to end, so every classification lands in exactly one band.
URGENCY_MIN = 1
URGENCY_MAX = 10

# Channel classes, ordered by escalation. Used to reject an inverted band map
# (e.g. a notify band sitting ABOVE the call band).
_CHANNEL_CLASS_RANK = {"none": 0, "notify": 1, "call": 2}


class ChannelBand(BaseModel):
    """One urgency -> channel-class band (rubric v2 alert banding).

    ``channel_class`` is one of ``call`` / ``notify`` / ``none``; the highest
    ``min_score`` band an event's urgency clears wins.
    """

    min_score: int
    channel_class: str

    @field_validator("channel_class")
    @classmethod
    def _validate_channel_class(cls, v: str) -> str:
        allowed = set(_CHANNEL_CLASS_RANK)
        if v not in allowed:
            raise ValueError(f"channel_class must be one of {sorted(allowed)}, got {v!r}")
        return v


# ---------------------------------------------------------------------------
# Alert models
# ---------------------------------------------------------------------------


class UrgencyLevel(BaseModel):
    min_score: int
    action: str
    retry_interval_minutes: int = 5
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


class AcknowledgmentConfig(BaseModel):
    call_duration_threshold_seconds: int = 15
    # ge=1: a mistyped 0 would make each round place zero calls yet still march the
    # event to failed_terminal having never rung the operator — same failure class
    # the RetryConfig.max_rounds bound guards, so fail fast at config load.
    max_call_retries: int = Field(default=3, ge=1)
    retry_interval_minutes: int = 5
    cooldown_hours: int = 6
    call_poll_timeout_seconds: int = 90
    call_poll_interval_seconds: int = 5
    call_retry_pause_seconds: int = 10


class RetryConfig(BaseModel):
    """Cross-cycle phone-call retry bound (Phase 1).

    ``max_rounds`` caps how many retry rounds a single event may run across
    scheduler cycles, enforced against the durable ``events.alert_round_count``
    counter (never in-memory state). When the counter reaches this cap the event
    moves to a terminal ``failed_terminal`` status and stops re-entering the
    retry loop. This is the ONLY retry bound (the old, never-read
    ``urgency_levels.*.retry_attempts`` knob is gone). Life-safety: keep this high
    enough that a real 9-10 keeps calling.

    Constrained to ``>= 1`` so a mistyped ``0``/negative fails fast at config
    load rather than silently satisfying ``alert_round_count >= max_rounds`` on
    first touch and disabling every call-tier alert system-wide.

    ``sweep_max_age_minutes`` bounds the cycle-driven retry sweep by recency: only
    events whose LAST activity (``events.last_updated_at``) falls within this
    window are re-entered by the sweep. An actively-retrying event has its
    ``last_updated_at`` bumped every round, so it stays inside the window; a stale
    ``retry_pending`` row left over from a historical event or an unacknowledged
    ``--test-alert`` (both still within DB retention) ages out and is NOT swept —
    otherwise a deploy would re-activate every historical ``retry_pending`` row at
    once (a call storm). Keep it comfortably larger than
    ``max_rounds * acknowledgment.retry_interval_minutes`` so a legitimately
    in-progress retry never ages out mid-sequence. An event stranded BEYOND this
    window by a process outage longer than the window is not silently abandoned:
    the sweep finalizes it fail-loud (terminal + SMS/push fallback) rather than
    leave it in ``retry_pending`` limbo.

    ``sweep_max_events_per_cycle`` bounds how many events the sweep may drive
    through a (blocking) call round in a single scheduler cycle, so a crisis that
    leaves many events retry-pending cannot stall article fetch/classification for
    the whole cycle; the remainder are picked up on the next cycle. Oldest-waiting
    events are processed first. ``0`` disables the bound (process all).
    """

    max_rounds: int = Field(default=10, ge=1)
    sweep_max_age_minutes: int = Field(default=180, ge=1)
    sweep_max_events_per_cycle: int = Field(default=3, ge=0)
    # An event aged out of the re-call window (above) but whose last activity is
    # still within THIS larger window is a RECENTLY-stranded call-tier event (e.g. a
    # process outage longer than sweep_max_age_minutes): it is finalized terminally
    # AND notified via the SMS+push fallback. An event older than this is stale (a
    # pre-existing historical row) and is finalized with an error log only — no
    # SMS/push, so a post-deploy backlog does not spam the operator about weeks-old
    # events. Keep it comfortably above sweep_max_age_minutes.
    sweep_notify_max_age_minutes: int = Field(default=1440, ge=1)
    # Wall-clock bound on how long the cycle-driven sweep may spend placing (blocking)
    # call rounds per scheduler cycle, so a backlog of unacknowledged call-tier events
    # cannot hold the pipeline cycle lock long enough to starve fetch/classification of
    # a NEW incident. Complements sweep_max_events_per_cycle (a count bound). Checked
    # BETWEEN rounds, so the sweep can overshoot by at most one in-progress round
    # (~max_call_retries * (call_poll_timeout_seconds + call_retry_pause_seconds)); a
    # single round is atomic and cannot be interrupted. Fully removing the residual
    # lock hold requires running the rounds off the cycle lock (a future change).
    # 0 disables.
    sweep_max_seconds_per_cycle: int = Field(default=120, ge=0)


class AlertTemplates(BaseModel):
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


class PushConfig(BaseModel):
    enabled: bool = False
    tokens: list[str] = []


class AlertsConfig(BaseModel):
    phone_number: str
    language: str = "pl"
    urgency_levels: dict[str, UrgencyLevel]
    acknowledgment: AcknowledgmentConfig
    retry: RetryConfig = RetryConfig()
    templates: AlertTemplates = AlertTemplates()
    push: PushConfig = PushConfig()
    # Urgency -> channel-class bands (rubric v2), the single source of truth for
    # AlertPolicy's band mapping: >= 9 -> call, 5-8 -> notify (SMS/push), <= 4 ->
    # none. The per-tier `urgency_levels.*.channel` still routes a NOTIFY band to
    # sms/push/both; these bands only decide the class.
    channel_bands: list[ChannelBand] = [
        ChannelBand(min_score=9, channel_class="call"),
        ChannelBand(min_score=5, channel_class="notify"),
        ChannelBand(min_score=1, channel_class="none"),
    ]

    @model_validator(mode="after")
    def _validate_channel_bands(self) -> "AlertsConfig":
        """Fail fast on a band map that could silence the call tier.

        ``AlertPolicy`` reads the whole alert decision out of this map, so one YAML
        typo here (an empty list, a missing ``call`` band, an urgency the map does
        not cover, or a notify band sitting above the call band) would silently
        route an urgency-10 event on Polish soil to NOTIFY or to nothing at all --
        with every test still green. A misconfigured band map must break at config
        load, never in production.
        """
        bands = self.channel_bands
        if not bands:
            raise ValueError("alerts.channel_bands must not be empty (it is the only alert-band map AlertPolicy reads)")

        classes = {b.channel_class for b in bands}
        if "call" not in classes:
            raise ValueError(
                "alerts.channel_bands must contain a band with channel_class: call — "
                "without it no event can ever place a phone call (urgency 9-10 is life-safety critical)"
            )

        scores = [b.min_score for b in bands]
        out_of_range = [s for s in scores if not URGENCY_MIN <= s <= URGENCY_MAX]
        if out_of_range:
            raise ValueError(
                f"alerts.channel_bands min_score values must be within the urgency scale "
                f"{URGENCY_MIN}-{URGENCY_MAX}, got {sorted(out_of_range)}"
            )
        if len(set(scores)) != len(scores):
            raise ValueError(f"alerts.channel_bands min_score values must be unique, got {sorted(scores)}")

        band_classes = [b.channel_class for b in bands]
        if len(set(band_classes)) != len(band_classes):
            # Two bands of the same class (e.g. call at 10 AND call at 9) make "the
            # call tier" ambiguous: the band map would still escalate monotonically,
            # yet callers asking "what is the lowest call urgency?" could disagree
            # with AlertPolicy's band lookup. Everything downstream (the corroborator's
            # acknowledged/failed_terminal absorption guard, its concrete-country gate)
            # keys off ONE call tier -- a disagreement there can silence a real call.
            # One band per class, always.
            raise ValueError(
                f"alerts.channel_bands must contain at most one band per channel_class, got {sorted(band_classes)} "
                "(two bands of the same class make the call tier ambiguous)"
            )

        if min(scores) > URGENCY_MIN:
            raise ValueError(
                f"alerts.channel_bands must cover every urgency: the lowest band's min_score must be "
                f"{URGENCY_MIN}, got {min(scores)} (urgencies below it map to no band at all)"
            )

        ranks = [_CHANNEL_CLASS_RANK[b.channel_class] for b in sorted(bands, key=lambda b: b.min_score, reverse=True)]
        if ranks != sorted(ranks, reverse=True):
            raise ValueError(
                "alerts.channel_bands must escalate with urgency: the call band's min_score must be "
                "above the notify band's, which must be above the none band's"
            )
        return self

    @model_validator(mode="after")
    def _validate_sweep_windows(self) -> "AlertsConfig":
        # The retry sweep re-calls an event only while its last activity is within
        # retry.sweep_max_age_minutes, and a round bumps last_updated_at only at its
        # END. If the inter-round interval is not comfortably smaller than the sweep
        # window, a live event ages out of the window between rounds and is finalized
        # before it can ring again — silently disabling ring-until-acknowledged. Fail
        # fast at config load rather than in production.
        if self.acknowledgment.retry_interval_minutes >= self.retry.sweep_max_age_minutes:
            raise ValueError(
                "alerts.acknowledgment.retry_interval_minutes "
                f"({self.acknowledgment.retry_interval_minutes}) must be less than "
                f"alerts.retry.sweep_max_age_minutes ({self.retry.sweep_max_age_minutes}) "
                "so an actively-retrying event is not aged out of the sweep between rounds"
            )
        if self.retry.sweep_notify_max_age_minutes < self.retry.sweep_max_age_minutes:
            raise ValueError(
                "alerts.retry.sweep_notify_max_age_minutes "
                f"({self.retry.sweep_notify_max_age_minutes}) must be >= "
                f"alerts.retry.sweep_max_age_minutes ({self.retry.sweep_max_age_minutes})"
            )
        return self


# ---------------------------------------------------------------------------
# Other models
# ---------------------------------------------------------------------------


class ClassificationConfig(BaseModel):
    model: str = "claude-haiku-4-5-20251001"
    max_tokens: int = 512
    temperature: float = 0.0
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

    @field_validator("summary_similarity_metric")
    @classmethod
    def _validate_summary_metric(cls, v: str) -> str:
        allowed = {"ratio", "partial_ratio", "token_sort_ratio", "token_set_ratio", "WRatio", "QRatio"}
        if v not in allowed:
            raise ValueError(f"summary_similarity_metric must be one of {sorted(allowed)}, got {v!r}")
        return v


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
    eval_set_file: str = "tests/fixtures/eval_set.yaml"
    # Report-only regression eval set (frozen past classifier behavior), run
    # non-gating alongside the gate eval (eval_set_file).
    regression_eval_set_file: str = "tests/fixtures/eval_set.yaml"


class ProcessingDedup(BaseModel):
    same_source_title_threshold: int = 85
    cross_source_title_threshold: int = 95
    lookback_minutes: int = 60


class ProcessingConfig(BaseModel):
    dedup: ProcessingDedup


class DedupConfig(BaseModel):
    """Event-deduplication settings (the new EventDeduplicator surface).

    ``min_event_urgency`` is the config-driven pre-dedup event-creation gate that
    replaces the hardcoded ``corroborator._MIN_EVENT_URGENCY``: a classification
    whose urgency is below this does not create an event row (its classification
    is still persisted). The military-flag drop is exempted for ``debris_found`` /
    ``official_statement`` stories in code, so an sms-tier meta-event cannot be
    dropped before the deduplicator sees it.
    """

    min_event_urgency: int = 5


# ---------------------------------------------------------------------------
# Top-level config
# ---------------------------------------------------------------------------


class SentinelConfig(BaseModel):
    monitoring: MonitoringConfig
    geography: GeographyConfig = GeographyConfig()
    sources: SourcesConfig
    classification: ClassificationConfig
    alerts: AlertsConfig
    scheduler: SchedulerConfig
    database: DatabaseConfig
    logging: LoggingConfig
    testing: TestingConfig
    processing: ProcessingConfig
    dedup: DedupConfig = DedupConfig()

    @model_validator(mode="after")
    def _validate_event_gate_below_alert_bands(self) -> "SentinelConfig":
        """The pre-event gate must never sit above an alerting band.

        ``dedup.min_event_urgency`` drops a classification BEFORE any event row
        exists — before dedup, before dispatch, before any alert. If it were set
        above the lowest alerting (notify/call) band, every event in the gap would
        die silently with all tests green: e.g. min_event_urgency 7 with a notify
        band at 5 kills every urgency-5/6 SMS-tier event. Cross-checked at load.
        """
        alerting = [b.min_score for b in self.alerts.channel_bands if b.channel_class in ("notify", "call")]
        if not alerting:
            return self
        lowest_alerting = min(alerting)
        if self.dedup.min_event_urgency > lowest_alerting:
            raise ValueError(
                f"dedup.min_event_urgency ({self.dedup.min_event_urgency}) must be <= the lowest alerting "
                f"alerts.channel_bands min_score ({lowest_alerting}) — otherwise alert-band events are "
                "dropped before an event row is ever created and no alert can fire for them"
            )
        return self


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
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

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
