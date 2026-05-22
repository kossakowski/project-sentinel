"""Tests for the dashboard database access layer (`dashboard.db.DashboardDB`).

These tests are fully hermetic: they build a local SQLite database from the
production schema (the four CREATE TABLE blocks in SPEC.md) with hand-crafted
sample rows, and never touch the network or the production server.

The sample data is designed to exercise pagination, every filter, every sort
column, the pipeline-status join logic (unclassified / classified /
event_created / alert_sent), FTS5 search, and the LIKE fallback.
"""

import json
import sqlite3

import pytest

from dashboard.db import DashboardDB
from dashboard.sync import build_fts_index

# ---------------------------------------------------------------------------
# Schema -- the four production tables, verbatim from SPEC.md.
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE articles (
    id TEXT PRIMARY KEY,
    source_name TEXT NOT NULL,
    source_url TEXT NOT NULL,
    source_type TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT,
    language TEXT NOT NULL,
    published_at TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    url_hash TEXT NOT NULL,
    title_normalized TEXT NOT NULL,
    raw_metadata TEXT
);
CREATE TABLE classifications (
    id TEXT PRIMARY KEY,
    article_id TEXT NOT NULL,
    is_military_event INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    urgency_score INTEGER NOT NULL,
    affected_countries TEXT NOT NULL,
    aggressor TEXT,
    is_new_event INTEGER NOT NULL,
    confidence REAL NOT NULL,
    summary_pl TEXT,
    classified_at TEXT NOT NULL,
    model_used TEXT NOT NULL,
    input_tokens INTEGER,
    output_tokens INTEGER
);
CREATE TABLE events (
    id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    urgency_score INTEGER NOT NULL,
    affected_countries TEXT NOT NULL,
    aggressor TEXT,
    summary_pl TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_updated_at TEXT NOT NULL,
    source_count INTEGER NOT NULL DEFAULT 1,
    article_ids TEXT NOT NULL,
    alert_status TEXT NOT NULL DEFAULT 'pending',
    acknowledged_at TEXT
);
CREATE TABLE alert_records (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    alert_type TEXT NOT NULL,
    twilio_sid TEXT,
    status TEXT NOT NULL,
    duration_seconds INTEGER,
    attempt_number INTEGER NOT NULL DEFAULT 1,
    sent_at TEXT NOT NULL,
    message_body TEXT
);
"""


def _article_row(
    article_id: str,
    *,
    source_name: str,
    source_type: str,
    language: str,
    title: str,
    summary: str,
    published_at: str,
    fetched_at: str | None = None,
    raw_metadata: dict | None = None,
) -> tuple:
    """Build an `articles` row tuple in column order."""
    return (
        article_id,
        source_name,
        f"https://example.com/{article_id}",
        source_type,
        title,
        summary,
        language,
        published_at,
        fetched_at or published_at,
        f"hash-{article_id}",
        title.lower(),
        json.dumps(raw_metadata or {"keyword_match": "drone"}),
    )


def _classification_row(
    classification_id: str,
    article_id: str,
    *,
    urgency_score: int,
    event_type: str = "airspace_violation",
    confidence: float = 0.9,
    is_military_event: int = 1,
) -> tuple:
    """Build a `classifications` row tuple in column order."""
    return (
        classification_id,
        article_id,
        is_military_event,
        event_type,
        urgency_score,
        json.dumps(["PL"]),
        "RU",
        1,
        confidence,
        f"Polskie podsumowanie {article_id}",
        f"2026-05-20T12:00:0{urgency_score % 10}+00:00",
        "claude-haiku-4-5-20251001",
        1076,
        150,
    )


def _build_sentinel_db(path: str) -> None:
    """Populate a local SQLite file at ``path`` with varied sample data.

    Articles created (8 total):
      a1  TASS / rss / en       -- classified, urgency 9, in event ev1 (alert)
      a2  TVN24 / rss / pl      -- classified, urgency 7, in event ev1 (alert)
      a3  Onet / google_news /pl-- classified, urgency 3, no event
      a4  TASS-TG / telegram /ru-- classified, urgency 5, in event ev2 (no alert)
      a5  Onet / rss / pl       -- UNCLASSIFIED (filtered out)
      a6  PAP / google_news /en -- UNCLASSIFIED
      a7  Defence24 / rss / pl  -- classified, urgency 2, no event
      a8  Reuters / rss / en    -- UNCLASSIFIED (no summary -> NULL)
    """
    conn = sqlite3.connect(path)
    try:
        conn.executescript(_SCHEMA)

        articles = [
            _article_row(
                "a1", source_name="TASS", source_type="rss", language="en",
                title="Russian drone strike near Polish border",
                summary="Multiple military drones crossed into Poland airspace.",
                published_at="2026-05-22T10:00:00+00:00",
            ),
            _article_row(
                "a2", source_name="TVN24", source_type="rss", language="pl",
                title="Drony nad Polska wykryte przez wojsko",
                summary="Wojsko potwierdza, ze drone naruszyl przestrzen.",
                published_at="2026-05-22T09:00:00+00:00",
            ),
            _article_row(
                "a3", source_name="Onet", source_type="google_news",
                language="pl",
                title="Politycy komentuja sytuacje na granicy",
                summary="Komentarze polityczne po incydencie granicznym.",
                published_at="2026-05-21T08:00:00+00:00",
            ),
            _article_row(
                "a4", source_name="TASS-Telegram", source_type="telegram",
                language="ru",
                title="Telegram channel reports troop movement",
                summary="A drone was found near the border region.",
                published_at="2026-05-20T07:00:00+00:00",
            ),
            _article_row(
                "a5", source_name="Onet", source_type="rss", language="pl",
                title="Pogoda na weekend bedzie sloneczna",
                summary="Prognoza pogody zapowiada cieple dni.",
                published_at="2026-05-19T06:00:00+00:00",
            ),
            _article_row(
                "a6", source_name="PAP", source_type="google_news",
                language="en",
                title="Economic forum opens in Warsaw",
                summary="Business leaders gather for an annual conference.",
                published_at="2026-05-18T05:00:00+00:00",
            ),
            _article_row(
                "a7", source_name="Defence24", source_type="rss",
                language="pl",
                title="Analiza zdolnosci obronnych regionu",
                summary="Artykul analityczny o systemach obrony.",
                published_at="2026-05-17T04:00:00+00:00",
            ),
            # a8 has NULL summary -- exercises COALESCE / null handling.
            (
                "a8", "Reuters", "https://example.com/a8", "rss",
                "Sports roundup of the week", None, "en",
                "2026-05-16T03:00:00+00:00", "2026-05-16T03:00:00+00:00",
                "hash-a8", "sports roundup of the week", None,
            ),
        ]
        conn.executemany(
            "INSERT INTO articles VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", articles
        )

        classifications = [
            _classification_row("c1", "a1", urgency_score=9,
                                 event_type="drone_attack", confidence=0.95),
            _classification_row("c2", "a2", urgency_score=7,
                                 event_type="airspace_violation",
                                 confidence=0.88),
            _classification_row("c3", "a3", urgency_score=3,
                                 event_type="none", confidence=0.40,
                                 is_military_event=0),
            _classification_row("c4", "a4", urgency_score=5,
                                 event_type="troop_movement",
                                 confidence=0.60),
            _classification_row("c7", "a7", urgency_score=2,
                                 event_type="none", confidence=0.30,
                                 is_military_event=0),
        ]
        conn.executemany(
            "INSERT INTO classifications VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            classifications,
        )

        # ev1 links a1 + a2 and HAS alerts (-> alert_sent).
        # ev2 links a4 and has NO alerts (-> event_created).
        events = [
            (
                "ev1", "drone_attack", 9, json.dumps(["PL"]), "RU",
                "Atak dronow w poblizu polskiej granicy.",
                "2026-05-22T10:05:00+00:00", "2026-05-22T10:30:00+00:00",
                2, json.dumps(["a1", "a2"]), "sms_sent",
                "2026-05-22T10:35:00+00:00",
            ),
            (
                "ev2", "troop_movement", 5, json.dumps(["LT"]), "RU",
                "Ruch wojsk w poblizu granicy.",
                "2026-05-20T07:10:00+00:00", "2026-05-20T07:20:00+00:00",
                1, json.dumps(["a4"]), "pending", None,
            ),
        ]
        conn.executemany(
            "INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", events
        )

        alerts = [
            (
                "al1", "ev1", "phone_call", "CA111", "completed", 42, 1,
                "2026-05-22T10:35:00+00:00", "Alert: drone attack",
            ),
            (
                "al2", "ev1", "sms", "SM222", "sent", None, 1,
                "2026-05-22T10:36:00+00:00", "SMS update",
            ),
        ]
        conn.executemany(
            "INSERT INTO alert_records VALUES (?,?,?,?,?,?,?,?,?)", alerts
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sentinel_db_path(tmp_path):
    """Path to a freshly built local sentinel SQLite DB (no FTS index)."""
    path = tmp_path / "sentinel.db"
    _build_sentinel_db(str(path))
    return str(path)


@pytest.fixture
def fts_db_path(tmp_path):
    """Path where the FTS index DB should live (not built unless requested)."""
    return str(tmp_path / "sentinel_fts.db")


@pytest.fixture
def db_no_fts(sentinel_db_path, fts_db_path):
    """A `DashboardDB` over the sample DB with NO FTS index built."""
    database = DashboardDB(db_path=sentinel_db_path, fts_db_path=fts_db_path)
    yield database
    database.close()


@pytest.fixture
def db_with_fts(sentinel_db_path, fts_db_path):
    """A `DashboardDB` over the sample DB WITH the FTS5 index built."""
    build_fts_index(sentinel_db_path, fts_db_path)
    database = DashboardDB(db_path=sentinel_db_path, fts_db_path=fts_db_path)
    yield database
    database.close()


# ---------------------------------------------------------------------------
# Tests -- pagination, filters, sorting
# ---------------------------------------------------------------------------


def test_db_get_articles_pagination(sentinel_db_path, fts_db_path):
    """[1.2b, 1.4] page=2, page_size=25 returns the correct slice + metadata."""
    # 8 sample articles; with page_size=3, page 2 holds rows 4-6.
    db = DashboardDB(db_path=sentinel_db_path, fts_db_path=fts_db_path)
    try:
        page1 = db.get_articles(page=1, page_size=3,
                                sort="published_at", order="desc")
        page2 = db.get_articles(page=2, page_size=3,
                                sort="published_at", order="desc")

        assert page1["total"] == 8
        assert page1["page"] == 1
        assert page1["page_size"] == 3
        assert page1["total_pages"] == 3  # ceil(8 / 3)
        assert len(page1["articles"]) == 3
        assert len(page2["articles"]) == 3

        # No overlap between consecutive pages.
        ids1 = {a["id"] for a in page1["articles"]}
        ids2 = {a["id"] for a in page2["articles"]}
        assert ids1.isdisjoint(ids2)

        # Verified explicitly against the spec's stated parameters.
        big = db.get_articles(page=2, page_size=25)
        assert big["page"] == 2
        assert big["page_size"] == 25
    finally:
        db.close()


def test_db_get_articles_filters(db_no_fts):
    """[1.2b] Filtering by source_type='telegram' returns only telegram rows."""
    result = db_no_fts.get_articles(filters={"source_type": "telegram"})

    assert result["total"] == 1
    assert len(result["articles"]) == 1
    assert all(
        a["source_type"] == "telegram" for a in result["articles"]
    )
    assert result["articles"][0]["id"] == "a4"


def test_db_get_articles_filters_more(db_no_fts):
    """[1.2b] Additional filters: language, urgency range, event_type."""
    # language filter
    pl = db_no_fts.get_articles(filters={"language": "pl"})
    assert pl["total"] == 4
    assert all(a["language"] == "pl" for a in pl["articles"])

    # urgency_min / urgency_max (on the joined classification)
    urgent = db_no_fts.get_articles(
        filters={"urgency_min": 7, "urgency_max": 10}
    )
    assert urgent["total"] == 2
    assert {a["id"] for a in urgent["articles"]} == {"a1", "a2"}

    # event_type filter
    drone = db_no_fts.get_articles(filters={"event_type": "drone_attack"})
    assert drone["total"] == 1
    assert drone["articles"][0]["id"] == "a1"


def test_db_get_articles_sort(db_no_fts):
    """[1.2b] Sorting by urgency_score desc returns the highest score first."""
    result = db_no_fts.get_articles(
        sort="urgency_score", order="desc",
        filters={"pipeline_status": "classified"},
    )
    scores = [
        a["classification"]["urgency_score"] for a in result["articles"]
    ]
    assert scores == sorted(scores, reverse=True)
    assert scores[0] == 9  # a1 has the top urgency

    # Ascending direction is also honoured.
    asc = db_no_fts.get_articles(
        sort="urgency_score", order="asc",
        filters={"pipeline_status": "classified"},
    )
    asc_scores = [
        a["classification"]["urgency_score"] for a in asc["articles"]
    ]
    assert asc_scores == sorted(asc_scores)


def test_db_get_articles_pipeline_status(db_no_fts):
    """[1.2b, 1.4b] Filtering by pipeline_status='unclassified' returns rows
    that have no classification."""
    result = db_no_fts.get_articles(
        filters={"pipeline_status": "unclassified"}
    )

    # a5, a6, a8 have no classification row.
    assert result["total"] == 3
    assert {a["id"] for a in result["articles"]} == {"a5", "a6", "a8"}
    for article in result["articles"]:
        assert article["classification"] is None
        assert article["pipeline_status"] == "unclassified"


def test_db_pipeline_status_values(db_no_fts):
    """[1.2b, 1.4b] Each pipeline status is derived correctly from joins."""
    everything = db_no_fts.get_articles(page_size=100)
    by_id = {a["id"]: a for a in everything["articles"]}

    # a1 is in an event that has alerts -> alert_sent.
    assert by_id["a1"]["pipeline_status"] == "alert_sent"
    assert by_id["a1"]["has_alert"] is True
    # a4 is in an event with no alerts -> event_created.
    assert by_id["a4"]["pipeline_status"] == "event_created"
    assert by_id["a4"]["has_alert"] is False
    # a3 is classified but not in any event -> classified.
    assert by_id["a3"]["pipeline_status"] == "classified"
    # a5 has no classification -> unclassified.
    assert by_id["a5"]["pipeline_status"] == "unclassified"


def test_db_has_alert_filter(db_no_fts):
    """[1.2b] has_alert filter selects articles with / without alerts."""
    with_alert = db_no_fts.get_articles(filters={"has_alert": True})
    assert {a["id"] for a in with_alert["articles"]} == {"a1", "a2"}

    without_alert = db_no_fts.get_articles(filters={"has_alert": False})
    assert "a1" not in {a["id"] for a in without_alert["articles"]}
    assert without_alert["total"] == 6


# ---------------------------------------------------------------------------
# Tests -- article detail
# ---------------------------------------------------------------------------


def test_db_get_article_detail(db_no_fts):
    """[1.2c, 1.5] Detail includes classification, events, and alerts."""
    detail = db_no_fts.get_article_detail("a1")

    assert detail is not None
    assert detail["id"] == "a1"
    # Classification present.
    assert detail["classification"] is not None
    assert detail["classification"]["urgency_score"] == 9
    assert detail["classification"]["event_type"] == "drone_attack"
    # raw_metadata parsed to a dict.
    assert isinstance(detail["raw_metadata"], dict)
    # Linked event ev1 present, carrying its alert records.
    assert len(detail["events"]) == 1
    event = detail["events"][0]
    assert event["id"] == "ev1"
    assert len(event["alert_records"]) == 2
    alert_types = {a["alert_type"] for a in event["alert_records"]}
    assert alert_types == {"phone_call", "sms"}


def test_db_get_article_detail_unclassified(db_no_fts):
    """[1.2c, 1.5] An unclassified article has a null classification."""
    detail = db_no_fts.get_article_detail("a5")

    assert detail is not None
    assert detail["id"] == "a5"
    assert detail["classification"] is None
    assert detail["pipeline_status"] == "unclassified"
    assert detail["events"] == []


def test_db_get_article_detail_missing(db_no_fts):
    """[1.2c] A non-existent article id returns None."""
    assert db_no_fts.get_article_detail("does-not-exist") is None


# ---------------------------------------------------------------------------
# Tests -- search (FTS5 + LIKE fallback)
# ---------------------------------------------------------------------------


def test_db_search_fts5(db_with_fts):
    """[1.2d] FTS5 search returns ranked results matching the query."""
    assert db_with_fts.fts_available is True

    result = db_with_fts.search_articles("drone")
    # a1, a2, a4 all mention a drone in title or summary.
    ids = {a["id"] for a in result["articles"]}
    assert ids == {"a1", "a2", "a4"}
    assert result["total"] == 3
    # Every returned article genuinely matches.
    for article in result["articles"]:
        haystack = (
            article["title"] + " " + (article["summary"] or "")
        ).lower()
        assert "drone" in haystack


def test_db_search_fts5_ranked(db_with_fts):
    """[1.2d] FTS5 results are ordered by relevance rank, not arbitrarily."""
    # 'drone' appears in a1's title AND summary -> should rank above a4
    # where it appears only in the summary.
    result = db_with_fts.search_articles("drone")
    returned_ids = [a["id"] for a in result["articles"]]
    assert returned_ids[0] in ("a1", "a2")


def test_db_search_like_fallback(db_no_fts):
    """[1.2d] Without an FTS5 index, LIKE search returns matching results."""
    assert db_no_fts.fts_available is False

    result = db_no_fts.search_articles("drone")
    ids = {a["id"] for a in result["articles"]}
    # LIKE matches on title OR summary, same set as FTS for this corpus.
    assert ids == {"a1", "a2", "a4"}
    for article in result["articles"]:
        haystack = (
            article["title"] + " " + (article["summary"] or "")
        ).lower()
        assert "drone" in haystack


def test_db_search_empty_query(db_no_fts):
    """[1.2d] An empty / whitespace query yields an empty result set."""
    result = db_no_fts.search_articles("   ")
    assert result["total"] == 0
    assert result["articles"] == []


def test_db_search_like_special_chars(db_no_fts):
    """[1.2d] LIKE-wildcard characters in the query are escaped, not matched."""
    # No article contains a literal '%' so this must return nothing.
    result = db_no_fts.search_articles("%")
    assert result["total"] == 0


# ---------------------------------------------------------------------------
# Tests -- stats
# ---------------------------------------------------------------------------


def test_db_get_stats(db_no_fts):
    """[1.2e, 1.6] Stats include every required aggregation."""
    stats = db_no_fts.get_stats()

    # Required top-level keys.
    for key in (
        "total_articles", "total_classified", "total_events",
        "total_alerts", "articles_per_day", "urgency_distribution",
        "source_distribution", "language_distribution",
        "event_type_distribution", "pipeline_funnel",
    ):
        assert key in stats, f"missing stats key: {key}"

    assert stats["total_articles"] == 8
    assert stats["total_classified"] == 5
    assert stats["total_events"] == 2
    assert stats["total_alerts"] == 2

    # articles_per_day: 30 entries, each a {date, count} pair (req 1.6a).
    assert len(stats["articles_per_day"]) == 30
    for entry in stats["articles_per_day"]:
        assert set(entry.keys()) == {"date", "count"}

    # urgency_distribution: one bucket per score 1-10.
    assert len(stats["urgency_distribution"]) == 10
    urgency_by_score = {
        d["urgency_score"]: d["count"]
        for d in stats["urgency_distribution"]
    }
    assert urgency_by_score[9] == 1  # a1
    assert urgency_by_score[7] == 1  # a2
    assert urgency_by_score[10] == 0  # zero bucket present

    # source_distribution sorted by count descending.
    src_counts = [d["count"] for d in stats["source_distribution"]]
    assert src_counts == sorted(src_counts, reverse=True)

    # language_distribution covers all sample languages.
    langs = {d["language"] for d in stats["language_distribution"]}
    assert langs == {"pl", "en", "ru"}

    # pipeline_funnel has the four required stages (req 1.6b).
    funnel = stats["pipeline_funnel"]
    assert set(funnel.keys()) == {
        "collected", "classified", "events_created", "alerts_sent"
    }
    assert funnel["collected"] == 8
    assert funnel["classified"] == 5
    # ev1 (a1,a2) + ev2 (a4) -> 3 distinct articles reached events.
    assert funnel["events_created"] == 3
    # only ev1 produced alerts -> a1, a2 -> 2 distinct articles.
    assert funnel["alerts_sent"] == 2
