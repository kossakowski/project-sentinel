// Pure helpers for badge / cell rendering used by ArticleTable and tests.
// Kept separate from the JSX components so the mapping can be exercised by
// unit tests without rendering a tree.

import type { AnnotationLabel, PipelineStatus } from "../types";

/** Urgency score → CSS class (req 2.2d). null/undefined → null (no class). */
export function urgencyClass(score: number | null | undefined): string | null {
  if (score === null || score === undefined) return null;
  if (score >= 9) return "urgency-critical";
  if (score >= 7) return "urgency-high";
  if (score >= 5) return "urgency-medium";
  return "urgency-low";
}

/** Urgency tier label — pairs with `urgencyClass` for chart legends + a11y. */
export type UrgencyTier = "critical" | "high" | "medium" | "low";

/** Map an urgency score to a tier name (req 3.5). */
export function urgencyTier(score: number): UrgencyTier {
  if (score >= 9) return "critical";
  if (score >= 7) return "high";
  if (score >= 5) return "medium";
  return "low";
}

/** Urgency score → hex colour for SVG fills (req 3.5).
 *
 *  Mirrors the same 1-4 / 5-6 / 7-8 / 9-10 thresholds as `urgencyClass` —
 *  recharts' SVG bars need a literal fill colour (not a CSS class), so this
 *  function returns one shade per tier. Values are chosen to be legible on
 *  the dark dashboard background and to match the dashboard palette:
 *  - 1-4 gray (#64748b), 5-6 yellow (#f59e0b), 7-8 orange (#ea580c), 9-10 red (#dc2626).
 */
export function urgencyColor(score: number): string {
  switch (urgencyTier(score)) {
    case "critical":
      return "#dc2626";
    case "high":
      return "#ea580c";
    case "medium":
      return "#f59e0b";
    case "low":
      return "#64748b";
  }
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

/** Annotation badge config — small coloured dot + label (req 4.4).
 *
 *  Green for "correct", red for "incorrect", yellow for "uncertain".
 *  Colours mirror the Tailwind 500/600 family so they read clearly on the
 *  dashboard's dark surface. `color` is the inline hex used by the dot
 *  itself (recharts-style inline fills would otherwise force a separate
 *  CSS variable per tier). */
export interface AnnotationBadgeConfig {
  label: string;
  color: string;
  className: string;
}

const ANNOTATION_BADGE: Record<AnnotationLabel, AnnotationBadgeConfig> = {
  correct: { label: "Correct", color: "#16a34a", className: "annotation-dot annotation-dot-correct" },
  incorrect: { label: "Incorrect", color: "#dc2626", className: "annotation-dot annotation-dot-incorrect" },
  uncertain: { label: "Uncertain", color: "#eab308", className: "annotation-dot annotation-dot-uncertain" },
};

/** Map an annotation label to its colour + display text (req 4.4). */
export function annotationBadge(label: AnnotationLabel): AnnotationBadgeConfig {
  return ANNOTATION_BADGE[label] ?? ANNOTATION_BADGE.uncertain;
}
