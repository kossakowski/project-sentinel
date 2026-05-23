// Inline annotation badge for the article table (req 4.4).
//
// Tiny presentational component: a coloured circle + the label text.
// Green = correct, red = incorrect, yellow = uncertain. When the article has
// no annotation, the parent renders nothing — passing `null` here is also
// safe (returns an em dash placeholder for the cell renderer).

import type { ArticleAnnotation } from "../types";
import { annotationBadge } from "./badges";

interface AnnotationBadgeProps {
  annotation: ArticleAnnotation | null;
  /** Render a compact dot-only badge (default) or the dot + label text. */
  compact?: boolean;
}

/** Per-row annotation indicator (req 4.4). Returns an em dash when no
 *  annotation exists so the table cell never collapses to whitespace. */
export function AnnotationBadge({ annotation, compact = true }: AnnotationBadgeProps) {
  if (!annotation) {
    return (
      <span className="annotation-empty" data-testid="annotation-badge-empty">
        —
      </span>
    );
  }
  const cfg = annotationBadge(annotation.label);
  return (
    <span
      className={`annotation-badge annotation-badge-${annotation.label}`}
      title={cfg.label}
      data-testid={`annotation-badge-${annotation.label}`}
      data-annotation-label={annotation.label}
    >
      <span
        className={cfg.className}
        // Inline style keeps the colour wired to the spec mapping even when
        // the dashboard's CSS file hasn't been customised by the user.
        style={{ backgroundColor: cfg.color }}
        aria-hidden="true"
      />
      {!compact && <span className="annotation-badge-label">{cfg.label}</span>}
    </span>
  );
}
