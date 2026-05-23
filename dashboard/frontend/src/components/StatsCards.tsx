// Four KPI cards across the top of the overview page (req 3.2).
//
// Each card shows a primary number plus a small contextual line — daily
// average for total articles, % of total for classifications, "this DB" for
// events/alerts. The cards intentionally don't fetch anything themselves; the
// containing page passes the StatsResponse so all overview widgets share one
// /api/stats round-trip.

import type { StatsResponse } from "../types";

interface StatsCardsProps {
  stats: StatsResponse;
}

/** Format a count with thousand separators in the user's locale. */
function formatNumber(value: number): string {
  return value.toLocaleString();
}

/** Compute the mean of the per-day series (the 30-day rolling average). */
function dailyAverage(perDay: ReadonlyArray<{ count: number }>): number {
  if (perDay.length === 0) return 0;
  const total = perDay.reduce((sum, entry) => sum + entry.count, 0);
  return total / perDay.length;
}

/** Percentage of ``part`` relative to ``whole`` with one decimal place. */
function percentage(part: number, whole: number): string {
  if (whole === 0) return "0.0%";
  return `${((part / whole) * 100).toFixed(1)}%`;
}

interface CardProps {
  label: string;
  primary: string;
  secondary: string;
  testId: string;
}

function StatCard({ label, primary, secondary, testId }: CardProps) {
  return (
    <div className="stats-card" data-testid={testId}>
      <div className="stats-card-label">{label}</div>
      <div className="stats-card-primary">{primary}</div>
      <div className="stats-card-secondary">{secondary}</div>
    </div>
  );
}

export function StatsCards({ stats }: StatsCardsProps) {
  const avgPerDay = dailyAverage(stats.articles_per_day);
  return (
    <div className="stats-cards" data-testid="stats-cards">
      <StatCard
        label="Total Articles"
        primary={formatNumber(stats.total_articles)}
        secondary={`${avgPerDay.toFixed(0)} / day (30-day avg)`}
        testId="stats-card-articles"
      />
      <StatCard
        label="Total Classified"
        primary={formatNumber(stats.total_classified)}
        secondary={`${percentage(stats.total_classified, stats.total_articles)} of total`}
        testId="stats-card-classified"
      />
      <StatCard
        label="Total Events"
        primary={formatNumber(stats.total_events)}
        secondary={`${formatNumber(stats.pipeline_funnel.events_created)} articles reached events`}
        testId="stats-card-events"
      />
      <StatCard
        label="Total Alerts"
        primary={formatNumber(stats.total_alerts)}
        secondary={`${formatNumber(stats.pipeline_funnel.alerts_sent)} articles triggered alerts`}
        testId="stats-card-alerts"
      />
    </div>
  );
}
