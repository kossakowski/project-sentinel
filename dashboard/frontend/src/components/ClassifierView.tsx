// Side-by-side classifier input/output view on the article detail page
// (req 3.8, 3.8a, 3.8b).
//
// Left: the verbatim text sent to Claude (article.classifier_input).
// Right: the structured classification fields, with a Raw JSON toggle to
// flip the formatted display into a JSON dump (req 3.8a).
// When the article was filtered out before classification (no classification
// row), a single "not classified" notice is rendered (req 3.8b).

import { useState } from "react";

import type { ArticleDetail } from "../types";
import { urgencyClass } from "./badges";
import { formatWarsaw } from "../utils/datetime";

interface ClassifierViewProps {
  article: ArticleDetail;
}

/** Format 0.0-1.0 confidence as a whole-percent string. */
function formatConfidence(value: number): string {
  return `${Math.round(value * 100)}%`;
}

/** Boolean → "Yes"/"No" (or "—" for nullish). */
function boolLabel(value: boolean | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return value ? "Yes" : "No";
}

export function ClassifierView({ article }: ClassifierViewProps) {
  const [showRawJson, setShowRawJson] = useState(false);
  const classification = article.classification;

  // Spec req 3.8b — unclassified articles render a single notice with a gray
  // background, not the side-by-side layout. The wording is verbatim from the
  // spec so manual QA against the spec text is straightforward.
  if (classification === null) {
    return (
      <section
        className="classifier-view classifier-view-unclassified"
        aria-label="Classifier view"
        data-testid="classifier-view-unclassified"
      >
        <p className="classifier-view-unclassified-message">
          This article was not classified (filtered out before classification stage)
        </p>
      </section>
    );
  }

  return (
    <section
      className="classifier-view"
      aria-label="Classifier view"
      data-testid="classifier-view"
    >
      <div className="classifier-view-grid">
        <div className="classifier-view-pane classifier-view-input">
          <header className="classifier-view-pane-header">
            <h3 className="classifier-view-pane-title">Classifier Input</h3>
          </header>
          <pre
            className="classifier-view-input-body"
            data-testid="classifier-view-input"
          >
            {article.classifier_input}
          </pre>
        </div>

        <div className="classifier-view-pane classifier-view-output">
          <header className="classifier-view-pane-header">
            <h3 className="classifier-view-pane-title">Classifier Output</h3>
            <button
              type="button"
              className="classifier-view-toggle"
              aria-pressed={showRawJson}
              onClick={() => setShowRawJson((prev) => !prev)}
              data-testid="classifier-view-raw-toggle"
            >
              {showRawJson ? "Formatted" : "Raw JSON"}
            </button>
          </header>

          {showRawJson ? (
            <pre
              className="classifier-view-output-body classifier-view-output-raw"
              data-testid="classifier-view-output-raw"
            >
              {JSON.stringify(classification, null, 2)}
            </pre>
          ) : (
            <dl
              className="classifier-view-output-body classifier-output-grid"
              data-testid="classifier-view-output-formatted"
            >
              <dt>Urgency</dt>
              <dd
                className={`classifier-view-urgency ${urgencyClass(classification.urgency_score) ?? ""}`}
                data-testid="classifier-view-urgency"
              >
                {classification.urgency_score}
              </dd>

              <dt>Event type</dt>
              <dd>{classification.event_type ?? "—"}</dd>

              <dt>Confidence</dt>
              <dd>{formatConfidence(classification.confidence)}</dd>

              <dt>Affected countries</dt>
              <dd>{classification.affected_countries.join(", ") || "—"}</dd>

              <dt>Aggressor</dt>
              <dd>{classification.aggressor ?? "—"}</dd>

              <dt>Military event?</dt>
              <dd>{boolLabel(classification.is_military_event)}</dd>

              <dt>New event?</dt>
              <dd>{boolLabel(classification.is_new_event)}</dd>

              <dt>Summary (PL)</dt>
              <dd>{classification.summary_pl ?? "—"}</dd>

              <dt>Model</dt>
              <dd>{classification.model_used}</dd>

              <dt>Tokens (in/out)</dt>
              <dd>
                {classification.input_tokens ?? "—"} /{" "}
                {classification.output_tokens ?? "—"}
              </dd>

              <dt>Classified at</dt>
              <dd>{formatWarsaw(classification.classified_at)}</dd>
            </dl>
          )}
        </div>
      </div>
    </section>
  );
}
