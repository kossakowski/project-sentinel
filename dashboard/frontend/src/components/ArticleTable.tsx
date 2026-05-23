import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";

import type { Article, ArticleDetail, SortColumn, SortOrder } from "../types";
import { ALL_COLUMNS, type ColumnKey } from "./columns";
import { pipelineStatusBadge, urgencyClass } from "./badges";
import { safeHref } from "../utils/safeHref";
import { ApiError, fetchArticleDetail } from "../api/client";

interface ArticleTableProps {
  articles: Article[];
  visibleColumns: ReadonlyArray<ColumnKey>;
  /** Currently sorted column. Null when no explicit sort is active — under FTS
   *  rank ordering (req 1.4c) NO column is "sorted" so the table must render
   *  NO directional indicator (spec 2.2 implies converse of "the currently
   *  sorted column MUST show a directional indicator"). */
  sort: SortColumn | null;
  /** Sort direction; null mirrors a null sort. */
  order: SortOrder | null;
  /**
   * Called when the user clicks a sortable header. The handler decides whether
   * to toggle the direction or switch column — keeping the table itself stateless
   * with respect to URL synchronisation.
   */
  onSortChange: (column: SortColumn) => void;
  /**
   * Optional empty-state node. When omitted a generic message is rendered.
   */
  emptyState?: React.ReactNode;
  /**
   * Detail-fetcher override. Defaults to `fetchArticleDetail` from the API
   * client. Exists so unit tests can inject a deterministic stub instead of
   * mocking the global `fetch` per row expansion.
   */
  fetchDetail?: (id: string, init?: RequestInit) => Promise<ArticleDetail>;
}

interface DetailEntry {
  status: "loading" | "loaded" | "error";
  data: ArticleDetail | null;
  error: string | null;
}

// Sortable columns map 1:1 to backend whitelist (see dashboard/db.py).
const SORTABLE: ReadonlyArray<ColumnKey> = [
  "published_at",
  "fetched_at",
  "title",
  "source_name",
  "urgency_score",
  "confidence",
];

/** Article list table — req 2.2 (renders + headers), 2.2a (defaults via parent),
 * 2.2b (expandable rows with raw_metadata via lazy fetch), 2.2c (linked
 * titles), 2.2d (urgency colour), 2.2e (pipeline status badge). */
export function ArticleTable({
  articles,
  visibleColumns,
  sort,
  order,
  onSortChange,
  emptyState,
  fetchDetail,
}: ArticleTableProps) {
  const location = useLocation();
  // Pass the current URL state (pathname + search) on every title-link click
  // so the detail page can render a "Back to articles" link that restores the
  // user's previous filter/sort/page (req 3.10). Stable across renders so
  // ArticleRow's React.memo opportunities aren't broken — the value only
  // changes when the URL itself changes, which is exactly when we want it to.
  const linkState = useMemo(
    () => ({ from: `${location.pathname}${location.search}` }),
    [location.pathname, location.search],
  );

  const columns = useMemo(
    () =>
      ALL_COLUMNS.filter((col) =>
        (visibleColumns as ReadonlyArray<string>).includes(col.key),
      ),
    [visibleColumns],
  );

  const [expanded, setExpanded] = useState<Set<string>>(() => new Set<string>());
  // Per-row article-detail cache. Spec 2.2b requires raw_metadata in the
  // expanded section but the list endpoint intentionally omits it for I/O.
  // We lazy-fetch the full detail on first expand and keep the result so a
  // collapse+re-expand doesn't refetch.
  const [details, setDetails] = useState<Map<string, DetailEntry>>(
    () => new Map(),
  );
  // Track in-flight requests so we can abort them on unmount. Using a ref
  // (not state) so writing here doesn't trigger an unrelated re-render.
  const controllersRef = useRef<Map<string, AbortController>>(new Map());

  // On unmount, abort every in-flight detail fetch.
  useEffect(() => {
    const controllers = controllersRef.current;
    return () => {
      for (const controller of controllers.values()) controller.abort();
      controllers.clear();
    };
  }, []);

  // Default to the real API client. Test rigs can inject a deterministic
  // fetcher via props without having to mock global fetch.
  const fetcher = fetchDetail ?? fetchArticleDetail;

  const loadDetail = useCallback(
    (id: string) => {
      // Already loaded or already in flight — skip.
      if (details.has(id)) return;
      const controller = new AbortController();
      controllersRef.current.set(id, controller);
      setDetails((prev) => {
        const next = new Map(prev);
        next.set(id, { status: "loading", data: null, error: null });
        return next;
      });
      fetcher(id, { signal: controller.signal })
        .then((detail) => {
          if (controller.signal.aborted) return;
          setDetails((prev) => {
            const next = new Map(prev);
            next.set(id, { status: "loaded", data: detail, error: null });
            return next;
          });
        })
        .catch((error: unknown) => {
          if (controller.signal.aborted) return;
          const message =
            error instanceof ApiError
              ? error.message
              : error instanceof Error
                ? error.message
                : "Unknown error";
          setDetails((prev) => {
            const next = new Map(prev);
            next.set(id, { status: "error", data: null, error: message });
            return next;
          });
        })
        .finally(() => {
          controllersRef.current.delete(id);
        });
    },
    // `details` and `fetcher` close over current state — re-create when either
    // changes so the cached-result check above always sees the latest map.
    [details, fetcher],
  );

  function toggleRow(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
        // Lazy-fetch on first expand (req 2.2b raw_metadata).
        loadDetail(id);
      }
      return next;
    });
  }

  return (
    <div className="article-table-wrapper">
      <table className="article-table" aria-label="Articles">
        <thead>
          <tr>
            <th aria-label="Expand row" className="col-expand" />
            {columns.map((col) => {
              const sortable = SORTABLE.includes(col.key);
              // Only mark a column as sorted when the user has explicitly
              // chosen one (sort prop non-null). Under FTS rank ordering the
              // table has NO sorted column, so no indicator shows anywhere.
              const isSorted = sort !== null && sort === col.key;
              const indicator = isSorted ? (order === "asc" ? "▲" : "▼") : "";
              if (!sortable) {
                return (
                  <th key={col.key} className={`col-${col.key}`}>
                    {col.label}
                  </th>
                );
              }
              return (
                <th key={col.key} className={`col-${col.key} col-sortable`}>
                  <button
                    type="button"
                    className="col-sort-button"
                    onClick={() => onSortChange(col.key as SortColumn)}
                    aria-label={`Sort by ${col.label}`}
                    aria-pressed={isSorted}
                  >
                    {col.label}
                    {indicator && (
                      <span className="col-sort-indicator">{indicator}</span>
                    )}
                  </button>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {articles.length === 0 ? (
            <tr>
              <td
                className="empty-row"
                colSpan={columns.length + 1}
                data-testid="empty-state"
              >
                {emptyState ?? "No articles match the current filters."}
              </td>
            </tr>
          ) : (
            articles.map((article) => (
              <ArticleRow
                key={article.id}
                article={article}
                columns={columns.map((c) => c.key)}
                expanded={expanded.has(article.id)}
                detail={details.get(article.id) ?? null}
                onToggle={() => toggleRow(article.id)}
                linkState={linkState}
              />
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

interface ArticleRowProps {
  article: Article;
  columns: ColumnKey[];
  expanded: boolean;
  detail: DetailEntry | null;
  onToggle: () => void;
  /** Forwarded to the title `<Link>` so the detail page can navigate back to
   *  the previously-filtered list (req 3.10). */
  linkState: { from: string };
}

function ArticleRow({
  article,
  columns,
  expanded,
  detail,
  onToggle,
  linkState,
}: ArticleRowProps) {
  return (
    <>
      <tr className="article-row" data-testid={`article-row-${article.id}`}>
        <td className="col-expand">
          <button
            type="button"
            className="row-expand-button"
            aria-expanded={expanded}
            aria-label={expanded ? "Collapse row" : "Expand row"}
            onClick={onToggle}
          >
            {expanded ? "▾" : "▸"}
          </button>
        </td>
        {columns.map((key) => (
          <td key={key} className={`col-${key} ${cellClassFor(key, article)}`}>
            {renderCell(key, article, linkState)}
          </td>
        ))}
      </tr>
      {expanded && (
        <tr className="article-row-expanded">
          <td colSpan={columns.length + 1}>
            <ArticleRowDetail article={article} detail={detail} />
          </td>
        </tr>
      )}
    </>
  );
}

function ArticleRowDetail({
  article,
  detail,
}: {
  article: Article;
  detail: DetailEntry | null;
}) {
  return (
    <div className="article-row-detail" data-testid="article-detail">
      <h4>Summary</h4>
      <p className="article-summary">{article.summary ?? "(no summary)"}</p>
      {article.classification && (
        <>
          <h4>Classification</h4>
          <dl className="classification-grid">
            <dt>Urgency</dt>
            <dd>{article.classification.urgency_score}</dd>
            <dt>Event type</dt>
            <dd>{article.classification.event_type ?? "—"}</dd>
            <dt>Confidence</dt>
            <dd>{formatConfidence(article.classification.confidence)}</dd>
            <dt>Aggressor</dt>
            <dd>{article.classification.aggressor ?? "—"}</dd>
            <dt>Affected countries</dt>
            <dd>{article.classification.affected_countries.join(", ") || "—"}</dd>
            {article.classification.summary_pl && (
              <>
                <dt>Summary (PL)</dt>
                <dd>{article.classification.summary_pl}</dd>
              </>
            )}
          </dl>
        </>
      )}
      <RawMetadataBlock detail={detail} />
      <p>
        {(() => {
          const href = safeHref(article.source_url);
          return href ? (
            <a
              className="article-source-link"
              href={href}
              target="_blank"
              rel="noopener noreferrer"
            >
              Open source ↗
            </a>
          ) : (
            <span
              className="article-source-link article-source-link-disabled"
              data-testid="article-source-link-unsafe"
            >
              {article.source_url}
            </span>
          );
        })()}
      </p>
    </div>
  );
}

/** Lazy-loaded raw_metadata block (spec req 2.2b).
 *
 *  The list endpoint omits raw_metadata to keep payloads small (db.py
 *  `_list_select_columns`), so we fetch the full detail on first expand and
 *  render the parsed JSON here. Three visible states: loading spinner,
 *  inline error, parsed key:value table. */
function RawMetadataBlock({ detail }: { detail: DetailEntry | null }) {
  if (detail === null || detail.status === "loading") {
    return (
      <>
        <h4>Raw metadata</h4>
        <p
          className="article-raw-metadata-loading"
          data-testid="article-raw-metadata-loading"
        >
          Loading metadata…
        </p>
      </>
    );
  }
  if (detail.status === "error") {
    return (
      <>
        <h4>Raw metadata</h4>
        <p
          className="article-raw-metadata-error"
          data-testid="article-raw-metadata-error"
        >
          Couldn't load metadata: {detail.error ?? "Unknown error"}
        </p>
      </>
    );
  }
  const metadata = detail.data?.raw_metadata ?? {};
  const entries = Object.entries(metadata);
  if (entries.length === 0) {
    return (
      <>
        <h4>Raw metadata</h4>
        <p data-testid="article-raw-metadata-empty">(none)</p>
      </>
    );
  }
  return (
    <>
      <h4>Raw metadata</h4>
      <pre
        className="article-raw-metadata"
        data-testid="article-raw-metadata"
      >
        {JSON.stringify(metadata, null, 2)}
      </pre>
    </>
  );
}

function cellClassFor(key: ColumnKey, article: Article): string {
  if (key === "urgency_score") {
    const cls = urgencyClass(article.classification?.urgency_score ?? null);
    return cls ?? "";
  }
  return "";
}

function renderCell(
  key: ColumnKey,
  article: Article,
  linkState: { from: string },
) {
  switch (key) {
    case "published_at":
      return formatDate(article.published_at);
    case "fetched_at":
      return formatDate(article.fetched_at);
    case "title":
      return (
        <Link
          to={`/articles/${encodeURIComponent(article.id)}`}
          state={linkState}
          className="article-title-link"
          data-testid="article-title-link"
        >
          {article.title}
        </Link>
      );
    case "source_name":
      return article.source_name;
    case "source_type":
      return article.source_type;
    case "source_url": {
      const href = safeHref(article.source_url);
      return href ? (
        <a href={href} target="_blank" rel="noopener noreferrer">
          link
        </a>
      ) : (
        <span data-testid="source-url-unsafe">{article.source_url}</span>
      );
    }
    case "language":
      return article.language.toUpperCase();
    case "urgency_score":
      return article.classification?.urgency_score ?? "—";
    case "event_type":
      return article.classification?.event_type ?? "—";
    case "confidence":
      return article.classification
        ? formatConfidence(article.classification.confidence)
        : "—";
    case "aggressor":
      return article.classification?.aggressor ?? "—";
    case "affected_countries":
      return (
        article.classification?.affected_countries.join(", ") || "—"
      );
    case "pipeline_status": {
      const cfg = pipelineStatusBadge(article.pipeline_status);
      return (
        <span className={cfg.className} data-testid="pipeline-badge">
          {cfg.label}
        </span>
      );
    }
    case "summary_pl":
      return article.classification?.summary_pl ?? "—";
    case "is_military_event":
      if (!article.classification) return "—";
      return article.classification.is_military_event ? "Yes" : "No";
    default:
      return null;
  }
}

function formatDate(iso: string): string {
  if (!iso) return "—";
  // Render only the YYYY-MM-DD HH:MM portion to keep the table compact.
  // Suffix " UTC" so users don't misread these ISO timestamps as their own
  // local time — every value in the DB is stored as UTC.
  const trimmed = iso.replace("T", " ").slice(0, 16);
  return trimmed ? `${trimmed} UTC` : iso;
}

function formatConfidence(value: number): string {
  return `${Math.round(value * 100)}%`;
}
