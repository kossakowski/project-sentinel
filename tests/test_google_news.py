"""Tests for the Google News fetcher."""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from sentinel.config import GoogleNewsQuery
from sentinel.fetchers.google_news import GoogleNewsFetcher


SAMPLE_GNEWS_RSS = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>military attack Poland - Google News</title>
    <item>
      <title>NATO increases presence near Polish border - Reuters</title>
      <link>https://news.google.com/rss/articles/CBMiK2h0dHBz</link>
      <pubDate>Mon, 10 Mar 2025 12:00:00 GMT</pubDate>
      <description>NATO allies bolster eastern flank.</description>
    </item>
    <item>
      <title>Poland raises military readiness - BBC</title>
      <link>https://news.google.com/rss/articles/CBMiL2h0dHBz</link>
      <pubDate>Mon, 10 Mar 2025 11:30:00 GMT</pubDate>
      <description>Polish defense forces on high alert.</description>
    </item>
  </channel>
</rss>
"""


def _make_response(content: str, status_code: int = 200):
    """Create a mock httpx.Response."""
    return httpx.Response(
        status_code=status_code,
        text=content,
        headers={},
        request=httpx.Request("GET", "https://news.google.com/rss/search"),
    )


def test_url_construction(config):
    """Verify feed URL built correctly for each language."""
    fetcher = GoogleNewsFetcher(config)

    # English query
    en_query = GoogleNewsQuery(query="military attack Poland", language="en")
    url = fetcher.build_feed_url(en_query)
    assert "news.google.com/rss/search" in url
    assert "military%20attack%20Poland" in url
    assert "when:1h" in url
    assert "hl=en" in url
    assert "gl=US" in url
    assert "ceid=US:en" in url

    # Polish query
    pl_query = GoogleNewsQuery(query="atak wojskowy Polska", language="pl")
    url_pl = fetcher.build_feed_url(pl_query)
    assert "hl=pl" in url_pl
    assert "gl=PL" in url_pl
    assert "ceid=PL:pl" in url_pl

    # Ukrainian query
    uk_query = GoogleNewsQuery(query="test", language="uk")
    url_uk = fetcher.build_feed_url(uk_query)
    assert "hl=uk" in url_uk
    assert "gl=UA" in url_uk

    # Russian query
    ru_query = GoogleNewsQuery(query="test", language="ru")
    url_ru = fetcher.build_feed_url(ru_query)
    assert "hl=ru" in url_ru
    assert "gl=RU" in url_ru


@pytest.mark.asyncio
async def test_parse_results(config):
    """Parse Google News RSS entries."""
    fetcher = GoogleNewsFetcher(config)
    mock_resp = _make_response(SAMPLE_GNEWS_RSS)

    with patch("sentinel.fetchers.google_news.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        articles = await fetcher.fetch()

    assert len(articles) == 2
    assert articles[0].source_type == "google_news"
    assert articles[0].title == "NATO increases presence near Polish border - Reuters"
    assert articles[0].source_name == "GoogleNews:military attack Poland"
    assert articles[0].language == "en"
    assert articles[0].fetched_at is not None
    assert articles[0].published_at is not None


def test_polish_query(config):
    """Polish-language query URL constructed correctly."""
    fetcher = GoogleNewsFetcher(config)

    query = GoogleNewsQuery(query="inwazja Polska", language="pl")
    url = fetcher.build_feed_url(query)

    assert "inwazja%20Polska" in url
    assert "hl=pl" in url
    assert "gl=PL" in url
    assert "ceid=PL:pl" in url
    assert "when:1h" in url


@pytest.mark.asyncio
async def test_rate_limit_handling(config):
    """HTTP 429 handled gracefully."""
    fetcher = GoogleNewsFetcher(config)
    mock_resp = _make_response("", status_code=429)

    with patch("sentinel.fetchers.google_news.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        # Should not raise, should return empty list
        articles = await fetcher.fetch()

    assert articles == []
