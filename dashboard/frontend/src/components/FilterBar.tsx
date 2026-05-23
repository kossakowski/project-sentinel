import type { ChangeEvent } from "react";

export interface FilterState {
  source_name: string;
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
  source_name: "",
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

  return (
    <div className="filter-bar" role="group" aria-label="Filter articles">
      <div className="filter-bar-row">
        <label className="filter-field">
          <span>Source</span>
          <select
            value={value.source_name}
            onChange={handleInput("source_name")}
            data-testid="filter-source"
          >
            <option value="">All sources</option>
            {sourceOptions.map((source) => (
              <option key={source} value={source}>
                {source}
              </option>
            ))}
          </select>
        </label>

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

/** Convert raw filter inputs into API query params, dropping empty fields. */
export function filterStateToQuery(
  state: FilterState,
): Record<string, string | number | boolean | undefined> {
  const out: Record<string, string | number | boolean | undefined> = {};
  if (state.source_name) out.source_name = state.source_name;
  if (state.source_type) out.source_type = state.source_type;
  if (state.language) out.language = state.language;
  if (state.event_type) out.event_type = state.event_type;
  if (state.urgency_min) {
    const n = Number(state.urgency_min);
    if (Number.isFinite(n)) out.urgency_min = n;
  }
  if (state.urgency_max) {
    const n = Number(state.urgency_max);
    if (Number.isFinite(n)) out.urgency_max = n;
  }
  if (state.date_from) out.date_from = state.date_from;
  if (state.date_to) out.date_to = state.date_to;
  if (state.has_alert) out.has_alert = true;
  return out;
}
