// Column metadata shared between ArticleTable and ColumnPicker (req 2.3).
//
// `ColumnKey` is the authoritative list of every column the table can render.
// `DEFAULT_VISIBLE_COLUMNS` matches the spec exactly (req 2.2a). Anything not
// in the default set is hidden until the user toggles it via ColumnPicker.

export type ColumnKey =
  | "published_at"
  | "fetched_at"
  | "title"
  | "source_name"
  | "source_type"
  | "source_url"
  | "language"
  | "urgency_score"
  | "event_type"
  | "confidence"
  | "aggressor"
  | "affected_countries"
  | "pipeline_status"
  | "summary_pl"
  | "is_military_event"
  | "annotation";

export interface ColumnDef {
  key: ColumnKey;
  label: string;
  /** Whether the column header is clickable for sorting on the backend. */
  sortable: boolean;
}

/** Every column the user can choose to display. Order = display order. */
export const ALL_COLUMNS: ReadonlyArray<ColumnDef> = [
  { key: "published_at", label: "Published", sortable: true },
  { key: "fetched_at", label: "Fetched", sortable: true },
  { key: "title", label: "Title", sortable: true },
  { key: "source_name", label: "Source", sortable: true },
  { key: "source_type", label: "Source type", sortable: false },
  { key: "source_url", label: "URL", sortable: false },
  { key: "language", label: "Lang", sortable: false },
  { key: "urgency_score", label: "Urgency", sortable: true },
  { key: "event_type", label: "Event type", sortable: false },
  { key: "confidence", label: "Confidence", sortable: true },
  { key: "aggressor", label: "Aggressor", sortable: false },
  { key: "affected_countries", label: "Countries", sortable: false },
  { key: "pipeline_status", label: "Status", sortable: false },
  { key: "summary_pl", label: "Summary (PL)", sortable: false },
  { key: "is_military_event", label: "Military?", sortable: false },
  // Phase 4 (req 4.4) — coloured dot per annotation label, "—" when none.
  { key: "annotation", label: "Note", sortable: false },
];

/** Spec req 2.2a default visible columns (Phase 4 req 4.4a adds annotation). */
export const DEFAULT_VISIBLE_COLUMNS: ReadonlyArray<ColumnKey> = [
  "published_at",
  "title",
  "source_name",
  "language",
  "urgency_score",
  "event_type",
  "pipeline_status",
  "annotation",
];

/** localStorage key for persisted column visibility (req 2.3a). */
export const COLUMN_STORAGE_KEY = "dashboard.columns";

/** localStorage key for persisted page size (req 2.7a). */
export const PAGE_SIZE_STORAGE_KEY = "dashboard.pageSize";
