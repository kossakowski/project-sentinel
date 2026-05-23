// Pipeline funnel for the overview page (req 3.3, 3.3a).
//
// Renders the four pipeline stages as a clean horizontal bar list rather
// than recharts' <FunnelChart>: with only four stages and a click-to-filter
// requirement, a simple bar list is more accessible (real links, real
// keyboard focus) and avoids the SVG-event-listener pitfalls of clicking
// individual funnel cells. Each row navigates to the articles page filtered
// to that pipeline stage (req 3.3a). The "Collected" row navigates to the
// full unfiltered list (every article was collected).

import { Link } from "react-router-dom";

import type { PipelineFunnel as PipelineFunnelData } from "../types";

interface PipelineFunnelProps {
  funnel: PipelineFunnelData;
}

interface Stage {
  key: keyof PipelineFunnelData;
  label: string;
  /** Target route — Collected has no filter, others filter by status. */
  to: string;
  /** Test selector. */
  testId: string;
}

const STAGES: ReadonlyArray<Stage> = [
  { key: "collected", label: "Collected", to: "/articles", testId: "funnel-stage-collected" },
  {
    key: "classified",
    label: "Classified",
    to: "/articles?pipeline_status=classified",
    testId: "funnel-stage-classified",
  },
  {
    key: "events_created",
    label: "Events Created",
    to: "/articles?pipeline_status=event_created",
    testId: "funnel-stage-events_created",
  },
  {
    key: "alerts_sent",
    label: "Alerts Sent",
    to: "/articles?pipeline_status=alert_sent",
    testId: "funnel-stage-alerts_sent",
  },
];

/** Percentage of ``part`` relative to ``whole`` with one decimal place. */
function percentageOf(part: number, whole: number): string {
  if (whole === 0) return "0.0%";
  return `${((part / whole) * 100).toFixed(1)}%`;
}

/** Bar width as a percentage of the collected stage (always 100% for collected). */
function widthPercent(value: number, max: number): number {
  if (max === 0) return 0;
  return (value / max) * 100;
}

export function PipelineFunnel({ funnel }: PipelineFunnelProps) {
  const collected = funnel.collected;
  return (
    <section
      className="pipeline-funnel"
      aria-label="Pipeline funnel"
      data-testid="pipeline-funnel"
    >
      <h3 className="overview-section-heading">Pipeline funnel</h3>
      <ul className="pipeline-funnel-list">
        {STAGES.map((stage) => {
          const count = funnel[stage.key];
          const width = widthPercent(count, collected);
          const pct = percentageOf(count, collected);
          return (
            <li key={stage.key} className="pipeline-funnel-row">
              <Link
                to={stage.to}
                className="pipeline-funnel-link"
                data-testid={stage.testId}
                aria-label={`${stage.label}: ${count.toLocaleString()} articles (${pct} of collected)`}
              >
                <div className="pipeline-funnel-label">
                  <span className="pipeline-funnel-name">{stage.label}</span>
                  <span className="pipeline-funnel-count">
                    {count.toLocaleString()}{" "}
                    <span className="pipeline-funnel-pct">({pct} of collected)</span>
                  </span>
                </div>
                <div className="pipeline-funnel-bar-track" aria-hidden="true">
                  <div
                    className={`pipeline-funnel-bar pipeline-funnel-bar-${stage.key}`}
                    style={{ width: `${width}%` }}
                  />
                </div>
              </Link>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
