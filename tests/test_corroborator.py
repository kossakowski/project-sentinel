"""Tests for sentinel.classification.corroborator."""

from datetime import datetime, timedelta, timezone

from sentinel.classification.corroborator import Corroborator
from sentinel.models import Article, ClassificationResult, Event


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


def _make_classification(article: Article, **overrides) -> ClassificationResult:
    """Helper to build a ClassificationResult with sensible defaults."""
    defaults = {
        "article_id": article.id,
        "is_military_event": True,
        "event_type": "invasion",
        "urgency_score": 9,
        "affected_countries": ["PL"],
        "aggressor": "RU",
        "is_new_event": True,
        "confidence": 0.9,
        "summary_pl": "Rosja dokonala inwazji na Polske.",
        "classified_at": datetime.now(timezone.utc),
        "model_used": "claude-haiku-4-5-20251001",
        "input_tokens": 287,
        "output_tokens": 94,
    }
    defaults.update(overrides)
    return ClassificationResult(**defaults)


class TestCorroborator:
    """Acceptance tests for the Corroborator."""

    def test_single_source_creates_event(self, db, config):
        """One classification -> one event with source_count=1."""
        corroborator = Corroborator(db, config)
        article = _make_article()
        db.insert_article(article)

        classification = _make_classification(article)
        events = corroborator.process_classifications([classification])

        assert len(events) == 1
        assert events[0].source_count == 1

    def test_two_sources_same_event(self, db, config):
        """Two compatible classifications from independent sources -> one event with source_count=2."""
        corroborator = Corroborator(db, config)

        article1 = _make_article(
            source_name="SourceA",
            source_url="https://source-a.com/article/1",
            title="Russia invades Poland",
        )
        article2 = _make_article(
            source_name="SourceB",
            source_url="https://source-b.com/article/2",
            title="Russian invasion of Poland confirmed",
        )
        db.insert_article(article1)
        db.insert_article(article2)

        c1 = _make_classification(article1)
        c2 = _make_classification(article2)

        events = corroborator.process_classifications([c1, c2])

        # Should result in one event updated once
        # The first creates the event, the second updates it
        assert len(events) == 2  # one create + one update returned
        final_event = events[-1]
        assert final_event.source_count == 2

    def test_different_events_separate(self, db, config):
        """'invasion of Poland' and 'cyberattack on Estonia' -> two separate events."""
        corroborator = Corroborator(db, config)

        article1 = _make_article(
            source_name="SourceA",
            source_url="https://source-a.com/article/1",
            title="Russia invades Poland",
        )
        article2 = _make_article(
            source_name="SourceB",
            source_url="https://source-b.com/article/2",
            title="Cyberattack on Estonian infrastructure",
        )
        db.insert_article(article1)
        db.insert_article(article2)

        c1 = _make_classification(article1, event_type="invasion", affected_countries=["PL"])
        c2 = _make_classification(
            article2,
            event_type="cyber_attack",
            affected_countries=["EE"],
            summary_pl="Cyberatak na infrastrukture Estonii.",
        )

        events = corroborator.process_classifications([c1, c2])

        assert len(events) == 2
        event_types = {e.event_type for e in events}
        assert "invasion" in event_types
        assert "cyber_attack" in event_types

    def test_compatible_types_grouped(self, db, config):
        """'airstrike' and 'missile_strike' on same country -> same event."""
        corroborator = Corroborator(db, config)

        article1 = _make_article(
            source_name="SourceA",
            source_url="https://source-a.com/article/1",
            title="Airstrike reported in Poland",
        )
        article2 = _make_article(
            source_name="SourceB",
            source_url="https://source-b.com/article/2",
            title="Missile strike hits Poland",
        )
        db.insert_article(article1)
        db.insert_article(article2)

        c1 = _make_classification(article1, event_type="airstrike")
        c2 = _make_classification(article2, event_type="missile_strike")

        events = corroborator.process_classifications([c1, c2])

        # Both should map to the same event
        assert len(events) == 2
        final_event = events[-1]
        assert final_event.source_count == 2

    def test_incompatible_types_separate(self, db, config):
        """'cyber_attack' and 'naval_blockade' -> separate events."""
        corroborator = Corroborator(db, config)

        article1 = _make_article(
            source_name="SourceA",
            source_url="https://source-a.com/article/1",
        )
        article2 = _make_article(
            source_name="SourceB",
            source_url="https://source-b.com/article/2",
        )
        db.insert_article(article1)
        db.insert_article(article2)

        c1 = _make_classification(article1, event_type="cyber_attack")
        c2 = _make_classification(article2, event_type="naval_blockade")

        events = corroborator.process_classifications([c1, c2])

        assert len(events) == 2
        event_types = {e.event_type for e in events}
        assert "cyber_attack" in event_types
        assert "naval_blockade" in event_types

    def test_outside_time_window_separate(self, db, config):
        """Same event type but 2 hours apart -> separate events."""
        corroborator = Corroborator(db, config)

        now = datetime.now(timezone.utc)
        two_hours_ago = now - timedelta(hours=2)

        article1 = _make_article(
            source_name="SourceA",
            source_url="https://source-a.com/article/1",
        )
        article2 = _make_article(
            source_name="SourceB",
            source_url="https://source-b.com/article/2",
        )
        db.insert_article(article1)
        db.insert_article(article2)

        c1 = _make_classification(article1, classified_at=two_hours_ago)
        c2 = _make_classification(article2, classified_at=now)

        # Process c1 first, then c2
        events1 = corroborator.process_classifications([c1])
        assert len(events1) == 1

        events2 = corroborator.process_classifications([c2])
        assert len(events2) == 1

        # They should be separate events (different IDs)
        assert events1[0].id != events2[0].id

    def test_source_independence(self, db, config):
        """Same Reuters story on 3 sites -> source_count=1, not 3."""
        corroborator = Corroborator(db, config)

        # Three articles with 90%+ similar titles (syndicated content)
        base_title = "Reuters: Russia launches full-scale military invasion of Poland"
        article1 = _make_article(
            source_name="BBC",
            source_url="https://bbc.com/news/article/1",
            title=base_title,
        )
        article2 = _make_article(
            source_name="CNN",
            source_url="https://cnn.com/news/article/2",
            title=base_title,  # Identical title = syndicated
        )
        article3 = _make_article(
            source_name="AlJazeera",
            source_url="https://aljazeera.com/news/article/3",
            title=base_title,  # Identical title = syndicated
        )
        db.insert_article(article1)
        db.insert_article(article2)
        db.insert_article(article3)

        c1 = _make_classification(article1)
        c2 = _make_classification(article2)
        c3 = _make_classification(article3)

        events = corroborator.process_classifications([c1, c2, c3])

        # All should be in the same event, but source_count should remain 1
        final_event = events[-1]
        assert final_event.source_count == 1

    def test_corroboration_threshold_met(self, db, config):
        """2 independent sources with urgency >= 9 -> event eligible for phone call."""
        corroborator = Corroborator(db, config)

        article1 = _make_article(
            source_name="PAP",
            source_url="https://pap.pl/article/1",
            title="Rosja zaatakowala Polske - inwazja trwa",
        )
        article2 = _make_article(
            source_name="BBC",
            source_url="https://bbc.com/news/article/2",
            title="Russia invades Poland in full-scale military operation",
        )
        db.insert_article(article1)
        db.insert_article(article2)

        c1 = _make_classification(article1, urgency_score=10)
        c2 = _make_classification(article2, urgency_score=10)

        events = corroborator.process_classifications([c1, c2])

        final_event = events[-1]
        assert final_event.source_count == 2
        assert final_event.alert_status == "phone_call"

    def test_corroboration_threshold_not_met(self, db, config):
        """1 source for critical event -> SMS only, not phone call."""
        corroborator = Corroborator(db, config)

        article = _make_article(
            source_name="PAP",
            source_url="https://pap.pl/article/1",
        )
        db.insert_article(article)

        classification = _make_classification(article, urgency_score=9)
        events = corroborator.process_classifications([classification])

        assert len(events) == 1
        assert events[0].source_count == 1
        # With urgency 9 but only 1 source, should be SMS not phone_call
        assert events[0].alert_status == "sms"

    def test_event_urgency_max(self, db, config):
        """Event with scores 7 and 9 -> event urgency = 9."""
        corroborator = Corroborator(db, config)

        article1 = _make_article(
            source_name="SourceA",
            source_url="https://source-a.com/article/1",
            title="Military escalation at Polish border",
        )
        article2 = _make_article(
            source_name="SourceB",
            source_url="https://source-b.com/article/2",
            title="Full-scale invasion of Poland underway",
        )
        db.insert_article(article1)
        db.insert_article(article2)

        c1 = _make_classification(article1, urgency_score=7)
        c2 = _make_classification(article2, urgency_score=9)

        events = corroborator.process_classifications([c1, c2])

        final_event = events[-1]
        assert final_event.urgency_score == 9

    def test_event_updated_with_new_article(self, db, config):
        """New article added to existing event updates article_ids and last_updated_at."""
        corroborator = Corroborator(db, config)

        article1 = _make_article(
            source_name="SourceA",
            source_url="https://source-a.com/article/1",
            title="Russia launches invasion of Poland",
        )
        article2 = _make_article(
            source_name="SourceB",
            source_url="https://source-b.com/article/2",
            title="Poland under Russian military attack",
        )
        db.insert_article(article1)
        db.insert_article(article2)

        c1 = _make_classification(article1)
        events1 = corroborator.process_classifications([c1])
        assert len(events1) == 1
        first_event = events1[0]

        c2 = _make_classification(article2)
        events2 = corroborator.process_classifications([c2])
        assert len(events2) == 1
        updated_event = events2[0]

        assert updated_event.id == first_event.id
        assert len(updated_event.article_ids) == 2
        assert article1.id in updated_event.article_ids
        assert article2.id in updated_event.article_ids

    def test_low_urgency_no_event(self, db, config):
        """Urgency 1-4 -> no event created (log only)."""
        corroborator = Corroborator(db, config)

        article = _make_article()
        db.insert_article(article)

        classification = _make_classification(article, urgency_score=3)
        events = corroborator.process_classifications([classification])

        assert len(events) == 0

    def test_dry_run_sets_alert_status(self, db, config):
        """In dry-run mode, events get alert_status='dry_run' instead of real statuses."""
        corroborator = Corroborator(db, config, dry_run=True)

        article = _make_article()
        db.insert_article(article)

        classification = _make_classification(article, urgency_score=10)
        events = corroborator.process_classifications([classification])

        assert len(events) == 1
        assert events[0].alert_status == "dry_run"

    def test_dry_run_via_config(self, db, config):
        """Dry-run flag from config.testing.dry_run is picked up by Corroborator."""
        config.testing.dry_run = True
        corroborator = Corroborator(db, config)

        article = _make_article()
        db.insert_article(article)

        classification = _make_classification(article, urgency_score=9)
        events = corroborator.process_classifications([classification])

        assert len(events) == 1
        assert events[0].alert_status == "dry_run"

    def test_different_summaries_not_merged(self, db, config):
        """Same type/country/window but very different summary_pl -> separate events."""
        corroborator = Corroborator(db, config)

        article1 = _make_article(
            source_name="SourceA",
            source_url="https://source-a.com/article/1",
            title="Russian missile hits Warsaw",
        )
        article2 = _make_article(
            source_name="SourceB",
            source_url="https://source-b.com/article/2",
            title="Cyberattack on Polish power grid",
        )
        db.insert_article(article1)
        db.insert_article(article2)

        c1 = _make_classification(
            article1,
            event_type="invasion",
            affected_countries=["PL"],
            summary_pl="Rosja dokonala inwazji na Polske, wojska przekroczyly granice.",
        )
        c2 = _make_classification(
            article2,
            event_type="invasion",
            affected_countries=["PL"],
            summary_pl="Trzesienie ziemi w Turcji spowodowalo duze zniszczenia.",
        )

        events = corroborator.process_classifications([c1, c2])

        # Despite same event_type and country, completely different summaries should not merge
        assert len(events) == 2
        assert events[0].id != events[1].id

    def test_cross_source_type_syndication(self, db, config):
        """Telegram post + RSS article quoting it verbatim -> source_count=1, not 2."""
        corroborator = Corroborator(db, config)

        # Telegram post from official source
        article1 = _make_article(
            source_name="Ukrainian Air Force",
            source_url="https://t.me/kpszsu/12345",
            source_type="telegram",
            title="Russian drones detected entering Polish airspace near Zamość",
        )
        # RSS article quoting the same Telegram post
        article2 = _make_article(
            source_name="RMF24",
            source_url="https://rmf24.pl/article/1",
            source_type="rss",
            title="Russian drones detected entering Polish airspace near Zamość",
        )
        db.insert_article(article1)
        db.insert_article(article2)

        c1 = _make_classification(
            article1,
            event_type="airspace_violation",
            summary_pl="Rosyjskie drony wykryto nad Polską w rejonie Zamościa.",
        )
        c2 = _make_classification(
            article2,
            event_type="airspace_violation",
            summary_pl="Rosyjskie drony wykryto nad Polską w rejonie Zamościa.",
        )

        events = corroborator.process_classifications([c1, c2])

        final_event = events[-1]
        # Despite different source_types, identical titles should be detected
        # as syndicated content -> source_count stays at 1
        assert final_event.source_count == 1

    def test_low_urgency_classification_stored(self, db, config):
        """Low-urgency classifications are stored in the database even though no event is created."""
        corroborator = Corroborator(db, config)

        article = _make_article()
        db.insert_article(article)

        classification = _make_classification(
            article, urgency_score=2, is_military_event=False
        )
        events = corroborator.process_classifications([classification])

        assert len(events) == 0

        # The classification should still be in the database
        with db.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM classifications WHERE id = %s", (classification.id,)
                )
                row = cur.fetchone()
        assert row is not None
        assert row["urgency_score"] == 2
