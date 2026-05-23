// "All | Classified | Unclassified" tabs above the article table (req 2.5).
//
// Implementation choice for req 2.5a: the spec says "Classified" must include
// articles whose pipeline_status is classified, event_created, or alert_sent.
// Phase 1's backend already does that — `dashboard/db.py` maps the query param
// `pipeline_status=classified` to `c.id IS NOT NULL`, which matches any article
// that reached the classification stage (including the later event_created /
// alert_sent stages). So we just pass the tab value straight through; no
// frontend translation needed. The "All" tab sends no `pipeline_status` filter.

import type { PipelineStatus } from "../types";

export type FilterTabValue = "all" | "classified" | "unclassified";

export interface TabCounts {
  all: number;
  classified: number;
  unclassified: number;
}

interface FilterTabsProps {
  value: FilterTabValue;
  counts: TabCounts;
  onChange: (next: FilterTabValue) => void;
}

interface TabEntry {
  value: FilterTabValue;
  label: string;
}

const TABS: ReadonlyArray<TabEntry> = [
  { value: "all", label: "All" },
  { value: "classified", label: "Classified" },
  { value: "unclassified", label: "Unclassified" },
];

export function FilterTabs({ value, counts, onChange }: FilterTabsProps) {
  return (
    <div className="filter-tabs" role="tablist" aria-label="Pipeline status">
      {TABS.map((tab) => {
        const active = value === tab.value;
        return (
          <button
            key={tab.value}
            type="button"
            role="tab"
            aria-selected={active}
            className={`filter-tab ${active ? "filter-tab-active" : ""}`}
            onClick={() => onChange(tab.value)}
            data-testid={`filter-tab-${tab.value}`}
          >
            <span className="filter-tab-label">{tab.label}</span>
            <span className="filter-tab-count" data-testid="filter-tab-count">
              {counts[tab.value].toLocaleString()}
            </span>
          </button>
        );
      })}
    </div>
  );
}

/**
 * Translate a tab value into the `pipeline_status` query parameter the backend
 * understands. Returns `undefined` for the "all" tab so the param is omitted.
 */
export function tabToPipelineStatus(
  tab: FilterTabValue,
): PipelineStatus | "all" | undefined {
  if (tab === "all") return undefined;
  return tab;
}
