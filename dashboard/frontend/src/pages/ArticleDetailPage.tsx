// Full article detail page at route ``/articles/:id`` (req 3.7, 3.10).
//
// Renders a header (title, source link, dates, language + pipeline badges),
// the ClassifierView, and the EventTimeline (when events exist). Includes a
// "Back to articles" link that round-trips the previous filter/sort/page
// state via location.state.from (set by ArticleTable's title link), falling
// back to ``/articles`` when the page was opened directly.

import { Link, useLocation, useParams } from "react-router-dom";

import { ClassifierView } from "../components/ClassifierView";
import { EventTimeline } from "../components/EventTimeline";
import { pipelineStatusBadge } from "../components/badges";
import { useArticleDetail } from "../hooks/useArticleDetail";
import { safeHref } from "../utils/safeHref";

interface LocationStateFrom {
  from?: string;
}

/** Resolve the "Back to articles" target — preserves prior filter state. */
function resolveBackTarget(state: unknown): string {
  if (
    state &&
    typeof state === "object" &&
    "from" in state &&
    typeof (state as LocationStateFrom).from === "string"
  ) {
    return (state as LocationStateFrom).from ?? "/articles";
  }
  return "/articles";
}

export function ArticleDetailPage() {
  const { id } = useParams<{ id: string }>();
  const location = useLocation();
  const backTo = resolveBackTarget(location.state);
  const { data, loading, error } = useArticleDetail(id);

  if (!id) {
    return (
      <div className="article-detail-page" data-testid="article-detail-no-id">
        <p>No article id provided.</p>
        <Link to="/articles">← Back to articles</Link>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="article-detail-page" data-testid="article-detail-loading">
        <Link
          to={backTo}
          className="article-detail-back-link"
          data-testid="article-detail-back-link"
        >
          ← Back to articles
        </Link>
        <p>Loading article…</p>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="article-detail-page" data-testid="article-detail-error">
        <Link
          to={backTo}
          className="article-detail-back-link"
          data-testid="article-detail-back-link"
        >
          ← Back to articles
        </Link>
        <p className="article-detail-error-message">
          {error
            ? `Couldn't load article: ${error.message}`
            : "Article not found."}
        </p>
      </div>
    );
  }

  const sourceHref = safeHref(data.source_url);
  const pipelineBadge = pipelineStatusBadge(data.pipeline_status);

  return (
    <div className="article-detail-page" data-testid="article-detail">
      <Link
        to={backTo}
        className="article-detail-back-link"
        data-testid="article-detail-back-link"
      >
        ← Back to articles
      </Link>

      <header
        className="article-detail-header"
        data-testid="article-detail-header"
      >
        <h1 className="article-detail-title" data-testid="article-detail-title">
          {data.title}
        </h1>
        <dl className="article-detail-meta">
          <dt>Source</dt>
          <dd>
            {sourceHref ? (
              <a
                href={sourceHref}
                target="_blank"
                rel="noopener noreferrer"
                data-testid="article-detail-source-link"
              >
                {data.source_name}
              </a>
            ) : (
              <span data-testid="article-detail-source-unsafe">
                {data.source_name}
              </span>
            )}
          </dd>
          <dt>Published</dt>
          <dd data-testid="article-detail-published">{data.published_at}</dd>
          <dt>Fetched</dt>
          <dd data-testid="article-detail-fetched">{data.fetched_at}</dd>
          <dt>Language</dt>
          <dd>
            <span
              className="article-detail-language-badge"
              data-testid="article-detail-language-badge"
            >
              {data.language.toUpperCase()}
            </span>
          </dd>
          <dt>Pipeline</dt>
          <dd>
            <span
              className={pipelineBadge.className}
              data-testid="article-detail-pipeline-badge"
            >
              {pipelineBadge.label}
            </span>
          </dd>
        </dl>
      </header>

      <ClassifierView article={data} />

      <EventTimeline events={data.events ?? []} />
    </div>
  );
}
