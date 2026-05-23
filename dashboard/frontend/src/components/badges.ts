// Pure helpers for badge / cell rendering used by ArticleTable and tests.
// Kept separate from the JSX components so the mapping can be exercised by
// unit tests without rendering a tree.

import type { PipelineStatus } from "../types";

/** Urgency score → CSS class (req 2.2d). null/undefined → null (no class). */
export function urgencyClass(score: number | null | undefined): string | null {
  if (score === null || score === undefined) return null;
  if (score >= 9) return "urgency-critical";
  if (score >= 7) return "urgency-high";
  if (score >= 5) return "urgency-medium";
  return "urgency-low";
}

/** Pipeline status → display config (req 2.2e). */
export interface BadgeConfig {
  label: string;
  className: string;
}

const PIPELINE_BADGE: Record<PipelineStatus, BadgeConfig> = {
  unclassified: { label: "Unclassified", className: "badge badge-unclassified" },
  classified: { label: "Classified", className: "badge badge-classified" },
  event_created: { label: "Event", className: "badge badge-event" },
  alert_sent: { label: "Alert", className: "badge badge-alert" },
};

export function pipelineStatusBadge(status: PipelineStatus): BadgeConfig {
  return PIPELINE_BADGE[status] ?? PIPELINE_BADGE.unclassified;
}
