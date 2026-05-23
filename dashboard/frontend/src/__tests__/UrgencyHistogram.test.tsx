// Tests for UrgencyHistogram — covers test #7 (req 3.5).
//
// The bar colours come from urgencyColor() in components/badges.ts; we assert
// the colour for one bar per tier (low/medium/high/critical) plus the four
// expected hex values from the spec mapping.

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { UrgencyHistogram } from "../components/UrgencyHistogram";
import { urgencyColor } from "../components/badges";

describe("UrgencyHistogram", () => {
  // covers test #7 (req 3.5) — bars are coloured per the 1-4 / 5-6 / 7-8 / 9-10
  // tier mapping. We assert the rendered SVG <path> fill for one bar per tier.
  it("test_urgency_histogram_colors", () => {
    const data = [
      { urgency_score: 1, count: 100 }, // low → gray
      { urgency_score: 2, count: 80 },
      { urgency_score: 3, count: 60 },
      { urgency_score: 4, count: 40 },
      { urgency_score: 5, count: 30 }, // medium → yellow
      { urgency_score: 6, count: 20 },
      { urgency_score: 7, count: 10 }, // high → orange
      { urgency_score: 8, count: 5 },
      { urgency_score: 9, count: 2 }, // critical → red
      { urgency_score: 10, count: 1 },
    ];

    render(<UrgencyHistogram data={data} width={600} height={280} />);

    const chart = screen.getByTestId("urgency-histogram");
    expect(chart).toBeInTheDocument();
    expect(chart.querySelector("svg")).toBeTruthy();

    // Spec-mandated colour mapping for the four tiers.
    expect(urgencyColor(1)).toBe("#64748b");
    expect(urgencyColor(5)).toBe("#f59e0b");
    expect(urgencyColor(7)).toBe("#ea580c");
    expect(urgencyColor(9)).toBe("#dc2626");

    // The Cell components emit <path fill="#xxx"> inside the bar group.
    // Collect every rendered path's fill and confirm we see all four tier
    // colours on the canvas.
    const paths = chart.querySelectorAll("path[fill]");
    const fills = new Set<string>();
    paths.forEach((p) => {
      const fill = p.getAttribute("fill");
      if (fill) fills.add(fill.toLowerCase());
    });
    expect(fills.has(urgencyColor(1).toLowerCase())).toBe(true);
    expect(fills.has(urgencyColor(5).toLowerCase())).toBe(true);
    expect(fills.has(urgencyColor(7).toLowerCase())).toBe(true);
    expect(fills.has(urgencyColor(9).toLowerCase())).toBe(true);
  });
});
