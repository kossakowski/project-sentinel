// Tests for ArticleTable — covers reqs 2.2, 2.2a, 2.2b, 2.2d, 2.2e.

import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { ArticleTable } from "../components/ArticleTable";
import {
  DEFAULT_VISIBLE_COLUMNS,
  type ColumnKey,
} from "../components/columns";
import { urgencyClass, pipelineStatusBadge } from "../components/badges";
import type { ArticleDetail, SortColumn, SortOrder } from "../types";
import { makeArticle, makeUnclassifiedArticle } from "./fixtures";
import { routerFutureFlags } from "../utils/routerFutureFlags";

function makeDetail(overrides: Partial<ArticleDetail> = {}): ArticleDetail {
  const base = makeArticle();
  return {
    ...base,
    raw_metadata: {
      keyword_match: "drone",
      source_kind: "rss",
      original_url: "https://example.test/article-1",
    },
    events: [],
    classifier_input:
      "Source: TVN24 (rss)\nLanguage: pl\nPublished: 2026-05-22T10:00:00+00:00\nTitle: Article one\nSummary: Body of article one with details.",
    ...overrides,
  };
}

function renderTable(props: {
  visibleColumns?: ReadonlyArray<ColumnKey>;
  onSortChange?: (col: SortColumn) => void;
  sort?: SortColumn | null;
  order?: SortOrder | null;
  fetchDetail?: (id: string) => Promise<ArticleDetail>;
} = {}) {
  const onSortChange = props.onSortChange ?? vi.fn();
  const article = makeArticle();
  const unclassified = makeUnclassifiedArticle({
    classification: null,
    pipeline_status: "unclassified",
  });
  // Default detail fetcher returns a fixture-based detail for any id, so the
  // test rig doesn't have to mock fetch globally just to satisfy the expand.
  const defaultFetcher = (id: string) =>
    Promise.resolve(makeDetail({ id }));
  const utils = render(
    <MemoryRouter future={routerFutureFlags}>
      <ArticleTable
        articles={[article, unclassified]}
        visibleColumns={props.visibleColumns ?? DEFAULT_VISIBLE_COLUMNS}
        sort={props.sort === undefined ? "published_at" : props.sort}
        order={props.order === undefined ? "desc" : props.order}
        onSortChange={onSortChange}
        fetchDetail={props.fetchDetail ?? defaultFetcher}
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
      "Note",
    ]);
    // Sanity: default list itself matches the spec (Phase 4 req 4.4a adds
    // the annotation column to the defaults).
    expect(DEFAULT_VISIBLE_COLUMNS).toEqual([
      "published_at",
      "title",
      "source_name",
      "language",
      "urgency_score",
      "event_type",
      "pipeline_status",
      "annotation",
    ]);
  });

  // covers 2.2b
  it("test_expandable_row", async () => {
    const user = userEvent.setup();
    const fetchDetail = vi.fn((id: string) =>
      Promise.resolve(
        makeDetail({
          id,
          raw_metadata: {
            keyword_match: "drone",
            ingest_method: "rss",
          },
        }),
      ),
    );
    renderTable({ fetchDetail });

    // Before click: no expanded detail in the DOM.
    expect(screen.queryByTestId("article-detail")).not.toBeInTheDocument();
    expect(fetchDetail).not.toHaveBeenCalled();

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

    // Lazy-fetch was triggered exactly once for this row.
    expect(fetchDetail).toHaveBeenCalledTimes(1);
    expect(fetchDetail).toHaveBeenCalledWith(
      "art-1",
      expect.objectContaining({ signal: expect.any(Object) }),
    );

    // After the fetch resolves, raw_metadata renders as pretty-printed JSON.
    await waitFor(() => {
      expect(screen.getByTestId("article-raw-metadata")).toBeInTheDocument();
    });
    const metaBlock = screen.getByTestId("article-raw-metadata");
    expect(metaBlock.textContent).toContain("keyword_match");
    expect(metaBlock.textContent).toContain("drone");
    expect(metaBlock.textContent).toContain("ingest_method");

    // Toggle closes the expansion.
    await user.click(screen.getByRole("button", { name: /collapse row/i }));
    expect(screen.queryByTestId("article-detail")).not.toBeInTheDocument();

    // Re-expand the same row: detail is cached, no second fetch.
    await user.click(
      screen.getAllByRole("button", { name: /expand row/i })[0],
    );
    expect(fetchDetail).toHaveBeenCalledTimes(1);
    // The cached raw_metadata is rendered without a loading flash.
    expect(screen.getByTestId("article-raw-metadata")).toBeInTheDocument();
  });

  // covers 2.2b: lazy-fetch failure surfaces an inline error block.
  it("renders an inline error when raw_metadata fetch fails", async () => {
    const user = userEvent.setup();
    const fetchDetail = vi.fn(() => Promise.reject(new Error("503 boom")));
    renderTable({ fetchDetail });

    await user.click(
      screen.getAllByRole("button", { name: /expand row/i })[0],
    );

    await waitFor(() => {
      expect(
        screen.getByTestId("article-raw-metadata-error"),
      ).toBeInTheDocument();
    });
    expect(
      screen.getByTestId("article-raw-metadata-error").textContent,
    ).toContain("503 boom");
  });

  // covers 2.2: no sort indicator MUST appear when no column is sorted (the
  // converse of "the currently sorted column MUST show a directional
  // indicator" — under FTS rank ordering no column is "sorted" at all).
  it("renders no sort indicator when sort is null", () => {
    renderTable({ sort: null, order: null });
    // No header should carry the ▲/▼ arrow.
    const indicators = document.querySelectorAll(".col-sort-indicator");
    expect(indicators.length).toBe(0);
    // The published_at header (sortable) is still rendered as a button.
    const published = screen.getByRole("button", { name: /sort by published/i });
    expect(published.getAttribute("aria-pressed")).toBe("false");
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
      <MemoryRouter future={routerFutureFlags}>
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
      <MemoryRouter future={routerFutureFlags}>
        <ArticleTable
          articles={[malicious]}
          visibleColumns={["title", "source_url"]}
          sort="published_at"
          order="desc"
          onSortChange={() => {}}
          fetchDetail={(id) => Promise.resolve(makeDetail({ id }))}
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
      <MemoryRouter future={routerFutureFlags}>
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
