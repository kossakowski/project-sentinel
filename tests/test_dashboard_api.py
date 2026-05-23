"""Tests for the dashboard Flask API (`dashboard.app` + the API blueprints).

Fully hermetic: the Flask app is pointed at a local SQLite DB built from the
production schema, and the only network-touching unit (the SCP step in
`dashboard.sync`) is monkeypatched. No real SSH / SCP / production server.

The sample-DB builder is reused from `test_dashboard_db` so both test modules
exercise the same fixture data.
"""

import os
import sqlite3

import pytest

from dashboard.app import create_app
from dashboard.classifier_input import (
    ENRICHMENT_NOT_FETCHED_NOTE,
    build_classifier_input,
)
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
    flask_app = create_app(db_path=sentinel_db_path, fts_db_path=fts_db_path, dev_cors=True)
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


def test_app_factory_frontend_placeholder(sentinel_db_path, fts_db_path, monkeypatch, tmp_path):
    """[1.1] With no built frontend, `/` returns the JSON status placeholder.

    Independent of whether ``dashboard/frontend/dist/`` happens to exist on
    disk: Phase 2's ``npm run build`` deliverable creates that directory, so a
    test that asserts the placeholder behavior must NOT rely on its absence.
    We monkeypatch ``config.FRONTEND_DIST_DIR`` to a guaranteed-nonexistent
    path BEFORE calling ``create_app`` (the route closes over the constant at
    registration time -- see ``_register_frontend_routes``).
    """
    from dashboard import config as dashboard_config

    nonexistent_dist = str(tmp_path / "no-such-frontend-dist")
    monkeypatch.setattr(dashboard_config, "FRONTEND_DIST_DIR", nonexistent_dist)
    assert not os.path.exists(nonexistent_dist)

    build_fts_index(sentinel_db_path, fts_db_path)
    placeholder_app = create_app(
        db_path=sentinel_db_path,
        fts_db_path=fts_db_path,
        dev_cors=True,
    )
    placeholder_app.config.update(TESTING=True)
    placeholder_client = placeholder_app.test_client()

    resp = placeholder_client.get("/")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "frontend not built"}


def test_app_cors_dev_mode(client):
    """[1.1a] CORS headers are present for the localhost:5173 dev origin."""
    resp = client.get("/api/stats", headers={"Origin": "http://localhost:5173"})
    assert resp.status_code == 200
    assert resp.headers.get("Access-Control-Allow-Origin") == "http://localhost:5173"


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
    assert body["total"] == 9
    assert body["page"] == 1
    assert body["page_size"] == 25
    assert body["total_pages"] == 1

    # Per-article shape -- field names must match the spec exactly.
    article = next(a for a in body["articles"] if a["id"] == "a1")
    for key in (
        "id",
        "source_name",
        "source_url",
        "source_type",
        "title",
        "summary",
        "language",
        "published_at",
        "fetched_at",
        "classification",
        "pipeline_status",
        "has_alert",
    ):
        assert key in article, f"missing article field: {key}"

    # Nested classification shape for a classified article.
    classification = article["classification"]
    for key in (
        "urgency_score",
        "event_type",
        "is_military_event",
        "confidence",
        "affected_countries",
        "aggressor",
        "summary_pl",
        "classified_at",
        "input_tokens",
        "output_tokens",
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
    assert body["total"] == 4
    for article in body["articles"]:
        assert article["classification"] is None
        assert article["pipeline_status"] == "unclassified"


def test_api_articles_page_size_clamped(client):
    """[1.4] An out-of-range page_size falls back to the default (50)."""
    resp = client.get("/api/articles?page_size=999")
    assert resp.get_json()["page_size"] == 50


def test_api_articles_filter_and_sort(client):
    """[1.4] source_type filter + urgency_score sort applied via the API."""
    resp = client.get("/api/articles?source_type=telegram&sort=published_at&order=desc")
    body = resp.get_json()
    assert body["total"] == 1
    assert body["articles"][0]["source_type"] == "telegram"


def test_api_articles_source_name_multi_select(client):
    """[1.4, 2.4] Repeated ``?source_name=`` params return articles from ANY listed source.

    The dashboard's multi-select source filter (spec 2.4) serialises each
    selected source as a repeated query param. The API must collect them via
    ``getlist`` and pass to the DB layer as a list so an ``IN`` clause is
    used; a single value path still works (backwards compatible).
    """
    # Single source -- equality path.
    resp = client.get("/api/articles?source_name=TVN24")
    body = resp.get_json()
    assert {a["id"] for a in body["articles"]} == {"a2"}
    assert body["total"] == 1

    # Multi-select via repeated params -- IN(...) path.
    resp = client.get("/api/articles?source_name=TVN24&source_name=TASS")
    body = resp.get_json()
    assert {a["id"] for a in body["articles"]} == {"a1", "a2"}
    assert body["total"] == 2

    # Three sources -- proves the IN list scales beyond two.
    resp = client.get("/api/articles?source_name=TVN24&source_name=TASS&source_name=Onet")
    body = resp.get_json()
    assert {a["id"] for a in body["articles"]} == {"a1", "a2", "a3", "a5"}

    # No source_name parameter at all -- filter omitted, full set returned.
    resp = client.get("/api/articles")
    body = resp.get_json()
    assert body["total"] == 9


def test_api_articles_source_name_whitespace_only_dropped(client):
    """[1.4, 2.4] Whitespace-only ``source_name`` values are filtered out.

    ``[s for s in getlist(...) if s]`` only drops empty strings -- a
    whitespace-only value like ``"   "`` is truthy and survives, then reaches
    the DB and produces a silent no-match query. The API must strip whitespace
    and drop any value that's empty after stripping, so the request behaves
    identically to "no source_name filter applied".
    """
    # Baseline: no source_name filter at all -- full 9-article fixture.
    baseline = client.get("/api/articles").get_json()
    assert baseline["total"] == 9

    # Single whitespace-only value: filter must be omitted (same as baseline).
    resp = client.get("/api/articles?source_name=%20%20%20")
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["total"] == baseline["total"]
    assert {a["id"] for a in body["articles"]} == {a["id"] for a in baseline["articles"]}

    # Two whitespace-only values: same behavior (filter omitted entirely).
    resp = client.get("/api/articles?source_name=%20%20%20&source_name=%09")
    body = resp.get_json()
    assert body["total"] == baseline["total"]

    # Mixed: one whitespace-only + one real value -- only the real value applies.
    resp = client.get("/api/articles?source_name=%20%20%20&source_name=TVN24")
    body = resp.get_json()
    assert {a["id"] for a in body["articles"]} == {"a2"}
    assert body["total"] == 1

    # Whitespace padding around a real value is trimmed -- "  TVN24  " matches TVN24.
    resp = client.get("/api/articles?source_name=%20%20TVN24%20%20")
    body = resp.get_json()
    assert {a["id"] for a in body["articles"]} == {"a2"}


def test_api_articles_search(client):
    """[1.4, 1.2d] GET /api/articles?q=drone returns matching articles."""
    resp = client.get("/api/articles?q=drone")
    assert resp.status_code == 200
    body = resp.get_json()

    ids = {a["id"] for a in body["articles"]}
    assert ids == {"a1", "a2", "a4", "a9"}
    assert body["total"] == 4
    # Each result genuinely matches the query term.
    for article in body["articles"]:
        haystack = (article["title"] + " " + (article["summary"] or "")).lower()
        assert "drone" in haystack


def test_api_articles_search_with_filters(client):
    """[1.4c] Acceptance test #20: search composes with filters and sort.

    ``?q=drone&pipeline_status=unclassified`` returns articles whose title or
    summary matches "drone" AND that have no classification. The fixture
    includes a9 -- an unclassified Polish article whose summary mentions
    "drone" -- so the unclassified-filtered search MUST return EXACTLY {a9}.
    A broken filter that returned all drone matches would return
    {a1, a2, a4, a9}; a broken search that returned all unclassified would
    return {a5, a6, a8, a9}; this assertion pins both axes.

    An explicit ``sort`` parameter MUST override FTS rank ordering.
    """
    # Search + pipeline_status=unclassified -- a9 is the only unclassified
    # drone-mentioning article. Tightens the previous vacuous "returns zero".
    resp = client.get("/api/articles?q=drone&pipeline_status=unclassified")
    body = resp.get_json()
    assert body["total"] == 1
    assert {a["id"] for a in body["articles"]} == {"a9"}

    # Search + classified filter -- the three classified drone articles.
    resp = client.get("/api/articles?q=drone&pipeline_status=classified")
    body = resp.get_json()
    assert body["total"] == 3
    assert {a["id"] for a in body["articles"]} == {"a1", "a2", "a4"}

    # Search + source_type filter -- only a4 is a telegram drone article.
    resp = client.get("/api/articles?q=drone&source_type=telegram")
    body = resp.get_json()
    assert body["total"] == 1
    assert body["articles"][0]["id"] == "a4"

    # Search + urgency filter -- a1 (urgency 9) and a2 (urgency 7) only.
    resp = client.get("/api/articles?q=drone&urgency_min=7")
    body = resp.get_json()
    assert {a["id"] for a in body["articles"]} == {"a1", "a2"}

    # Default search (no explicit sort) -- FTS rank ordering. a1 has "drone"
    # in both title AND summary so it ranks first.
    resp = client.get("/api/articles?q=drone")
    body = resp.get_json()
    assert body["articles"][0]["id"] == "a1"

    # Explicit sort overrides FTS rank: ascending published_at -> a9 first
    # (oldest drone article in the fixture: 2026-05-15).
    resp = client.get("/api/articles?q=drone&sort=published_at&order=asc")
    body = resp.get_json()
    assert body["articles"][0]["id"] == "a9"

    # Explicit sort by urgency descending under search -> a1 first (urgency 9).
    resp = client.get("/api/articles?q=drone&sort=urgency_score&order=desc")
    body = resp.get_json()
    assert body["articles"][0]["id"] == "a1"


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


def _extract_per_article_block(article: dict) -> str:
    """Return the exact per-article block from the live classifier template.

    Renders ``USER_PROMPT_TEMPLATE`` from ``classifier.py`` with the article's
    fields, then extracts the substring between the ``"Analyze this article:"``
    preamble and the trailing ``"Respond with JSON:"`` schema -- i.e. the
    Source/Language/Published/Title/Summary block the dashboard reconstructs.

    Used by the reconstruction test to assert byte-for-byte equality against
    the real template, so any drift in classifier.py's per-article format
    fails the test.
    """
    from sentinel.classification.classifier import USER_PROMPT_TEMPLATE

    rendered = USER_PROMPT_TEMPLATE.format(
        source_name=article["source_name"],
        source_type=article["source_type"],
        language=article["language"],
        published_at=article["published_at"],
        title=article["title"],
        summary=article["summary"],
    )
    # Slice between the preamble line and the schema header.
    head = "Analyze this article:\n\n"
    tail = "\n\nRespond with JSON:"
    head_idx = rendered.index(head) + len(head)
    tail_idx = rendered.index(tail, head_idx)
    return rendered[head_idx:tail_idx]


def test_classifier_input_reconstruction():
    """[1.5a] The reconstructed input matches the classifier.py prompt format.

    Asserts the reconstruction equals byte-for-byte the per-article block
    extracted directly from ``USER_PROMPT_TEMPLATE`` -- any drift in the
    classifier's per-article format (a reordered line, a renamed field, a new
    line) fails this test deterministically.
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

    # Exact match against the live classifier per-article block -- this fails
    # if classifier.py's format drifts (line reorder, field rename, new line).
    template_block = _extract_per_article_block(article)
    assert result == template_block


def test_classifier_input_with_enrichment_note():
    """[1.5a] An enrichment-flagged article whose body fetch failed gets the
    caution note appended -- matching ``Classifier._build_user_prompt``.

    The classifier appends a note after the Summary line when
    ``raw_metadata.enrichment.method`` is in {heuristic, llm} AND
    ``enrichment.fetched`` is falsy. The dashboard reconstruction must do the
    same -- otherwise the displayed input misrepresents what the classifier
    actually saw for production-exercised enrichment-flagged articles.
    """
    article = {
        "source_name": "Google News",
        "source_type": "google_news",
        "language": "en",
        "published_at": "2026-05-22T10:00:00+00:00",
        "title": "Vague NATO country headline",
        "summary": "Vague NATO country headline",
        "raw_metadata": {
            "enrichment": {
                "method": "heuristic",
                "fetched": False,
                "original_summary": "Vague NATO country headline",
            }
        },
    }
    result = build_classifier_input(article)

    # Reconstruction equals the 5-line block plus the note appended on a new
    # line right after the Summary -- byte-for-byte the same shape the
    # classifier produces (see classifier.py:_build_user_prompt).
    expected = (
        "Source: Google News (google_news)\n"
        "Language: en\n"
        "Published: 2026-05-22T10:00:00+00:00\n"
        "Title: Vague NATO country headline\n"
        "Summary: Vague NATO country headline\n" + ENRICHMENT_NOT_FETCHED_NOTE
    )
    assert result == expected

    # Also true for method='llm' (the other branch the classifier triggers on).
    article_llm = dict(article)
    article_llm["raw_metadata"] = {"enrichment": {"method": "llm", "fetched": False}}
    assert build_classifier_input(article_llm).endswith("\n" + ENRICHMENT_NOT_FETCHED_NOTE)


def test_enrichment_note_matches_classifier_source():
    """[1.5a] The dashboard's enrichment caution note is byte-identical to the
    string the classifier appends in ``_build_user_prompt``.

    Reads the classifier source via ``inspect.getsource`` and reconstructs the
    note from the Python string literals there (one literal per line via
    implicit concatenation). Asserts that reconstruction equals the dashboard
    constant. This is the drift guard: if classifier.py changes the note,
    this test fails before the dashboard misrepresents what the classifier
    saw.
    """
    import inspect
    import re

    from sentinel.classification.classifier import Classifier

    source = inspect.getsource(Classifier._build_user_prompt)
    # Find the consecutive string literals starting with the note prefix.
    # The source looks like:
    #   "Note: Article body could not be fetched. The summary above may just be "
    #   "the headline repeated. Exercise extreme caution with country attribution "
    #   "— do not assume a monitored country is affected unless explicitly stated.",
    note_segments = re.findall(r'"((?:Note:|the headline repeated|—)[^"]*)"', source)
    # We expect exactly the three segments that make up the implicit-concat
    # literal -- if classifier.py reflows them or adds/removes a line, this
    # count changes and the test fails.
    assert len(note_segments) == 3, (
        f"expected 3 note segments in classifier.py, got {len(note_segments)}: {note_segments!r}"
    )
    reconstructed = "".join(note_segments)
    assert reconstructed == ENRICHMENT_NOT_FETCHED_NOTE, (
        "classifier.py note has drifted from dashboard.ENRICHMENT_NOT_FETCHED_NOTE"
    )


def test_classifier_input_without_enrichment_note():
    """[1.5a] When enrichment was successful (fetched=True) or absent, the
    caution note is NOT appended -- the classifier only adds it when the body
    fetch failed for an enrichment-flagged article.
    """
    # Case 1: enrichment succeeded.
    article_fetched = {
        "source_name": "Google News",
        "source_type": "google_news",
        "language": "en",
        "published_at": "2026-05-22T10:00:00+00:00",
        "title": "Some title",
        "summary": "Enriched body content.",
        "raw_metadata": {
            "enrichment": {"method": "heuristic", "fetched": True},
        },
    }
    assert ENRICHMENT_NOT_FETCHED_NOTE not in build_classifier_input(article_fetched)

    # Case 2: enrichment method is "none" (article was not flagged).
    article_none = {
        "source_name": "Direct RSS",
        "source_type": "rss",
        "language": "en",
        "published_at": "2026-05-22T10:00:00+00:00",
        "title": "Some title",
        "summary": "A full summary already.",
        "raw_metadata": {"enrichment": {"method": "none"}},
    }
    assert ENRICHMENT_NOT_FETCHED_NOTE not in build_classifier_input(article_none)

    # Case 3: no raw_metadata at all.
    article_no_meta = {
        "source_name": "Direct RSS",
        "source_type": "rss",
        "language": "en",
        "published_at": "2026-05-22T10:00:00+00:00",
        "title": "Some title",
        "summary": "Body",
    }
    assert ENRICHMENT_NOT_FETCHED_NOTE not in build_classifier_input(article_no_meta)


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
        "total_articles",
        "total_classified",
        "total_events",
        "total_alerts",
        "articles_per_day",
        "classified_per_day",
        "urgency_distribution",
        "source_distribution",
        "language_distribution",
        "event_type_distribution",
        "pipeline_funnel",
    ):
        assert key in body, f"missing stats field: {key}"

    assert body["total_articles"] == 9
    assert body["total_classified"] == 5

    # articles_per_day: 30 zero-filled day entries (req 1.6a).
    assert len(body["articles_per_day"]) == 30
    for entry in body["articles_per_day"]:
        assert set(entry.keys()) == {"date", "count"}

    # classified_per_day (req 3.4a) — same 30-day calendar so the overview
    # chart can plot two point-aligned series.
    assert len(body["classified_per_day"]) == 30
    article_dates = [e["date"] for e in body["articles_per_day"]]
    classified_dates = [e["date"] for e in body["classified_per_day"]]
    assert article_dates == classified_dates
    for entry in body["classified_per_day"]:
        assert set(entry.keys()) == {"date", "count"}

    # pipeline_funnel: the four required stages (req 1.6b).
    funnel = body["pipeline_funnel"]
    assert set(funnel.keys()) == {"collected", "classified", "events_created", "alerts_sent"}
    assert funnel["collected"] == 9
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
    assert result.article_count == 9
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
        row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='articles_fts'").fetchone()
        assert row is not None

        # It is populated and answers a MATCH query ordered by rank.
        hits = conn.execute(
            "SELECT article_id FROM articles_fts WHERE articles_fts MATCH 'drone' ORDER BY rank"
        ).fetchall()
        assert len(hits) == 4
    finally:
        conn.close()

    # And DashboardDB picks the index up and uses it.
    db = DashboardDB(db_path=sentinel_db_path, fts_db_path=fts_path)
    try:
        assert db.fts_available is True
        result = db.search_articles("drone")
        assert result["total"] == 4
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
    assert body["result"]["article_count"] == 9

    # After the sync, status reflects the recorded result (req 1.7a).
    status_after = client.get("/api/sync/status")
    after = status_after.get_json()
    assert after["last_sync"] is not None
    assert after["result"]["success"] is True


# ---------------------------------------------------------------------------
# Tunnel mode API integration (req 1.1c)
# ---------------------------------------------------------------------------


def test_api_tunnel_scp_once_per_startup(sentinel_db_path, monkeypatch):
    """[1.1c] Acceptance: tunnel mode SCPs once at app startup, not per-request.

    Spec req 1.1c says ``--tunnel`` ``fetches a fresh copy of the production
    database over SSH on each dashboard startup``. The dashboard must not
    SCP on every request: a page load that hits multiple endpoints would
    otherwise serialise multiple ~5-10s SCPs and become unusable.

    This test monkeypatches `subprocess.run` to (a) count invocations and
    (b) populate the temp path with a local sample DB. It then calls
    `create_app(tunnel=True)`, issues several API requests, and asserts that
    the SCP fired EXACTLY ONCE across the whole lifecycle.

    Regression guard for the fix to finding #1 / the resolver decision to
    cache the tunnel SCP at app-startup.
    """
    import shutil

    from dashboard import db as db_module

    scp_calls: list[list[str]] = []

    class _FakeCompletedProcess:
        returncode = 0
        stderr = ""
        args: list = []

    def fake_run(argv, capture_output, text, timeout):  # noqa: ARG001
        scp_calls.append(list(argv))
        # Drop a real sample DB at the destination so the subsequent SQLite
        # open + queries succeed.
        shutil.copy(sentinel_db_path, argv[-1])
        result = _FakeCompletedProcess()
        result.args = list(argv)
        return result

    monkeypatch.setattr(db_module.subprocess, "run", fake_run)

    # create_app with tunnel=True must perform the SCP itself, once.
    flask_app = create_app(tunnel=True, dev_cors=False)
    flask_app.config.update(TESTING=True)
    client = flask_app.test_client()

    # Exactly one SCP after the factory ran.
    assert len(scp_calls) == 1, (
        f"create_app(tunnel=True) should SCP exactly once at startup, got {len(scp_calls)} SCP call(s)"
    )

    # Make multiple GETs across different endpoints -- still only ONE SCP.
    resp1 = client.get("/api/articles")
    resp2 = client.get("/api/stats")
    resp3 = client.get("/api/articles?page=2&page_size=25")
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp3.status_code == 200

    assert len(scp_calls) == 1, (
        f"Tunnel mode must reuse the startup-fetched DB across requests, got {len(scp_calls)} SCP call(s) after 3 GETs"
    )

    # The cached temp DB path is exposed on app.config so teardown is testable.
    cached_path = flask_app.config.get("TUNNEL_TEMPFILE")
    assert cached_path is not None
    assert os.path.exists(cached_path)

    # Cleanup callback removes the temp file (atexit would otherwise handle it).
    cleanup = flask_app.config.get("TUNNEL_CLEANUP")
    assert callable(cleanup)
    cleanup()
    assert not os.path.exists(cached_path)


# ---------------------------------------------------------------------------
# Classifier-input None summary coercion (req 1.5a, finding #5)
# ---------------------------------------------------------------------------


def test_api_article_detail_null_summary_renders_as_none_literal(client):
    """[1.5a] An article with NULL summary in DB renders ``Summary: None``.

    The production classifier's ``_build_user_prompt`` passes the article's
    summary straight to ``str.format``, which coerces a None value to the
    literal string ``"None"``. The dashboard reconstruction must do the same
    so byte-for-byte parity holds even on the (rare) NULL-summary edge case.
    Fixture row ``a8`` has ``summary IS NULL``.
    """
    resp = client.get("/api/articles/a8")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["summary"] is None
    # Reconstruction must contain the literal "Summary: None" line.
    assert "Summary: None" in body["classifier_input"]


# ---------------------------------------------------------------------------
# CLI argument parsing + sync-before-serve (req 1.8, finding #11)
# ---------------------------------------------------------------------------


def test_cli_parse_args():
    """[1.8] CLI argparse exposes every required flag with the right defaults.

    Validates `dashboard.cli.build_parser()` so renames / removals of CLI
    flags fail the test, even when the integration path isn't exercised.
    """
    from dashboard import cli as cli_module
    from dashboard import config as dashboard_config

    parser = cli_module.build_parser()

    # No args: every flag falls to its declared default.
    defaults = parser.parse_args([])
    assert defaults.port == dashboard_config.DEFAULT_PORT
    assert defaults.db == dashboard_config.DEFAULT_DB_PATH
    assert defaults.tunnel is False
    assert defaults.sync is False

    # Explicit overrides parse as declared.
    overridden = parser.parse_args(["--port", "5005", "--db", "/tmp/x.db", "--tunnel", "--sync"])
    assert overridden.port == 5005
    assert overridden.db == "/tmp/x.db"
    assert overridden.tunnel is True
    assert overridden.sync is True


def test_cli_sync_then_serve(monkeypatch, tmp_path):
    """[1.8] ``--sync`` runs `sync_db` BEFORE `app.run` starts the server.

    Both `sync_db` and `app.run` are monkeypatched; the test asserts both
    were called exactly once, that `sync_db` ran first, AND that the same
    ``--db`` argument flowed to both `sync_db` and `create_app` -- a refactor
    that forgot to pass ``--db`` to `create_app` would slip through without
    this latter assertion.
    """
    from dashboard import cli as cli_module
    from dashboard.sync import SyncResult

    call_order: list[str] = []
    sync_args: dict = {}
    create_args: dict = {}

    def fake_sync_db(db_path=None, fts_db_path=None):
        call_order.append("sync")
        sync_args["db_path"] = db_path
        sync_args["fts_db_path"] = fts_db_path
        return SyncResult(success=True, file_size=1024, article_count=42, duration=0.1)

    class _FakeApp:
        def __init__(self):
            self.run_calls = []

        def run(self, host=None, port=None, threaded=None):
            call_order.append("run")
            self.run_calls.append({"host": host, "port": port, "threaded": threaded})

    fake_app = _FakeApp()

    def fake_create_app(db_path=None, tunnel=False, fts_db_path=None):
        call_order.append("create_app")
        create_args["db_path"] = db_path
        create_args["tunnel"] = tunnel
        create_args["fts_db_path"] = fts_db_path
        return fake_app

    monkeypatch.setattr(cli_module, "sync_db", fake_sync_db)
    monkeypatch.setattr(cli_module, "create_app", fake_create_app)

    db_path = str(tmp_path / "sentinel.db")
    rc = cli_module.main(["--sync", "--port", "9999", "--db", db_path])

    assert rc == 0
    # Both phases ran, and sync came strictly before run.
    assert "sync" in call_order
    assert "run" in call_order
    assert call_order.index("sync") < call_order.index("run")
    # Port flag wired through to app.run.
    assert fake_app.run_calls == [{"host": "127.0.0.1", "port": 9999, "threaded": True}]
    # --db flag wired through to BOTH sync_db AND create_app (req 1.8).
    assert sync_args["db_path"] == db_path
    assert create_args["db_path"] == db_path
    # --tunnel was not passed, so create_app sees the default False.
    assert create_args["tunnel"] is False
    # fts_db_path is derived from the --db argument (co-located).
    assert create_args["fts_db_path"] == sync_args["fts_db_path"]


def test_cli_sync_failure_short_circuits(monkeypatch, tmp_path, capsys):
    """[1.8] When --sync fails, main exits with code 1 and never calls app.run."""
    from dashboard import cli as cli_module
    from dashboard.sync import SyncResult

    def fake_sync_db(db_path=None, fts_db_path=None):
        return SyncResult(success=False, error="SCP failed: timeout")

    create_app_called: list[bool] = []

    def fake_create_app(db_path=None, tunnel=False, fts_db_path=None):
        create_app_called.append(True)
        raise AssertionError("create_app must not run when sync fails")

    monkeypatch.setattr(cli_module, "sync_db", fake_sync_db)
    monkeypatch.setattr(cli_module, "create_app", fake_create_app)

    rc = cli_module.main(["--sync", "--db", str(tmp_path / "x.db")])
    assert rc == 1
    assert create_app_called == []


def test_run_dashboard_sh_help_smoke():
    """[1.8a] ``./dashboard/run-dashboard.sh --help`` exits 0 with usage text.

    Skipped if the project venv isn't where the script expects it -- the
    script tries to bootstrap one, which would touch the filesystem. The
    happy path of this test just verifies the script forwards ``--help`` to
    ``python -m dashboard`` cleanly.
    """
    import os
    import subprocess

    # Derive every path from __file__ so the test works regardless of cwd.
    # ``__file__`` is ``<repo>/tests/test_dashboard_api.py``; the repo root is
    # one level up, and the script lives at ``<repo>/dashboard/run-dashboard.sh``.
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = os.path.join(repo_root, "dashboard", "run-dashboard.sh")
    venv_python = os.path.join(repo_root, ".venv", "bin", "python")
    if not os.path.exists(venv_python):
        pytest.skip(f"venv python not found at {venv_python}")

    result = subprocess.run(
        [script, "--help"],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=repo_root,
    )
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    # argparse's auto-generated --help mentions every declared flag.
    combined = result.stdout + result.stderr
    assert "--port" in combined
    assert "--db" in combined
    assert "--tunnel" in combined
    assert "--sync" in combined


# ---------------------------------------------------------------------------
# API-layer filter coverage (finding #5)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "params,expected_ids,assertion",
    [
        # source_name -- a4's source_name is TASS-Telegram (unique).
        (
            {"source_name": "TASS-Telegram"},
            {"a4"},
            lambda a: a["source_name"] == "TASS-Telegram",
        ),
        # language -- en in the fixture: a1, a6, a8.
        (
            {"language": "en"},
            {"a1", "a6", "a8"},
            lambda a: a["language"] == "en",
        ),
        # urgency_max -- classified articles with urgency <= 3: a3 (3), a7 (2).
        # Unclassified articles have NULL urgency so they are excluded.
        (
            {"urgency_max": 3},
            {"a3", "a7"},
            lambda a: a["classification"] is not None and a["classification"]["urgency_score"] <= 3,
        ),
        # event_type -- only a1 is drone_attack.
        (
            {"event_type": "drone_attack"},
            {"a1"},
            lambda a: a["classification"] is not None and a["classification"]["event_type"] == "drone_attack",
        ),
        # has_alert=true -- a1 and a2 (event ev1 had alerts).
        (
            {"has_alert": "true"},
            {"a1", "a2"},
            lambda a: a["has_alert"] is True,
        ),
        # has_alert=false -- everything else.
        (
            {"has_alert": "false"},
            {"a3", "a4", "a5", "a6", "a7", "a8", "a9"},
            lambda a: a["has_alert"] is False,
        ),
        # date_from -- only articles on/after 2026-05-21 (a1, a2, a3).
        (
            {"date_from": "2026-05-21"},
            {"a1", "a2", "a3"},
            lambda a: a["published_at"] >= "2026-05-21",
        ),
        # date_to -- only articles published on/before 2026-05-17. A bare
        # ``YYYY-MM-DD`` upper bound now expands to end-of-day at the DB
        # layer (finding #4), so this matches every row published on
        # 2026-05-17 (a7 at 04:00:00, plus a8 + a9 from earlier days).
        (
            {"date_to": "2026-05-17"},
            {"a7", "a8", "a9"},
            lambda a: a["published_at"][:10] <= "2026-05-17",
        ),
        # date_from + date_to bracket with bare dates -- a4 (2026-05-20),
        # a5 (2026-05-19). The bare date_to upper bound is inclusive of
        # the whole day.
        (
            {"date_from": "2026-05-19", "date_to": "2026-05-20"},
            {"a4", "a5"},
            lambda a: "2026-05-19" <= a["published_at"][:10] <= "2026-05-20",
        ),
    ],
    ids=[
        "source_name",
        "language",
        "urgency_max",
        "event_type",
        "has_alert_true",
        "has_alert_false",
        "date_from",
        "date_to",
        "date_range",
    ],
)
def test_api_articles_filter_each(client, params, expected_ids, assertion):
    """[1.4, 1.2b, finding #5] Each filter narrows the result set via the API.

    Exercises every single-filter wiring through the HTTP surface. A typo or
    rename in ``args.get("<name>")`` -> ``filters["<name>"]`` mapping would
    silently regress (the dict swallows None), so this is the regression
    guard for the API layer of every filter listed in spec req 1.2b.
    """
    query = "&".join(f"{k}={v}" for k, v in params.items())
    resp = client.get(f"/api/articles?{query}")
    assert resp.status_code == 200, (params, resp.get_json())
    body = resp.get_json()
    ids = {a["id"] for a in body["articles"]}
    assert ids == expected_ids, (params, ids, body["total"])
    # Every returned row really satisfies the filter (not just the count).
    for article in body["articles"]:
        assert assertion(article), (params, article)


def test_api_articles_filter_default_order(client):
    """[1.4, finding #10] One ordered-list spot check on the default sort.

    The set-equality assertions in `test_api_articles_filter_each` do not
    pin the order, so a regression that changed the default sort (e.g.
    silently sorted ascending, or used a different column) would still pass
    above. Picking one representative case (``language=pl``) and asserting
    the EXACT id ORDER under the default ``published_at desc`` locks the
    default sort at the API layer.
    """
    resp = client.get("/api/articles?language=pl")
    assert resp.status_code == 200
    body = resp.get_json()
    ids = [a["id"] for a in body["articles"]]
    # Polish fixture rows ordered by published_at DESC:
    #   a2 2026-05-22T09  > a3 2026-05-21T08  > a5 2026-05-19T06
    #   > a7 2026-05-17T04 > a9 2026-05-15T02
    assert ids == ["a2", "a3", "a5", "a7", "a9"], ids


# ---------------------------------------------------------------------------
# Stale-FTS regression (finding #1 / #7): tunnel mode must NOT use stale FTS
# ---------------------------------------------------------------------------


def test_api_tunnel_skips_stale_fts(sentinel_db_path, fts_db_path, monkeypatch, tmp_path):
    """[1.1c, finding #1/#7] Tunnel mode skips a stale local FTS DB.

    Reproduces the bug the reviewer reported: a user runs ``--sync`` (writing
    ``dashboard/data/sentinel_fts.db``), then later runs ``--tunnel``. Without
    the fix, the tunnel-fetched DB gets the STALE FTS attached and search
    returns wrong/empty results. With the fix, ``_maybe_attach_fts`` short-
    circuits in tunnel mode and search falls back to LIKE -- per spec 1.1c
    "FTS5 is not built for the temporary copy, so search falls back to LIKE."

    Builds a stale FTS DB containing only a placeholder row that does NOT
    match any article in the tunnel-fetched DB, then asserts that the search
    still returns the 4 drone matches via LIKE (proving FTS was NOT consulted).
    """
    import shutil
    import sqlite3 as sql

    from dashboard import db as db_module

    # 1. Build a stale FTS DB at the path tunnel mode SHOULD ignore.
    # The stale FTS has a single placeholder row whose article_id (`STALE_ID`)
    # is absent from the tunnel-fetched DB, so a stale-FTS join would return
    # zero hits for "drone". A LIKE fallback returns the 4 fixture matches.
    if os.path.exists(fts_db_path):
        os.remove(fts_db_path)
    fts_conn = sql.connect(fts_db_path)
    try:
        fts_conn.execute("CREATE VIRTUAL TABLE articles_fts USING fts5(article_id UNINDEXED, title, summary)")
        fts_conn.execute(
            "INSERT INTO articles_fts (article_id, title, summary) VALUES ('STALE_ID', 'stale title', 'stale summary')"
        )
        fts_conn.commit()
    finally:
        fts_conn.close()
    assert os.path.exists(fts_db_path)

    # 2. Mock subprocess.run so tunnel mode SCPs the sample DB into its temp
    # path. Tunnel mode now sees BOTH a co-located fts file (the stale one)
    # AND a freshly fetched DB -- exactly the bug condition.
    def fake_run(argv, capture_output, text, timeout):  # noqa: ARG001
        shutil.copy(sentinel_db_path, argv[-1])

        class _OK:
            returncode = 0
            stderr = ""

        return _OK()

    monkeypatch.setattr(db_module.subprocess, "run", fake_run)

    flask_app = create_app(tunnel=True, fts_db_path=fts_db_path, dev_cors=False)
    flask_app.config.update(TESTING=True)
    fresh_client = flask_app.test_client()

    # 2b. Build a request-scoped DashboardDB the same way the API does and
    # assert ``fts_available`` is False. The behavioral search assertion
    # below would still pass IF a stale FTS happened to coincidentally
    # return the right result set; this assertion guards directly against
    # any FTS attachment in tunnel mode, not just the visible effects.
    cached_path = flask_app.config["TUNNEL_TEMPFILE"]
    db_probe = DashboardDB(tunnel=True, db_path=cached_path, fts_db_path=fts_db_path)
    try:
        assert db_probe.fts_available is False, (
            "tunnel-mode DashboardDB must NOT attach the stale FTS index "
            "(per req 1.1c the temp copy has no co-located FTS)"
        )
    finally:
        db_probe.close()

    # 3. Run a search through the API. If the stale FTS were used, this would
    # match only article_id='STALE_ID' (which doesn't exist in the tunnel DB)
    # and return zero hits. With the fix, LIKE returns all 4 drone matches.
    resp = fresh_client.get("/api/articles?q=drone")
    assert resp.status_code == 200
    body = resp.get_json()
    ids = {a["id"] for a in body["articles"]}
    assert ids == {"a1", "a2", "a4", "a9"}, (
        f"tunnel-mode search should fall back to LIKE per req 1.1c "
        f"and return 4 matches; got {ids} (total={body['total']})"
    )
    assert body["total"] == 4

    # Clean up the cached tempfile.
    cleanup = flask_app.config.get("TUNNEL_CLEANUP")
    if callable(cleanup):
        cleanup()


# ---------------------------------------------------------------------------
# Tunnel-mode sync refusal (finding #8)
# ---------------------------------------------------------------------------


def test_api_sync_refused_in_tunnel_mode(sentinel_db_path, monkeypatch):
    """[finding #8] ``POST /api/sync`` returns 409 in tunnel mode.

    In tunnel mode the dashboard already fetches a fresh copy of the
    production DB at startup, and ``SENTINEL_DB_PATH`` points at the temp
    file in /tmp. Allowing /api/sync would write the sync-state JSON into
    /tmp and overwrite the temp DB. Refusing the request with HTTP 409 keeps
    the contract clear -- tunnel mode is "always fresh on startup" and the
    sync endpoint is for sync mode.
    """
    import shutil

    from dashboard import db as db_module

    def fake_run(argv, capture_output, text, timeout):  # noqa: ARG001
        shutil.copy(sentinel_db_path, argv[-1])

        class _OK:
            returncode = 0
            stderr = ""

        return _OK()

    monkeypatch.setattr(db_module.subprocess, "run", fake_run)

    flask_app = create_app(tunnel=True, dev_cors=False)
    flask_app.config.update(TESTING=True)
    tunnel_client = flask_app.test_client()

    resp = tunnel_client.post("/api/sync")
    assert resp.status_code == 409, resp.get_json()
    body = resp.get_json()
    assert "error" in body
    assert "tunnel" in body["error"].lower()

    cleanup = flask_app.config.get("TUNNEL_CLEANUP")
    if callable(cleanup):
        cleanup()


def test_api_sync_status_signals_tunnel_mode(sentinel_db_path, monkeypatch):
    """[finding #2] ``GET /api/sync/status`` flags tunnel mode in its response.

    In tunnel mode there is no persisted sync record by design (the DB is
    fetched on each startup, and ``POST /api/sync`` is refused). Returning
    a bare ``{"last_sync": null}`` would be indistinguishable from a fresh
    install where no sync has ever run -- which can mislead the dashboard
    into prompting the user to sync. The status response carries an explicit
    ``tunnel_mode: true`` flag so the client knows the null is intentional.
    """
    import shutil

    from dashboard import db as db_module

    def fake_run(argv, capture_output, text, timeout):  # noqa: ARG001
        shutil.copy(sentinel_db_path, argv[-1])

        class _OK:
            returncode = 0
            stderr = ""

        return _OK()

    monkeypatch.setattr(db_module.subprocess, "run", fake_run)

    flask_app = create_app(tunnel=True, dev_cors=False)
    flask_app.config.update(TESTING=True)
    tunnel_client = flask_app.test_client()

    resp = tunnel_client.get("/api/sync/status")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body == {"last_sync": None, "tunnel_mode": True}

    cleanup = flask_app.config.get("TUNNEL_CLEANUP")
    if callable(cleanup):
        cleanup()


# ---------------------------------------------------------------------------
# CORS disabled-mode coverage (finding #13)
# ---------------------------------------------------------------------------


def test_app_no_cors_when_disabled(sentinel_db_path, fts_db_path):
    """[1.1a, finding #13] ``create_app(dev_cors=False)`` adds no CORS header.

    The positive case is covered by ``test_app_cors_dev_mode``. This test is
    the negative-case regression guard: a refactor that broadens CORS to ``*``
    or unconditionally enables it would slip through without this assertion.
    """
    build_fts_index(sentinel_db_path, fts_db_path)
    no_cors_app = create_app(db_path=sentinel_db_path, fts_db_path=fts_db_path, dev_cors=False)
    no_cors_app.config.update(TESTING=True)
    no_cors_client = no_cors_app.test_client()

    resp = no_cors_client.get("/api/stats", headers={"Origin": "http://localhost:5173"})
    assert resp.status_code == 200
    assert "Access-Control-Allow-Origin" not in resp.headers


def test_app_cors_denies_non_vite_origin(client):
    """[1.1a, finding #13] CORS is scoped to localhost:5173, not other origins.

    A refactor that uses ``CORS(app)`` without ``resources={...origins=...}``
    would echo any Origin header. This test ensures only the Vite dev origin
    is allowed.
    """
    resp = client.get("/api/stats", headers={"Origin": "http://evil.example.com"})
    assert resp.status_code == 200
    allowed = resp.headers.get("Access-Control-Allow-Origin")
    # Either no header at all, or echoed as the Vite origin (never the attacker).
    assert allowed in (None, "http://localhost:5173")
    assert allowed != "http://evil.example.com"
    assert allowed != "*"


def test_app_cors_denies_non_vite_origin_preflight(client):
    """[1.1a, finding #13] Preflight (OPTIONS) requests from a non-Vite Origin
    are not granted CORS approval.

    A browser issues a preflight ``OPTIONS`` with ``Origin`` +
    ``Access-Control-Request-Method`` before any non-simple cross-origin
    request. The simple-GET test above misses preflight regressions, so we
    pin the preflight-denial behavior explicitly: the evil origin must not
    appear in ``Access-Control-Allow-Origin`` and the wildcard must never be
    used.
    """
    resp = client.options(
        "/api/stats",
        headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    allowed = resp.headers.get("Access-Control-Allow-Origin")
    # Either no header at all, or echoed as the Vite origin (never the attacker).
    assert allowed in (None, "http://localhost:5173"), allowed
    assert allowed != "https://evil.example.com"
    assert allowed != "*"


# ---------------------------------------------------------------------------
# Date-range validation (finding #14)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "param,value",
    [
        ("date_from", "yesterday"),
        ("date_from", "not-a-date"),
        ("date_from", "2026/05/22"),  # wrong separator
        ("date_to", "tomorrow"),
        ("date_to", "26-05-22"),  # 2-digit year
        # Calendar-impossible dates: month13, day30 of feb, hour25.
        # The previous shape-only regex let these through; the calendar-aware
        # validator now rejects them.
        ("date_to", "2026-13-01"),
        ("date_from", "2026-02-30"),
        ("date_from", "2026-05-22T25:00:00"),
    ],
    ids=[
        "from-word",
        "from-garbage",
        "from-slashes",
        "to-word",
        "to-2digit-year",
        "to-month13",
        "from-feb30",
        "from-hour25",
    ],
)
def test_api_articles_rejects_invalid_date(client, param, value):
    """[finding #14] Non-ISO ``date_from``/``date_to`` return HTTP 400.

    Spec doesn't require validation, but accepting arbitrary strings under
    lex comparison silently returns wrong-or-empty results -- a UX trap
    worth a 400. Validation goes through ``datetime.fromisoformat`` so
    calendar-impossible values (month 13, Feb 30, hour 25) are caught too.
    """
    resp = client.get(f"/api/articles?{param}={value}")
    assert resp.status_code == 400, resp.get_json()
    body = resp.get_json()
    assert "error" in body
    # Combined-error shape: ``fields`` carries the per-parameter messages,
    # so a single bad parameter shows up under its own key.
    assert "fields" in body
    assert param in body["fields"]


def test_api_articles_combines_date_field_errors(client):
    """[finding #7] Both ``date_from`` and ``date_to`` errors arrive together.

    A user with two bad dates gets ONE 400 response listing BOTH problems,
    not two round-trips. Locks the combined-error contract introduced
    alongside the calendar-aware validator.
    """
    resp = client.get("/api/articles?date_from=yesterday&date_to=tomorrow")
    assert resp.status_code == 400, resp.get_json()
    body = resp.get_json()
    assert body["error"] == "Invalid ISO date(s)"
    assert set(body["fields"].keys()) == {"date_from", "date_to"}
    # Each field carries a human-readable error mentioning the bad value.
    assert "yesterday" in body["fields"]["date_from"]
    assert "tomorrow" in body["fields"]["date_to"]


def test_api_articles_accepts_valid_iso_dates(client):
    """[finding #14] Valid ISO 8601 prefixes for date_from/date_to are accepted.

    The Werkzeug test client decodes ``+`` in query strings as a space, so we
    URL-encode the few values containing ``+`` to round-trip correctly.
    """
    from urllib.parse import quote

    valid_values = [
        "2026-05-22",
        "2026-05-22T10:00",
        "2026-05-22T10:00:00",
        "2026-05-22T10:00:00.123",
        "2026-05-22T10:00:00Z",
        "2026-05-22T10:00:00+00:00",
        "2026-05-22 10:00:00",
    ]
    for v in valid_values:
        # quote() escapes ``+`` to ``%2B`` (and leaves the colon/T alone),
        # so the value arrives at the API byte-for-byte.
        resp = client.get(f"/api/articles?date_from={quote(v, safe=':T.- ')}")
        assert resp.status_code == 200, (v, resp.get_json())
