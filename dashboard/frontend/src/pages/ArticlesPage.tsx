import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { ArticleTable } from "../components/ArticleTable";
import { ColumnPicker } from "../components/ColumnPicker";
import {
  COLUMN_STORAGE_KEY,
  DEFAULT_VISIBLE_COLUMNS,
  PAGE_SIZE_STORAGE_KEY,
  type ColumnKey,
} from "../components/columns";
import {
  EMPTY_FILTERS,
  FilterBar,
  filterStateToQuery,
  type FilterState,
} from "../components/FilterBar";
import { FilterTabs, type FilterTabValue, tabToPipelineStatus } from "../components/FilterTabs";
import { SearchBar } from "../components/SearchBar";
import {
  ALLOWED_PAGE_SIZES,
  Pagination,
  isValidPageSize,
  type PageSize,
} from "../components/Pagination";
import { SyncButton } from "../components/SyncButton";
import { useArticles } from "../hooks/useArticles";
import { useLocalStorage } from "../hooks/useLocalStorage";
import { fetchArticles, fetchStats } from "../api/client";
import type { ArticleQueryParams, SortColumn, SortOrder } from "../types";

const DEFAULT_PAGE_SIZE: PageSize = 50;
const DEFAULT_SORT: SortColumn = "published_at";
const DEFAULT_ORDER: SortOrder = "desc";

/** Whole articles page, composed of FilterTabs / FilterBar / SearchBar /
 *  ColumnPicker / SyncButton / ArticleTable / Pagination (req 2.x). */
export function ArticlesPage() {
  const [searchParams, setSearchParams] = useSearchParams();

  // Persistent UI preferences.
  const [visibleColumns, setVisibleColumns] = useLocalStorage<ColumnKey[]>(
    COLUMN_STORAGE_KEY,
    [...DEFAULT_VISIBLE_COLUMNS],
  );
  const [storedPageSize, setStoredPageSize] = useLocalStorage<PageSize>(
    PAGE_SIZE_STORAGE_KEY,
    DEFAULT_PAGE_SIZE,
  );

  // Read state straight from the URL so reloads restore everything (req 2.4a, 2.6a).
  const tab = (searchParams.get("tab") as FilterTabValue) || "all";
  const search = searchParams.get("q") ?? "";
  const sort = (searchParams.get("sort") as SortColumn) || DEFAULT_SORT;
  const order = (searchParams.get("order") as SortOrder) || DEFAULT_ORDER;
  const page = Math.max(1, Number(searchParams.get("page") ?? "1") || 1);
  const pageSizeFromUrl = Number(searchParams.get("page_size") ?? "");
  const pageSize: PageSize = isValidPageSize(pageSizeFromUrl)
    ? pageSizeFromUrl
    : storedPageSize;

  // Filter state pulled from URL (so it survives reload).
  const filters: FilterState = useMemo(
    () => ({
      source_name: searchParams.get("source_name") ?? "",
      source_type: searchParams.get("source_type") ?? "",
      language: searchParams.get("language") ?? "",
      urgency_min: searchParams.get("urgency_min") ?? "",
      urgency_max: searchParams.get("urgency_max") ?? "",
      date_from: searchParams.get("date_from") ?? "",
      date_to: searchParams.get("date_to") ?? "",
      event_type: searchParams.get("event_type") ?? "",
      has_alert: searchParams.get("has_alert") === "true",
    }),
    [searchParams],
  );

  // Track sources/event types for the FilterBar dropdowns (populated from /api/stats).
  const [sourceOptions, setSourceOptions] = useState<string[]>([]);
  const [eventTypeOptions, setEventTypeOptions] = useState<string[]>([]);
  useEffect(() => {
    let cancelled = false;
    fetchStats()
      .then((stats) => {
        if (cancelled) return;
        setSourceOptions(stats.source_distribution.map((s) => s.source_name));
        setEventTypeOptions(
          stats.event_type_distribution.map((s) => s.event_type),
        );
      })
      .catch(() => {
        // Silent here — useArticles handles the broader error surface via toasts.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Build the API query from URL state.
  const baseFilters = filterStateToQuery(filters);
  const pipelineStatus = tabToPipelineStatus(tab);
  const params: ArticleQueryParams = {
    ...baseFilters,
    sort,
    order,
    page,
    page_size: pageSize,
    ...(pipelineStatus ? { pipeline_status: pipelineStatus } : {}),
    ...(search ? { q: search } : {}),
  };

  // Counter that bumps after a sync — forces useArticles to refetch fresh data.
  const [refreshTick, setRefreshTick] = useState(0);

  // Main fetch (current view).
  const { data, loading, error } = useArticles(params, refreshTick);

  // Side fetches for the tab counts — each tab shows the count of matching
  // articles, so we need the totals for "all", "classified", "unclassified"
  // under the current filters/search (req 2.5).
  const [tabCounts, setTabCounts] = useState({
    all: 0,
    classified: 0,
    unclassified: 0,
  });
  useEffect(() => {
    let cancelled = false;
    async function loadCounts() {
      try {
        const [allRes, classifiedRes, unclassifiedRes] = await Promise.all([
          fetchTabCount({ ...params, page: 1, page_size: 25, pipeline_status: undefined }),
          fetchTabCount({ ...params, page: 1, page_size: 25, pipeline_status: "classified" }),
          fetchTabCount({ ...params, page: 1, page_size: 25, pipeline_status: "unclassified" }),
        ]);
        if (cancelled) return;
        setTabCounts({
          all: allRes,
          classified: classifiedRes,
          unclassified: unclassifiedRes,
        });
      } catch {
        // Errors on the count side-channel are non-fatal; useArticles already
        // surfaces the main load failure.
      }
    }
    loadCounts();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    search,
    refreshTick,
    JSON.stringify(baseFilters),
  ]);

  // --- URL-mutating handlers -------------------------------------------------

  const updateSearchParams = useCallback(
    (mutator: (next: URLSearchParams) => void) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          mutator(next);
          return next;
        },
        { replace: false },
      );
    },
    [setSearchParams],
  );

  function onTabChange(next: FilterTabValue) {
    updateSearchParams((p) => {
      if (next === "all") p.delete("tab");
      else p.set("tab", next);
      p.set("page", "1");
    });
  }

  function onSortChange(column: SortColumn) {
    const nextOrder: SortOrder =
      sort === column ? (order === "asc" ? "desc" : "asc") : "desc";
    updateSearchParams((p) => {
      p.set("sort", column);
      p.set("order", nextOrder);
      p.set("page", "1");
    });
  }

  function onPageChange(nextPage: number) {
    updateSearchParams((p) => {
      p.set("page", String(nextPage));
    });
  }

  function onPageSizeChange(size: PageSize) {
    setStoredPageSize(size);
    updateSearchParams((p) => {
      p.set("page_size", String(size));
      p.set("page", "1"); // req 2.7b
    });
  }

  function onFilterChange(next: FilterState) {
    updateSearchParams((p) => {
      applyFilterToUrl(p, next);
      p.set("page", "1");
    });
  }

  function onClearFilters() {
    updateSearchParams((p) => {
      applyFilterToUrl(p, EMPTY_FILTERS);
      p.set("page", "1");
    });
  }

  function onSearchChange(query: string) {
    updateSearchParams((p) => {
      if (query) p.set("q", query);
      else p.delete("q");
      p.set("page", "1");
    });
  }

  function toggleColumn(key: ColumnKey) {
    setVisibleColumns((prev) => {
      const set = new Set(prev);
      if (set.has(key)) set.delete(key);
      else set.add(key);
      // Preserve the canonical column order from ALL_COLUMNS.
      return [...set] as ColumnKey[];
    });
  }

  const articles = data?.articles ?? [];
  const totalPages = data?.total_pages ?? 0;
  const total = data?.total ?? 0;

  return (
    <div className="articles-page">
      <header className="articles-page-header">
        <h1>Articles</h1>
        <SyncButton onSyncComplete={() => setRefreshTick((t) => t + 1)} />
      </header>

      <SearchBar initialValue={search} onDebouncedChange={onSearchChange} />

      <FilterTabs value={tab} counts={tabCounts} onChange={onTabChange} />

      <FilterBar
        value={filters}
        sourceOptions={sourceOptions}
        eventTypeOptions={eventTypeOptions}
        onChange={onFilterChange}
        onClear={onClearFilters}
      />

      <div className="articles-page-toolbar">
        <ColumnPicker
          visible={visibleColumns.length ? visibleColumns : DEFAULT_VISIBLE_COLUMNS}
          onToggle={toggleColumn}
        />
        {loading && (
          <span className="articles-page-loading" data-testid="loading">
            Loading…
          </span>
        )}
        {error && (
          <span className="articles-page-error" data-testid="error-banner">
            {error.message}
          </span>
        )}
      </div>

      <ArticleTable
        articles={articles}
        visibleColumns={
          visibleColumns.length ? visibleColumns : DEFAULT_VISIBLE_COLUMNS
        }
        sort={sort}
        order={order}
        onSortChange={onSortChange}
      />

      <Pagination
        page={page}
        totalPages={totalPages}
        total={total}
        pageSize={pageSize}
        onPageChange={onPageChange}
        onPageSizeChange={onPageSizeChange}
      />
    </div>
  );
}

// --- Helpers -----------------------------------------------------------------

async function fetchTabCount(params: ArticleQueryParams): Promise<number> {
  const result = await fetchArticles(params);
  return result.total;
}

function applyFilterToUrl(target: URLSearchParams, next: FilterState) {
  const map: Array<[keyof FilterState, string]> = [
    ["source_name", "source_name"],
    ["source_type", "source_type"],
    ["language", "language"],
    ["urgency_min", "urgency_min"],
    ["urgency_max", "urgency_max"],
    ["date_from", "date_from"],
    ["date_to", "date_to"],
    ["event_type", "event_type"],
  ];
  for (const [key, name] of map) {
    const value = next[key];
    if (typeof value === "string" && value) target.set(name, value);
    else target.delete(name);
  }
  if (next.has_alert) target.set("has_alert", "true");
  else target.delete("has_alert");
}

// Re-export so jamming a stray import won't break in tests.
export { ALLOWED_PAGE_SIZES };
