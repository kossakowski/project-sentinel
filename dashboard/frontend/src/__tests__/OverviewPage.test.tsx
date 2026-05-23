// Tests for the Phase 3 overview page and its widgets.
//
// Covers acceptance tests #1-#5 from the spec:
//   test_overview_page_renders       (3.1)
//   test_view_toggle_switches        (3.1a)
//   test_stats_cards_display         (3.2)
//   test_pipeline_funnel_counts      (3.3)
//   test_funnel_stage_navigation     (3.3a)
//
// Recharts components are exercised in dedicated chart-component tests
// (TimeSeriesChart.test.tsx, UrgencyHistogram.test.tsx, SourceBreakdown.test.tsx)
// where we mount with explicit width/height so jsdom can render the SVG.
// OverviewPage.test.tsx therefore mocks ResponsiveContainer with a stub so the
// SVG renders deterministically when the page is mounted as a whole.

import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import type { ReactNode } from "react";

import * as client from "../api/client";
import { ToastProvider } from "../components/Toast";
import { OverviewPage } from "../pages/OverviewPage";
import { routerFutureFlags } from "../utils/routerFutureFlags";
import { makeStats } from "./fixtures";

// Force ResponsiveContainer to render with deterministic dimensions so its
// child chart actually paints under jsdom. The real ResponsiveContainer uses
// ResizeObserver + getBoundingClientRect, both of which return 0×0 in jsdom.
vi.mock("recharts", async () => {
  const actual = await vi.importActual<typeof import("recharts")>("recharts");
  return {
    ...actual,
    ResponsiveContainer: ({ children, width = 600, height = 280 }: {
      children: ReactNode;
      width?: number | string;
      height?: number | string;
    }) => (
      <div
        data-testid="responsive-container-stub"
        style={{ width: typeof width === "number" ? width : 600, height: typeof height === "number" ? height : 280 }}
      >
        {children}
      </div>
    ),
  };
});

/** Surfaces the MemoryRouter location.search via a hidden node — used to
 *  assert URL state changes from inside the test. */
function LocationProbe() {
  const location = useLocation();
  return <span data-testid="location-search">{location.search}</span>;
}

function renderOverview(initial: string[] = ["/"]) {
  return render(
    <MemoryRouter initialEntries={initial} future={routerFutureFlags}>
      <ToastProvider>
        <Routes>
          <Route path="/" element={<OverviewPage />} />
          <Route
            path="/articles"
            element={
              <div data-testid="articles-page-stub">Articles page</div>
            }
          />
        </Routes>
        <LocationProbe />
      </ToastProvider>
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("OverviewPage", () => {
  // covers test #1 (req 3.1) — overview page is reachable at /, renders stats
  // cards + the pipeline view (the default).
  it("test_overview_page_renders", async () => {
    vi.spyOn(client, "fetchStats").mockResolvedValue(makeStats());

    renderOverview();

    // Wait until the stats payload resolves and the page renders cards/charts.
    await waitFor(() => {
      expect(screen.getByTestId("overview-page")).toBeInTheDocument();
    });
    expect(screen.getByTestId("stats-cards")).toBeInTheDocument();
    // Default mode is pipeline → funnel + time-series visible.
    expect(screen.getByTestId("overview-pipeline")).toBeInTheDocument();
    expect(screen.getByTestId("pipeline-funnel")).toBeInTheDocument();
    expect(screen.getByTestId("time-series-chart")).toBeInTheDocument();
    // Analytics view not rendered by default.
    expect(screen.queryByTestId("overview-analytics")).not.toBeInTheDocument();
  });

  // covers test #2 (req 3.1a) — ViewToggle switches between Pipeline and
  // Analytics modes and reflects the choice in the URL.
  it("test_view_toggle_switches", async () => {
    vi.spyOn(client, "fetchStats").mockResolvedValue(makeStats());

    const user = userEvent.setup();
    renderOverview();

    await waitFor(() => {
      expect(screen.getByTestId("view-toggle")).toBeInTheDocument();
    });

    // Pipeline button is active by default.
    expect(
      screen.getByTestId("view-toggle-pipeline").getAttribute("aria-pressed"),
    ).toBe("true");
    expect(screen.getByTestId("overview-pipeline")).toBeInTheDocument();

    // Click Analytics → URL gains ?view=analytics, page swaps content.
    await user.click(screen.getByTestId("view-toggle-analytics"));

    await waitFor(() => {
      expect(screen.getByTestId("overview-analytics")).toBeInTheDocument();
    });
    expect(
      screen.getByTestId("view-toggle-analytics").getAttribute("aria-pressed"),
    ).toBe("true");
    expect(screen.queryByTestId("overview-pipeline")).not.toBeInTheDocument();
    expect(screen.getByTestId("urgency-histogram")).toBeInTheDocument();
    expect(screen.getByTestId("source-breakdown")).toBeInTheDocument();
    expect(screen.getByTestId("location-search").textContent).toContain(
      "view=analytics",
    );

    // Click Pipeline again → URL drops ?view= (default), funnel returns.
    await user.click(screen.getByTestId("view-toggle-pipeline"));
    await waitFor(() => {
      expect(screen.getByTestId("overview-pipeline")).toBeInTheDocument();
    });
    expect(screen.getByTestId("location-search").textContent).not.toContain(
      "view=analytics",
    );
  });

  // covers test #3 (req 3.2) — StatsCards renders four KPI cards with values.
  it("test_stats_cards_display", async () => {
    vi.spyOn(client, "fetchStats").mockResolvedValue(
      makeStats({
        total_articles: 37542,
        total_classified: 5812,
        total_events: 501,
        total_alerts: 365,
      }),
    );

    renderOverview();

    await waitFor(() => {
      expect(screen.getByTestId("stats-card-articles")).toBeInTheDocument();
    });

    const articlesCard = screen.getByTestId("stats-card-articles");
    const classifiedCard = screen.getByTestId("stats-card-classified");
    const eventsCard = screen.getByTestId("stats-card-events");
    const alertsCard = screen.getByTestId("stats-card-alerts");

    // Primary numbers (formatted with thousand separators).
    expect(articlesCard.textContent).toMatch(/37[,\s]?542/);
    expect(classifiedCard.textContent).toMatch(/5[,\s]?812/);
    expect(eventsCard.textContent).toMatch(/501/);
    expect(alertsCard.textContent).toMatch(/365/);

    // Classified card shows the % of total (5812/37542 ≈ 15.5%).
    expect(classifiedCard.textContent).toMatch(/15\.5%/);
  });

  // covers test #4 (req 3.3) — funnel shows correct counts AND drop-off %.
  it("test_pipeline_funnel_counts", async () => {
    vi.spyOn(client, "fetchStats").mockResolvedValue(
      makeStats({
        pipeline_funnel: {
          collected: 1000,
          classified: 200,
          events_created: 50,
          alerts_sent: 10,
        },
      }),
    );

    renderOverview();

    await waitFor(() => {
      expect(screen.getByTestId("pipeline-funnel")).toBeInTheDocument();
    });

    const collected = screen.getByTestId("funnel-stage-collected");
    const classified = screen.getByTestId("funnel-stage-classified");
    const events = screen.getByTestId("funnel-stage-events_created");
    const alerts = screen.getByTestId("funnel-stage-alerts_sent");

    // Counts visible in each row.
    expect(collected.textContent).toMatch(/1,000/);
    expect(classified.textContent).toMatch(/200/);
    expect(events.textContent).toMatch(/50/);
    expect(alerts.textContent).toMatch(/10/);

    // Percent drop-off computed against collected.
    expect(classified.textContent).toMatch(/20\.0%/);
    expect(events.textContent).toMatch(/5\.0%/);
    expect(alerts.textContent).toMatch(/1\.0%/);
  });

  // covers test #5 (req 3.3a) — clicking a funnel stage navigates to the
  // articles page with the appropriate pipeline_status filter.
  it("test_funnel_stage_navigation", async () => {
    vi.spyOn(client, "fetchStats").mockResolvedValue(makeStats());

    const user = userEvent.setup();
    renderOverview();

    await waitFor(() => {
      expect(screen.getByTestId("funnel-stage-classified")).toBeInTheDocument();
    });

    // Each link target is rendered as an <a href>. Click "Classified" and
    // assert we land on /articles?pipeline_status=classified.
    const link = screen.getByTestId("funnel-stage-classified");
    expect(link.getAttribute("href")).toBe(
      "/articles?pipeline_status=classified",
    );
    await user.click(link);
    await waitFor(() => {
      expect(screen.getByTestId("articles-page-stub")).toBeInTheDocument();
    });
    expect(screen.getByTestId("location-search").textContent).toBe(
      "?pipeline_status=classified",
    );
  });
});
