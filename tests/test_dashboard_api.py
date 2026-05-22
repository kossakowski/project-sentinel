"""Tests for the dashboard Flask API (`dashboard.app` + the API blueprints).

Fully hermetic: the Flask app is pointed at a local SQLite DB built from the
production schema, and the only network-touching unit (the SCP step in
`dashboard.sync`) is monkeypatched. No real SSH / SCP / production server.

The sample-DB builder is reused from `test_dashboard_db` so both test modules
exercise the same fixture data.
"""

import json
import sqlite3

import pytest

from dashboard.app import create_app
from dashboard.classifier_input import build_classifier_input
from dashboard.db import DashboardDB
from dashboard.sync import build_fts_index
from tests.test_dashboard_db import _build_sentinel_db

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sentinel_db_path(tmp_path):
    """Path to a freshly built local sentinel SQLite DB."""
    path = tmp_path / "sentinel.db"
    _build_sentinel_db(str(path))
    return str(path)


@pytest.fixture
def fts_db_path(tmp_path):
    """Path for the FTS index DB (built lazily by tests that need it)."""
    return str(tmp_path / "sentinel_fts.db")


@pytest.fixture
def app(sentinel_db_path, fts_db_path):
    """A Flask app wired to the local sample DB, with an FTS index built."""
    build_fts_index(sentinel_db_path, fts_db_path)
    flask_app = create_app(
        db_path=sentinel_db_path, fts_db_path=fts_db_path, dev_cors=True
    )
    flask_app.config.update(TESTING=True)
    return flask_app


@pytest.fixture
def client(app):
    """A Flask test client for the wired app."""
    return app.test_client()


# ---------------------------------------------------------------------------
# App factory + CORS
# ---------------------------------------------------------------------------


def test_app_factory_creates_app(app):
    """[1.1] The factory returns a Flask app with the API blueprint registered."""
    from flask import Flask

    assert isinstance(app, Flask)
    # API blueprints registered.
    assert "articles" in app.blueprints
    assert "stats" in app.blueprints
    assert "sync" in app.blueprints

    # The /api-prefixed routes exist on the URL map.
    rules = {rule.rule for rule in app.url_map.iter_rules()}
    assert "/api/articles" in rules
    assert "/api/stats" in rules
    assert "/api/sync" in rules


def test_app_factory_frontend_placeholder(client):
    """[1.1] With no built frontend, `/` returns the JSON status placeholder."""
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "frontend not built"}


def test_app_cors_dev_mode(client):
    """[1.1a] CORS headers are present for the localhost:5173 dev origin."""
    resp = client.get(
        "/api/stats", headers={"Origin": "http://localhost:5173"}
    )
    assert resp.status_code == 200
    assert (
        resp.headers.get("Access-Control-Allow-Origin")
        == "http://localhost:5173"
    )


def test_api_missing_db_returns_503(tmp_path):
    """[1.1b, 1.2] With no DB synced yet, API endpoints return a clean 503.

    A fresh install (no `sentinel.db`) must degrade gracefully -- a JSON 503
    with an actionable message -- rather than a 500 stack trace.
    """
    missing = str(tmp_path / "not_synced.db")  # never created
    fresh_app = create_app(db_path=missing, dev_cors=False)
    fresh_app.config.update(TESTING=True)
    fresh_client = fresh_app.test_client()

    resp = fresh_client.get("/api/stats")
    assert resp.status_code == 503
    body = resp.get_json()
    assert "error" in body
    assert body.get("needs_sync") is True


# ---------------------------------------------------------------------------
# GET /api/articles
# ---------------------------------------------------------------------------


def test_api_articles_endpoint(client):
    """[1.4, 1.4a] GET /api/articles returns the required JSON shape."""
    resp = client.get("/api/articles?page=1&page_size=25")
    assert resp.status_code == 200
    body = resp.get_json()

    # Top-level shape (req 1.4a).
    for key in ("articles", "total", "page", "page_size", "total_pages"):
        assert key in body
    assert body["total"] == 8
    assert body["page"] == 1
    assert body["page_size"] == 25
    assert body["total_pages"] == 1

    # Per-article shape -- field names must match the spec exactly.
    article = next(a for a in body["articles"] if a["id"] == "a1")
    for key in (
        "id", "source_name", "source_url", "source_type", "title",
        "summary", "language", "published_at", "fetched_at",
        "classification", "pipeline_status", "has_alert",
    ):
        assert key in article, f"missing article field: {key}"

    # Nested classification shape for a classified article.
    classification = article["classification"]
    for key in (
        "urgency_score", "event_type", "is_military_event", "confidence",
        "affected_countries", "aggressor", "summary_pl", "classified_at",
        "input_tokens", "output_tokens",
    ):
        assert key in classification, f"missing classification field: {key}"
    assert classification["is_military_event"] is True
    assert isinstance(classification["affected_countries"], list)

    # a1 reached an event with alerts.
    assert article["pipeline_status"] == "alert_sent"
    assert article["has_alert"] is True


def test_api_articles_unclassified_status(client):
    """[1.4b] An article with no classification has status 'unclassified'."""
    resp = client.get("/api/articles?pipeline_status=unclassified")
    body = resp.get_json()
    assert body["total"] == 3
    for article in body["articles"]:
        assert article["classification"] is None
        assert article["pipeline_status"] == "unclassified"


def test_api_articles_page_size_clamped(client):
    """[1.4] An out-of-range page_size falls back to the default (50)."""
    resp = client.get("/api/articles?page_size=999")
    assert resp.get_json()["page_size"] == 50


def test_api_articles_filter_and_sort(client):
    """[1.4] source_type filter + urgency_score sort applied via the API."""
    resp = client.get(
        "/api/articles?source_type=telegram&sort=published_at&order=desc"
    )
    body = resp.get_json()
    assert body["total"] == 1
    assert body["articles"][0]["source_type"] == "telegram"


def test_api_articles_search(client):
    """[1.4, 1.2d] GET /api/articles?q=drone returns matching articles."""
    resp = client.get("/api/articles?q=drone")
    assert resp.status_code == 200
    body = resp.get_json()

    ids = {a["id"] for a in body["articles"]}
    assert ids == {"a1", "a2", "a4"}
    assert body["total"] == 3
    # Each result genuinely matches the query term.
    for article in body["articles"]:
        haystack = (
            article["title"] + " " + (article["summary"] or "")
        ).lower()
        assert "drone" in haystack


# ---------------------------------------------------------------------------
# GET /api/articles/<id>
# ---------------------------------------------------------------------------


def test_api_article_detail_endpoint(client):
    """[1.5, 1.5a, 1.5b] Detail returns classifier_input and linked events."""
    resp = client.get("/api/articles/a1")
    assert resp.status_code == 200
    body = resp.get_json()

    assert body["id"] == "a1"
    assert body["classification"] is not None

    # classifier_input present and shaped as the 5-line block (req 1.5a).
    assert "classifier_input" in body
    ci = body["classifier_input"]
    assert ci.startswith("Source: TASS (rss)")
    assert "Language: en" in ci
    assert "Published: 2026-05-22T10:00:00+00:00" in ci
    assert "Title: Russian drone strike near Polish border" in ci
    assert "Summary:" in ci

    # events array with alert_records (req 1.5b).
    assert len(body["events"]) == 1
    event = body["events"][0]
    assert event["id"] == "ev1"
    assert len(event["alert_records"]) == 2


def test_api_article_detail_not_found(client):
    """[1.5] An unknown article id returns HTTP 404 with a JSON error."""
    resp = client.get("/api/articles/no-such-id")
    assert resp.status_code == 404
    assert "error" in resp.get_json()


def test_api_article_detail_unclassified(client):
    """[1.5] An unclassified article still returns a classifier_input block."""
    resp = client.get("/api/articles/a5")
    body = resp.get_json()
    assert body["classification"] is None
    assert body["events"] == []
    # classifier_input is still reconstructed (it does not need a classification).
    assert body["classifier_input"].startswith("Source: Onet (rss)")


# ---------------------------------------------------------------------------
# Classifier-input reconstruction (req 1.5a)
# ---------------------------------------------------------------------------


def test_classifier_input_reconstruction():
    """[1.5a] The reconstructed input matches the classifier.py prompt format.

    The expected string is built from `USER_PROMPT_TEMPLATE` in
    `sentinel/classification/classifier.py` -- the per-article 5-line block:
    Source / Language / Published / Title / Summary.
    """
    article = {
        "source_name": "TVN24",
        "source_type": "rss",
        "language": "pl",
        "published_at": "2026-05-22T10:00:00+00:00",
        "title": "Drony nad Polska",
        "summary": "Wojsko potwierdza naruszenie przestrzeni.",
    }
    result = build_classifier_input(article)

    expected = (
        "Source: TVN24 (rss)\n"
        "Language: pl\n"
        "Published: 2026-05-22T10:00:00+00:00\n"
        "Title: Drony nad Polska\n"
        "Summary: Wojsko potwierdza naruszenie przestrzeni."
    )
    assert result == expected

    # Cross-check field-by-field against the real classifier template, so
    # this test fails if classifier.py's format ever drifts.
    from sentinel.classification.classifier import USER_PROMPT_TEMPLATE

    rendered = USER_PROMPT_TEMPLATE.format(
        source_name=article["source_name"],
        source_type=article["source_type"],
        language=article["language"],
        published_at=article["published_at"],
        title=article["title"],
        summary=article["summary"],
    )
    # Every line of our reconstruction appears verbatim in the real prompt.
    for line in result.split("\n"):
        assert line in rendered


def test_classifier_input_missing_published():
    """[1.5a] A missing published_at renders as the literal 'unknown'.

    This matches `Classifier._build_user_prompt`, which uses 'unknown' when
    the article has no published_at.
    """
    article = {
        "source_name": "PAP",
        "source_type": "google_news",
        "language": "en",
        "published_at": None,
        "title": "Headline",
        "summary": "Body",
    }
    result = build_classifier_input(article)
    assert "Published: unknown" in result


# ---------------------------------------------------------------------------
# GET /api/stats
# ---------------------------------------------------------------------------


def test_api_stats_endpoint(client):
    """[1.6, 1.6a, 1.6b] GET /api/stats returns every required stat field."""
    resp = client.get("/api/stats")
    assert resp.status_code == 200
    body = resp.get_json()

    for key in (
        "total_articles", "total_classified", "total_events",
        "total_alerts", "articles_per_day", "urgency_distribution",
        "source_distribution", "language_distribution",
        "event_type_distribution", "pipeline_funnel",
    ):
        assert key in body, f"missing stats field: {key}"

    assert body["total_articles"] == 8
    assert body["total_classified"] == 5

    # articles_per_day: 30 zero-filled day entries (req 1.6a).
    assert len(body["articles_per_day"]) == 30
    for entry in body["articles_per_day"]:
        assert set(entry.keys()) == {"date", "count"}

    # pipeline_funnel: the four required stages (req 1.6b).
    funnel = body["pipeline_funnel"]
    assert set(funnel.keys()) == {
        "collected", "classified", "events_created", "alerts_sent"
    }
    assert funnel["collected"] == 8
    assert funnel["classified"] == 5
    assert funnel["events_created"] == 3
    assert funnel["alerts_sent"] == 2


# ---------------------------------------------------------------------------
# Sync result shape + endpoints
# ---------------------------------------------------------------------------


def test_sync_result_shape(sentinel_db_path, fts_db_path, tmp_path, monkeypatch):
    """[1.3b] A sync result carries success, file_size, article_count, duration.

    The network-touching SCP step is mocked: instead of copying from the
    production server, it copies the local sample DB to the destination.
    `build_fts_index` runs for real against that local file.
    """
    import shutil

    from dashboard import sync as sync_module

    dest = str(tmp_path / "synced.db")

    def fake_scp(dest_path):
        # Stand in for the real SCP -- copy the local sample DB instead.
        shutil.copy(sentinel_db_path, dest_path)

    monkeypatch.setattr(sync_module, "scp_database", fake_scp)

    result = sync_module.sync_db(db_path=dest, fts_db_path=fts_db_path)

    assert result.success is True
    assert result.file_size > 0
    assert result.article_count == 8
    assert result.duration >= 0
    assert result.error is None

    # to_dict() exposes all fields for the JSON response.
    as_dict = result.to_dict()
    for key in ("success", "file_size", "article_count", "duration", "error"):
        assert key in as_dict


def test_sync_result_shape_failure(tmp_path, monkeypatch):
    """[1.3b] A failed sync returns success=False with an error message."""
    from dashboard import sync as sync_module

    def failing_scp(dest_path):
        raise RuntimeError("SCP failed: connection refused")

    monkeypatch.setattr(sync_module, "scp_database", failing_scp)

    result = sync_module.sync_db(db_path=str(tmp_path / "x.db"))
    assert result.success is False
    assert result.error is not None
    assert "connection refused" in result.error


def test_fts_index_creation(sentinel_db_path, tmp_path):
    """[1.3a] After building the index, the FTS5 table exists and is queryable.

    This exercises the REAL FTS5 index-build logic (`build_fts_index`) against
    a local DB file -- nothing about the index build is mocked.
    """
    fts_path = str(tmp_path / "fresh_fts.db")
    build_fts_index(sentinel_db_path, fts_path)

    # The FTS index lives in its own DB file -- the source DB is untouched.
    import os

    assert os.path.exists(fts_path)

    # The articles_fts virtual table exists and is queryable.
    conn = sqlite3.connect(fts_path)
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='articles_fts'"
        ).fetchone()
        assert row is not None

        # It is populated and answers a MATCH query ordered by rank.
        hits = conn.execute(
            "SELECT article_id FROM articles_fts "
            "WHERE articles_fts MATCH 'drone' ORDER BY rank"
        ).fetchall()
        assert len(hits) == 3
    finally:
        conn.close()

    # And DashboardDB picks the index up and uses it.
    db = DashboardDB(db_path=sentinel_db_path, fts_db_path=fts_path)
    try:
        assert db.fts_available is True
        result = db.search_articles("drone")
        assert result["total"] == 3
    finally:
        db.close()


def test_api_sync_endpoint(client, app, tmp_path, monkeypatch):
    """[1.7, 1.7a] POST /api/sync triggers a sync; GET /api/sync/status reports it.

    The SCP step is mocked to copy a separate "remote" sample DB into the
    app's configured DB path; the FTS rebuild runs for real.
    """
    import shutil

    from dashboard import sync as sync_module

    # A distinct sample DB standing in for the production server's copy --
    # the mocked SCP copies FROM this INTO the app's configured DB path.
    remote_db = str(tmp_path / "remote_sentinel.db")
    _build_sentinel_db(remote_db)

    def fake_scp(dest_path):
        shutil.copy(remote_db, dest_path)

    monkeypatch.setattr(sync_module, "scp_database", fake_scp)

    # Before any sync, status reports last_sync == null (req 1.7a).
    status_before = client.get("/api/sync/status")
    assert status_before.status_code == 200
    assert status_before.get_json() == {"last_sync": None}

    # POST /api/sync runs the sync synchronously and returns the result.
    resp = client.post("/api/sync")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "last_sync" in body
    assert body["last_sync"] is not None
    assert body["result"]["success"] is True
    assert body["result"]["article_count"] == 8

    # After the sync, status reflects the recorded result (req 1.7a).
    status_after = client.get("/api/sync/status")
    after = status_after.get_json()
    assert after["last_sync"] is not None
    assert after["result"]["success"] is True
