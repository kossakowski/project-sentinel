import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import type { Article, SortColumn, SortOrder } from "../types";
import { ALL_COLUMNS, type ColumnKey } from "./columns";
import { pipelineStatusBadge, urgencyClass } from "./badges";
import { safeHref } from "../utils/safeHref";

interface ArticleTableProps {
  articles: Article[];
  visibleColumns: ReadonlyArray<ColumnKey>;
  sort: SortColumn;
  order: SortOrder;
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
 * 2.2b (expandable rows), 2.2c (linked titles), 2.2d (urgency colour),
 * 2.2e (pipeline status badge). */
export function ArticleTable({
  articles,
  visibleColumns,
  sort,
  order,
  onSortChange,
  emptyState,
}: ArticleTableProps) {
  const columns = useMemo(
    () =>
      ALL_COLUMNS.filter((col) =>
        (visibleColumns as ReadonlyArray<string>).includes(col.key),
      ),
    [visibleColumns],
  );

  const [expanded, setExpanded] = useState<Set<string>>(() => new Set<string>());

  function toggleRow(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
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
              const isSorted = sort === col.key;
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
                onToggle={() => toggleRow(article.id)}
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
  onToggle: () => void;
}

function ArticleRow({ article, columns, expanded, onToggle }: ArticleRowProps) {
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
            {renderCell(key, article)}
          </td>
        ))}
      </tr>
      {expanded && (
        <tr className="article-row-expanded">
          <td colSpan={columns.length + 1}>
            <ArticleRowDetail article={article} />
          </td>
        </tr>
      )}
    </>
  );
}

function ArticleRowDetail({ article }: { article: Article }) {
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
            <dd>{article.classification.event_type}</dd>
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

function cellClassFor(key: ColumnKey, article: Article): string {
  if (key === "urgency_score") {
    const cls = urgencyClass(article.classification?.urgency_score ?? null);
    return cls ?? "";
  }
  return "";
}

function renderCell(key: ColumnKey, article: Article) {
  switch (key) {
    case "published_at":
      return formatDate(article.published_at);
    case "fetched_at":
      return formatDate(article.fetched_at);
    case "title":
      return (
        <Link
          to={`/articles/${article.id}`}
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
  const trimmed = iso.replace("T", " ").slice(0, 16);
  return trimmed || iso;
}

function formatConfidence(value: number): string {
  return `${Math.round(value * 100)}%`;
}
