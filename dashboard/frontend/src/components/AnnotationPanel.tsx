// Annotation panel rendered on the article detail page (Phase 4, req 4.3).
//
// Three controls:
//   * Label selector — Correct, Incorrect, Uncertain (req 4.3, 4.3a).
//   * Expected urgency — number input 1-10 (or blank for "no opinion").
//   * Notes — free-text textarea.
//
// Behaviour:
//   * On submit, POST /api/annotations via useAnnotation().save (req 4.3b).
//   * On success, the form stays on screen with the saved values pre-filled
//     and a "Last updated" timestamp surfaces (req 4.3a).
//   * Delete button only appears when an annotation already exists, and
//     gates the request behind a window.confirm() prompt (req 4.3c).

import { useEffect, useState } from "react";

import type { Annotation, AnnotationLabel } from "../types";
import { useAnnotation } from "../hooks/useAnnotations";
import { annotationBadge } from "./badges";
import { formatWarsaw } from "../utils/datetime";

interface AnnotationPanelProps {
  articleId: string;
  /** Server-loaded annotation passed by the parent. `null` when no annotation
   *  exists yet; `undefined` when the parent did not pre-load (the hook
   *  fetches itself in that case). */
  initialAnnotation?: Annotation | null;
  /** Test seam — defaults to window.confirm so the panel works out of the
   *  box without forcing every test to stub `window.confirm`. */
  confirmDelete?: (message: string) => boolean;
}

interface FormState {
  label: AnnotationLabel;
  urgencyInput: string;
  notes: string;
}

const LABEL_OPTIONS: ReadonlyArray<{
  value: AnnotationLabel;
  display: string;
  icon: string;
}> = [
  { value: "correct", display: "Correct", icon: "✓" },
  { value: "incorrect", display: "Incorrect", icon: "✗" },
  { value: "uncertain", display: "Uncertain", icon: "?" },
];

const DEFAULT_FORM: FormState = { label: "correct", urgencyInput: "", notes: "" };

/** Hydrate the form state from an existing annotation (req 4.3a). */
function formFromAnnotation(annotation: Annotation | null): FormState {
  if (!annotation) return DEFAULT_FORM;
  return {
    label: annotation.label,
    urgencyInput:
      annotation.expected_urgency === null || annotation.expected_urgency === undefined
        ? ""
        : String(annotation.expected_urgency),
    notes: annotation.notes ?? "",
  };
}

/** Validate the urgency input. Returns the parsed int (or null when blank),
 *  or a string error message. Mirrors the backend's 1-10 range so the user
 *  sees the same constraint client-side without waiting for the API to 400. */
function parseUrgency(raw: string): number | null | string {
  const trimmed = raw.trim();
  if (trimmed === "") return null;
  // Reject anything that's not a base-10 integer.
  if (!/^-?\d+$/.test(trimmed)) return "Urgency must be an integer 1-10.";
  const n = parseInt(trimmed, 10);
  if (Number.isNaN(n) || n < 1 || n > 10) return "Urgency must be an integer 1-10.";
  return n;
}

export function AnnotationPanel({
  articleId,
  initialAnnotation,
  confirmDelete = (msg) => window.confirm(msg),
}: AnnotationPanelProps) {
  const { annotation, loading, saving, error, save, remove } = useAnnotation(
    articleId,
    initialAnnotation,
  );
  const [form, setForm] = useState<FormState>(() => formFromAnnotation(annotation));
  const [localError, setLocalError] = useState<string | null>(null);
  const [justSaved, setJustSaved] = useState(false);

  // Whenever the server-side annotation changes (initial load, save, or
  // delete), re-hydrate the form so the displayed values stay in sync with
  // the persisted state. Without this, deleting wouldn't visually clear
  // the inputs and the next save would reuse stale notes.
  useEffect(() => {
    setForm(formFromAnnotation(annotation));
  }, [annotation]);

  // Clear the "just saved" indicator after a moment so the success badge
  // doesn't linger forever — but keep the form populated.
  useEffect(() => {
    if (!justSaved) return;
    const timer = setTimeout(() => setJustSaved(false), 2500);
    return () => clearTimeout(timer);
  }, [justSaved]);

  const hasAnnotation = annotation !== null;

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLocalError(null);
    const urgency = parseUrgency(form.urgencyInput);
    if (typeof urgency === "string") {
      // Client-side validation failure: never round-trip a payload the
      // backend will reject anyway.
      setLocalError(urgency);
      return;
    }
    const saved = await save({
      label: form.label,
      expected_urgency: urgency,
      notes: form.notes.trim() === "" ? null : form.notes,
    });
    if (saved) setJustSaved(true);
  }

  async function onDelete() {
    if (!hasAnnotation) return;
    const ok = confirmDelete("Delete this annotation? This cannot be undone.");
    if (!ok) return;
    await remove();
    setLocalError(null);
    setJustSaved(false);
  }

  return (
    <section
      className="annotation-panel"
      aria-label="Annotation"
      data-testid="annotation-panel"
    >
      <header className="annotation-panel-header">
        <h3 className="overview-section-heading">Annotation</h3>
        {hasAnnotation && annotation && (
          <span
            className="annotation-panel-updated"
            data-testid="annotation-panel-updated"
          >
            Last updated {formatWarsaw(annotation.updated_at)}
          </span>
        )}
      </header>

      {loading ? (
        <p data-testid="annotation-panel-loading">Loading annotation…</p>
      ) : (
        <form
          className="annotation-panel-form"
          onSubmit={onSubmit}
          // noValidate so our JS validator owns user-facing errors rather
          // than the browser silently blocking submission on type=number
          // min/max constraints (which would deliver no visible feedback).
          noValidate
          data-testid="annotation-panel-form"
        >
          <fieldset className="annotation-panel-label-group">
            <legend className="annotation-panel-label-legend">Label</legend>
            <div className="annotation-panel-label-buttons" role="radiogroup">
              {LABEL_OPTIONS.map((option) => {
                const cfg = annotationBadge(option.value);
                const selected = form.label === option.value;
                return (
                  <button
                    key={option.value}
                    type="button"
                    role="radio"
                    aria-checked={selected}
                    className={`annotation-panel-label-button ${
                      selected ? "annotation-panel-label-button-selected" : ""
                    }`}
                    style={selected ? { borderColor: cfg.color, color: cfg.color } : undefined}
                    onClick={() => setForm((prev) => ({ ...prev, label: option.value }))}
                    data-testid={`annotation-panel-label-${option.value}`}
                  >
                    <span aria-hidden="true">{option.icon}</span>{" "}
                    <span>{option.display}</span>
                  </button>
                );
              })}
            </div>
          </fieldset>

          <label className="annotation-panel-field">
            <span className="annotation-panel-field-label">
              Expected urgency (1-10)
            </span>
            <input
              type="number"
              min={1}
              max={10}
              step={1}
              value={form.urgencyInput}
              onChange={(event) =>
                setForm((prev) => ({ ...prev, urgencyInput: event.target.value }))
              }
              placeholder="leave blank for no opinion"
              data-testid="annotation-panel-urgency"
              className="annotation-panel-input"
            />
          </label>

          <label className="annotation-panel-field">
            <span className="annotation-panel-field-label">Notes</span>
            <textarea
              value={form.notes}
              onChange={(event) =>
                setForm((prev) => ({ ...prev, notes: event.target.value }))
              }
              rows={4}
              placeholder="Free-text notes…"
              data-testid="annotation-panel-notes"
              className="annotation-panel-textarea"
            />
          </label>

          {localError && (
            <p
              className="annotation-panel-error"
              role="alert"
              data-testid="annotation-panel-local-error"
            >
              {localError}
            </p>
          )}

          {error && (
            <p
              className="annotation-panel-error"
              role="alert"
              data-testid="annotation-panel-server-error"
            >
              {error.message}
            </p>
          )}

          {justSaved && (
            <p
              className="annotation-panel-success"
              role="status"
              data-testid="annotation-panel-success"
            >
              Annotation saved.
            </p>
          )}

          <div className="annotation-panel-actions">
            <button
              type="submit"
              className="annotation-panel-save"
              disabled={saving}
              data-testid="annotation-panel-save"
            >
              {saving ? "Saving…" : hasAnnotation ? "Update annotation" : "Save annotation"}
            </button>
            {hasAnnotation && (
              <button
                type="button"
                className="annotation-panel-delete"
                onClick={onDelete}
                disabled={saving}
                data-testid="annotation-panel-delete"
              >
                Delete annotation
              </button>
            )}
          </div>
        </form>
      )}
    </section>
  );
}
