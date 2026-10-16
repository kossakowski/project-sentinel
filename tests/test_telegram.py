"""Tests for the Telegram fetcher."""

import logging
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import telethon

from sentinel.config import SentinelConfig
from sentinel.fetchers.telegram import TelegramFetcher
from sentinel.models import Article


def _make_telegram_config(enabled: bool = False) -> dict:
    """Build a config dict with telegram settings."""
    return {
        "monitoring": {
            "target_countries": [{"code": "PL", "name": "Poland", "name_native": "Polska"}],
            "aggressor_countries": [{"code": "RU", "name": "Russia", "name_native": "Rosja"}],
            "keywords": {"en": {"critical": ["attack"], "high": ["buildup"]}},
            "exclude_keywords": {"en": ["exercise"]},
        },
        "sources": {
            "rss": [
                {
                    "name": "TestFeed",
                    "url": "https://example.com/rss.xml",
                    "language": "en",
                    "enabled": True,
                    "priority": 2,
                },
            ],
            "gdelt": {
                "enabled": True,
                "lookback_minutes": 60,
                "themes": ["ARMEDCONFLICT"],
            },
            "google_news": {
                "enabled": True,
                "queries": [{"query": "test", "language": "en"}],
            },
            "telegram": {
                "enabled": enabled,
                "api_id": 12345 if enabled else None,
                "api_hash": "abc123def456" if enabled else None,
                "session_name": "test_session",
                "channels": [
                    {
                        "name": "Test Channel",
                        "channel_id": "@test_channel",
                        "language": "uk",
                        "priority": 1,
                    },
                ]
                if enabled
                else [],
            },
        },
        "processing": {
            "dedup": {
                "same_source_title_threshold": 85,
                "cross_source_title_threshold": 95,
                "lookback_minutes": 60,
            },
        },
        "classification": {
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 512,
            "temperature": 0.0,
            "corroboration_required": 2,
            "corroboration_window_minutes": 60,
        },
        "alerts": {
            "phone_number": "+48123456789",
            "language": "pl",
            "urgency_levels": {
                "critical": {
                    "min_score": 9,
                    "action": "phone_call",
                    "corroboration_required": 2,
                    "retry_attempts": 3,
                    "retry_interval_minutes": 5,
                    "fallback": "sms",
                },
            },
            "acknowledgment": {
                "call_duration_threshold_seconds": 15,
                "max_call_retries": 3,
                "retry_interval_minutes": 5,
                "cooldown_hours": 6,
            },
        },
        "scheduler": {"interval_minutes": 15, "jitter_seconds": 30},
        "database": {"path": "data/sentinel.db", "article_retention_days": 30, "event_retention_days": 90},
        "logging": {"level": "INFO", "file": "logs/sentinel.log", "max_size_mb": 50, "backup_count": 5},
        "testing": {"dry_run": False},
    }


def _make_mock_message(
    text: str, chat_id: int = 123, msg_id: int = 456, views: int = 100, forwards: int = 5
) -> MagicMock:
    """Create a mock Telegram message."""
    msg = MagicMock()
    msg.text = text
    msg.chat_id = chat_id
    msg.id = msg_id
    msg.date = datetime(2025, 3, 10, 12, 0, 0, tzinfo=UTC)
    msg.views = views
    msg.forwards = forwards
    return msg


def test_message_to_article():
    """Telegram message converted to Article correctly."""
    config_dict = _make_telegram_config(enabled=True)
    config = SentinelConfig(**config_dict)
    fetcher = TelegramFetcher(config)

    message = _make_mock_message(
        text="Breaking: Military movement detected near border",
        chat_id=123,
        msg_id=789,
    )

    # Keyed by the numeric peer id that start() resolves for each channel.
    channel_map = {123: config.sources.telegram.channels[0]}
    article = fetcher._message_to_article(message, channel_map)

    assert article is not None
    assert article.source_type == "telegram"
    assert article.title == "Breaking: Military movement detected near border"
    assert article.summary == "Breaking: Military movement detected near border"
    assert article.source_name == "Test Channel"
    assert article.language == "uk"
    assert "test_channel" in article.source_url
    assert str(789) in article.source_url
    assert article.raw_metadata["message_id"] == 789
    assert article.raw_metadata["views"] == 100
    assert article.raw_metadata["forwards"] == 5


@pytest.mark.asyncio
async def test_buffer_cleared_on_fetch():
    """Buffer emptied after fetch() call."""
    config_dict = _make_telegram_config(enabled=True)
    config = SentinelConfig(**config_dict)
    fetcher = TelegramFetcher(config)

    # Manually add articles to buffer
    article = Article(
        source_name="Test Channel",
        source_url="https://t.me/test/1",
        source_type="telegram",
        title="Test message",
        summary="Test message",
        language="uk",
        published_at=datetime.now(UTC),
        fetched_at=datetime.now(UTC),
    )
    fetcher.buffer.append(article)
    fetcher.buffer.append(article)

    assert len(fetcher.buffer) == 2

    articles = await fetcher.fetch()
    assert len(articles) == 2
    assert len(fetcher.buffer) == 0

    # Second fetch should be empty
    articles2 = await fetcher.fetch()
    assert len(articles2) == 0


@pytest.mark.asyncio
async def test_disabled_telegram():
    """Returns empty list when disabled."""
    config_dict = _make_telegram_config(enabled=False)
    config = SentinelConfig(**config_dict)
    fetcher = TelegramFetcher(config)

    articles = await fetcher.fetch()
    assert articles == []


def test_long_message_truncated():
    """Message longer than 500 chars truncated in summary."""
    config_dict = _make_telegram_config(enabled=True)
    config = SentinelConfig(**config_dict)
    fetcher = TelegramFetcher(config)

    long_text = "A" * 700
    message = _make_mock_message(text=long_text)

    channel_map = {123: config.sources.telegram.channels[0]}
    article = fetcher._message_to_article(message, channel_map)

    assert article is not None
    # Title truncated to 200
    assert len(article.title) == 200
    # Summary truncated to 500
    assert len(article.summary) == 500


# ---------------------------------------------------------------------------
# Channel mapping through the peer ids resolved at start()
# ---------------------------------------------------------------------------

PEER_IDS = {"@test_channel": -1001111111111, "@second_channel": -1002222222222, -1003333333333: -1003333333333}


class _FakeTelegramClient:
    """Stands in for telethon's TelegramClient: resolves PEER_IDS and records handlers."""

    def __init__(self, session, api_id, api_hash):
        self.handlers = []
        self.resolved = []

    async def start(self):
        return self

    async def get_peer_id(self, peer):
        self.resolved.append(peer)
        if peer not in PEER_IDS:
            raise ValueError(f"No user has {peer!r} as username")
        return PEER_IDS[peer]

    def on(self, event):
        def register(callback):
            self.handlers.append((event, callback))
            return callback

        return register

    async def disconnect(self):
        return None


def _two_channel_config(extra_channel: dict | None = None) -> SentinelConfig:
    config_dict = _make_telegram_config(enabled=True)
    config_dict["sources"]["telegram"]["channels"].append(
        {"name": "Second Channel", "channel_id": "@second_channel", "language": "ru", "priority": 1}
    )
    if extra_channel is not None:
        config_dict["sources"]["telegram"]["channels"].append(extra_channel)
    return SentinelConfig(**config_dict)


async def _started_fetcher(monkeypatch, config: SentinelConfig) -> TelegramFetcher:
    monkeypatch.setattr(telethon, "TelegramClient", _FakeTelegramClient)
    fetcher = TelegramFetcher(config)
    await fetcher.start()
    return fetcher


async def _deliver(fetcher: TelegramFetcher, message) -> None:
    for _event, callback in fetcher.client.handlers:
        await callback(SimpleNamespace(message=message))


@pytest.mark.asyncio
async def test_message_maps_to_its_own_channel(monkeypatch):
    fetcher = await _started_fetcher(monkeypatch, _two_channel_config())
    assert fetcher.channels_by_peer == {
        -1001111111111: fetcher.config.sources.telegram.channels[0],
        -1002222222222: fetcher.config.sources.telegram.channels[1],
    }
    [(event, _callback)] = fetcher.client.handlers
    assert sorted(event.chats) == sorted(fetcher.channels_by_peer)

    await _deliver(fetcher, _make_mock_message("Second channel post", chat_id=-1002222222222, msg_id=77))
    await _deliver(fetcher, _make_mock_message("First channel post", chat_id=-1001111111111, msg_id=11))
    second, first = await fetcher.fetch()

    assert second.source_name == "Second Channel"
    assert second.language == "ru"
    assert second.source_url == "https://t.me/second_channel/77"
    assert second.raw_metadata["channel_id"] == "@second_channel"
    assert first.source_name == "Test Channel"
    assert first.language == "uk"
    assert first.source_url == "https://t.me/test_channel/11"


@pytest.mark.asyncio
async def test_unmatched_message_dropped(monkeypatch, caplog):
    fetcher = await _started_fetcher(monkeypatch, _two_channel_config())
    stray = _make_mock_message("Post from a chat that is not configured", chat_id=-1009999999999, msg_id=5)

    with caplog.at_level(logging.WARNING):
        await _deliver(fetcher, stray)
        assert fetcher._message_to_article(stray, fetcher.channels_by_peer) is None

    assert await fetcher.fetch() == []
    assert "-1009999999999" in caplog.text


@pytest.mark.asyncio
async def test_unresolvable_channel_is_left_out(monkeypatch, caplog):
    unknown = {"name": "Gone Channel", "channel_id": "@gone_channel", "language": "uk", "priority": 1}
    with caplog.at_level(logging.ERROR):
        fetcher = await _started_fetcher(monkeypatch, _two_channel_config(unknown))
    assert sorted(ch.name for ch in fetcher.channels_by_peer.values()) == ["Second Channel", "Test Channel"]
    assert "Gone Channel" in caplog.text

    await _deliver(fetcher, _make_mock_message("Still monitored", chat_id=-1001111111111, msg_id=3))
    [article] = await fetcher.fetch()
    assert article.source_name == "Test Channel"


@pytest.mark.asyncio
async def test_numeric_channel_id_resolves_as_a_peer_id(monkeypatch):
    numeric = {"name": "Numeric Channel", "channel_id": "-1003333333333", "language": "uk", "priority": 1}
    fetcher = await _started_fetcher(monkeypatch, _two_channel_config(numeric))
    assert -1003333333333 in fetcher.client.resolved
    assert fetcher.channels_by_peer[-1003333333333].name == "Numeric Channel"
