import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { ArticleTable } from "../components/ArticleTable";
import { ColumnPicker } from "../components/ColumnPicker";
import {
  ALL_COLUMNS,
  COLUMN_STORAGE_KEY,
  DEFAULT_VISIBLE_COLUMNS,
  PAGE_SIZE_STORAGE_KEY,
  type ColumnKey,
} from "../components/columns";
import {
  FilterBar,
  filterStateToQuery,
  type FilterState,
} from "../components/FilterBar";
import { FilterTabs, type FilterTabValue, tabToPipelineStatus } from "../components/FilterTabs";
import { SearchBar } from "../components/SearchBar";
import {
  Pagination,
  isValidPageSize,
  type PageSize,
} from "../components/Pagination";
import { SyncButton } from "../components/SyncButton";
import { useToasts } from "../components/Toast";
import { useArticles } from "../hooks/useArticles";
import { useLocalStorage } from "../hooks/useLocalStorage";
import { ApiError, fetchArticles, fetchStats } from "../api/client";
import type { ArticleQueryParams, SortColumn, SortOrder } from "../types";

const DEFAULT_PAGE_SIZE: PageSize = 50;

// Canonical set of column keys — used by the localStorage shape validator
// below to reject any persisted column list that contains stale or invalid
// keys (e.g. a column renamed in a later release).
const VALID_COLUMN_KEYS = new Set<string>(ALL_COLUMNS.map((c) => c.key));

function isColumnKeyList(value: unknown): value is ColumnKey[] {
  return (
    Array.isArray(value) &&
    value.every((v) => typeof v === "string" && VALID_COLUMN_KEYS.has(v))
  );
}

function isStoredPageSize(value: unknown): value is PageSize {
  return typeof value === "number" && isValidPageSize(value);
}

/** Whole articles page, composed of FilterTabs / FilterBar / SearchBar /
 *  ColumnPicker / SyncButton / ArticleTable / Pagination (req 2.x). */
export function ArticlesPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { notify } = useToasts();

  // Persistent UI preferences. The validators reject any corrupted shape (a
  // stray devtools edit, a stale value from a prior release) AND clear the
  // bad key so downstream consumers (ArticleTable.visibleColumns.includes)
  // never see non-array data.
  const [visibleColumns, setVisibleColumns] = useLocalStorage<ColumnKey[]>(
    COLUMN_STORAGE_KEY,
    [...DEFAULT_VISIBLE_COLUMNS],
    isColumnKeyList,
  );
  const [storedPageSize, setStoredPageSize] = useLocalStorage<PageSize>(
    PAGE_SIZE_STORAGE_KEY,
    DEFAULT_PAGE_SIZE,
    isStoredPageSize,
  );

  // Read state straight from the URL so reloads restore everything (req 2.4a, 2.6a).
  const tab = (searchParams.get("tab") as FilterTabValue) || "all";
  const search = searchParams.get("q") ?? "";
  // User-chosen sort is detected by the literal presence of `sort=` in the URL.
  // When absent we pass `null` down so the header indicator stays blank (req
  // 2.2: indicator appears only when a column IS sorted) AND we do NOT send
  // `sort=` to the backend (preserves FTS rank ordering, req 1.4c).
  const userSort = searchParams.get("sort") as SortColumn | null;
  const userOrder = searchParams.get("order") as SortOrder | null;
  const page = Math.max(1, Number(searchParams.get("page") ?? "1") || 1);
  const pageSizeFromUrl = Number(searchParams.get("page_size") ?? "");
  const pageSize: PageSize = isValidPageSize(pageSizeFromUrl)
    ? pageSizeFromUrl
    : storedPageSize;

  // Filter state pulled from URL (so it survives reload).
  const filters: FilterState = useMemo(
    () => ({
      source_names: searchParams.getAll("source_name").filter(Boolean),
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

  // Counter that bumps after a sync — forces useArticles AND fetchStats to
  // refetch fresh data so filter dropdowns and counts stay in sync (req 2.8).
  const [refreshTick, setRefreshTick] = useState(0);

  // Track sources/event types for the FilterBar dropdowns (populated from /api/stats).
  const [sourceOptions, setSourceOptions] = useState<string[]>([]);
  const [eventTypeOptions, setEventTypeOptions] = useState<string[]>([]);
  useEffect(() => {
    // Use AbortController so a fast refreshTick bump or unmount cancels the
    // in-flight request rather than just discarding its result (req 2.9
    // consistency with useArticles).
    const controller = new AbortController();
    fetchStats({ signal: controller.signal })
      .then((stats) => {
        if (controller.signal.aborted) return;
        setSourceOptions(stats.source_distribution.map((s) => s.source_name));
        setEventTypeOptions(
          stats.event_type_distribution.map((s) => s.event_type),
        );
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        const message = errorMessage(error);
        // Spec req 2.9a — API errors MUST be surfaced to the user.
        notify(
          `Couldn't load source/event filters: ${message}`,
          "error",
        );
      });
    return () => controller.abort();
    // refreshTick re-runs the effect after a successful sync — picks up new
    // sources/event_types that didn't exist at first mount.
  }, [refreshTick, notify]);

  // Build the API query from URL state. `sort`/`order` are added only when
  // the user has explicitly clicked a column header (preserves FTS rank
  // ordering, req 1.4c).
  const baseFilters = filterStateToQuery(filters);
  const pipelineStatus = tabToPipelineStatus(tab);
  const params: ArticleQueryParams = {
    ...baseFilters,
    // Multi-select source_name -> repeated ?source_name= params (req 2.4).
    ...(filters.source_names.length > 0
      ? { source_name: filters.source_names }
      : {}),
    page,
    page_size: pageSize,
    ...(userSort ? { sort: userSort } : {}),
    ...(userSort && userOrder ? { order: userOrder } : {}),
    ...(pipelineStatus ? { pipeline_status: pipelineStatus } : {}),
    ...(search ? { q: search } : {}),
  };

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
  // Stable JSON snapshot of the dependencies the tab-counts effect actually
  // needs (filters + search + source_names). Sort/order are intentionally
  // excluded — totals are pipeline_status-only counts and sort doesn't affect
  // them. Including source_names here so a multi-select change invalidates.
  const sourceNamesKey = filters.source_names.join("");
  useEffect(() => {
    const controller = new AbortController();
    async function loadCounts() {
      try {
        const baseParams: ArticleQueryParams = {
          ...baseFilters,
          ...(filters.source_names.length > 0
            ? { source_name: filters.source_names }
            : {}),
          ...(search ? { q: search } : {}),
        };
        const [allRes, classifiedRes, unclassifiedRes] = await Promise.all([
          fetchTabCount(
            { ...baseParams, page: 1, page_size: 25 },
            controller.signal,
          ),
          fetchTabCount(
            { ...baseParams, page: 1, page_size: 25, pipeline_status: "classified" },
            controller.signal,
          ),
          fetchTabCount(
            { ...baseParams, page: 1, page_size: 25, pipeline_status: "unclassified" },
            controller.signal,
          ),
        ]);
        if (controller.signal.aborted) return;
        setTabCounts({
          all: allRes,
          classified: classifiedRes,
          unclassified: unclassifiedRes,
        });
      } catch (caught: unknown) {
        if (controller.signal.aborted) return;
        // One toast per failed loadCounts run — even though three /api/articles
        // calls fire in parallel, the user only needs to know counts are stale.
        // Spec req 2.9a forbids silently swallowing the failure.
        notify(`Couldn't refresh tab counts: ${errorMessage(caught)}`, "error");
      }
    }
    loadCounts();
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    search,
    refreshTick,
    JSON.stringify(baseFilters),
    sourceNamesKey,
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

  const onTabChange = useCallback(
    (next: FilterTabValue) => {
      updateSearchParams((p) => {
        if (next === "all") p.delete("tab");
        else p.set("tab", next);
        p.set("page", "1");
      });
    },
    [updateSearchParams],
  );

  const onSortChange = useCallback(
    (column: SortColumn) => {
      // Reads the current state from the URL via the searchParams snapshot —
      // each click writes back an explicit `sort=...&order=...` so the backend
      // sees a user-chosen sort going forward.
      const currentSort = searchParams.get("sort") as SortColumn | null;
      const currentOrder = searchParams.get("order") as SortOrder | null;
      const nextOrder: SortOrder =
        currentSort === column
          ? currentOrder === "asc"
            ? "desc"
            : "asc"
          : "desc";
      updateSearchParams((p) => {
        p.set("sort", column);
        p.set("order", nextOrder);
        p.set("page", "1");
      });
    },
    [searchParams, updateSearchParams],
  );

  const onPageChange = useCallback(
    (nextPage: number) => {
      updateSearchParams((p) => {
        p.set("page", String(nextPage));
      });
    },
    [updateSearchParams],
  );

  const onPageSizeChange = useCallback(
    (size: PageSize) => {
      setStoredPageSize(size);
      updateSearchParams((p) => {
        p.set("page_size", String(size));
        p.set("page", "1"); // req 2.7b
      });
    },
    [setStoredPageSize, updateSearchParams],
  );

  const onFilterChange = useCallback(
    (next: FilterState) => {
      updateSearchParams((p) => {
        applyFilterToUrl(p, next);
        p.set("page", "1");
      });
    },
    [updateSearchParams],
  );

  // Clear ALL filter-like state in one go — FilterBar fields, active tab,
  // search query, sort/order, and page. page_size stays put (lives in
  // localStorage per req 2.7a).
  const onClearFilters = useCallback(() => {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams();
        // Preserve page_size only — everything else clears.
        const pageSizeParam = prev.get("page_size");
        if (pageSizeParam) next.set("page_size", pageSizeParam);
        return next;
      },
      { replace: false },
    );
  }, [setSearchParams]);

  // Stabilised so SearchBar's debounce effect doesn't reset on every parent
  // re-render — protects the 300ms guarantee in req 2.6.
  const onSearchChange = useCallback(
    (query: string) => {
      updateSearchParams((p) => {
        if (query) p.set("q", query);
        else p.delete("q");
        p.set("page", "1");
      });
    },
    [updateSearchParams],
  );

  const toggleColumn = useCallback((key: ColumnKey) => {
    setVisibleColumns((prev) => {
      const set = new Set(prev);
      if (set.has(key)) set.delete(key);
      else set.add(key);
      // Preserve the canonical column order from ALL_COLUMNS.
      return [...set] as ColumnKey[];
    });
  }, [setVisibleColumns]);

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
        sort={userSort}
        order={userOrder}
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

async function fetchTabCount(
  params: ArticleQueryParams,
  signal?: AbortSignal,
): Promise<number> {
  const result = await fetchArticles(params, signal ? { signal } : undefined);
  return result.total;
}

function applyFilterToUrl(target: URLSearchParams, next: FilterState) {
  // Multi-valued source_names is handled separately (delete + append per
  // value) since URLSearchParams cannot express a repeated param via set().
  target.delete("source_name");
  for (const source of next.source_names) {
    const trimmed = source.trim();
    if (trimmed) target.append("source_name", trimmed);
  }

  const map: Array<[Exclude<keyof FilterState, "source_names" | "has_alert">, string]> = [
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
    // Trim string filters so leading/trailing whitespace doesn't show up in
    // shared URLs or get round-tripped to the backend (req 2.4a polish).
    if (typeof value === "string" && value.trim()) target.set(name, value.trim());
    else target.delete(name);
  }
  if (next.has_alert) target.set("has_alert", "true");
  else target.delete("has_alert");
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Unknown error";
}
