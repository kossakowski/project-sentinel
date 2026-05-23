// Tests for ArticlesPage orchestration — covers the iteration-2 fixes:
//   F1/F2 toast surfacing of /api/stats and tab-count errors (req 2.9a)
//   F3 conditional sort param wiring (preserves req 1.4c FTS rank ordering)
//   F4 broad "Clear all filters" reset
//   F6 stats refresh on Sync (req 2.8)
//
// The page wires together a lot of child components; each test mocks just the
// API surface it cares about to keep failure modes legible.

import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import type { ReactNode } from "react";

import { ApiError } from "../api/client";
import * as client from "../api/client";
import { ToastProvider } from "../components/Toast";
import { ArticlesPage } from "../pages/ArticlesPage";
import type {
  ArticleListResponse,
  StatsResponse,
  SyncStatus,
} from "../types";
import { routerFutureFlags } from "../utils/routerFutureFlags";

/** Tiny in-tree probe that surfaces the MemoryRouter's current location.search
 *  via a hidden DOM node, so URL-reset assertions can read the URL without
 *  needing window.location (MemoryRouter doesn't drive window.location). */
function LocationProbe() {
  const location = useLocation();
  return <span data-testid="location-search">{location.search}</span>;
}

function emptyArticles(overrides: Partial<ArticleListResponse> = {}): ArticleListResponse {
  return {
    articles: [],
    total: 0,
    page: 1,
    page_size: 50,
    total_pages: 0,
    ...overrides,
  };
}

function emptyStats(overrides: Partial<StatsResponse> = {}): StatsResponse {
  return {
    total_articles: 0,
    total_classified: 0,
    total_events: 0,
    total_alerts: 0,
    articles_per_day: [],
    classified_per_day: [],
    urgency_distribution: [],
    source_distribution: [{ source_name: "TVN24", count: 1 }],
    language_distribution: [],
    event_type_distribution: [{ event_type: "airspace_violation", count: 1 }],
    pipeline_funnel: {
      collected: 0,
      classified: 0,
      events_created: 0,
      alerts_sent: 0,
    },
    annotation_stats: {
      total: 0,
      by_label: { correct: 0, incorrect: 0, uncertain: 0 },
      average_urgency_deviation: null,
    },
    ...overrides,
  };
}

function emptySyncStatus(overrides: Partial<SyncStatus> = {}): SyncStatus {
  return {
    last_sync: null,
    ...overrides,
  };
}

function renderPage(initialEntries: string[] = ["/articles"]): ReactNode {
  return render(
    <MemoryRouter initialEntries={initialEntries} future={routerFutureFlags}>
      <ToastProvider>
        <ArticlesPage />
        <LocationProbe />
      </ToastProvider>
    </MemoryRouter>,
  ) as unknown as ReactNode;
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ArticlesPage", () => {
  // covers F1 (req 2.9a) — /api/stats failure must produce a visible toast.
  it("test_stats_error_surfaces_toast", async () => {
    vi.spyOn(client, "fetchStats").mockRejectedValue(
      new ApiError("500 stats DB locked", 500, { error: "stats DB locked" }, "/api/stats"),
    );
    vi.spyOn(client, "fetchArticles").mockResolvedValue(emptyArticles());
    vi.spyOn(client, "fetchSyncStatus").mockResolvedValue(emptySyncStatus());

    renderPage();

    await waitFor(() => {
      expect(
        screen.getByText(/Couldn't load source\/event filters/i),
      ).toBeInTheDocument();
    });
  });

  // covers F2 (req 2.9a) — /api/articles tab-count failure must surface a toast.
  // Note: one toast per failed loadCounts invocation, NOT one per of the three
  // parallel calls.
  it("test_tab_count_error_surfaces_single_toast", async () => {
    vi.spyOn(client, "fetchStats").mockResolvedValue(emptyStats());
    vi.spyOn(client, "fetchSyncStatus").mockResolvedValue(emptySyncStatus());

    // Promise.all will reject with the first failure — three calls all fail
    // here, but we expect ONE toast.
    vi.spyOn(client, "fetchArticles").mockRejectedValue(
      new ApiError("500 boom", 500, null, "/api/articles"),
    );

    renderPage();

    await waitFor(() => {
      expect(
        screen.getByText(/Couldn't refresh tab counts/i),
      ).toBeInTheDocument();
    });
    // Only one tab-counts toast, even though three /api/articles requests fired.
    expect(
      screen.getAllByText(/Couldn't refresh tab counts/i),
    ).toHaveLength(1);
  });

  // covers F3 (req 1.4c) — when no `sort` URL param is set, fetchArticles must
  // be called WITHOUT a sort param. When `sort` is in the URL, the param must
  // round-trip to the API call.
  it("test_conditional_sort_param", async () => {
    vi.spyOn(client, "fetchStats").mockResolvedValue(emptyStats());
    vi.spyOn(client, "fetchSyncStatus").mockResolvedValue(emptySyncStatus());
    const fetchSpy = vi
      .spyOn(client, "fetchArticles")
      .mockResolvedValue(emptyArticles());

    // No sort in URL — backend should fall through to FTS rank / default order.
    renderPage(["/articles?q=drone"]);

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalled();
    });

    const calls = fetchSpy.mock.calls.filter(([params]) => {
      const p = params as Record<string, unknown>;
      // Just the main /api/articles call (page_size 50), not the tab-count
      // calls (page_size 25).
      return p?.page_size === 50;
    });
    expect(calls.length).toBeGreaterThan(0);
    const mainParams = calls[0][0] as Record<string, unknown>;
    expect(mainParams).not.toHaveProperty("sort");
    expect(mainParams).not.toHaveProperty("order");
    expect(mainParams.q).toBe("drone");

    fetchSpy.mockClear();

    // Mount fresh with sort in URL — backend should now see the explicit sort.
    renderPage(["/articles?q=drone&sort=urgency_score&order=asc"]);

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalled();
    });
    const sortedCalls = fetchSpy.mock.calls.filter(([params]) => {
      const p = params as Record<string, unknown>;
      return p?.page_size === 50;
    });
    expect(sortedCalls.length).toBeGreaterThan(0);
    const sortedParams = sortedCalls[0][0] as Record<string, unknown>;
    expect(sortedParams.sort).toBe("urgency_score");
    expect(sortedParams.order).toBe("asc");
  });

  // covers F4 / spec test_filter_clear_all (req 2.4b) — Clear all filters must
  // reset every URL-backed filter param plus the visible state. ``page_size``
  // is the ONLY param allowed to survive (req 2.7a).
  it("test_clear_filters_resets_all_state", async () => {
    vi.spyOn(client, "fetchStats").mockResolvedValue(emptyStats());
    vi.spyOn(client, "fetchSyncStatus").mockResolvedValue(emptySyncStatus());
    vi.spyOn(client, "fetchArticles").mockResolvedValue(emptyArticles());

    const user = userEvent.setup();
    renderPage([
      "/articles?q=drone&tab=classified&sort=urgency_score&order=asc&page=3&source_name=TVN24&source_name=TASS&urgency_min=5&urgency_max=10&date_from=2026-05-01&date_to=2026-05-22&source_type=rss&language=pl&event_type=drone_attack&has_alert=true&page_size=25",
    ]);

    // Active tab indicator should reflect "classified" before clearing.
    await waitFor(() => {
      const classifiedTab = screen.getByTestId("filter-tab-classified");
      expect(classifiedTab.getAttribute("aria-selected")).toBe("true");
    });

    // The search input mirrors the URL `q` param.
    expect(
      (screen.getByTestId("search-input") as HTMLInputElement).value,
    ).toBe("drone");

    // The source multi-select trigger reflects two selected sources.
    expect(screen.getByTestId("filter-source").textContent).toBe("2 sources");

    await user.click(screen.getByTestId("filter-clear"));

    // Active tab is back to "All".
    await waitFor(() => {
      const allTab = screen.getByTestId("filter-tab-all");
      expect(allTab.getAttribute("aria-selected")).toBe("true");
    });

    // Search input cleared.
    expect(
      (screen.getByTestId("search-input") as HTMLInputElement).value,
    ).toBe("");

    // FilterBar fields cleared.
    expect(screen.getByTestId("filter-source").textContent).toBe("All sources");
    expect(
      (screen.getByTestId("filter-urgency-min") as HTMLInputElement).value,
    ).toBe("");

    // URL is the source of truth — assert every filter/search/sort/order/page
    // query param is gone. page_size is the only allowed survivor (req 2.7a).
    await waitFor(() => {
      const url = screen.getByTestId("location-search").textContent ?? "";
      const lookup = `?${url.startsWith("?") ? url.slice(1) : url}`;
      expect(lookup).not.toMatch(/[?&]q=/);
      expect(lookup).not.toMatch(/[?&]tab=/);
      expect(lookup).not.toMatch(/[?&]sort=/);
      expect(lookup).not.toMatch(/[?&]order=/);
      expect(lookup).not.toMatch(/[?&]page=/);
      expect(lookup).not.toMatch(/[?&]source_name=/);
      expect(lookup).not.toMatch(/[?&]source_type=/);
      expect(lookup).not.toMatch(/[?&]language=/);
      expect(lookup).not.toMatch(/[?&]urgency_min=/);
      expect(lookup).not.toMatch(/[?&]urgency_max=/);
      expect(lookup).not.toMatch(/[?&]date_from=/);
      expect(lookup).not.toMatch(/[?&]date_to=/);
      expect(lookup).not.toMatch(/[?&]event_type=/);
      expect(lookup).not.toMatch(/[?&]has_alert=/);
      // page_size MAY survive (allowed by spec req 2.7a).
    });
  });

  // covers F6 (req 2.8) — Sync must trigger a fresh /api/stats call so
  // newly-added sources show up in FilterBar dropdowns.
  it("test_sync_refreshes_stats", async () => {
    const statsSpy = vi
      .spyOn(client, "fetchStats")
      .mockResolvedValue(emptyStats());
    vi.spyOn(client, "fetchArticles").mockResolvedValue(emptyArticles());
    vi.spyOn(client, "fetchSyncStatus").mockResolvedValue(emptySyncStatus());
    vi.spyOn(client, "triggerSync").mockResolvedValue({
      last_sync: "2026-05-23T12:00:00+00:00",
      result: {
        success: true,
        file_size: 1,
        article_count: 100,
        duration: 0.1,
        error: null,
      },
    });

    const user = userEvent.setup();
    renderPage();

    // Initial mount fires one stats fetch.
    await waitFor(() => {
      expect(statsSpy).toHaveBeenCalledTimes(1);
    });

    // Click Sync — wait for the trigger to resolve, then assert stats refetched.
    await user.click(screen.getByTestId("sync-button"));

    await waitFor(() => {
      expect(statsSpy).toHaveBeenCalledTimes(2);
    });
  });
});
