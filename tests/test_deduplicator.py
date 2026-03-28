"""Tests for sentinel.processing.deduplicator."""

from datetime import datetime, timezone

from sentinel.models import Article
from sentinel.processing.deduplicator import Deduplicator


def _make_article(**overrides) -> Article:
    """Helper to build an Article with sensible defaults."""
    defaults = {
        "source_name": "TestSource",
        "source_url": "https://example.com/article/1",
        "source_type": "rss",
        "title": "Russia launches military operation near Polish border",
        "summary": "Russian forces have begun operations.",
        "language": "en",
        "published_at": datetime.now(timezone.utc),
        "fetched_at": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    return Article(**defaults)


class TestDeduplicator:
    """Acceptance tests for the Deduplicator."""

    def test_exact_url_duplicate_rejected(self, db, config):
        """Same URL is rejected as a duplicate."""
        dedup = Deduplicator(db, config)
        article = _make_article()
        # Insert into DB first
        db.insert_article(article)
        # Same URL should be a duplicate
        assert dedup.is_duplicate(article) is True

    def test_different_url_passes(self, db, config):
        """Different URL with different title is not a duplicate."""
        dedup = Deduplicator(db, config)
        a1 = _make_article(
            source_url="https://example.com/article/1",
            title="Russia launches military operation near Polish border",
        )
        db.insert_article(a1)
        a2 = _make_article(
            source_url="https://example.com/article/2",
            title="NATO summit discusses Baltic defense strategy",
        )
        assert dedup.is_duplicate(a2) is False

    def test_fuzzy_title_same_source_rejected(self, db, config):
        """~90% similar title from same source is rejected (republished)."""
        dedup = Deduplicator(db, config)
        a1 = _make_article(
            source_url="https://example.com/article/1",
            title="Russia launches massive military operation near Polish border",
        )
        db.insert_article(a1)
        # Slightly different title, same source
        a2 = _make_article(
            source_url="https://example.com/article/2",
            title="Russia launches major military operation near Polish border",
        )
        assert dedup.is_duplicate(a2) is True

    def test_fuzzy_title_different_source_passes(self, db, config):
        """~90% similar title from different source passes (corroboration)."""
        dedup = Deduplicator(db, config)
        a1 = _make_article(
            source_name="SourceA",
            source_url="https://source-a.com/article/1",
            title="Russia launches massive military operation near Polish border",
        )
        db.insert_article(a1)
        # Similar title, different source, similarity between 85-95%
        a2 = _make_article(
            source_name="SourceB",
            source_url="https://source-b.com/article/2",
            title="Russia launches major military operation near Polish border",
        )
        assert dedup.is_duplicate(a2) is False

    def test_very_similar_title_cross_source_rejected(self, db, config):
        """>=95% similar from different source is rejected (syndicated)."""
        dedup = Deduplicator(db, config)
        a1 = _make_article(
            source_name="SourceA",
            source_url="https://source-a.com/article/1",
            title="Russia launches military operation near Polish border today",
        )
        db.insert_article(a1)
        # Nearly identical title from different source
        a2 = _make_article(
            source_name="SourceB",
            source_url="https://source-b.com/article/2",
            title="Russia launches military operation near Polish border today",
        )
        assert dedup.is_duplicate(a2) is True

    def test_old_article_not_checked(self, db, config):
        """Article outside lookback window is not compared for fuzzy match."""
        dedup = Deduplicator(db, config)
        # Insert an article with old fetched_at -- it won't appear in get_recent_titles
        # because PostgreSQL's NOW() - INTERVAL filters it out.
        # We simulate this by inserting directly with an old timestamp.
        old_article = _make_article(
            source_url="https://example.com/article/old",
            title="Russia launches military operation near Polish border",
        )
        # Insert the article normally, then update fetched_at to an old timestamp
        db.insert_article(old_article)
        with db.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE articles SET fetched_at = %s WHERE id = %s",
                    ("2020-01-01T00:00:00+00:00", old_article.id),
                )

        # New article with similar title should NOT be flagged as duplicate
        new_article = _make_article(
            source_url="https://example.com/article/new",
            title="Russia launches military operation near Polish border",
        )
        assert dedup.is_duplicate(new_article) is False

    def test_empty_db_all_pass(self, db, config):
        """First run with empty DB -- all articles pass."""
        dedup = Deduplicator(db, config)
        titles = [
            "Russia launches military operation near border",
            "NATO summit discusses defense strategy",
            "Poland increases military spending significantly",
            "Baltic states request additional troops deployment",
            "European Union condemns aggressive posturing",
        ]
        articles = [
            _make_article(
                source_url=f"https://example.com/article/{i}",
                title=titles[i],
            )
            for i in range(5)
        ]
        result = dedup.deduplicate_batch(articles)
        assert len(result) == 5

    def test_batch_internal_dedup(self, db, config):
        """Two identical articles in the same batch -- only first passes."""
        dedup = Deduplicator(db, config)
        a1 = _make_article(source_url="https://example.com/article/1")
        a2 = _make_article(source_url="https://example.com/article/1")
        result = dedup.deduplicate_batch([a1, a2])
        assert len(result) == 1
        assert result[0].id == a1.id
