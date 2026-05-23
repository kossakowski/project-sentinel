// Per-source horizontal bar chart + per-language chip group (req 3.6).
//
// Sources are sorted by count descending (the backend already does this; the
// component re-sorts defensively so a future API change can't subtly break
// the layout). To keep the chart readable on dashboards with 30+ feeds we
// trim to the top N — the full table view is available on the articles page
// behind a source filter.

import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { LanguageBucket, SourceBucket } from "../types";

interface SourceBreakdownProps {
  sources: SourceBucket[];
  languages: LanguageBucket[];
  /** Maximum number of sources to render (default 15). */
  maxSources?: number;
  height?: number;
  /** Tests can set this to render BarChart directly at a fixed width
   *  (ResponsiveContainer fails in jsdom). */
  width?: number;
}

/** Sort + truncate the source list defensively. */
function topSources(sources: SourceBucket[], max: number): SourceBucket[] {
  const sorted = [...sources].sort((a, b) => b.count - a.count);
  return sorted.slice(0, max);
}

/** Total of all language counts — denominator for percentages. */
function totalCount(buckets: ReadonlyArray<{ count: number }>): number {
  return buckets.reduce((sum, b) => sum + b.count, 0);
}

export function SourceBreakdown({
  sources,
  languages,
  maxSources = 15,
  height = 360,
  width,
}: SourceBreakdownProps) {
  const top = topSources(sources, maxSources);
  const langTotal = totalCount(languages);

  const chart = (
    <BarChart
      data={top}
      layout="vertical"
      margin={{ top: 8, right: 24, left: 80, bottom: 8 }}
      width={width}
      height={height}
    >
      <CartesianGrid strokeDasharray="3 3" stroke="#334155" horizontal={false} />
      <XAxis type="number" stroke="#94a3b8" fontSize={12} allowDecimals={false} />
      <YAxis
        type="category"
        dataKey="source_name"
        stroke="#94a3b8"
        fontSize={12}
        width={120}
      />
      <Tooltip
        contentStyle={{
          background: "#1e293b",
          border: "1px solid #334155",
          color: "#e2e8f0",
        }}
        cursor={{ fill: "#1e293b88" }}
      />
      <Bar dataKey="count" fill="#60a5fa" isAnimationActive={false} />
    </BarChart>
  );

  return (
    <section
      className="source-breakdown"
      aria-label="Source and language breakdown"
      data-testid="source-breakdown"
    >
      <h3 className="overview-section-heading">Sources (top {top.length})</h3>
      {width !== undefined ? (
        chart
      ) : (
        <ResponsiveContainer width="100%" height={height}>
          {chart}
        </ResponsiveContainer>
      )}

      <h4 className="overview-subsection-heading">Languages</h4>
      <ul
        className="language-chip-group"
        aria-label="Language distribution"
        data-testid="language-chip-group"
      >
        {languages.map((bucket) => {
          const pct = langTotal === 0 ? 0 : (bucket.count / langTotal) * 100;
          return (
            <li
              key={bucket.language}
              className="language-chip"
              data-testid={`language-chip-${bucket.language}`}
            >
              <span className="language-chip-code">
                {bucket.language.toUpperCase()}
              </span>
              <span className="language-chip-pct">{pct.toFixed(1)}%</span>
              <span className="language-chip-count">
                {bucket.count.toLocaleString()}
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
