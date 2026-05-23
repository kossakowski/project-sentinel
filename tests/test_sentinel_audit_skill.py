"""Tests for the `/sentinel-audit` skill's SKILL.md structural contents.

The sentinel-audit skill is an LLM prompt rather than executable Python, so its
acceptance tests are structural string-presence checks against the markdown
file. Phase 3 of SPEC_ALERT_GROUPING.md changes the per-article iteration in
the report to group by `event_id`; these tests assert the grouping, ordering,
and JSON-array parsing documentation are all present, and that the unchanged
keyword-filter (Step 2) and source-health (Step 4) sections were preserved.

Runnable from the project root: `.venv/bin/pytest tests/test_sentinel_audit_skill.py -v`.
"""

from pathlib import Path

import pytest

_SKILL_MD_PATH = Path(__file__).resolve().parent.parent / ".claude" / "skills" / "sentinel-audit" / "SKILL.md"


@pytest.fixture(scope="module")
def skill_md_text() -> str:
    """Read the SKILL.md once per test module."""
    assert _SKILL_MD_PATH.exists(), f"Expected SKILL.md at {_SKILL_MD_PATH}"
    return _SKILL_MD_PATH.read_text(encoding="utf-8")


def test_skill_md_documents_event_grouping(skill_md_text: str) -> None:
    """SKILL.md must document event-grouped iteration and the per-event block layout.

    Asserts every required literal separately so the failure message identifies
    which substring was missing.
    """
    required_literals = [
        "event_id",
        "events.article_ids",
        "Standalone classified articles",
    ]
    for literal in required_literals:
        assert literal in skill_md_text, (
            f"SKILL.md is missing the literal string {literal!r}; "
            "Phase 3 requires it for the event-grouped audit report."
        )

    # Per-event block layout: the spec says each event-block shows event_id
    # (8-char prefix), event_type, urgency_score, affected_countries,
    # source_count, first_seen_at -> last_updated_at span, alert_status, then
    # a bullet list of articles (title, source_name, published_at). Assert the
    # distinctive layout terms are all present.
    layout_terms = [
        "8-char prefix",
        "event_type",
        "urgency_score",
        "affected_countries",
        "source_count",
        "first_seen_at",
        "last_updated_at",
        "alert_status",
    ]
    for term in layout_terms:
        assert term in skill_md_text, (
            f"SKILL.md is missing the per-event block layout term {term!r}; "
            "Phase 3 requires every event block to document this field."
        )


def test_skill_md_documents_ordering(skill_md_text: str) -> None:
    """SKILL.md must state event blocks are ordered urgency_score desc, then first_seen_at desc."""
    # Flatten newlines so a single ordering sentence that wraps across lines
    # still matches as one window.
    normalized = skill_md_text.replace("\n", " ")
    assert "urgency_score" in normalized, "ordering sentence must reference urgency_score"
    assert "first_seen_at" in normalized, "ordering sentence must reference first_seen_at"

    # Walk every `urgency_score` occurrence and check whether the surrounding
    # ~400-char window also describes descending order with first_seen_at as
    # the secondary key. A 400-char window comfortably contains a sentence
    # like "ordered by `urgency_score` descending then `first_seen_at` desc".
    found_ordering_sentence = False
    needle = "urgency_score"
    cursor = 0
    while True:
        idx = normalized.find(needle, cursor)
        if idx < 0:
            break
        window = normalized[idx : idx + 400]
        if "first_seen_at" in window and ("descending" in window or "desc" in window):
            found_ordering_sentence = True
            break
        cursor = idx + 1
    assert found_ordering_sentence, (
        "SKILL.md must contain a sentence stating event blocks are ordered by "
        "`urgency_score` descending then `first_seen_at` descending."
    )


def test_skill_md_preserves_unchanged_sections(skill_md_text: str) -> None:
    """SKILL.md must still contain the keyword-filter (Step 2) and source-health (Step 4) sections."""
    # Distinctive phrases from Step 2 (keyword filter audit).
    step2_phrases = [
        "Keyword filter audit",
        "MISSED",
    ]
    for phrase in step2_phrases:
        assert phrase in skill_md_text, (
            f"SKILL.md is missing the Step 2 keyword-filter phrase {phrase!r}; Phase 3 must not modify Step 2."
        )

    # Distinctive phrases from Step 4 (source health check).
    step4_phrases = [
        "Source health check",
    ]
    for phrase in step4_phrases:
        assert phrase in skill_md_text, (
            f"SKILL.md is missing the Step 4 source-health phrase {phrase!r}; Phase 3 must not modify Step 4."
        )

    # The audit-timestamp logic in Step 0 / Step 6 must be untouched, so the
    # `.last-audit-timestamp` filename string MUST still be present.
    assert ".last-audit-timestamp" in skill_md_text, (
        "SKILL.md is missing the `.last-audit-timestamp` reference; Phase 3 must not change the audit timestamp logic."
    )

    # The output format obligation (single markdown file in the existing
    # location) must remain — verify the report-path template is still here.
    assert "data/audit-reports/audit-" in skill_md_text, (
        "SKILL.md is missing the audit-report path template; Phase 3 must not change the output file location."
    )


def test_skill_md_documents_json_array_format(skill_md_text: str) -> None:
    """SKILL.md must mention either SQLite `json_each` or a Python `json.loads` parse."""
    assert "json_each" in skill_md_text or "json.loads" in skill_md_text, (
        "SKILL.md must document either the SQLite `json_each` extension or a "
        "Python-side `json.loads` parse for the `events.article_ids` JSON array."
    )
