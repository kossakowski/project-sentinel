"""Content enrichment for articles with insufficient summaries.

Two-gate system:
1. Heuristic gate (free): detects summary ≈ title (Google News, GDELT)
2. LLM gate (cheap): detects vague/clickbait titles with technically-different summaries
Then fetches article body for all flagged articles.
"""

import asyncio
import json
import logging
import re
from difflib import SequenceMatcher

import anthropic
import httpx
from googlenewsdecoder import new_decoderv1

from sentinel.config import SentinelConfig
from sentinel.models import Article
from sentinel.utils import strip_html

VAGUENESS_CHECK_PROMPT = (
    "You are an input quality gate for a military threat classifier. Your job is to determine "
    "whether a news article's title and summary provide SUFFICIENT FACTUAL INFORMATION for a "
    "classifier to make a reliable threat assessment.\n"
    "\n"
    "An article has SUFFICIENT information if it answers BOTH:\n"
    "1. WHAT happened? (a specific event: strike, drone incursion, explosion, military movement "
    "— not just 'alarm' or 'tensions')\n"
    "2. WHERE did it happen? (a specific country or city — not just 'NATO country', "
    "'the region', or 'near the border')\n"
    "\n"
    "Flag as INSUFFICIENT if ANY of these apply:\n"
    "- The summary adds no information beyond the title (duplicate or near-duplicate)\n"
    "- The title uses vague geographic references ('NATO country', 'a country', "
    "'the border region') instead of naming the specific country\n"
    "- The title is primarily emotional/clickbait ('Horror!', 'Truth revealed', 'Shocking', "
    "'Sad words') rather than factual\n"
    "- The title describes REACTIONS (resignation, political fallout, analysis) but is phrased "
    "to sound like an active threat\n"
    "- The title is clearly a debunking or explainer ('truth came out', 'what really happened', "
    "'fact check') but contains alarming keywords\n"
    "- The summary is just the title with an outlet name appended\n"
    "\n"
    "Flag as SUFFICIENT if:\n"
    "- The title names a specific country AND describes a specific event, even if the summary "
    "is poor\n"
    "- The title + summary together provide enough context to determine what happened and where\n"
    "- The article is clearly about a non-threatening topic (diplomacy, economics, historical) "
    "regardless of keywords\n"
    "\n"
    "Respond with JSON only:\n"
    '{"needs_enrichment": true/false, "reason": "one sentence"}'
)

_OUTLET_SUFFIXES_RE = re.compile(
    r"\s*[-–—|]\s*[A-ZÀ-Ž][\w\s.'']+$"
    r"|\s+[A-ZÀ-Ž][\w\s.'']{2,}$",
    re.UNICODE,
)


class ArticleEnricher:
    """Enriches articles that have insufficient summaries before classification."""

    def __init__(self, config: SentinelConfig) -> None:
        self.config = config
        self.logger = logging.getLogger("sentinel.enricher")
        self._client: anthropic.Anthropic | None = None

    @property
    def _anthropic(self) -> anthropic.Anthropic:
        if self._client is None:
            self._client = anthropic.Anthropic()
        return self._client

    # ------------------------------------------------------------------
    # Gate 1: Heuristic (free, instant)
    # ------------------------------------------------------------------

    @staticmethod
    def _strip_outlet(text: str) -> str:
        """Strip trailing outlet name patterns like ' - Onet' or ' WP Wiadomości'."""
        return _OUTLET_SUFFIXES_RE.sub("", text).strip()

    @staticmethod
    def is_garbage_summary(article: Article) -> bool:
        """Check if summary is essentially the title repeated (possibly with outlet name)."""
        title = article.title.strip().lower()
        summary = article.summary.strip().lower()

        if not summary or not title:
            return True

        title_clean = ArticleEnricher._strip_outlet(title).rstrip(".,;:!? ")
        summary_clean = ArticleEnricher._strip_outlet(summary).rstrip(".,;:!? ")

        if not title_clean or not summary_clean:
            return True

        # If summary is much longer than title, it has real additional content
        # (e.g. Telegram: title is first 200 chars, summary is first 500 chars)
        if len(summary_clean) > len(title_clean) * 1.4:
            return False

        if summary_clean in title_clean or title_clean in summary_clean:
            return True

        ratio = SequenceMatcher(None, title_clean, summary_clean).ratio()
        return ratio > 0.85

    # ------------------------------------------------------------------
    # Gate 2: LLM vagueness check (for articles passing heuristic)
    # ------------------------------------------------------------------

    def _check_vagueness_llm(self, article: Article) -> bool:
        """Ask Haiku whether the title+summary provide sufficient info. Returns True if enrichment needed."""
        user_msg = (
            f"Source: {article.source_name} ({article.source_type})\n"
            f"Language: {article.language}\n"
            f"Title: {article.title}\n"
            f"Summary: {article.summary}"
        )
        try:
            response = self._anthropic.messages.create(
                model=self.config.classification.model,
                max_tokens=100,
                temperature=0,
                system=VAGUENESS_CHECK_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
            )
            raw = response.content[0].text.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            data = json.loads(raw)
            needs = data.get("needs_enrichment", False)
            if needs:
                self.logger.debug(
                    "LLM flagged '%s': %s", article.title[:60], data.get("reason", "")
                )
            return bool(needs)
        except Exception as e:
            self.logger.warning("LLM vagueness check failed for '%s': %s", article.title[:60], e)
            return False

    # ------------------------------------------------------------------
    # Body fetcher
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_url(article: Article) -> str:
        """Resolve the real article URL. Decodes Google News redirect URLs locally."""
        url = article.source_url
        if "news.google.com/rss/articles/" in url:
            try:
                result = new_decoderv1(url)
                if result and result.get("decoded_url"):
                    return result["decoded_url"]
            except Exception:
                pass
        return url

    @staticmethod
    def _extract_og_description(html_content: str) -> str | None:
        """Try to extract og:description from raw HTML."""
        for pattern in [
            r'<meta\s+[^>]*(?:property|name)=["\']og:description["\'][^>]*content=["\']([^"\']+)["\']',
            r'<meta\s+[^>]*content=["\']([^"\']+)["\'][^>]*(?:property|name)=["\']og:description["\']',
        ]:
            m = re.search(pattern, html_content, re.IGNORECASE)
            if m:
                text = m.group(1).strip()
                if len(text) > 50:
                    return text[:500]
        return None

    async def _fetch_body(self, article: Article) -> str | None:
        """Fetch article body text via og:description extraction."""
        real_url = self._resolve_url(article)
        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=5.0,
                headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"},
            ) as client:
                resp = await client.get(real_url)
                resp.raise_for_status()

                # Primary: og:description (concise, high quality)
                text = self._extract_og_description(resp.text)
                if text:
                    return text

                # Fallback: strip script/style/nav then extract text
                if len(resp.text) > 1000:
                    cleaned = re.sub(r"<script[^>]*>.*?</script>", " ", resp.text, flags=re.DOTALL | re.IGNORECASE)
                    cleaned = re.sub(r"<style[^>]*>.*?</style>", " ", cleaned, flags=re.DOTALL | re.IGNORECASE)
                    text = strip_html(cleaned)
                    text = re.sub(r"\s+", " ", text).strip()
                    if len(text) > 100:
                        return text[:500]

                return None
        except Exception as e:
            self.logger.debug("Body fetch failed for '%s': %s", article.title[:60], e)
            return None

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def enrich_batch(self, articles: list[Article]) -> list[Article]:
        """Enrich articles with insufficient summaries before classification.

        1. Heuristic gate: detect summary ≈ title
        2. LLM gate: for articles passing heuristic, check if title is vague
        3. Fetch body for all flagged articles in parallel
        4. Replace summary with body text (or annotate failure)
        """
        if not articles:
            return articles

        to_enrich: list[Article] = []
        passed: list[Article] = []

        for article in articles:
            if self.is_garbage_summary(article):
                article.raw_metadata["enrichment"] = {
                    "method": "heuristic",
                    "original_summary": article.summary,
                }
                to_enrich.append(article)
            else:
                passed.append(article)

        heuristic_count = len(to_enrich)

        for article in passed:
            if self._check_vagueness_llm(article):
                article.raw_metadata["enrichment"] = {
                    "method": "llm",
                    "original_summary": article.summary,
                }
                to_enrich.append(article)
            else:
                article.raw_metadata["enrichment"] = {"method": "none"}

        llm_count = len(to_enrich) - heuristic_count

        if to_enrich:
            self.logger.info(
                "Enriching %d articles (heuristic=%d, llm=%d)",
                len(to_enrich), heuristic_count, llm_count,
            )
            bodies = await asyncio.gather(
                *(self._fetch_body(a) for a in to_enrich),
                return_exceptions=True,
            )
            enriched_ok = 0
            enriched_fail = 0
            for article, body in zip(to_enrich, bodies):
                if isinstance(body, str) and body:
                    article.summary = body
                    article.raw_metadata["enrichment"]["fetched"] = True
                    enriched_ok += 1
                else:
                    article.raw_metadata["enrichment"]["fetched"] = False
                    enriched_fail += 1

            self.logger.info(
                "Enrichment results: %d fetched, %d failed", enriched_ok, enriched_fail,
            )

        return articles
