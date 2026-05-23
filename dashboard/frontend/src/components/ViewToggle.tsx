// Pipeline / Analytics switcher for the overview page (req 3.1a).
//
// The active mode is stored in the URL query string (``?view=pipeline`` /
// ``?view=analytics``) by the parent OverviewPage, so the view is
// bookmarkable. This component is stateless — it just renders two buttons
// and reports the user's choice back through onChange.

export type ViewMode = "pipeline" | "analytics";

interface ViewToggleProps {
  value: ViewMode;
  onChange: (next: ViewMode) => void;
}

interface ToggleEntry {
  value: ViewMode;
  label: string;
}

const MODES: ReadonlyArray<ToggleEntry> = [
  { value: "pipeline", label: "Pipeline" },
  { value: "analytics", label: "Analytics" },
];

export function ViewToggle({ value, onChange }: ViewToggleProps) {
  return (
    <div
      className="view-toggle"
      role="tablist"
      aria-label="Overview view mode"
      data-testid="view-toggle"
    >
      {MODES.map((entry) => {
        const active = value === entry.value;
        return (
          <button
            key={entry.value}
            type="button"
            role="tab"
            aria-selected={active}
            aria-pressed={active}
            className={`view-toggle-button ${active ? "view-toggle-button-active" : ""}`}
            onClick={() => onChange(entry.value)}
            data-testid={`view-toggle-${entry.value}`}
          >
            {entry.label}
          </button>
        );
      })}
    </div>
  );
}

/** Coerce an arbitrary string (e.g. a URL query value) to a ViewMode. */
export function parseViewMode(value: string | null | undefined): ViewMode {
  return value === "analytics" ? "analytics" : "pipeline";
}
