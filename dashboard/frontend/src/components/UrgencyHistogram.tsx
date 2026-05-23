// Urgency-score distribution bar chart (req 3.5).
//
// One bar per urgency score 1-10, coloured by the same thresholds as the
// table cells (req 2.2d). Backend zero-fills missing buckets so the chart
// always has the full 1-10 range.

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { UrgencyBucket } from "../types";
import { urgencyColor, urgencyTier } from "./badges";

interface UrgencyHistogramProps {
  data: UrgencyBucket[];
  height?: number;
  /** Set this to render the BarChart directly at the given width instead of
   *  ResponsiveContainer (jsdom can't measure parents, so tests need fixed
   *  pixel sizing). */
  width?: number;
}

interface ChartPoint {
  urgency_score: number;
  count: number;
  color: string;
  tier: string;
}

function preparePoints(buckets: UrgencyBucket[]): ChartPoint[] {
  return buckets.map((bucket) => ({
    urgency_score: bucket.urgency_score,
    count: bucket.count,
    color: urgencyColor(bucket.urgency_score),
    tier: urgencyTier(bucket.urgency_score),
  }));
}

export function UrgencyHistogram({
  data,
  height = 280,
  width,
}: UrgencyHistogramProps) {
  const points = preparePoints(data);

  const chart = (
    <BarChart
      data={points}
      margin={{ top: 16, right: 16, left: 8, bottom: 8 }}
      width={width}
      height={height}
    >
      <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
      <XAxis
        dataKey="urgency_score"
        stroke="#94a3b8"
        fontSize={12}
        label={{
          value: "Urgency score",
          position: "insideBottom",
          offset: -4,
          fill: "#94a3b8",
        }}
      />
      <YAxis stroke="#94a3b8" fontSize={12} allowDecimals={false} />
      <Tooltip
        contentStyle={{
          background: "#1e293b",
          border: "1px solid #334155",
          color: "#e2e8f0",
        }}
        cursor={{ fill: "#1e293b88" }}
      />
      <Bar dataKey="count" isAnimationActive={false}>
        {points.map((point) => (
          <Cell
            key={point.urgency_score}
            fill={point.color}
            data-testid={`urgency-bar-${point.urgency_score}`}
          />
        ))}
      </Bar>
    </BarChart>
  );

  return (
    <section
      className="urgency-histogram"
      aria-label="Urgency score distribution"
      data-testid="urgency-histogram"
    >
      <h3 className="overview-section-heading">Urgency distribution</h3>
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
