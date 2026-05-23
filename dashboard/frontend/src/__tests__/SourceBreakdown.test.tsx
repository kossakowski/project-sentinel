// Tests for SourceBreakdown — covers test #8 (req 3.6).
//
// Sources must render in count-descending order regardless of the order the
// backend hands them in. We mount with explicit pixel sizing because jsdom
// can't measure a ResponsiveContainer's parent (recharts paints nothing in
// that case).

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { SourceBreakdown } from "../components/SourceBreakdown";

describe("SourceBreakdown", () => {
  // covers test #8 (req 3.6) — sources displayed in descending count order
  // even when the input list arrives in some other order.
  it("test_source_breakdown_sorted", () => {
    const sources = [
      { source_name: "Onet", count: 400 },
      { source_name: "TVN24", count: 200 },
      { source_name: "TASS", count: 300 },
      { source_name: "Rzeczpospolita", count: 100 },
    ];
    const languages = [
      { language: "pl", count: 600 },
      { language: "en", count: 300 },
      { language: "uk", count: 100 },
    ];

    render(
      <SourceBreakdown
        sources={sources}
        languages={languages}
        width={600}
        height={360}
      />,
    );

    const chart = screen.getByTestId("source-breakdown");
    expect(chart).toBeInTheDocument();

    // Recharts renders the y-axis category labels in DOM order. Pull them
    // out in document order and assert descending-count ordering: Onet
    // (400) → TASS (300) → TVN24 (200) → Rzeczpospolita (100).
    const svg = chart.querySelector("svg");
    expect(svg).toBeTruthy();
    const textElements = Array.from(svg!.querySelectorAll("text"));
    const labels = textElements.map((t) => t.textContent ?? "");
    const onetIdx = labels.indexOf("Onet");
    const tassIdx = labels.indexOf("TASS");
    const tvnIdx = labels.indexOf("TVN24");
    const rzpIdx = labels.indexOf("Rzeczpospolita");
    expect(onetIdx).toBeGreaterThanOrEqual(0);
    expect(tassIdx).toBeGreaterThan(onetIdx);
    expect(tvnIdx).toBeGreaterThan(tassIdx);
    expect(rzpIdx).toBeGreaterThan(tvnIdx);

    // Language chips rendered with percentages.
    expect(screen.getByTestId("language-chip-pl")).toBeInTheDocument();
    expect(screen.getByTestId("language-chip-pl").textContent).toMatch(
      /60\.0%/,
    );
    expect(screen.getByTestId("language-chip-en").textContent).toMatch(
      /30\.0%/,
    );
    expect(screen.getByTestId("language-chip-uk").textContent).toMatch(
      /10\.0%/,
    );
  });
});
