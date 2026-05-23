// Tests for ArticleTable — covers reqs 2.2, 2.2a, 2.2b, 2.2d, 2.2e.

import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { ArticleTable } from "../components/ArticleTable";
import {
  DEFAULT_VISIBLE_COLUMNS,
  type ColumnKey,
} from "../components/columns";
import { urgencyClass, pipelineStatusBadge } from "../components/badges";
import type { SortColumn } from "../types";
import { makeArticle, makeUnclassifiedArticle } from "./fixtures";

function renderTable(props: {
  visibleColumns?: ReadonlyArray<ColumnKey>;
  onSortChange?: (col: SortColumn) => void;
} = {}) {
  const onSortChange = props.onSortChange ?? vi.fn();
  const article = makeArticle();
  const unclassified = makeUnclassifiedArticle({
    classification: null,
    pipeline_status: "unclassified",
  });
  const utils = render(
    <MemoryRouter>
      <ArticleTable
        articles={[article, unclassified]}
        visibleColumns={props.visibleColumns ?? DEFAULT_VISIBLE_COLUMNS}
        sort="published_at"
        order="desc"
        onSortChange={onSortChange}
      />
    </MemoryRouter>,
  );
  return { ...utils, onSortChange };
}

describe("ArticleTable", () => {
  // covers 2.2
  it("test_article_table_renders", () => {
    renderTable();
    expect(screen.getByText("Article one")).toBeInTheDocument();
    expect(screen.getByText("Unclassified article")).toBeInTheDocument();
    // Article title link points at /articles/:id (req 2.2c) — sanity-checked here.
    const link = screen.getByText("Article one").closest("a");
    expect(link).toHaveAttribute("href", "/articles/art-1");
  });

  // covers 2.2
  it("test_column_sorting", async () => {
    const onSortChange = vi.fn();
    const user = userEvent.setup();
    renderTable({ onSortChange });

    const urgencyHeader = screen.getByRole("button", { name: /sort by urgency/i });
    await user.click(urgencyHeader);
    expect(onSortChange).toHaveBeenCalledWith("urgency_score");

    const publishedHeader = screen.getByRole("button", { name: /sort by published/i });
    await user.click(publishedHeader);
    expect(onSortChange).toHaveBeenLastCalledWith("published_at");
  });

  // covers 2.2a
  it("test_default_columns", () => {
    renderTable();
    const headers = screen.getAllByRole("columnheader");
    const headerLabels = headers
      .map((h) => h.textContent ?? "")
      .filter((t) => t.trim().length > 0)
      .map((t) => t.replace(/[▲▼]/g, "").trim());
    expect(headerLabels).toEqual([
      "Published",
      "Title",
      "Source",
      "Lang",
      "Urgency",
      "Event type",
      "Status",
    ]);
    // Sanity: default list itself matches the spec.
    expect(DEFAULT_VISIBLE_COLUMNS).toEqual([
      "published_at",
      "title",
      "source_name",
      "language",
      "urgency_score",
      "event_type",
      "pipeline_status",
    ]);
  });

  // covers 2.2b
  it("test_expandable_row", async () => {
    const user = userEvent.setup();
    renderTable();

    // Before click: no expanded detail in the DOM.
    expect(screen.queryByTestId("article-detail")).not.toBeInTheDocument();

    const expandButtons = screen.getAllByRole("button", { name: /expand row/i });
    await user.click(expandButtons[0]);

    const detail = screen.getByTestId("article-detail");
    expect(within(detail).getByText("Summary")).toBeInTheDocument();
    expect(within(detail).getByText("Body of article one with details.")).toBeInTheDocument();
    // Classification block surfaces nested classifier output.
    expect(within(detail).getByText("Classification")).toBeInTheDocument();
    expect(within(detail).getByText("airspace_violation")).toBeInTheDocument();
    // Source URL link (req 2.2b).
    expect(within(detail).getByText(/open source/i)).toHaveAttribute(
      "href",
      "https://example.test/article-1",
    );

    // Toggle closes the expansion.
    await user.click(screen.getByRole("button", { name: /collapse row/i }));
    expect(screen.queryByTestId("article-detail")).not.toBeInTheDocument();
  });

  // covers 2.2d
  it("test_urgency_color_coding", () => {
    expect(urgencyClass(null)).toBeNull();
    expect(urgencyClass(undefined)).toBeNull();
    expect(urgencyClass(1)).toBe("urgency-low");
    expect(urgencyClass(4)).toBe("urgency-low");
    expect(urgencyClass(5)).toBe("urgency-medium");
    expect(urgencyClass(6)).toBe("urgency-medium");
    expect(urgencyClass(7)).toBe("urgency-high");
    expect(urgencyClass(8)).toBe("urgency-high");
    expect(urgencyClass(9)).toBe("urgency-critical");
    expect(urgencyClass(10)).toBe("urgency-critical");

    render(
      <MemoryRouter>
        <ArticleTable
          articles={[
            makeArticle({
              id: "art-9",
              classification: { ...makeArticle().classification!, urgency_score: 9 },
            }),
            makeArticle({
              id: "art-3",
              classification: { ...makeArticle().classification!, urgency_score: 3 },
            }),
            makeUnclassifiedArticle({ id: "art-uncls" }),
          ]}
          visibleColumns={["title", "urgency_score"]}
          sort="published_at"
          order="desc"
          onSortChange={() => {}}
        />
      </MemoryRouter>,
    );
    // Only look at tbody cells — the th carries `col-urgency_score` too but is
    // not where the colour code is meant to land.
    const urgencyCells = document.querySelectorAll("tbody td.col-urgency_score");
    expect(urgencyCells[0].className).toContain("urgency-critical");
    expect(urgencyCells[1].className).toContain("urgency-low");
    expect(urgencyCells[2].className).not.toContain("urgency-");
    expect(urgencyCells[2].textContent).toBe("—");
  });

  // Defense-in-depth against XSS via untrusted source_url (F7 from review).
  it("renders unsafe source URLs as plain text", async () => {
    const user = userEvent.setup();
    const malicious = makeArticle({
      id: "art-evil",
      title: "Suspicious article",
      source_url: "javascript:alert(1)",
    });

    render(
      <MemoryRouter>
        <ArticleTable
          articles={[malicious]}
          visibleColumns={["title", "source_url"]}
          sort="published_at"
          order="desc"
          onSortChange={() => {}}
        />
      </MemoryRouter>,
    );

    // The source_url column renders the raw value as plain text (no anchor)
    // when the scheme is not http(s).
    const unsafeSpan = screen.getByTestId("source-url-unsafe");
    expect(unsafeSpan.tagName.toLowerCase()).toBe("span");
    expect(unsafeSpan).toHaveTextContent("javascript:alert(1)");

    // Expand row — the detail's "Open source" link must also fall back to a
    // plain-text span instead of a real <a>.
    await user.click(screen.getByRole("button", { name: /expand row/i }));
    expect(
      screen.getByTestId("article-source-link-unsafe"),
    ).toHaveTextContent("javascript:alert(1)");
    expect(screen.queryByText(/open source/i)).not.toBeInTheDocument();
  });

  // covers 2.2e
  it("test_pipeline_status_badges", () => {
    expect(pipelineStatusBadge("unclassified")).toEqual({
      label: "Unclassified",
      className: "badge badge-unclassified",
    });
    expect(pipelineStatusBadge("classified")).toEqual({
      label: "Classified",
      className: "badge badge-classified",
    });
    expect(pipelineStatusBadge("event_created")).toEqual({
      label: "Event",
      className: "badge badge-event",
    });
    expect(pipelineStatusBadge("alert_sent")).toEqual({
      label: "Alert",
      className: "badge badge-alert",
    });

    render(
      <MemoryRouter>
        <ArticleTable
          articles={[
            makeArticle({ id: "a1", pipeline_status: "alert_sent" }),
            makeArticle({ id: "a2", pipeline_status: "event_created" }),
            makeArticle({ id: "a3", pipeline_status: "classified" }),
            makeUnclassifiedArticle({ id: "a4" }),
          ]}
          visibleColumns={["title", "pipeline_status"]}
          sort="published_at"
          order="desc"
          onSortChange={() => {}}
        />
      </MemoryRouter>,
    );
    const badges = screen.getAllByTestId("pipeline-badge");
    expect(badges).toHaveLength(4);
    expect(badges[0]).toHaveTextContent("Alert");
    expect(badges[0]).toHaveClass("badge-alert");
    expect(badges[1]).toHaveTextContent("Event");
    expect(badges[1]).toHaveClass("badge-event");
    expect(badges[2]).toHaveTextContent("Classified");
    expect(badges[2]).toHaveClass("badge-classified");
    expect(badges[3]).toHaveTextContent("Unclassified");
    expect(badges[3]).toHaveClass("badge-unclassified");
  });
});
