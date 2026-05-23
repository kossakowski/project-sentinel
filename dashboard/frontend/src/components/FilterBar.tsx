import type { ChangeEvent } from "react";
import { useEffect, useRef, useState } from "react";

export interface FilterState {
  // Multi-select (req 2.4): each selected source contributes a repeated
  // ``?source_name=`` URL param and the backend AND-s with the rest of the
  // filters via SQL ``IN (?, ?, ...)``.
  source_names: string[];
  source_type: string;
  language: string;
  urgency_min: string;
  urgency_max: string;
  date_from: string;
  date_to: string;
  event_type: string;
  has_alert: boolean;
}

export const EMPTY_FILTERS: FilterState = {
  source_names: [],
  source_type: "",
  language: "",
  urgency_min: "",
  urgency_max: "",
  date_from: "",
  date_to: "",
  event_type: "",
  has_alert: false,
};

interface FilterBarProps {
  value: FilterState;
  /** Lists of options sourced from /api/stats so the user picks real values. */
  sourceOptions: string[];
  eventTypeOptions: string[];
  onChange: (next: FilterState) => void;
  onClear: () => void;
}

const SOURCE_TYPES: ReadonlyArray<{ value: string; label: string }> = [
  { value: "", label: "All" },
  { value: "rss", label: "RSS" },
  { value: "google_news", label: "Google News" },
  { value: "telegram", label: "Telegram" },
];

const LANGUAGES: ReadonlyArray<{ value: string; label: string }> = [
  { value: "", label: "All" },
  { value: "pl", label: "PL" },
  { value: "en", label: "EN" },
  { value: "uk", label: "UK" },
];

/** Filter form for the articles page (req 2.4). Filters take effect on every
 *  change — no "Apply" button (req 2.4a). URL syncing is owned by the parent. */
export function FilterBar({
  value,
  sourceOptions,
  eventTypeOptions,
  onChange,
  onClear,
}: FilterBarProps) {
  function setField<K extends keyof FilterState>(key: K, next: FilterState[K]) {
    onChange({ ...value, [key]: next });
  }

  function handleInput(key: keyof FilterState) {
    return (event: ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
      setField(key, event.target.value as FilterState[typeof key]);
    };
  }

  function handleCheckbox(event: ChangeEvent<HTMLInputElement>) {
    setField("has_alert", event.target.checked);
  }

  function handleSourceToggle(source: string) {
    const present = value.source_names.includes(source);
    const next = present
      ? value.source_names.filter((s) => s !== source)
      : [...value.source_names, source];
    setField("source_names", next);
  }

  return (
    <div className="filter-bar" role="group" aria-label="Filter articles">
      <div className="filter-bar-row">
        <SourceMultiSelect
          selected={value.source_names}
          options={sourceOptions}
          onToggle={handleSourceToggle}
        />

        <label className="filter-field">
          <span>Source type</span>
          <select
            value={value.source_type}
            onChange={handleInput("source_type")}
            data-testid="filter-source-type"
          >
            {SOURCE_TYPES.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </label>

        <label className="filter-field">
          <span>Language</span>
          <select
            value={value.language}
            onChange={handleInput("language")}
            data-testid="filter-language"
          >
            {LANGUAGES.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </label>

        <label className="filter-field">
          <span>Event type</span>
          <select
            value={value.event_type}
            onChange={handleInput("event_type")}
            data-testid="filter-event-type"
          >
            <option value="">All</option>
            {eventTypeOptions.map((opt) => (
              <option key={opt} value={opt}>
                {opt}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="filter-bar-row">
        <label className="filter-field">
          <span>Urgency min</span>
          <input
            type="number"
            min={1}
            max={10}
            value={value.urgency_min}
            onChange={handleInput("urgency_min")}
            data-testid="filter-urgency-min"
          />
        </label>

        <label className="filter-field">
          <span>Urgency max</span>
          <input
            type="number"
            min={1}
            max={10}
            value={value.urgency_max}
            onChange={handleInput("urgency_max")}
            data-testid="filter-urgency-max"
          />
        </label>

        <label className="filter-field">
          <span>Date from</span>
          <input
            type="date"
            value={value.date_from}
            onChange={handleInput("date_from")}
            data-testid="filter-date-from"
          />
        </label>

        <label className="filter-field">
          <span>Date to</span>
          <input
            type="date"
            value={value.date_to}
            onChange={handleInput("date_to")}
            data-testid="filter-date-to"
          />
        </label>

        <label className="filter-field filter-field-checkbox">
          <input
            type="checkbox"
            checked={value.has_alert}
            onChange={handleCheckbox}
            data-testid="filter-has-alert"
          />
          <span>Has alert</span>
        </label>

        <button
          type="button"
          className="filter-clear-button"
          onClick={onClear}
          data-testid="filter-clear"
        >
          Clear all filters
        </button>
      </div>
    </div>
  );
}

interface SourceMultiSelectProps {
  selected: string[];
  options: string[];
  onToggle: (source: string) => void;
}

/** Multi-select dropdown for source_name (spec req 2.4).
 *
 *  Trigger button shows the count of selected sources ("All sources" /
 *  "1 source" / "N sources"); clicking it opens a popover with a checkbox per
 *  option, so the user can tick multiple sources. Implementation pattern
 *  matches ColumnPicker for visual consistency. */
function SourceMultiSelect({
  selected,
  options,
  onToggle,
}: SourceMultiSelectProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);

  // Close on outside click so the popover behaves like a native dropdown.
  // Also close on Escape so the popover follows the standard keyboard pattern
  // for menus / dialogs (matches how native ``<select>`` dropdowns dismiss).
  useEffect(() => {
    if (!open) return;
    function onDocMouseDown(event: MouseEvent) {
      if (!rootRef.current) return;
      const target = event.target as Node | null;
      if (target && !rootRef.current.contains(target)) {
        setOpen(false);
      }
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDocMouseDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onDocMouseDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const selectedSet = new Set(selected);
  const triggerLabel =
    selected.length === 0
      ? "All sources"
      : selected.length === 1
        ? selected[0]
        : `${selected.length} sources`;

  return (
    <div className="filter-field source-multiselect" ref={rootRef}>
      <span className="filter-field-label">Source</span>
      <button
        type="button"
        className="source-multiselect-trigger"
        aria-haspopup="true"
        aria-expanded={open}
        onClick={() => setOpen((prev) => !prev)}
        data-testid="filter-source"
      >
        {triggerLabel}
      </button>
      {open && (
        <div
          className="source-multiselect-popover"
          role="menu"
          data-testid="filter-source-popover"
        >
          <p className="source-multiselect-heading">Filter by source</p>
          {options.length === 0 ? (
            <p className="source-multiselect-empty">No sources available</p>
          ) : (
            <ul className="source-multiselect-list">
              {options.map((source) => {
                const checked = selectedSet.has(source);
                return (
                  <li key={source}>
                    <label className="source-multiselect-item">
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => onToggle(source)}
                        data-testid={`filter-source-option-${source}`}
                      />
                      <span>{source}</span>
                    </label>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

/** Convert raw filter inputs into API query params, dropping empty fields.
 *
 *  ``source_names`` is special: it is multi-valued so it cannot be expressed
 *  in this flat record (each value must hit the URL as a separate
 *  ``?source_name=`` param). The caller is expected to handle the array
 *  serialisation; this helper returns everything BUT the source list. */
export function filterStateToQuery(
  state: FilterState,
): Record<string, string | number | boolean | undefined> {
  const out: Record<string, string | number | boolean | undefined> = {};
  if (state.source_type) out.source_type = state.source_type;
  if (state.language) out.language = state.language;
  if (state.event_type) out.event_type = state.event_type;
  // Urgency clamp (recurring F20): values < 1 are a no-op (DB minimum is 1)
  // so we drop them rather than ship `urgency_min=0` to the backend.
  if (state.urgency_min) {
    const n = Number(state.urgency_min);
    if (Number.isFinite(n) && n >= 1) out.urgency_min = n;
  }
  if (state.urgency_max) {
    const n = Number(state.urgency_max);
    if (Number.isFinite(n) && n >= 1) out.urgency_max = n;
  }
  if (state.date_from) out.date_from = state.date_from;
  if (state.date_to) out.date_to = state.date_to;
  if (state.has_alert) out.has_alert = true;
  return out;
}
