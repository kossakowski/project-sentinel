"""Ingestion fixes: Telegram articles are not enriched; the Google News decoder has a deadline."""

import asyncio
import threading
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from sentinel.models import Article
from sentinel.processing import enricher as enricher_module
from sentinel.processing.enricher import ArticleEnricher, resolve_article_url
from sentinel.processing.fulltext import fetch_full_text

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
GOOGLE_NEWS_URL = "https://news.google.com/rss/articles/CBMiZ2h0dHBzOi8vZXhhbXBsZS50ZXN0L25ld3M?oc=5"


def _article(title, summary, *, source_type="rss", source_name="Feed", url="https://example.test/news/1"):
    return Article(
        source_name=source_name,
        source_url=url,
        source_type=source_type,
        title=title,
        summary=summary,
        language="uk",
        published_at=NOW,
        fetched_at=NOW,
    )


# ---------------------------------------------------------------------------
# 3.6: the enricher never fetches a page for a Telegram article
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_telegram_article_not_enriched(prod_config):
    # A short Air Force post: title == summary, which the heuristic gate would flag.
    text = "Загроза застосування балістичного озброєння з півночі!"
    telegram = _article(
        text, text, source_type="telegram", source_name="Ukrainian Air Force", url="https://t.me/kpszsu/12345"
    )
    headline_only = _article(
        "Alarm w kraju NATO - Radio Zet", "Alarm w kraju NATO Radio Zet", source_type="google_news"
    )
    enricher = ArticleEnricher(prod_config)

    with (
        patch.object(enricher, "_fetch_body", new_callable=AsyncMock, return_value="Treść artykułu z gazety.") as body,
        patch.object(enricher, "_check_vagueness_direct", new_callable=AsyncMock, return_value=False) as direct,
        patch.object(enricher, "_check_vagueness_llm", MagicMock(return_value=False)) as legacy,
    ):
        result = await enricher.enrich_batch([telegram, headline_only])

    assert result == [telegram, headline_only]
    assert telegram.raw_metadata["enrichment"] == {"method": "none", "reason": "full_text_source"}
    assert telegram.summary == text and telegram.title == text
    # Only the RSS-style article reached the page fetch; no gate ran for the Telegram post.
    body.assert_awaited_once_with(headline_only)
    direct.assert_not_awaited()
    legacy.assert_not_called()
    assert headline_only.raw_metadata["enrichment"]["fetched"] is True


# ---------------------------------------------------------------------------
# 3.7: the Google News decoder runs off the event loop, under a deadline
# ---------------------------------------------------------------------------


@pytest.fixture
def stalled_decoder(monkeypatch):
    """Replace the decoder with one that blocks its thread until the test ends."""
    release = threading.Event()
    calls: list[str] = []

    def decode(url, *args, **kwargs):
        calls.append(url)
        release.wait(30)
        return {"status": True, "decoded_url": "https://publisher.example/too-late"}

    monkeypatch.setattr(enricher_module, "new_decoderv1", decode)
    yield calls
    release.set()


@pytest.mark.asyncio
async def test_decoder_stall_respects_deadline(prod_config, monkeypatch, stalled_decoder):
    deadline = 0.3
    prod_config.processing.url_decode_timeout_seconds = deadline
    article = _article("Alarm", "Alarm", source_type="google_news", url=GOOGLE_NEWS_URL)
    loop = asyncio.get_running_loop()
    ticks = 0

    async def sibling():
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0.01)

    ticker = asyncio.create_task(sibling())
    try:
        started = loop.time()
        resolved = await resolve_article_url(article, deadline)
        elapsed = loop.time() - started
        # The stall cost the deadline, not the event loop: the sibling kept running.
        assert resolved == GOOGLE_NEWS_URL
        assert elapsed < deadline + 1
        assert ticks >= 10

        # Enricher: the page fetch goes to the original URL once the deadline passes.
        requested = []
        real_async_client = httpx.AsyncClient

        def recording_client(**kwargs):
            kwargs["transport"] = httpx.MockTransport(
                lambda request: requested.append(str(request.url)) or httpx.Response(404)
            )
            return real_async_client(**kwargs)

        monkeypatch.setattr(enricher_module.httpx, "AsyncClient", recording_client)
        ticks_before = ticks
        assert await ArticleEnricher(prod_config)._fetch_body(article) is None
        assert requested == [GOOGLE_NEWS_URL]
        assert ticks - ticks_before >= 10

        # Full text: same resolver, same fallback to the original URL.
        fetched = []
        client = real_async_client(
            transport=httpx.MockTransport(lambda request: fetched.append(str(request.url)) or httpx.Response(403))
        )
        async with client:
            full = await fetch_full_text(article, client=client, decode_timeout=deadline)
        assert full.status == "http_403" and full.url == GOOGLE_NEWS_URL
        assert fetched == [GOOGLE_NEWS_URL]
        assert len(stalled_decoder) == 3
    finally:
        ticker.cancel()


@pytest.mark.asyncio
async def test_decoder_saturation_still_meets_deadline(stalled_decoder):
    """More stalled decodes than worker threads: every caller still returns by its deadline."""
    deadline = 0.3
    articles = [
        _article(f"Alarm {n}", "Alarm", source_type="google_news", url=f"{GOOGLE_NEWS_URL}&n={n}") for n in range(12)
    ]
    loop = asyncio.get_running_loop()
    started = loop.time()
    resolved = await asyncio.gather(*(resolve_article_url(a, deadline) for a in articles))
    assert resolved == [a.source_url for a in articles]
    assert loop.time() - started < deadline + 1
    # Jobs still queued when their caller gave up never ran.
    assert len(stalled_decoder) <= enricher_module._DECODER_WORKERS


@pytest.mark.asyncio
async def test_stuck_decoder_threads_are_replaced_then_skipped(monkeypatch):
    """Stuck threads are replaced up to the cap; past it, resolution is skipped without waiting."""
    pool = enricher_module._DecoderPool(workers=2, max_threads=3)
    monkeypatch.setattr(enricher_module, "_decoder_pool", pool)
    release = threading.Event()
    calls: list[str] = []
    decoded = "https://publisher.example/a"

    def decode(url):
        calls.append(url.rsplit("&", 1)[-1])
        if "hang" in url:
            release.wait(30)
        return {"status": True, "decoded_url": decoded}

    monkeypatch.setattr(enricher_module, "new_decoderv1", decode)
    deadline = 0.4
    loop = asyncio.get_running_loop()

    def google_news(tag):
        return _article(tag, tag, source_type="google_news", url=f"{GOOGLE_NEWS_URL}&{tag}")

    async def timed(tag):
        article = google_news(tag)
        started = loop.time()
        resolved = await resolve_article_url(article, deadline)
        return article, resolved, loop.time() - started

    try:
        # Both workers stall past the deadline.
        hung = [google_news("hang1"), google_news("hang2")]
        assert await asyncio.gather(*(resolve_article_url(a, deadline) for a in hung)) == [a.source_url for a in hung]

        # A replacement thread decodes the next link at once instead of waiting out the deadline.
        _, resolved, elapsed = await timed("fast1")
        assert resolved == decoded and elapsed < deadline / 2

        # The replacement stalls too: all three allowed threads are now stuck.
        article, resolved, _ = await timed("hang3")
        assert resolved == article.source_url

        # Past the cap the original URL comes back at once and the decoder is not called.
        article, resolved, elapsed = await timed("fast2")
        assert resolved == article.source_url and elapsed < deadline / 2
        assert sorted(calls[:2]) == ["hang1", "hang2"] and calls[2:] == ["fast1", "hang3"]

        # Once the stuck decoders return, their threads retire and decoding resumes.
        release.set()
        for _ in range(200):
            _, resolved, _ = await timed("fast3")
            if resolved == decoded:
                break
            await asyncio.sleep(0.01)
        assert resolved == decoded
        assert calls[-1] == "fast3" and "fast2" not in calls
    finally:
        release.set()


@pytest.mark.asyncio
async def test_google_news_page_is_not_used_as_the_body(prod_config, monkeypatch):
    """An undecoded link serves Google's own page: its description is not taken as the article."""

    def broken(url):
        raise ValueError("unexpected page layout")

    monkeypatch.setattr(enricher_module, "new_decoderv1", broken)
    google_page = (
        '<html><head><meta property="og:description" content="Comprehensive up-to-date news coverage, '
        'aggregated from sources all over the world by Google News."></head><body></body></html>'
    )
    publisher_page = (
        '<html><head><meta property="og:description" content="Rosyjskie drony naruszyły polską przestrzeń '
        'powietrzną nad Lubelszczyzną, poinformowało Dowództwo Operacyjne."></head><body></body></html>'
    )
    requested = []
    real_async_client = httpx.AsyncClient

    def respond(request):
        requested.append(str(request.url))
        return httpx.Response(200, text=google_page if request.url.host == "news.google.com" else publisher_page)

    def mock_client(**kwargs):
        kwargs["transport"] = httpx.MockTransport(respond)
        return real_async_client(**kwargs)

    monkeypatch.setattr(enricher_module.httpx, "AsyncClient", mock_client)
    google_news = _article(
        "Alarm w kraju NATO - Radio Zet", "Alarm w kraju NATO Radio Zet", source_type="google_news", url=GOOGLE_NEWS_URL
    )
    publisher = _article("Drony nad Lubelszczyzną", "Drony nad Lubelszczyzną")

    await ArticleEnricher(prod_config).enrich_batch([google_news, publisher])

    assert sorted(requested) == sorted([GOOGLE_NEWS_URL, "https://example.test/news/1"])
    # The Google News article keeps its headline and stays marked as not fetched,
    # so the classifier still gets its headline-only caution.
    assert google_news.summary == "Alarm w kraju NATO Radio Zet"
    assert google_news.raw_metadata["enrichment"]["fetched"] is False
    # The same extraction still works for a publisher page.
    assert publisher.summary.startswith("Rosyjskie drony naruszyły")
    assert publisher.raw_metadata["enrichment"]["fetched"] is True


@pytest.mark.asyncio
async def test_decoded_url_is_used_within_deadline(monkeypatch):
    monkeypatch.setattr(
        enricher_module, "new_decoderv1", lambda url: {"status": True, "decoded_url": "https://publisher.example/a"}
    )
    article = _article("Alarm", "Alarm", source_type="google_news", url=GOOGLE_NEWS_URL)
    assert await resolve_article_url(article, 5) == "https://publisher.example/a"


@pytest.mark.asyncio
async def test_decoder_failure_uses_original_url(monkeypatch):
    def broken(url):
        raise ValueError("unexpected page layout")

    monkeypatch.setattr(enricher_module, "new_decoderv1", broken)
    article = _article("Alarm", "Alarm", source_type="google_news", url=GOOGLE_NEWS_URL)
    assert await resolve_article_url(article, 5) == GOOGLE_NEWS_URL


@pytest.mark.asyncio
async def test_non_google_news_url_skips_the_decoder(monkeypatch):
    monkeypatch.setattr(enricher_module, "new_decoderv1", MagicMock(side_effect=AssertionError("decoder called")))
    article = _article("Alarm", "Alarm")
    assert await resolve_article_url(article, 5) == "https://example.test/news/1"


def test_decode_timeout_defaults_to_ten_seconds(prod_config):
    assert prod_config.processing.url_decode_timeout_seconds == 10
