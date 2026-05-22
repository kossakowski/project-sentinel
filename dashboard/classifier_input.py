"""Reconstruction of the text that was sent to the classifier (req 1.5a).

The production classifier builds its user prompt from a fixed 5-line block --
see ``USER_PROMPT_TEMPLATE`` and ``Classifier._build_user_prompt`` in
``sentinel/classification/classifier.py``. This module reproduces that block
so the dashboard can show the user exactly what the classifier saw alongside
what it produced.

The classifier's full prompt also wraps the block in "Analyze this article:"
plus a JSON schema and an urgency scale; the dashboard intentionally shows
just the article-specific block, which is the part that varies per article.

Field rendering, matched to the classifier:

* ``Source: {source_name} ({source_type})``
* ``Language: {language}``
* ``Published: {published_at}``  -- the classifier calls ``.isoformat()`` on
  the datetime, or uses the literal ``"unknown"`` when it is missing. The
  dashboard DB stores ``published_at`` already as an ISO 8601 string, so it is
  passed through verbatim; an empty/missing value renders as ``"unknown"``.
* ``Title: {title}``
* ``Summary: {summary}``

When ``raw_metadata.enrichment.method`` is ``heuristic`` or ``llm`` AND
``enrichment.fetched`` is falsy, the classifier appends a caution note after
the Summary line (see ``classifier.py`` lines ~245-253). The dashboard
reproduces the same note here so the reconstruction matches what the classifier
actually saw -- otherwise enrichment-flagged-but-not-fetched articles would
show a misleadingly clean input block.
"""

# Literal used by the classifier when published_at is absent.
_UNKNOWN_PUBLISHED = "unknown"

# Caution note appended by the classifier when enrichment was attempted (the
# heuristic or LLM gate flagged the article) but the body fetch failed. Kept
# byte-for-byte identical to the literal in
# ``sentinel/classification/classifier.py:_build_user_prompt`` -- if either
# string drifts, ``test_classifier_input_reconstruction`` (which extracts the
# note from the live classifier module) will fail.
ENRICHMENT_NOT_FETCHED_NOTE = (
    "Note: Article body could not be fetched. The summary above may just be "
    "the headline repeated. Exercise extreme caution with country attribution "
    "— do not assume a monitored country is affected unless explicitly stated."
)


def _needs_enrichment_note(article: dict) -> bool:
    """Return True if the classifier would have appended the caution note.

    The condition mirrors ``Classifier._build_user_prompt``: enrichment was
    attempted (method ∈ {heuristic, llm}) and the body fetch did not succeed.
    """
    raw_metadata = article.get("raw_metadata") or {}
    if not isinstance(raw_metadata, dict):
        return False
    enrichment = raw_metadata.get("enrichment") or {}
    if not isinstance(enrichment, dict):
        return False
    method = enrichment.get("method")
    if method not in ("heuristic", "llm"):
        return False
    return not enrichment.get("fetched")


def build_classifier_input(article: dict) -> str:
    """Return the classifier-input block for an article dict.

    Args:
        article: an article dict as produced by `DashboardDB.get_article_detail`
            (must contain source_name, source_type, language, published_at,
            title, summary; may contain raw_metadata with enrichment info).

    Returns:
        The reconstructed multi-line string, identical to the per-article
        block that ``Classifier._build_user_prompt`` embeds in its prompt --
        including the enrichment caution note when the article was
        enrichment-flagged but its body could not be fetched.
    """
    published = article.get("published_at") or _UNKNOWN_PUBLISHED
    summary = article.get("summary")
    if summary is None:
        summary = ""

    block = (
        f"Source: {article.get('source_name', '')} "
        f"({article.get('source_type', '')})\n"
        f"Language: {article.get('language', '')}\n"
        f"Published: {published}\n"
        f"Title: {article.get('title', '')}\n"
        f"Summary: {summary}"
    )

    if _needs_enrichment_note(article):
        block += "\n" + ENRICHMENT_NOT_FETCHED_NOTE

    return block
