// Last-30-days articles-per-day line chart (req 3.4, 3.4a, 3.4b).
//
// Two series — total articles collected, and the subset that reached
// classification. Both come from /api/stats and are point-aligned by date
// (the backend builds the same 30-day calendar for both), so an index-by-
// index merge here is safe.

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { ArticlesPerDay } from "../types";

interface TimeSeriesChartProps {
  collected: ArticlesPerDay[];
  classified: ArticlesPerDay[];
  /** Fixed chart height — production uses ResponsiveContainer for width;
   *  this prop exists so tests can shrink the canvas. */
  height?: number;
  /** When set, render the LineChart directly at this width instead of
   *  wrapping in ResponsiveContainer. Used by tests because jsdom can't
   *  measure the parent and ResponsiveContainer collapses to 0×0. */
  width?: number;
}

interface MergedPoint {
  date: string;
  collected: number;
  classified: number;
}

function mergeSeries(
  collected: ArticlesPerDay[],
  classified: ArticlesPerDay[],
): MergedPoint[] {
  // Build a date → classified-count lookup so we don't assume the arrays are
  // perfectly aligned. The backend produces them aligned (same 30-day loop),
  // but defensive coding here makes the chart safe against any future drift.
  const classifiedByDate = new Map<string, number>();
  for (const entry of classified) {
    classifiedByDate.set(entry.date, entry.count);
  }
  return collected.map((entry) => ({
    date: entry.date,
    collected: entry.count,
    classified: classifiedByDate.get(entry.date) ?? 0,
  }));
}

/** Trim YYYY-MM-DD to MM-DD for tick labels (less crowded on x-axis). */
function shortDate(date: string): string {
  return date.length >= 10 ? date.slice(5) : date;
}

export function TimeSeriesChart({
  collected,
  classified,
  height = 280,
  width,
}: TimeSeriesChartProps) {
  const data = mergeSeries(collected, classified);

  const chart = (
    <LineChart
      data={data}
      margin={{ top: 16, right: 24, left: 8, bottom: 8 }}
      width={width}
      height={height}
    >
      <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
      <XAxis
        dataKey="date"
        tickFormatter={shortDate}
        stroke="#94a3b8"
        fontSize={12}
      />
      <YAxis stroke="#94a3b8" fontSize={12} allowDecimals={false} />
      <Tooltip
        contentStyle={{
          background: "#1e293b",
          border: "1px solid #334155",
          color: "#e2e8f0",
        }}
        labelStyle={{ color: "#94a3b8" }}
      />
      <Legend wrapperStyle={{ color: "#e2e8f0" }} />
      <Line
        type="monotone"
        dataKey="collected"
        name="Collected"
        stroke="#60a5fa"
        strokeWidth={2}
        dot={false}
        isAnimationActive={false}
      />
      <Line
        type="monotone"
        dataKey="classified"
        name="Classified"
        stroke="#fbbf24"
        strokeWidth={2}
        dot={false}
        isAnimationActive={false}
      />
    </LineChart>
  );

  return (
    <section
      className="time-series-chart"
      aria-label="Articles per day"
      data-testid="time-series-chart"
    >
      <h3 className="overview-section-heading">Articles per day (last 30 days)</h3>
      {width !== undefined ? (
        chart
      ) : (
        <ResponsiveContainer width="100%" height={height}>
          {chart}
        </ResponsiveContainer>
      )}
    </section>
  );
}
