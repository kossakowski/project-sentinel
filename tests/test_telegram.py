"""Tests for the Telegram fetcher."""

import asyncio
import logging
import time
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import telethon
from telethon.errors import FloodWaitError

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
    """Stands in for telethon's TelegramClient: resolves its peer_ids and records handlers."""

    def __init__(self, session, api_id, api_hash):
        self.handlers = []
        self.resolved = []
        # Per client, so a test can make a channel resolvable (or not) after start().
        self.peer_ids = dict(PEER_IDS)
        self.failure: Exception | None = None

    async def start(self):
        return self

    async def get_peer_id(self, peer):
        self.resolved.append(peer)
        if self.failure is not None:
            raise self.failure
        if peer not in self.peer_ids:
            raise ValueError(f"No user has {peer!r} as username")
        return self.peer_ids[peer]

    def add_event_handler(self, callback, event):
        self.handlers.append((event, callback))

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


GONE_CHANNEL = {"name": "Gone Channel", "channel_id": "@gone_channel", "language": "uk", "priority": 1}
GONE_PEER_ID = -1004444444444


async def _deliver_to_matching(fetcher: TelegramFetcher, message) -> None:
    """Deliver like telethon does: only to the handlers whose chats include the message's chat."""
    for event, callback in fetcher.client.handlers:
        if message.chat_id in event.chats:
            await callback(SimpleNamespace(message=message))


async def _drain_with_retry(fetcher: TelegramFetcher) -> list[Article]:
    """Call fetch() and wait for the channel retry it schedules in the background."""
    articles = await fetcher.fetch()
    if fetcher._retry_task is not None:
        await fetcher._retry_task
    return articles


@pytest.mark.asyncio
async def test_unresolved_channel_is_retried_on_fetch(monkeypatch, caplog):
    fetcher = await _started_fetcher(monkeypatch, _two_channel_config(GONE_CHANNEL))
    assert GONE_PEER_ID not in fetcher.channels_by_peer

    # Still not resolvable: the retry logs it and keeps it pending.
    with caplog.at_level(logging.WARNING):
        assert await _drain_with_retry(fetcher) == []
    assert fetcher.client.resolved.count("@gone_channel") == 2
    assert "Gone Channel" in caplog.text
    assert GONE_PEER_ID not in fetcher.channels_by_peer

    # The lookup succeeds on a later fetch: the channel joins and its messages map to it.
    fetcher.client.peer_ids["@gone_channel"] = GONE_PEER_ID
    await _drain_with_retry(fetcher)
    assert fetcher.channels_by_peer[GONE_PEER_ID].name == "Gone Channel"
    assert [sorted(event.chats) for event, _callback in fetcher.client.handlers] == [
        sorted([-1001111111111, -1002222222222]),
        [GONE_PEER_ID],
    ]

    await _deliver_to_matching(fetcher, _make_mock_message("Back on air", chat_id=GONE_PEER_ID, msg_id=9))
    await _deliver_to_matching(fetcher, _make_mock_message("Monitored all along", chat_id=-1001111111111, msg_id=10))
    gone, first = await _drain_with_retry(fetcher)
    assert gone.source_name == "Gone Channel"
    assert gone.source_url == "https://t.me/gone_channel/9"
    assert first.source_name == "Test Channel"

    # Nothing is pending any more, so later fetches resolve nothing.
    lookups = len(fetcher.client.resolved)
    await _drain_with_retry(fetcher)
    assert len(fetcher.client.resolved) == lookups


class _OfflineAtStartClient(_FakeTelegramClient):
    """Connects, but every channel lookup fails until a test clears ``failure``."""

    def __init__(self, session, api_id, api_hash):
        super().__init__(session, api_id, api_hash)
        self.failure = ConnectionError("Telegram is unreachable")


@pytest.mark.asyncio
async def test_listener_starts_once_a_channel_resolves_after_start(monkeypatch):
    monkeypatch.setattr(telethon, "TelegramClient", _OfflineAtStartClient)
    fetcher = TelegramFetcher(_two_channel_config())
    await fetcher.start()
    assert fetcher.channels_by_peer == {}
    assert fetcher.client.handlers == []

    fetcher.client.failure = None
    await _drain_with_retry(fetcher)
    [(event, _callback)] = fetcher.client.handlers
    assert sorted(event.chats) == sorted([-1001111111111, -1002222222222])

    await _deliver_to_matching(fetcher, _make_mock_message("First post after the retry", chat_id=-1002222222222))
    [article] = await fetcher.fetch()
    assert article.source_name == "Second Channel"


@pytest.mark.asyncio
async def test_channel_retry_honours_flood_wait(monkeypatch):
    fetcher = await _started_fetcher(monkeypatch, _two_channel_config(GONE_CHANNEL))
    fetcher.client.failure = FloodWaitError(request=None, capture=3600)
    await _drain_with_retry(fetcher)
    lookups = len(fetcher.client.resolved)

    # Inside the wait Telegram asked for, no lookup is attempted.
    fetcher.client.failure = None
    fetcher.client.peer_ids["@gone_channel"] = GONE_PEER_ID
    await _drain_with_retry(fetcher)
    assert len(fetcher.client.resolved) == lookups
    assert GONE_PEER_ID not in fetcher.channels_by_peer

    # Once the wait has passed, the next fetch resolves the channel.
    fetcher._retry_not_before = 0.0
    await _drain_with_retry(fetcher)
    assert fetcher.channels_by_peer[GONE_PEER_ID].name == "Gone Channel"


class _FloodWaitedLookupClient(_FakeTelegramClient):
    """Answers a lookup of each username in ``flood_waits`` with a Telegram flood wait of that many seconds."""

    def __init__(self, session, api_id, api_hash):
        super().__init__(session, api_id, api_hash)
        self.flood_waits = {"@gone_channel": 7200, "@second_channel": 60}

    async def get_peer_id(self, peer):
        if peer in self.flood_waits:
            self.resolved.append(peer)
            raise FloodWaitError(request=None, capture=self.flood_waits[peer])
        return await super().get_peer_id(peer)


@pytest.mark.asyncio
async def test_flood_wait_on_one_channel_does_not_stop_the_others(monkeypatch):
    config_dict = _make_telegram_config(enabled=True)
    config_dict["sources"]["telegram"]["channels"] = [
        GONE_CHANNEL,
        {"name": "Test Channel", "channel_id": "@test_channel", "language": "uk", "priority": 1},
        {"name": "Second Channel", "channel_id": "@second_channel", "language": "ru", "priority": 1},
        {"name": "Numeric Channel", "channel_id": "-1003333333333", "language": "uk", "priority": 1},
    ]
    monkeypatch.setattr(telethon, "TelegramClient", _FloodWaitedLookupClient)
    fetcher = TelegramFetcher(SentinelConfig(**config_dict))
    await fetcher.start()

    # The flood wait on the first channel does not keep the channels after it from resolving.
    assert fetcher.client.resolved == ["@gone_channel", "@test_channel", "@second_channel", -1003333333333]
    assert sorted(ch.name for ch in fetcher.channels_by_peer.values()) == ["Numeric Channel", "Test Channel"]
    [(event, _callback)] = fetcher.client.handlers
    assert sorted(event.chats) == sorted([-1001111111111, -1003333333333])
    await _deliver_to_matching(fetcher, _make_mock_message("Monitored despite the wait", chat_id=-1003333333333))
    [article] = await fetcher.fetch()
    assert article.source_name == "Numeric Channel"

    # The next retry waits for the longest flood wait seen, not the last one.
    assert fetcher._retry_not_before > time.monotonic() + 7000
    lookups = len(fetcher.client.resolved)
    await _drain_with_retry(fetcher)
    assert len(fetcher.client.resolved) == lookups

    # Once the wait has passed, the flood-waited channels join.
    fetcher.client.flood_waits = {}
    fetcher.client.peer_ids["@gone_channel"] = GONE_PEER_ID
    fetcher._retry_not_before = 0.0
    await _drain_with_retry(fetcher)
    assert fetcher.channels_by_peer[GONE_PEER_ID].name == "Gone Channel"
    assert fetcher.channels_by_peer[-1002222222222].name == "Second Channel"
    assert fetcher._unresolved == []


@pytest.mark.asyncio
async def test_slow_channel_retry_does_not_block_fetch_and_stops_cleanly(monkeypatch):
    fetcher = await _started_fetcher(monkeypatch, _two_channel_config(GONE_CHANNEL))
    lookup_started = asyncio.Event()

    async def never_answers(peer):
        lookup_started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(fetcher.client, "get_peer_id", never_answers)
    await _deliver(fetcher, _make_mock_message("Delivered while a lookup hangs", chat_id=-1001111111111, msg_id=2))

    [article] = await asyncio.wait_for(fetcher.fetch(), timeout=1)
    assert article.source_name == "Test Channel"
    await asyncio.wait_for(lookup_started.wait(), timeout=1)
    retry_task = fetcher._retry_task

    # A second fetch while the lookup still hangs starts no second attempt.
    assert await asyncio.wait_for(fetcher.fetch(), timeout=1) == []
    assert fetcher._retry_task is retry_task

    await asyncio.wait_for(fetcher.stop(), timeout=1)
    assert retry_task.cancelled()
