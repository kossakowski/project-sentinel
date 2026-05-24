// Full event detail page at route ``/events/:id``
// (SPEC_ALERT_GROUPING.md req 2.4, 2.5).
//
// Renders three blocks:
//   1. Event metadata header (id, type, urgency badge, affected countries
//      chips, aggressor, summary_pl, first/last seen, source count,
//      alert status)
//   2. Article list — every member article with title (Link to
//      ``/articles/:id``), source_name, published_at, language, urgency
//      badge. Ordered by ``published_at`` ASC (spec 2.5b).
//   3. Alert timeline — every ``alert_record`` with sent_at, alert_type,
//      status, and a 200-char-truncated message_body that expands on click
//      (spec 2.5c). Ordered by sent_at ASC.
//
// Spec 2.5d: the "← Back" link uses React Router's ``navigate(-1)`` so it
// respects browser history semantics rather than a hardcoded path.

import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { urgencyClass } from "../components/badges";
import { useEventDetail } from "../hooks/useEventDetail";
import type { AlertRecord, Article } from "../types";
import { formatWarsaw } from "../utils/datetime";

/** Max characters of message_body shown before the "expand" toggle (spec 2.5c). */
const MESSAGE_BODY_PREVIEW_LIMIT = 200;

export function EventDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { data, loading, error } = useEventDetail(id);

  // Spec 2.5d — history-based back navigation. Wrapped in a callback so the
  // button can render whether the page is loading, errored, or rendered.
  const handleBack = () => navigate(-1);

  if (!id) {
    return (
      <div className="event-detail-page" data-testid="event-detail-no-id">
        <BackButton onClick={handleBack} />
        <p>No event id provided.</p>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="event-detail-page" data-testid="event-detail-loading">
        <BackButton onClick={handleBack} />
        <p>Loading event…</p>
      </div>
    );
  }

  // 404 -> spec 2.4b not-found UI. Other errors -> generic error block.
  if (error || !data) {
    const isNotFound = error?.status === 404;
    return (
      <div
        className="event-detail-page"
        data-testid={isNotFound ? "event-detail-not-found" : "event-detail-error"}
      >
        <BackButton onClick={handleBack} />
        <h2>{isNotFound ? "Event not found" : "Couldn't load event"}</h2>
        <p className="event-detail-error-message">
          {error
            ? isNotFound
              ? `No event with id ${id}.`
              : `Couldn't load event: ${error.message}`
            : "Event not found."}
        </p>
      </div>
    );
  }

  const urgencyBadgeClass = urgencyClass(data.urgency_score) ?? "";

  return (
    <div className="event-detail-page" data-testid="event-detail">
      <BackButton onClick={handleBack} />

      <header className="event-detail-header" data-testid="event-detail-header">
        <h1 className="event-detail-title" data-testid="event-detail-title">
          Event {data.id.slice(0, 8)}
        </h1>
        <dl className="event-detail-meta">
          <dt>Event ID</dt>
          <dd data-testid="event-detail-id">{data.id}</dd>
          <dt>Event type</dt>
          <dd data-testid="event-detail-type">{data.event_type}</dd>
          <dt>Urgency</dt>
          <dd>
            <span
              className={`event-detail-urgency-badge ${urgencyBadgeClass}`}
              data-testid="event-detail-urgency"
            >
              Urgency {data.urgency_score}
            </span>
          </dd>
          <dt>Affected countries</dt>
          <dd data-testid="event-detail-countries">
            {data.affected_countries.length === 0 ? (
              "—"
            ) : (
              <span className="event-detail-country-chips">
                {data.affected_countries.map((country) => (
                  <span
                    key={country}
                    className="event-detail-country-chip"
                    data-testid={`event-detail-country-${country}`}
                  >
                    {country}
                  </span>
                ))}
              </span>
            )}
          </dd>
          <dt>Aggressor</dt>
          <dd data-testid="event-detail-aggressor">{data.aggressor ?? "—"}</dd>
          <dt>Summary (PL)</dt>
          <dd data-testid="event-detail-summary">{data.summary_pl}</dd>
          <dt>First seen</dt>
          <dd data-testid="event-detail-first-seen">{formatWarsaw(data.first_seen_at)}</dd>
          <dt>Last updated</dt>
          <dd data-testid="event-detail-last-updated">{formatWarsaw(data.last_updated_at)}</dd>
          <dt>Source count</dt>
          <dd data-testid="event-detail-source-count">{data.source_count}</dd>
          <dt>Alert status</dt>
          <dd>
            <span
              className="event-detail-alert-status"
              data-testid="event-detail-alert-status"
            >
              {data.alert_status}
            </span>
          </dd>
        </dl>
      </header>

      <EventArticlesList articles={data.articles} />
      <AlertTimelineSection records={data.alert_records} />
    </div>
  );
}

function BackButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      className="event-detail-back-link"
      onClick={onClick}
      data-testid="event-detail-back-link"
    >
      ← Back
    </button>
  );
}

/** Section: every article in the event (spec 2.5b). */
function EventArticlesList({ articles }: { articles: Article[] }) {
  if (articles.length === 0) {
    return (
      <section
        className="event-detail-articles"
        aria-label="Event articles"
        data-testid="event-detail-articles-empty"
      >
        <h2 className="overview-section-heading">Articles in this event</h2>
        <p>No articles linked to this event.</p>
      </section>
    );
  }

  return (
    <section
      className="event-detail-articles"
      aria-label="Event articles"
      data-testid="event-detail-articles"
    >
      <h2 className="overview-section-heading">
        Articles in this event ({articles.length})
      </h2>
      <ul className="event-detail-articles-list">
        {articles.map((article) => {
          const urgency = article.classification?.urgency_score;
          const urgencyCls = urgency != null ? urgencyClass(urgency) : null;
          return (
            <li
              key={article.id}
              className="event-detail-article"
              data-testid={`event-detail-article-${article.id}`}
            >
              <Link
                to={`/articles/${encodeURIComponent(article.id)}`}
                className="event-detail-article-title"
                data-testid={`event-detail-article-link-${article.id}`}
              >
                {article.title}
              </Link>
              <dl className="event-detail-article-meta">
                <dt>Source</dt>
                <dd>{article.source_name}</dd>
                <dt>Published</dt>
                <dd>{formatWarsaw(article.published_at)}</dd>
                <dt>Language</dt>
                <dd>{article.language.toUpperCase()}</dd>
                {urgency != null && (
                  <>
                    <dt>Urgency</dt>
                    <dd>
                      <span
                        className={`event-detail-article-urgency ${urgencyCls ?? ""}`}
                      >
                        {urgency}
                      </span>
                    </dd>
                  </>
                )}
              </dl>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/** Section: alert timeline (spec 2.5c).
 *
 *  Each record shows sent_at, alert_type, status, and a 200-char preview of
 *  message_body. Records with longer bodies render an "Expand" toggle that
 *  reveals the full text in place. */
function AlertTimelineSection({ records }: { records: AlertRecord[] }) {
  if (records.length === 0) {
    return (
      <section
        className="event-detail-alert-timeline"
        aria-label="Alert timeline"
        data-testid="event-detail-alert-timeline-empty"
      >
        <h2 className="overview-section-heading">Alert timeline</h2>
        <p>No alert records.</p>
      </section>
    );
  }

  return (
    <section
      className="event-detail-alert-timeline"
      aria-label="Alert timeline"
      data-testid="event-detail-alert-timeline"
    >
      <h2 className="overview-section-heading">Alert timeline</h2>
      <ol className="event-detail-alert-timeline-list">
        {records.map((record) => (
          <AlertTimelineRow key={record.id} record={record} />
        ))}
      </ol>
    </section>
  );
}

function AlertTimelineRow({ record }: { record: AlertRecord }) {
  const [expanded, setExpanded] = useState(false);
  const body = record.message_body ?? "";
  const isLong = body.length > MESSAGE_BODY_PREVIEW_LIMIT;
  const visible = expanded || !isLong ? body : body.slice(0, MESSAGE_BODY_PREVIEW_LIMIT);

  return (
    <li
      className="event-detail-alert-timeline-item"
      data-testid={`event-detail-alert-${record.id}`}
    >
      <header className="event-detail-alert-timeline-header">
        <span className="event-detail-alert-timeline-sent">{formatWarsaw(record.sent_at)}</span>
        <span className="event-detail-alert-timeline-type">{record.alert_type}</span>
        <span className="event-detail-alert-timeline-status">{record.status}</span>
      </header>
      {body ? (
        <>
          <p
            className="event-detail-alert-timeline-body"
            data-testid={`event-detail-alert-body-${record.id}`}
          >
            {visible}
            {isLong && !expanded && "…"}
          </p>
          {isLong && (
            <button
              type="button"
              className="event-detail-alert-timeline-expand"
              onClick={() => setExpanded((prev) => !prev)}
              data-testid={`event-detail-alert-expand-${record.id}`}
            >
              {expanded ? "Collapse" : "Expand"}
            </button>
          )}
        </>
      ) : (
        <p className="event-detail-alert-timeline-body" data-testid={`event-detail-alert-body-${record.id}`}>
          (no message)
        </p>
      )}
    </li>
  );
}
