"""Tests for the annotation system (Phase 4).

Covers `dashboard.annotations.AnnotationDB`, the `/api/annotations` endpoints,
and the annotation-aware extensions to `/api/articles` + `/api/stats`. Each
test uses ``tmp_path`` to isolate both the sentinel DB and the annotations DB
so test parallelism is safe.

Test naming follows the SPEC's acceptance-test list (Phase 4) verbatim so spec
gates trace cleanly to the assertion that backs them.
"""

import os

import pytest

from dashboard.annotations import AnnotationDB, AnnotationValidationError
from dashboard.app import create_app
from dashboard.db import DashboardDB
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
def annotations_db_path(tmp_path):
    """Path for the annotations DB (auto-created on first AnnotationDB open)."""
    return str(tmp_path / "annotations.db")


@pytest.fixture
def annotation_db(annotations_db_path):
    """A fresh, write-capable `AnnotationDB` over the tmp annotations file."""
    db = AnnotationDB(db_path=annotations_db_path)
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def app(sentinel_db_path, annotations_db_path):
    """Flask app wired to BOTH the tmp sentinel DB and tmp annotations DB."""
    flask_app = create_app(
        db_path=sentinel_db_path,
        annotations_db_path=annotations_db_path,
        dev_cors=False,
    )
    flask_app.config.update(TESTING=True)
    return flask_app


@pytest.fixture
def client(app):
    """Flask test client for the wired app."""
    return app.test_client()


# ---------------------------------------------------------------------------
# Acceptance test #1 — DB auto-create (req 4.1, 4.1a)
# ---------------------------------------------------------------------------


def test_annotation_db_auto_create(tmp_path):
    """[4.1, 4.1a] AnnotationDB creates the file + ``annotations`` table on first use."""
    db_path = str(tmp_path / "nested" / "subdir" / "annotations.db")
    assert not os.path.exists(db_path)

    db = AnnotationDB(db_path=db_path)
    try:
        # File exists after construction.
        assert os.path.exists(db_path)

        # The annotations table exists with the spec-mandated columns.
        cur = db.conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='annotations'")
        assert cur.fetchone() is not None

        cols = {row["name"] for row in db.conn.execute("PRAGMA table_info(annotations)").fetchall()}
        assert cols == {
            "id",
            "article_id",
            "label",
            "expected_urgency",
            "notes",
            "created_at",
            "updated_at",
        }

        # Fresh DB starts empty.
        assert db.conn.execute("SELECT COUNT(*) FROM annotations").fetchone()[0] == 0
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Acceptance test #2 — upsert preserves created_at, updates updated_at (req 4.1b)
# ---------------------------------------------------------------------------


def test_annotation_upsert(annotation_db):
    """[4.1b] Creating an annotation twice for the same article updates in place."""
    first = annotation_db.upsert("a1", label="correct", expected_urgency=5, notes="initial")
    assert first["article_id"] == "a1"
    assert first["label"] == "correct"
    assert first["expected_urgency"] == 5
    assert first["notes"] == "initial"
    first_id = first["id"]
    first_created = first["created_at"]
    first_updated = first["updated_at"]

    # Re-upsert with different values — same article_id.
    second = annotation_db.upsert("a1", label="incorrect", expected_urgency=9, notes="revised")

    # The annotation table still holds exactly one row for a1.
    count = annotation_db.conn.execute("SELECT COUNT(*) FROM annotations WHERE article_id = ?", ("a1",)).fetchone()[0]
    assert count == 1

    # The id + created_at are preserved (the user is editing, not recreating).
    assert second["id"] == first_id
    assert second["created_at"] == first_created
    # The label / urgency / notes are refreshed.
    assert second["label"] == "incorrect"
    assert second["expected_urgency"] == 9
    assert second["notes"] == "revised"
    # ``updated_at`` may equal ``first_updated`` when the clock has not ticked
    # within the same microsecond, but it must NEVER move backwards.
    assert second["updated_at"] >= first_updated


def test_annotation_upsert_handles_nulls(annotation_db):
    """[4.1] expected_urgency=None and notes=None round-trip cleanly."""
    saved = annotation_db.upsert("a2", label="uncertain", expected_urgency=None, notes=None)
    assert saved["expected_urgency"] is None
    assert saved["notes"] is None
    fetched = annotation_db.get("a2")
    assert fetched is not None
    assert fetched["expected_urgency"] is None
    assert fetched["notes"] is None


def test_annotation_upsert_rejects_bad_input(annotation_db):
    """[4.1] Validation runs at the DB layer so callers can't sneak past."""
    with pytest.raises(AnnotationValidationError):
        annotation_db.upsert("a1", label="bogus")
    with pytest.raises(AnnotationValidationError):
        annotation_db.upsert("a1", label="correct", expected_urgency=0)
    with pytest.raises(AnnotationValidationError):
        annotation_db.upsert("a1", label="correct", expected_urgency=11)
    # Boolean is rejected even though Python treats it as int.
    with pytest.raises(AnnotationValidationError):
        annotation_db.upsert("a1", label="correct", expected_urgency=True)


# ---------------------------------------------------------------------------
# Acceptance tests #3-#9 — API: POST / GET / DELETE / validation
# ---------------------------------------------------------------------------


def test_create_annotation(client):
    """[4.2] POST /api/annotations creates and returns the saved annotation."""
    resp = client.post(
        "/api/annotations",
        json={
            "article_id": "a1",
            "label": "correct",
            "expected_urgency": 6,
            "notes": "Seems right but a bit conservative",
        },
    )
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    for key in ("id", "article_id", "label", "expected_urgency", "notes", "created_at", "updated_at"):
        assert key in body, f"missing field: {key}"
    assert body["article_id"] == "a1"
    assert body["label"] == "correct"
    assert body["expected_urgency"] == 6
    assert body["notes"] == "Seems right but a bit conservative"

    # A second POST for the same article id behaves as upsert (req 4.1b).
    resp2 = client.post(
        "/api/annotations",
        json={
            "article_id": "a1",
            "label": "incorrect",
            "expected_urgency": 9,
            "notes": "On reflection, urgency is too low",
        },
    )
    assert resp2.status_code == 200
    body2 = resp2.get_json()
    # Same id (id preserved on upsert).
    assert body2["id"] == body["id"]
    assert body2["label"] == "incorrect"
    # Created_at preserved; updated_at refreshed (or at least non-decreasing).
    assert body2["created_at"] == body["created_at"]
    assert body2["updated_at"] >= body["updated_at"]


def test_create_annotation_missing_article_id(client):
    """[4.2] POST without article_id returns HTTP 400."""
    resp = client.post("/api/annotations", json={"label": "correct"})
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_get_annotation(client):
    """[4.2a] GET /api/annotations/<article_id> returns the existing annotation."""
    client.post("/api/annotations", json={"article_id": "a1", "label": "uncertain"})
    resp = client.get("/api/annotations/a1")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["article_id"] == "a1"
    assert body["label"] == "uncertain"


def test_get_annotation_404(client):
    """[4.2a] GET returns HTTP 404 with an error message for unknown article."""
    resp = client.get("/api/annotations/nonexistent")
    assert resp.status_code == 404
    body = resp.get_json()
    assert "error" in body


def test_list_annotations_with_filter(client):
    """[4.2b] GET /api/annotations?label=incorrect returns only that label."""
    client.post("/api/annotations", json={"article_id": "a1", "label": "correct", "expected_urgency": 5})
    client.post("/api/annotations", json={"article_id": "a2", "label": "incorrect", "expected_urgency": 4})
    client.post("/api/annotations", json={"article_id": "a3", "label": "uncertain"})

    # No filter -> all three.
    full = client.get("/api/annotations").get_json()
    assert full["total"] == 3
    assert {a["article_id"] for a in full["annotations"]} == {"a1", "a2", "a3"}

    # Filter by label.
    incorrect = client.get("/api/annotations?label=incorrect").get_json()
    assert incorrect["total"] == 1
    assert incorrect["annotations"][0]["article_id"] == "a2"
    assert incorrect["annotations"][0]["label"] == "incorrect"

    # Article context (title + urgency) is joined in from the sentinel DB.
    # a2's title in the fixture is "Drony nad Polska wykryte przez wojsko".
    assert incorrect["annotations"][0]["article_title"] == "Drony nad Polska wykryte przez wojsko"
    assert incorrect["annotations"][0]["article_urgency_score"] == 7  # c2 urgency

    # Invalid label query param -> 400.
    bad = client.get("/api/annotations?label=garbage")
    assert bad.status_code == 400


def test_list_annotations_sort_default_updated_at_desc(client):
    """[4.2b] Default sort is updated_at desc — most recent first."""
    client.post("/api/annotations", json={"article_id": "a1", "label": "correct"})
    client.post("/api/annotations", json={"article_id": "a2", "label": "uncertain"})
    # Touch a1 again so it becomes the most recently updated.
    client.post("/api/annotations", json={"article_id": "a1", "label": "incorrect"})

    resp = client.get("/api/annotations?sort=updated_at&order=desc")
    body = resp.get_json()
    # a1 was updated last so it MUST come first under default ordering.
    assert body["annotations"][0]["article_id"] == "a1"


def test_delete_annotation(client):
    """[4.2c] DELETE removes the annotation and returns HTTP 204."""
    client.post("/api/annotations", json={"article_id": "a1", "label": "correct"})
    resp = client.delete("/api/annotations/a1")
    assert resp.status_code == 204
    # Body is empty per HTTP 204 contract.
    assert resp.data == b""

    # Subsequent GET returns 404.
    resp = client.get("/api/annotations/a1")
    assert resp.status_code == 404

    # Idempotent: deleting again still returns 204.
    resp = client.delete("/api/annotations/a1")
    assert resp.status_code == 204


def test_annotation_label_validation(client):
    """[4.2d] Invalid label -> HTTP 400 with {"error": "Invalid label"}."""
    resp = client.post(
        "/api/annotations",
        json={"article_id": "a1", "label": "not-a-real-label"},
    )
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["error"] == "Invalid label"


def test_annotation_urgency_validation(client):
    """[4.2e] Out-of-range or non-integer urgency -> HTTP 400."""
    # Too low.
    resp = client.post(
        "/api/annotations",
        json={"article_id": "a1", "label": "correct", "expected_urgency": 0},
    )
    assert resp.status_code == 400
    # Too high.
    resp = client.post(
        "/api/annotations",
        json={"article_id": "a1", "label": "correct", "expected_urgency": 11},
    )
    assert resp.status_code == 400
    # Non-int.
    resp = client.post(
        "/api/annotations",
        json={"article_id": "a1", "label": "correct", "expected_urgency": "five"},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Acceptance tests #12, #13 — annotation-aware articles API (req 4.5, 4.5a)
# ---------------------------------------------------------------------------


def test_articles_include_annotation(client):
    """[4.5] GET /api/articles includes an `annotation` field per article (null when absent)."""
    # Pre-create an annotation on a1.
    client.post(
        "/api/annotations",
        json={"article_id": "a1", "label": "correct", "expected_urgency": 8, "notes": "match"},
    )

    resp = client.get("/api/articles")
    assert resp.status_code == 200
    body = resp.get_json()

    by_id = {a["id"]: a for a in body["articles"]}

    # Annotated article carries the three-field shape.
    assert by_id["a1"]["annotation"] is not None
    assert set(by_id["a1"]["annotation"].keys()) == {"label", "expected_urgency", "notes"}
    assert by_id["a1"]["annotation"]["label"] == "correct"
    assert by_id["a1"]["annotation"]["expected_urgency"] == 8
    assert by_id["a1"]["annotation"]["notes"] == "match"

    # Unannotated articles carry null (not absent).
    assert by_id["a2"]["annotation"] is None
    assert by_id["a5"]["annotation"] is None


def test_article_detail_includes_annotation(client):
    """[4.5] Article detail endpoint also surfaces the annotation field."""
    client.post(
        "/api/annotations",
        json={"article_id": "a1", "label": "incorrect", "expected_urgency": 4},
    )
    resp = client.get("/api/articles/a1")
    body = resp.get_json()
    assert body["annotation"] is not None
    assert body["annotation"]["label"] == "incorrect"
    assert body["annotation"]["expected_urgency"] == 4

    # Article without annotation -> field present as null.
    resp = client.get("/api/articles/a2")
    body = resp.get_json()
    assert body["annotation"] is None


def test_articles_filter_by_annotation(client):
    """[4.5a] ?has_annotation and ?annotation_label filter via SQL — pagination respects them."""
    # Annotate a1=correct, a2=incorrect; leave the other 7 unannotated.
    client.post("/api/annotations", json={"article_id": "a1", "label": "correct"})
    client.post("/api/annotations", json={"article_id": "a2", "label": "incorrect"})

    # has_annotation=true -> only a1 and a2.
    annotated = client.get("/api/articles?has_annotation=true").get_json()
    assert annotated["total"] == 2
    assert {a["id"] for a in annotated["articles"]} == {"a1", "a2"}

    # has_annotation=false -> everything else.
    unannotated = client.get("/api/articles?has_annotation=false").get_json()
    assert unannotated["total"] == 7
    assert "a1" not in {a["id"] for a in unannotated["articles"]}
    assert "a2" not in {a["id"] for a in unannotated["articles"]}

    # annotation_label=correct -> just a1.
    only_correct = client.get("/api/articles?annotation_label=correct").get_json()
    assert only_correct["total"] == 1
    assert only_correct["articles"][0]["id"] == "a1"

    # annotation_label=incorrect -> just a2.
    only_incorrect = client.get("/api/articles?annotation_label=incorrect").get_json()
    assert only_incorrect["total"] == 1
    assert only_incorrect["articles"][0]["id"] == "a2"

    # Filtering composes with pagination — even at the smallest allowed
    # page size (25) the total respects the annotation filter so the
    # frontend never paginates over the unfiltered count.
    paginated = client.get("/api/articles?has_annotation=true&page=1&page_size=25").get_json()
    assert paginated["total"] == 2
    assert paginated["page_size"] == 25
    assert paginated["total_pages"] == 1
    assert len(paginated["articles"]) == 2


def test_articles_filter_composes_with_pipeline_status(client):
    """[4.5a] Annotation filter ANDs with other filters (pagination still correct)."""
    client.post("/api/annotations", json={"article_id": "a1", "label": "correct"})
    client.post("/api/annotations", json={"article_id": "a5", "label": "correct"})

    # a1 is classified+alert; a5 is unclassified. Combined filter narrows to a5.
    resp = client.get("/api/articles?annotation_label=correct&pipeline_status=unclassified")
    body = resp.get_json()
    assert body["total"] == 1
    assert body["articles"][0]["id"] == "a5"


# ---------------------------------------------------------------------------
# Acceptance test #14 — annotation stats (req 4.6)
# ---------------------------------------------------------------------------


def test_annotation_stats(client):
    """[4.6] /api/stats includes annotation counts and average urgency deviation."""
    # Empty state: stats present, total=0, deviation=null.
    empty_stats = client.get("/api/stats").get_json()
    assert "annotation_stats" in empty_stats
    assert empty_stats["annotation_stats"]["total"] == 0
    assert empty_stats["annotation_stats"]["by_label"] == {
        "correct": 0,
        "incorrect": 0,
        "uncertain": 0,
    }
    assert empty_stats["annotation_stats"]["average_urgency_deviation"] is None

    # Add annotations:
    # a1 has classification urgency=9; user says 5 -> deviation 4.
    # a2 has classification urgency=7; user says 4 -> deviation 3.
    # a5 is unclassified; deviation row excluded (no classification urgency).
    client.post("/api/annotations", json={"article_id": "a1", "label": "incorrect", "expected_urgency": 5})
    client.post("/api/annotations", json={"article_id": "a2", "label": "correct", "expected_urgency": 4})
    client.post("/api/annotations", json={"article_id": "a5", "label": "uncertain", "expected_urgency": 6})
    # a3 has classification but no expected_urgency on the annotation -> excluded from deviation.
    client.post("/api/annotations", json={"article_id": "a3", "label": "correct"})

    populated = client.get("/api/stats").get_json()
    stats = populated["annotation_stats"]
    assert stats["total"] == 4
    assert stats["by_label"] == {"correct": 2, "incorrect": 1, "uncertain": 1}
    # Deviation = mean(|9-5|, |7-4|) = mean(4, 3) = 3.5.
    assert stats["average_urgency_deviation"] == pytest.approx(3.5)


# ---------------------------------------------------------------------------
# Edge cases — annotations DB unavailable (fresh install / corruption)
# ---------------------------------------------------------------------------


def test_articles_with_no_annotations_db(sentinel_db_path, tmp_path):
    """No annotations.db file present -> every article's annotation is null and stats are zeroed."""
    nonexistent = str(tmp_path / "never_created.db")
    assert not os.path.exists(nonexistent)
    db = DashboardDB(db_path=sentinel_db_path, annotations_db_path=nonexistent)
    try:
        assert db.annotations_available is False
        articles = db.get_articles()
        for art in articles["articles"]:
            assert art["annotation"] is None
        stats = db.get_stats()
        assert stats["annotation_stats"]["total"] == 0
        assert stats["annotation_stats"]["by_label"] == {"correct": 0, "incorrect": 0, "uncertain": 0}
        assert stats["annotation_stats"]["average_urgency_deviation"] is None
    finally:
        db.close()


def test_filter_with_no_annotations_db_returns_empty(sentinel_db_path, tmp_path):
    """has_annotation=true with no annotations DB returns zero rows (sane fallback)."""
    nonexistent = str(tmp_path / "never_created.db")
    db = DashboardDB(db_path=sentinel_db_path, annotations_db_path=nonexistent)
    try:
        result = db.get_articles(filters={"has_annotation": True})
        assert result["total"] == 0
        # And the converse should match everything.
        result_false = db.get_articles(filters={"has_annotation": False})
        assert result_false["total"] == 9
    finally:
        db.close()


def test_search_with_annotation_filter(sentinel_db_path, annotations_db_path):
    """Search + annotation_label composes correctly under the LIKE path."""
    ann_db = AnnotationDB(db_path=annotations_db_path)
    try:
        # Two of the "drone" articles get annotated, one each label.
        ann_db.upsert("a1", label="correct")
        ann_db.upsert("a4", label="incorrect")
    finally:
        ann_db.close()

    db = DashboardDB(db_path=sentinel_db_path, annotations_db_path=annotations_db_path)
    try:
        result = db.search_articles("drone", filters={"annotation_label": "correct"})
        # a1, a2, a4, a9 mention drone — only a1 is labelled correct.
        assert result["total"] == 1
        assert result["articles"][0]["id"] == "a1"
    finally:
        db.close()


def test_annotation_persists_across_dashboard_db_reopen(sentinel_db_path, annotations_db_path):
    """Annotations written via AnnotationDB are visible through DashboardDB on a fresh open."""
    with AnnotationDB(db_path=annotations_db_path) as ann_db:
        ann_db.upsert("a1", label="uncertain", expected_urgency=7, notes="needs review")

    db = DashboardDB(db_path=sentinel_db_path, annotations_db_path=annotations_db_path)
    try:
        detail = db.get_article_detail("a1")
        assert detail is not None
        assert detail["annotation"] == {
            "label": "uncertain",
            "expected_urgency": 7,
            "notes": "needs review",
        }
    finally:
        db.close()
