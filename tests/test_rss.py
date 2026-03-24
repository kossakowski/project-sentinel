"""Tests for the RSS fetcher."""

import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from sentinel.fetchers.rss import RSSFetcher, strip_html


SAMPLE_RSS_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <item>
      <title>Russia moves troops near Polish border</title>
      <link>https://example.com/article/1</link>
      <pubDate>Mon, 10 Mar 2025 12:00:00 GMT</pubDate>
      <description>Russian forces have been observed moving near the border.</description>
    </item>
    <item>
      <title>Baltic defense ministers meet</title>
      <link>https://example.com/article/2</link>
      <pubDate>Mon, 10 Mar 2025 11:00:00 GMT</pubDate>
      <description>Defence ministers discuss regional security.</description>
    </item>
  </channel>
</rss>
"""

SAMPLE_RSS_NO_SUMMARY = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <item>
      <title>Breaking: Military alert</title>
      <link>https://example.com/article/3</link>
      <pubDate>Mon, 10 Mar 2025 10:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""

SAMPLE_RSS_NO_DATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <item>
      <title>Undated article</title>
      <link>https://example.com/article/4</link>
      <description>No date here.</description>
    </item>
  </channel>
</rss>
"""

SAMPLE_RSS_HTML_SUMMARY = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <item>
      <title>HTML summary article</title>
      <link>https://example.com/article/5</link>
      <pubDate>Mon, 10 Mar 2025 10:00:00 GMT</pubDate>
      <description>&lt;p&gt;This is &lt;b&gt;bold&lt;/b&gt; and &lt;a href="url"&gt;linked&lt;/a&gt; text.&lt;/p&gt;</description>
    </item>
  </channel>
</rss>
"""

MALFORMED_XML = """This is not valid XML at all!!!<broken"""

INCAPSULA_CHALLENGE = """\
<html>
<head>
<META NAME="robots" CONTENT="noindex,nofollow">
<script src="/_Incapsula_Resource?SWJIYLWA=5074a744e2e3d891814e9a2dace20bd4"></script>
<body>
</body></html>"""


def _make_response(
    content: str,
    status_code: int = 200,
    headers: dict | None = None,
    content_type: str | None = None,
):
    """Create a mock httpx.Response."""
    resp_headers = dict(headers or {})
    if content_type:
        resp_headers["content-type"] = content_type
    return httpx.Response(
        status_code=status_code,
        text=content,
        headers=resp_headers,
        request=httpx.Request("GET", "https://example.com/rss.xml"),
    )


@pytest.mark.asyncio
async def test_parse_valid_rss(config):
    """Parse a sample RSS XML, verify Article fields."""
    fetcher = RSSFetcher(config)

    mock_resp = _make_response(SAMPLE_RSS_XML)

    with patch("sentinel.fetchers.rss.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        articles = await fetcher.fetch()

    assert len(articles) == 2
    assert articles[0].source_type == "rss"
    assert articles[0].title == "Russia moves troops near Polish border"
    assert articles[0].source_name == "TestFeed"
    assert articles[0].language == "en"
    assert articles[0].source_url == "https://example.com/article/1"
    assert articles[0].summary == "Russian forces have been observed moving near the border."
    assert articles[0].fetched_at is not None
    assert articles[0].published_at is not None


@pytest.mark.asyncio
async def test_handle_missing_summary(config):
    """Entry without <summary> produces Article with empty summary."""
    fetcher = RSSFetcher(config)
    mock_resp = _make_response(SAMPLE_RSS_NO_SUMMARY)

    with patch("sentinel.fetchers.rss.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        articles = await fetcher.fetch()

    assert len(articles) == 1
    assert articles[0].summary == ""


@pytest.mark.asyncio
async def test_handle_missing_date(config):
    """Entry without <pubDate> uses current time."""
    fetcher = RSSFetcher(config)
    mock_resp = _make_response(SAMPLE_RSS_NO_DATE)

    with patch("sentinel.fetchers.rss.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        before = datetime.now(timezone.utc)
        articles = await fetcher.fetch()
        after = datetime.now(timezone.utc)

    assert len(articles) == 1
    # published_at should be approximately now since no date was provided
    assert before <= articles[0].published_at <= after


@pytest.mark.asyncio
async def test_handle_malformed_xml(config):
    """Malformed XML returns empty list and logs error."""
    fetcher = RSSFetcher(config)
    mock_resp = _make_response(MALFORMED_XML)

    with patch("sentinel.fetchers.rss.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        articles = await fetcher.fetch()

    assert articles == []


@pytest.mark.asyncio
async def test_conditional_get_304(config):
    """Server returns 304 Not Modified, returns empty list."""
    fetcher = RSSFetcher(config)

    # First: prime the cache with an ETag
    first_resp = _make_response(
        SAMPLE_RSS_XML, headers={"etag": '"abc123"'}
    )
    second_resp = _make_response("", status_code=304)

    call_count = 0

    async def mock_get(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return first_resp
        return second_resp

    with patch("sentinel.fetchers.rss.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=mock_get)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        # First fetch populates cache
        articles1 = await fetcher.fetch()
        assert len(articles1) == 2

        # Second fetch should get 304
        articles2 = await fetcher.fetch()
        assert articles2 == []


@pytest.mark.asyncio
async def test_multiple_feeds(config):
    """Polls 3 feeds, returns combined articles."""
    # Modify config to have 3 enabled RSS sources
    from sentinel.config import SentinelConfig

    config_dict = config.model_dump()
    config_dict["sources"]["rss"] = [
        {"name": "Feed1", "url": "https://example.com/feed1.xml", "language": "en", "enabled": True, "priority": 1},
        {"name": "Feed2", "url": "https://example.com/feed2.xml", "language": "pl", "enabled": True, "priority": 1},
        {"name": "Feed3", "url": "https://example.com/feed3.xml", "language": "en", "enabled": True, "priority": 2},
    ]
    multi_config = SentinelConfig(**config_dict)
    fetcher = RSSFetcher(multi_config)

    mock_resp = _make_response(SAMPLE_RSS_XML)

    with patch("sentinel.fetchers.rss.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        articles = await fetcher.fetch()

    # 2 articles per feed * 3 feeds = 6
    assert len(articles) == 6
    source_names = [a.source_name for a in articles]
    assert source_names.count("Feed1") == 2
    assert source_names.count("Feed2") == 2
    assert source_names.count("Feed3") == 2


@pytest.mark.asyncio
async def test_disabled_feed_skipped(config):
    """Feed with enabled: false not polled."""
    from sentinel.config import SentinelConfig

    config_dict = config.model_dump()
    config_dict["sources"]["rss"] = [
        {"name": "EnabledFeed", "url": "https://example.com/enabled.xml", "language": "en", "enabled": True, "priority": 1},
        {"name": "DisabledFeed", "url": "https://example.com/disabled.xml", "language": "en", "enabled": False, "priority": 1},
    ]
    multi_config = SentinelConfig(**config_dict)
    fetcher = RSSFetcher(multi_config)

    mock_resp = _make_response(SAMPLE_RSS_XML)

    with patch("sentinel.fetchers.rss.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        articles = await fetcher.fetch()

    # Only 2 articles from the enabled feed
    assert len(articles) == 2
    assert all(a.source_name == "EnabledFeed" for a in articles)
    # Should have made only 1 HTTP call
    assert mock_client.get.call_count == 1


@pytest.mark.asyncio
async def test_timeout_handling(config):
    """Request timeout returns empty list for that feed."""
    fetcher = RSSFetcher(config)

    with patch("sentinel.fetchers.rss.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        articles = await fetcher.fetch()

    assert articles == []


@pytest.mark.asyncio
async def test_html_stripped_from_summary(config):
    """HTML tags removed from summary text."""
    fetcher = RSSFetcher(config)
    mock_resp = _make_response(SAMPLE_RSS_HTML_SUMMARY)

    with patch("sentinel.fetchers.rss.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        articles = await fetcher.fetch()

    assert len(articles) == 1
    # HTML tags should be stripped
    assert "<p>" not in articles[0].summary
    assert "<b>" not in articles[0].summary
    assert "<a" not in articles[0].summary
    assert "bold" in articles[0].summary
    assert "linked" in articles[0].summary


def test_strip_html_function():
    """Direct test of the strip_html utility."""
    assert strip_html("<p>Hello <b>world</b></p>") == "Hello world"
    assert strip_html("plain text") == "plain text"
    assert strip_html("") == ""


@pytest.mark.asyncio
async def test_waf_bot_protection_detected(config):
    """WAF/Incapsula challenge page returns empty list with warning."""
    fetcher = RSSFetcher(config)
    mock_resp = _make_response(
        INCAPSULA_CHALLENGE,
        content_type="text/html",
    )

    with patch("sentinel.fetchers.rss.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        articles = await fetcher.fetch()

    assert articles == []
