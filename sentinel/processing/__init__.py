"""Processing pipeline -- normalize, deduplicate, and keyword-filter articles."""

from sentinel.config import SentinelConfig
from sentinel.database import Database
from sentinel.models import Article
from sentinel.processing.deduplicator import Deduplicator
from sentinel.processing.keyword_filter import KeywordFilter
from sentinel.processing.normalizer import Normalizer

__all__ = [
    "Normalizer",
    "Deduplicator",
    "KeywordFilter",
    "process_articles",
]


async def process_articles(
    raw_articles: list[Article],
    db: Database,
    config: SentinelConfig,
) -> list[Article]:
    """Full processing pipeline: normalize -> deduplicate -> keyword filter."""
    normalizer = Normalizer()
    deduplicator = Deduplicator(db, config)
    keyword_filter = KeywordFilter(config)

    # Step 1: Normalize
    normalized = normalizer.normalize_batch(raw_articles)

    # Step 2: Deduplicate
    unique = deduplicator.deduplicate_batch(normalized)

    # Step 3: Keyword filter
    relevant = keyword_filter.filter_batch(unique)

    return relevant
