import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4


def _normalize_title(title: str) -> str:
    nfkd = unicodedata.normalize("NFKD", title)
    stripped = "".join(c for c in nfkd if not unicodedata.combining(c))
    cleaned = re.sub(r"[^a-zA-Z0-9\s]", "", stripped)
    return re.sub(r"\s+", " ", cleaned).strip().lower()


def _url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def _dt_to_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.isoformat()


def _iso_to_dt(s: str | datetime | None) -> datetime | None:
    if s is None:
        return None
    if isinstance(s, datetime):
        return s
    return datetime.fromisoformat(s)


def _json_to_list(s: str | None) -> list:
    if s is None:
        return []
    if isinstance(s, list):
        return s
    return json.loads(s)


@dataclass
class Article:
    source_name: str
    source_url: str
    source_type: str
    title: str
    summary: str
    language: str
    published_at: datetime
    fetched_at: datetime
    raw_metadata: dict = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid4()))
    url_hash: str = field(init=False)
    title_normalized: str = field(init=False)

    def __post_init__(self) -> None:
        self.url_hash = _url_hash(self.source_url)
        self.title_normalized = _normalize_title(self.title)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source_name": self.source_name,
            "source_url": self.source_url,
            "source_type": self.source_type,
            "title": self.title,
            "summary": self.summary,
            "language": self.language,
            "published_at": _dt_to_iso(self.published_at),
            "fetched_at": _dt_to_iso(self.fetched_at),
            "raw_metadata": self.raw_metadata,
            "url_hash": self.url_hash,
            "title_normalized": self.title_normalized,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Article":
        raw_meta = d.get("raw_metadata", "{}")
        if isinstance(raw_meta, str):
            raw_meta = json.loads(raw_meta)

        article = cls(
            source_name=d["source_name"],
            source_url=d["source_url"],
            source_type=d["source_type"],
            title=d["title"],
            summary=d.get("summary", ""),
            language=d["language"],
            published_at=_iso_to_dt(d["published_at"]),
            fetched_at=_iso_to_dt(d["fetched_at"]),
            raw_metadata=raw_meta,
            id=d.get("id", str(uuid4())),
        )
        return article

    @classmethod
    def from_row(cls, row: dict) -> "Article":
        return cls.from_dict(dict(row))


@dataclass
class ClassificationResult:
    article_id: str
    is_military_event: bool
    event_type: str
    urgency_score: int
    affected_countries: list[str]
    aggressor: str
    is_new_event: bool
    confidence: float
    summary_pl: str
    classified_at: datetime
    model_used: str
    input_tokens: int
    output_tokens: int
    id: str = field(default_factory=lambda: str(uuid4()))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "article_id": self.article_id,
            "is_military_event": bool(self.is_military_event),
            "event_type": self.event_type,
            "urgency_score": self.urgency_score,
            "affected_countries": self.affected_countries or [],
            "aggressor": self.aggressor,
            "is_new_event": bool(self.is_new_event),
            "confidence": self.confidence,
            "summary_pl": self.summary_pl,
            "classified_at": _dt_to_iso(self.classified_at),
            "model_used": self.model_used,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ClassificationResult":
        return cls(
            article_id=d["article_id"],
            is_military_event=bool(d["is_military_event"]),
            event_type=d.get("event_type", ""),
            urgency_score=d["urgency_score"],
            affected_countries=_json_to_list(d.get("affected_countries")),
            aggressor=d.get("aggressor", ""),
            is_new_event=bool(d["is_new_event"]),
            confidence=d["confidence"],
            summary_pl=d.get("summary_pl", ""),
            classified_at=_iso_to_dt(d["classified_at"]),
            model_used=d["model_used"],
            input_tokens=d.get("input_tokens", 0),
            output_tokens=d.get("output_tokens", 0),
            id=d.get("id", str(uuid4())),
        )

    @classmethod
    def from_row(cls, row: dict) -> "ClassificationResult":
        return cls.from_dict(dict(row))


@dataclass
class Event:
    event_type: str
    urgency_score: int
    affected_countries: list[str]
    aggressor: str
    summary_pl: str
    first_seen_at: datetime
    last_updated_at: datetime
    source_count: int
    article_ids: list[str]
    alert_status: str = "pending"
    acknowledged_at: datetime | None = None
    id: str = field(default_factory=lambda: str(uuid4()))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "event_type": self.event_type,
            "urgency_score": self.urgency_score,
            "affected_countries": self.affected_countries or [],
            "aggressor": self.aggressor,
            "summary_pl": self.summary_pl,
            "first_seen_at": _dt_to_iso(self.first_seen_at),
            "last_updated_at": _dt_to_iso(self.last_updated_at),
            "source_count": self.source_count,
            "article_ids": self.article_ids or [],
            "alert_status": self.alert_status,
            "acknowledged_at": _dt_to_iso(self.acknowledged_at),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Event":
        return cls(
            event_type=d["event_type"],
            urgency_score=d["urgency_score"],
            affected_countries=_json_to_list(d.get("affected_countries")),
            aggressor=d.get("aggressor", ""),
            summary_pl=d["summary_pl"],
            first_seen_at=_iso_to_dt(d["first_seen_at"]),
            last_updated_at=_iso_to_dt(d["last_updated_at"]),
            source_count=d.get("source_count", 1),
            article_ids=_json_to_list(d.get("article_ids")),
            alert_status=d.get("alert_status", "pending"),
            acknowledged_at=_iso_to_dt(d.get("acknowledged_at")),
            id=d.get("id", str(uuid4())),
        )

    @classmethod
    def from_row(cls, row: dict) -> "Event":
        return cls.from_dict(dict(row))


@dataclass
class AlertRecord:
    event_id: str
    alert_type: str
    twilio_sid: str
    status: str
    attempt_number: int
    sent_at: datetime
    message_body: str
    duration_seconds: int | None = None
    user_id: str | None = None
    id: str = field(default_factory=lambda: str(uuid4()))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "event_id": self.event_id,
            "alert_type": self.alert_type,
            "twilio_sid": self.twilio_sid,
            "status": self.status,
            "duration_seconds": self.duration_seconds,
            "attempt_number": self.attempt_number,
            "sent_at": _dt_to_iso(self.sent_at),
            "message_body": self.message_body,
            "user_id": self.user_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AlertRecord":
        return cls(
            event_id=d["event_id"],
            alert_type=d["alert_type"],
            twilio_sid=d.get("twilio_sid", ""),
            status=d["status"],
            attempt_number=d.get("attempt_number", 1),
            sent_at=_iso_to_dt(d["sent_at"]),
            message_body=d.get("message_body", ""),
            duration_seconds=d.get("duration_seconds"),
            user_id=d.get("user_id"),
            id=d.get("id", str(uuid4())),
        )

    @classmethod
    def from_row(cls, row: dict) -> "AlertRecord":
        return cls.from_dict(dict(row))


@dataclass
class Tier:
    name: str
    available_channels: list[str]
    preference_mode: str
    max_countries: int | None = None
    preset_rules: dict | None = None
    is_active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    id: str = field(default_factory=lambda: str(uuid4()))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "available_channels": self.available_channels,
            "max_countries": self.max_countries,
            "preference_mode": self.preference_mode,
            "preset_rules": self.preset_rules,
            "is_active": bool(self.is_active),
            "created_at": _dt_to_iso(self.created_at),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Tier":
        available_channels = d.get("available_channels", [])
        if isinstance(available_channels, str):
            available_channels = json.loads(available_channels)
        preset_rules = d.get("preset_rules")
        if isinstance(preset_rules, str):
            preset_rules = json.loads(preset_rules)
        return cls(
            name=d["name"],
            available_channels=available_channels,
            preference_mode=d["preference_mode"],
            max_countries=d.get("max_countries"),
            preset_rules=preset_rules,
            is_active=bool(d.get("is_active", True)),
            created_at=_iso_to_dt(d.get("created_at", datetime.now(timezone.utc))),
            id=d.get("id", str(uuid4())),
        )

    @classmethod
    def from_row(cls, row: dict) -> "Tier":
        return cls.from_dict(dict(row))


@dataclass
class User:
    name: str
    phone_number: str
    tier_id: str
    language: str = "pl"
    is_active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    id: str = field(default_factory=lambda: str(uuid4()))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "phone_number": self.phone_number,
            "language": self.language,
            "tier_id": self.tier_id,
            "is_active": bool(self.is_active),
            "created_at": _dt_to_iso(self.created_at),
            "updated_at": _dt_to_iso(self.updated_at),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "User":
        return cls(
            name=d["name"],
            phone_number=d["phone_number"],
            tier_id=d["tier_id"],
            language=d.get("language", "pl"),
            is_active=bool(d.get("is_active", True)),
            created_at=_iso_to_dt(d.get("created_at", datetime.now(timezone.utc))),
            updated_at=_iso_to_dt(d.get("updated_at", datetime.now(timezone.utc))),
            id=d.get("id", str(uuid4())),
        )

    @classmethod
    def from_row(cls, row: dict) -> "User":
        return cls.from_dict(dict(row))


@dataclass
class UserAlertRule:
    user_id: str
    min_urgency: int
    max_urgency: int
    channel: str
    corroboration_required: int = 1
    priority: int = 0
    id: str = field(default_factory=lambda: str(uuid4()))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "min_urgency": self.min_urgency,
            "max_urgency": self.max_urgency,
            "channel": self.channel,
            "corroboration_required": self.corroboration_required,
            "priority": self.priority,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "UserAlertRule":
        return cls(
            user_id=d["user_id"],
            min_urgency=d["min_urgency"],
            max_urgency=d["max_urgency"],
            channel=d["channel"],
            corroboration_required=d.get("corroboration_required", 1),
            priority=d.get("priority", 0),
            id=d.get("id", str(uuid4())),
        )

    @classmethod
    def from_row(cls, row: dict) -> "UserAlertRule":
        return cls.from_dict(dict(row))


@dataclass
class ConfirmationCode:
    user_id: str
    event_id: str
    code: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    used_at: datetime | None = None
    id: str = field(default_factory=lambda: str(uuid4()))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "event_id": self.event_id,
            "code": self.code,
            "created_at": _dt_to_iso(self.created_at),
            "used_at": _dt_to_iso(self.used_at),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ConfirmationCode":
        return cls(
            user_id=d["user_id"],
            event_id=d["event_id"],
            code=d["code"],
            created_at=_iso_to_dt(d.get("created_at", datetime.now(timezone.utc))),
            used_at=_iso_to_dt(d.get("used_at")),
            id=d.get("id", str(uuid4())),
        )

    @classmethod
    def from_row(cls, row: dict) -> "ConfirmationCode":
        return cls.from_dict(dict(row))
