"""Article deduplicator -- URL hash and fuzzy title dedup."""

import logging

from rapidfuzz import fuzz

from sentinel.config import SentinelConfig
from sentinel.database import Database
from sentinel.models import Article


class Deduplicator:
    """Removes duplicate articles using exact URL and fuzzy title matching."""

    def __init__(self, db: Database, config: SentinelConfig) -> None:
        self.db = db
        self.config = config
        self.logger = logging.getLogger("sentinel.deduplicator")

    def is_duplicate(self, article: Article) -> bool:
        """Check if article is a duplicate. Returns True if it should be skipped."""
        # Strategy 1: exact URL dedup
        if self.db.article_exists(article.url_hash):
            self.logger.debug("URL duplicate: %s", article.source_url[:80])
            return True

        # Strategy 2: fuzzy title dedup
        dedup_cfg = self.config.processing.dedup
        recent_titles = self.db.get_recent_titles(dedup_cfg.lookback_minutes)

        for source_name, title_normalized in recent_titles:
            ratio = fuzz.ratio(article.title_normalized, title_normalized)

            # Very similar across any source -> duplicate (syndicated content)
            if ratio >= dedup_cfg.cross_source_title_threshold:
                self.logger.debug(
                    "Cross-source title duplicate (%.0f%%): %s",
                    ratio,
                    article.title[:60],
                )
                return True

            # Similar within same source -> duplicate (republished)
            if (
                ratio >= dedup_cfg.same_source_title_threshold
                and source_name == article.source_name
            ):
                self.logger.debug(
                    "Same-source title duplicate (%.0f%%): %s",
                    ratio,
                    article.title[:60],
                )
                return True

        return False

    def deduplicate_batch(self, articles: list[Article]) -> list[Article]:
        """Filter out duplicates from a batch. Non-duplicates are inserted into DB."""
        unique: list[Article] = []
        seen_hashes: set[str] = set()

        for article in articles:
            # Batch-internal dedup: skip if we already accepted an article
            # with the same url_hash in this batch
            if article.url_hash in seen_hashes:
                self.logger.debug(
                    "Batch-internal duplicate: %s", article.title[:60]
                )
                continue

            if self.is_duplicate(article):
                continue

            # Insert into DB so subsequent articles in the batch can dedup against it
            self.db.insert_article(article)
            seen_hashes.add(article.url_hash)
            unique.append(article)

        return unique
