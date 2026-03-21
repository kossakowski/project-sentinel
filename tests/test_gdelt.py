"""Tests for the GDELT fetcher."""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from sentinel.fetchers.gdelt import GDELTFetcher, GDELT_LANGUAGE_MAP


SAMPLE_GDELT_RESPONSE = {
    "articles": [
        {
            "url": "https://reuters.com/article/123",
            "title": "Military activity observed near Polish border",
            "seendate": "20250910T034800Z",
            "socialimage": "https://img.example.com/photo.jpg",
            "domain": "reuters.com",
            "language": "English",
            "sourcecountry": "United States",
        },
        {
            "url": "https://pap.pl/article/456",
            "title": "Aktywność wojskowa na granicy",
            "seendate": "20250910T040000Z",
            "domain": "pap.pl",
            "language": "Polish",
            "sourcecountry": "Poland",
        },
    ]
}


def _make_response(data: dict | str, status_code: int = 200):
    """Create a mock httpx.Response with JSON body."""
    if isinstance(data, str):
        content = data
    else:
        content = json.dumps(data)
    return httpx.Response(
        status_code=status_code,
        text=content,
        headers={"content-type": "application/json"},
        request=httpx.Request("GET", "https://api.gdeltproject.org/api/v2/doc/doc"),
    )


@pytest.mark.asyncio
async def test_parse_valid_response(config):
    """Parse sample GDELT JSON, verify Article fields."""
    fetcher = GDELTFetcher(config)
    mock_resp = _make_response(SAMPLE_GDELT_RESPONSE)

    with patch("sentinel.fetchers.gdelt.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        articles = await fetcher.fetch()

    assert len(articles) == 2

    art1 = articles[0]
    assert art1.source_type == "gdelt"
    assert art1.title == "Military activity observed near Polish border"
    assert art1.source_name == "GDELT:reuters.com"
    assert art1.source_url == "https://reuters.com/article/123"
    assert art1.language == "en"
    assert art1.published_at == datetime(2025, 9, 10, 3, 48, 0, tzinfo=timezone.utc)
    assert art1.raw_metadata == SAMPLE_GDELT_RESPONSE["articles"][0]

    art2 = articles[1]
    assert art2.language == "pl"
    assert art2.source_name == "GDELT:pap.pl"


def test_query_construction(config):
    """Verify query string built correctly from config."""
    fetcher = GDELTFetcher(config)
    query = fetcher.build_query()

    # Should contain theme filter
    assert "theme:ARMEDCONFLICT" in query

    # Should contain country filter with FIPS code
    assert "sourcecountry:PL" in query

    # Should use parentheses for grouping
    assert "(" in query and ")" in query


def test_date_parsing(config):
    """GDELT seendate format parsed correctly."""
    fetcher = GDELTFetcher(config)
    dt = fetcher._parse_seendate("20250910T034800Z")

    assert dt.year == 2025
    assert dt.month == 9
    assert dt.day == 10
    assert dt.hour == 3
    assert dt.minute == 48
    assert dt.second == 0
    assert dt.tzinfo == timezone.utc


@pytest.mark.asyncio
async def test_empty_response(config):
    """No articles returned, returns empty list."""
    fetcher = GDELTFetcher(config)
    mock_resp = _make_response({"articles": []})

    with patch("sentinel.fetchers.gdelt.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        articles = await fetcher.fetch()

    assert articles == []


@pytest.mark.asyncio
async def test_network_error(config):
    """Connection error returns empty list."""
    fetcher = GDELTFetcher(config)

    with patch("sentinel.fetchers.gdelt.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            side_effect=httpx.ConnectError("connection refused")
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        articles = await fetcher.fetch()

    assert articles == []


def test_language_mapping(config):
    """GDELT language names mapped to ISO codes."""
    assert GDELT_LANGUAGE_MAP["English"] == "en"
    assert GDELT_LANGUAGE_MAP["Polish"] == "pl"
    assert GDELT_LANGUAGE_MAP["Ukrainian"] == "uk"
    assert GDELT_LANGUAGE_MAP["Russian"] == "ru"
    assert GDELT_LANGUAGE_MAP["German"] == "de"
    assert GDELT_LANGUAGE_MAP["French"] == "fr"
