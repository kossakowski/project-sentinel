// Overview page — landing route ``/`` (req 3.1).
//
// Composition:
//   StatsCards (4 KPIs)
//   ViewToggle (Pipeline | Analytics)  -> URL-synced via ?view=
//   In "pipeline" mode:  PipelineFunnel + TimeSeriesChart
//   In "analytics" mode: UrgencyHistogram + SourceBreakdown
//
// All data comes from one /api/stats round-trip via useStats.

import { useCallback } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { PipelineFunnel } from "../components/PipelineFunnel";
import { SourceBreakdown } from "../components/SourceBreakdown";
import { StatsCards } from "../components/StatsCards";
import { TimeSeriesChart } from "../components/TimeSeriesChart";
import { UrgencyHistogram } from "../components/UrgencyHistogram";
import {
  ViewToggle,
  parseViewMode,
  type ViewMode,
} from "../components/ViewToggle";
import { useStats } from "../hooks/useStats";

export function OverviewPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const view = parseViewMode(searchParams.get("view"));

  const { data: stats, loading, error } = useStats();

  // Update the URL ?view= parameter on toggle so the chosen mode is
  // bookmarkable and survives a reload (req 3.1a).
  const onViewChange = useCallback(
    (next: ViewMode) => {
      setSearchParams(
        (prev) => {
          const params = new URLSearchParams(prev);
          if (next === "pipeline") {
            // Default mode — keep the URL short.
            params.delete("view");
          } else {
            params.set("view", next);
          }
          return params;
        },
        { replace: false },
      );
    },
    [setSearchParams],
  );

  return (
    <div className="overview-page" data-testid="overview-page">
      <header className="overview-page-header">
        <h1>Overview</h1>
        <nav className="overview-page-nav" aria-label="Dashboard sections">
          <Link
            to="/articles"
            className="overview-page-nav-link"
            data-testid="overview-nav-articles"
          >
            Browse articles →
          </Link>
        </nav>
      </header>

      {loading && !stats && (
        <p className="overview-page-loading" data-testid="overview-loading">
          Loading stats…
        </p>
      )}

      {error && !stats && (
        <p
          className="overview-page-error"
          data-testid="overview-error"
        >
          Failed to load stats: {error.message}
        </p>
      )}

      {stats && (
        <>
          <StatsCards stats={stats} />

          <ViewToggle value={view} onChange={onViewChange} />

          {view === "pipeline" ? (
            <div className="overview-grid" data-testid="overview-pipeline">
              <PipelineFunnel funnel={stats.pipeline_funnel} />
              <TimeSeriesChart
                collected={stats.articles_per_day}
                classified={stats.classified_per_day}
              />
            </div>
          ) : (
            <div className="overview-grid" data-testid="overview-analytics">
              <UrgencyHistogram data={stats.urgency_distribution} />
              <SourceBreakdown
                sources={stats.source_distribution}
                languages={stats.language_distribution}
              />
            </div>
          )}
        </>
      )}
    </div>
  );
}
