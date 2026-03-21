"""Tests for the Telegram fetcher."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

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
                {"name": "TestFeed", "url": "https://example.com/rss.xml", "language": "en", "enabled": True, "priority": 2},
            ],
            "gdelt": {
                "enabled": True,
                "update_interval_minutes": 15,
                "themes": ["ARMEDCONFLICT"],
                "cameo_codes": ["19"],
                "goldstein_threshold": -7.0,
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
                ] if enabled else [],
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
        "testing": {"dry_run": False, "test_mode": False, "test_headlines_file": "tests/fixtures/test_headlines.yaml"},
    }


def _make_mock_message(text: str, chat_id: int = 123, msg_id: int = 456, views: int = 100, forwards: int = 5) -> MagicMock:
    """Create a mock Telegram message."""
    msg = MagicMock()
    msg.text = text
    msg.chat_id = chat_id
    msg.id = msg_id
    msg.date = datetime(2025, 3, 10, 12, 0, 0, tzinfo=timezone.utc)
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

    channel_map = {
        ch.channel_id: ch for ch in config.sources.telegram.channels
    }
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
        published_at=datetime.now(timezone.utc),
        fetched_at=datetime.now(timezone.utc),
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

    channel_map = {
        ch.channel_id: ch for ch in config.sources.telegram.channels
    }
    article = fetcher._message_to_article(message, channel_map)

    assert article is not None
    # Title truncated to 200
    assert len(article.title) == 200
    # Summary truncated to 500
    assert len(article.summary) == 500
