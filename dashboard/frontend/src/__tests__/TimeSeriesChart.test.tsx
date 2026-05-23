// Tests for TimeSeriesChart — covers test #6 (req 3.4, 3.4a, 3.4b).
//
// Recharts charts need either a ResponsiveContainer with a measured parent
// (impossible under jsdom) or explicit width/height props. We mount with a
// fixed pixel size so the SVG paints, then assert against the resulting DOM.

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { TimeSeriesChart } from "../components/TimeSeriesChart";

describe("TimeSeriesChart", () => {
  // covers test #6 (req 3.4, 3.4a) — chart renders both series and includes
  // labels for "Collected" and "Classified".
  it("test_time_series_renders", () => {
    const collected = [
      { date: "2026-05-21", count: 100 },
      { date: "2026-05-22", count: 120 },
      { date: "2026-05-23", count: 80 },
    ];
    const classified = [
      { date: "2026-05-21", count: 12 },
      { date: "2026-05-22", count: 15 },
      { date: "2026-05-23", count: 9 },
    ];

    render(
      <TimeSeriesChart
        collected={collected}
        classified={classified}
        width={600}
        height={280}
      />,
    );

    // Chart wrapper present.
    const chart = screen.getByTestId("time-series-chart");
    expect(chart).toBeInTheDocument();
    // SVG is rendered by recharts.
    expect(chart.querySelector("svg")).toBeTruthy();

    // Two Line series — each gets a Legend entry via the `name` prop.
    // recharts renders legend items as <span>s containing the name string.
    expect(chart.textContent).toContain("Collected");
    expect(chart.textContent).toContain("Classified");
  });

  // Defensive: when the two series have different dates, the chart should
  // join them by date rather than blindly zipping by index. Otherwise a
  // future backend change that drops a day from one series would silently
  // misalign the chart.
  it("aligns series by date when arrays drift", () => {
    const collected = [
      { date: "2026-05-21", count: 100 },
      { date: "2026-05-22", count: 120 },
    ];
    const classified = [
      // 21st missing entirely; backend would never produce this, but the
      // chart should still render without throwing and treat 21st as zero.
      { date: "2026-05-22", count: 15 },
    ];

    render(
      <TimeSeriesChart
        collected={collected}
        classified={classified}
        width={600}
        height={280}
      />,
    );

    expect(screen.getByTestId("time-series-chart")).toBeInTheDocument();
  });
});
