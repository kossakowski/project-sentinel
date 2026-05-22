"""Reconstruction of the text that was sent to the classifier (req 1.5a).

The production classifier builds its user prompt from a fixed 5-line block --
see ``USER_PROMPT_TEMPLATE`` and ``Classifier._build_user_prompt`` in
``sentinel/classification/classifier.py``. This module reproduces ONLY that
5-line block so the dashboard can show the user exactly what the classifier
saw alongside what it produced.

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
"""

# Literal used by the classifier when published_at is absent.
_UNKNOWN_PUBLISHED = "unknown"


def build_classifier_input(article: dict) -> str:
    """Return the 5-line classifier-input block for an article dict.

    Args:
        article: an article dict as produced by `DashboardDB.get_article_detail`
            (must contain source_name, source_type, language, published_at,
            title, summary).

    Returns:
        The reconstructed multi-line string, identical to the per-article
        block that ``Classifier._build_user_prompt`` embeds in its prompt.
    """
    published = article.get("published_at") or _UNKNOWN_PUBLISHED
    summary = article.get("summary")
    if summary is None:
        summary = ""

    return (
        f"Source: {article.get('source_name', '')} "
        f"({article.get('source_type', '')})\n"
        f"Language: {article.get('language', '')}\n"
        f"Published: {published}\n"
        f"Title: {article.get('title', '')}\n"
        f"Summary: {summary}"
    )
