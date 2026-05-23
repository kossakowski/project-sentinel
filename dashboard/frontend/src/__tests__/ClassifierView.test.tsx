// Tests for ClassifierView — covers tests #10, #11, #12.
//
// 3.8  side-by-side input/output
// 3.8a Raw JSON toggle
// 3.8b unclassified-article notice

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ClassifierView } from "../components/ClassifierView";
import { makeArticleDetail, makeClassification } from "./fixtures";

describe("ClassifierView", () => {
  // covers test #10 (req 3.8) — left pane = input, right pane = output.
  it("test_classifier_view_side_by_side", () => {
    const detail = makeArticleDetail({
      classifier_input:
        "Source: TVN24 (rss)\nTitle: Drone over Polish airspace",
      classification: makeClassification({
        urgency_score: 8,
        event_type: "drone_attack",
        confidence: 0.87,
        affected_countries: ["PL"],
        aggressor: "RU",
        summary_pl: "Polski opis",
      }),
    });

    render(<ClassifierView article={detail} />);

    // Both panes mounted.
    const input = screen.getByTestId("classifier-view-input");
    const output = screen.getByTestId("classifier-view-output-formatted");
    expect(input).toBeInTheDocument();
    expect(output).toBeInTheDocument();

    // Input rendered verbatim — the <pre> preserves the spec-mandated
    // line-by-line classifier reconstruction.
    expect(input.textContent).toContain("Source: TVN24 (rss)");
    expect(input.textContent).toContain("Title: Drone over Polish airspace");

    // Output side shows all the required fields.
    expect(screen.getByTestId("classifier-view-urgency").textContent).toBe("8");
    expect(output.textContent).toContain("drone_attack");
    expect(output.textContent).toMatch(/87%/);
    expect(output.textContent).toContain("PL");
    expect(output.textContent).toContain("RU");
    expect(output.textContent).toContain("Polski opis");
  });

  // covers test #11 (req 3.8a) — Raw JSON toggle swaps the formatted view.
  it("test_classifier_view_raw_json_toggle", async () => {
    const classification = makeClassification({
      urgency_score: 7,
      event_type: "airspace_violation",
    });
    const detail = makeArticleDetail({ classification });

    const user = userEvent.setup();
    render(<ClassifierView article={detail} />);

    // Formatted display visible initially.
    expect(
      screen.getByTestId("classifier-view-output-formatted"),
    ).toBeInTheDocument();
    expect(
      screen.queryByTestId("classifier-view-output-raw"),
    ).not.toBeInTheDocument();

    // Click toggle → formatted view disappears, raw JSON appears.
    const toggle = screen.getByTestId("classifier-view-raw-toggle");
    await user.click(toggle);

    expect(
      screen.queryByTestId("classifier-view-output-formatted"),
    ).not.toBeInTheDocument();
    const raw = screen.getByTestId("classifier-view-output-raw");
    expect(raw).toBeInTheDocument();
    // The raw pane shows a JSON.stringify dump of the classification.
    // Comparing parsed JSON tolerates whitespace differences.
    const parsed = JSON.parse(raw.textContent ?? "");
    expect(parsed.urgency_score).toBe(7);
    expect(parsed.event_type).toBe("airspace_violation");

    // Toggle is pressed-state true and labels itself "Formatted" (return path).
    expect(toggle.getAttribute("aria-pressed")).toBe("true");

    // Click again to flip back.
    await user.click(toggle);
    expect(
      screen.getByTestId("classifier-view-output-formatted"),
    ).toBeInTheDocument();
  });

  // covers test #12 (req 3.8b) — articles with classification=null get a
  // single "not classified" notice and NO side-by-side panes.
  it("test_classifier_view_unclassified", () => {
    const detail = makeArticleDetail({ classification: null });

    render(<ClassifierView article={detail} />);

    const notice = screen.getByTestId("classifier-view-unclassified");
    expect(notice).toBeInTheDocument();
    expect(notice.textContent).toMatch(
      /This article was not classified \(filtered out before classification stage\)/,
    );
    // Side-by-side layout MUST NOT render in this case.
    expect(screen.queryByTestId("classifier-view")).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("classifier-view-input"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("classifier-view-output-formatted"),
    ).not.toBeInTheDocument();
  });
});
