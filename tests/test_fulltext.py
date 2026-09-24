"""Full-text fetch and extraction: never raises, reports why, caps length."""

import asyncio
from datetime import UTC, datetime

import httpx

from sentinel.models import Article
from sentinel.processing.fulltext import MAX_CHARS, extract_text, fetch_full_text

PARAGRAPH = (
    "Rosyjski dron wleciał w nocy nad województwo lubelskie. Wojsko poderwało myśliwce, "
    "a mieszkańcy otrzymali alert RCB. Rzecznik Dowództwa Operacyjnego potwierdził incydent. "
)


def page(body: str) -> str:
    return (
        "<html><head><title>Alarm</title></head><body><nav>Menu Sport Pogoda</nav>"
        f"<article><h1>Alarm na Lubelszczyźnie</h1><p>{body}</p><p>{body}</p></article>"
        "<footer>Polityka prywatności</footer></body></html>"
    )


def article(url="https://example.test/news/1"):
    now = datetime(2026, 9, 13, 3, 0, tzinfo=UTC)
    return Article(
        id="a1",
        source_name="src",
        source_url=url,
        source_type="rss",
        title="Alarm",
        summary="Alarm",
        language="pl",
        published_at=now,
        fetched_at=now,
    )


def client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)


def test_extract_text_keeps_the_article_and_drops_navigation():
    text = extract_text(page(PARAGRAPH), "https://example.test/news/1")
    assert "alert RCB" in text and "Polityka prywatności" not in text


def test_extract_text_caps_length_and_rejects_empty_pages():
    long = extract_text(page(PARAGRAPH * 200), "https://example.test/news/1")
    assert len(long) == MAX_CHARS
    assert extract_text("<html><body><p>Hi</p></body></html>", "https://example.test/") is None


def test_fetch_reports_blocked_pages_and_network_errors_without_raising():
    blocked = asyncio.run(fetch_full_text(article(), client=client(lambda r: httpx.Response(403))))
    assert blocked.status == "http_403" and blocked.text is None and not blocked.ok

    def fail(request):
        raise httpx.ConnectError("down", request=request)

    down = asyncio.run(fetch_full_text(article(), client=client(fail)))
    assert down.status == "error:ConnectError" and down.text is None


def test_fetch_returns_the_extracted_text():
    ok = asyncio.run(fetch_full_text(article(), client=client(lambda r: httpx.Response(200, text=page(PARAGRAPH)))))
    assert ok.ok and "myśliwce" in ok.text and ok.url == "https://example.test/news/1"
