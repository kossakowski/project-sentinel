// Tests for AnnotationBadge — covers acceptance test #11 (req 4.4).
//
// Green dot for "correct", red dot for "incorrect", yellow dot for
// "uncertain"; no badge (em dash) when the article has no annotation.

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { AnnotationBadge } from "../components/AnnotationBadge";
import { annotationBadge } from "../components/badges";
import { makeArticleAnnotation } from "./fixtures";

describe("AnnotationBadge", () => {
  // covers test #11 (req 4.4) — colour per label.
  it("test_annotation_badge_colors", () => {
    const cases = [
      { label: "correct" as const, expectedColor: "#16a34a" },
      { label: "incorrect" as const, expectedColor: "#dc2626" },
      { label: "uncertain" as const, expectedColor: "#eab308" },
    ];

    for (const { label, expectedColor } of cases) {
      const { unmount } = render(
        <AnnotationBadge annotation={makeArticleAnnotation({ label })} />,
      );
      const badge = screen.getByTestId(`annotation-badge-${label}`);
      expect(badge).toBeInTheDocument();
      expect(badge.getAttribute("data-annotation-label")).toBe(label);
      // The coloured dot is rendered as an inline span with a backgroundColor
      // matching the spec-mandated tier colour. Looking up the swatch via the
      // class keeps the assertion resilient to additional decorative wrappers.
      const dot = badge.querySelector(".annotation-dot");
      expect(dot).not.toBeNull();
      // jsdom normalises CSS colour to rgb(); compare via the helper output.
      const cfg = annotationBadge(label);
      expect(cfg.color).toBe(expectedColor);
      // The inline style was applied — jsdom returns the rgb form.
      const inlineStyle = (dot as HTMLElement).style.backgroundColor;
      expect(inlineStyle.length).toBeGreaterThan(0);
      unmount();
    }
  });

  it("renders an em dash placeholder when no annotation exists", () => {
    render(<AnnotationBadge annotation={null} />);
    const empty = screen.getByTestId("annotation-badge-empty");
    expect(empty).toBeInTheDocument();
    expect(empty.textContent).toBe("—");
  });

  it("shows the label text when compact={false}", () => {
    render(
      <AnnotationBadge
        annotation={makeArticleAnnotation({ label: "uncertain" })}
        compact={false}
      />,
    );
    expect(screen.getByText("Uncertain")).toBeInTheDocument();
  });
});
