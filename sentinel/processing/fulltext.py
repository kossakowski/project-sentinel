"""Fetch an article page and extract its full main text.

Shared by production (a planned second read of selected articles) and the eval suite
(which freezes the same extraction for labelling and replay), so both see identical text.
Never raises: a failed fetch returns an empty result with the reason, because a missing
full text must never block or delay an alert.
"""

import asyncio
from dataclasses import dataclass

import httpx
import trafilatura

from sentinel.models import Article
from sentinel.processing.enricher import ArticleEnricher

MAX_CHARS = 8000  # ~2,000 tokens: bounds cost and latency of a second read
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"


@dataclass(frozen=True)
class FullText:
    url: str
    text: str | None
    status: str  # "ok", "empty", "http_<code>", "error:<type>"

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def extract_text(html: str, url: str) -> str | None:
    """Main article text without comments, tables or navigation; None if nothing found."""
    text = trafilatura.extract(html, url=url, include_comments=False, include_tables=False, favor_precision=True)
    if not text:
        return None
    text = text.strip()
    return text[:MAX_CHARS] if len(text) > 80 else None


async def fetch_full_text(
    article: Article, *, timeout: float = 10.0, client: httpx.AsyncClient | None = None
) -> FullText:
    url = article.source_url
    try:
        url = ArticleEnricher._resolve_url(article)
        owns = client is None
        http = client or httpx.AsyncClient(follow_redirects=True, timeout=timeout, headers={"User-Agent": USER_AGENT})
        try:
            response = await http.get(url)
        finally:
            if owns:
                await http.aclose()
        if response.status_code >= 400:
            return FullText(url, None, f"http_{response.status_code}")
        text = await asyncio.to_thread(extract_text, response.text, str(response.url))
        return FullText(str(response.url), text, "ok" if text else "empty")
    except Exception as exc:  # network, decoding, parser: report, never raise
        return FullText(url, None, f"error:{type(exc).__name__}")
