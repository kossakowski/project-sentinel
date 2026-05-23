// Tests for ArticleDetailPage — covers test #9 (3.7a) and test #15 (3.10).

import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  MemoryRouter,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";

import * as client from "../api/client";
import { ArticleDetailPage } from "../pages/ArticleDetailPage";
import { ToastProvider } from "../components/Toast";
import { routerFutureFlags } from "../utils/routerFutureFlags";
import { makeArticleDetail, makeEventRecord } from "./fixtures";

function LocationProbe() {
  const location = useLocation();
  return (
    <span data-testid="location-search">
      {location.pathname}
      {location.search}
    </span>
  );
}

/** Test helper page that programmatically navigates to a detail URL with a
 *  preset location.state.from — mimicking what ArticleTable's title Link
 *  does on click. We use a button so userEvent drives the navigation, which
 *  is the closest thing to the production flow. */
function StubArticlesPage({ targetId, from }: { targetId: string; from: string }) {
  const navigate = useNavigate();
  return (
    <button
      type="button"
      onClick={() => navigate(`/articles/${targetId}`, { state: { from } })}
      data-testid="open-detail"
    >
      Open detail
    </button>
  );
}

function renderDetail(opts: {
  initial?: string[];
  fromForOpen?: string;
  targetId?: string;
} = {}) {
  const { initial = ["/articles/art-1"], fromForOpen, targetId } = opts;
  return render(
    <MemoryRouter initialEntries={initial} future={routerFutureFlags}>
      <ToastProvider>
        <Routes>
          <Route
            path="/articles"
            element={
              fromForOpen && targetId ? (
                <StubArticlesPage targetId={targetId} from={fromForOpen} />
              ) : (
                <div data-testid="articles-landing">Articles list</div>
              )
            }
          />
          <Route path="/articles/:id" element={<ArticleDetailPage />} />
        </Routes>
        <LocationProbe />
      </ToastProvider>
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ArticleDetailPage", () => {
  // covers test #9 (req 3.7a) — header shows title, source (link), dates,
  // language badge, pipeline-status badge.
  it("test_article_detail_header", async () => {
    vi.spyOn(client, "fetchArticleDetail").mockResolvedValue(
      makeArticleDetail({
        id: "art-detail-1",
        title: "Drone attack near border",
        source_name: "TVN24",
        source_url: "https://example.test/drone-attack",
        published_at: "2026-05-22T10:00:00+00:00",
        fetched_at: "2026-05-22T10:03:00+00:00",
        language: "pl",
        pipeline_status: "alert_sent",
      }),
    );

    renderDetail({ initial: ["/articles/art-detail-1"] });

    await waitFor(() => {
      expect(screen.getByTestId("article-detail")).toBeInTheDocument();
    });
    // Title.
    expect(screen.getByTestId("article-detail-title").textContent).toBe(
      "Drone attack near border",
    );
    // Source name rendered as an external link to source_url.
    const sourceLink = screen.getByTestId("article-detail-source-link");
    expect(sourceLink).toBeInTheDocument();
    expect(sourceLink.getAttribute("href")).toBe(
      "https://example.test/drone-attack",
    );
    expect(sourceLink.getAttribute("target")).toBe("_blank");
    // Dates rendered verbatim.
    expect(screen.getByTestId("article-detail-published").textContent).toBe(
      "2026-05-22T10:00:00+00:00",
    );
    expect(screen.getByTestId("article-detail-fetched").textContent).toBe(
      "2026-05-22T10:03:00+00:00",
    );
    // Language badge displays uppercase code.
    expect(
      screen.getByTestId("article-detail-language-badge").textContent,
    ).toBe("PL");
    // Pipeline status badge for alert_sent → "Alert".
    expect(
      screen.getByTestId("article-detail-pipeline-badge").textContent,
    ).toBe("Alert");
  });

  // covers test #15 (req 3.10) — back link preserves prior filter state
  // when the user came from /articles?... and falls back to /articles when
  // opened directly.
  it("test_navigation_back_preserves_state", async () => {
    vi.spyOn(client, "fetchArticleDetail").mockResolvedValue(
      makeArticleDetail({
        id: "art-detail-2",
        events: [makeEventRecord({ alert_records: [] })],
      }),
    );

    const user = userEvent.setup();
    renderDetail({
      initial: ["/articles?q=drone&tab=classified&page=3"],
      fromForOpen: "/articles?q=drone&tab=classified&page=3",
      targetId: "art-detail-2",
    });

    // Click the stub button to navigate into the detail route with the
    // matching location.state.from.
    await user.click(screen.getByTestId("open-detail"));

    await waitFor(() => {
      expect(screen.getByTestId("article-detail")).toBeInTheDocument();
    });
    const backLink = screen.getByTestId("article-detail-back-link");
    expect(backLink.getAttribute("href")).toBe(
      "/articles?q=drone&tab=classified&page=3",
    );

    // Direct visit (no location.state): back link falls back to /articles.
    vi.restoreAllMocks();
    vi.spyOn(client, "fetchArticleDetail").mockResolvedValue(
      makeArticleDetail({ id: "art-detail-3" }),
    );
    renderDetail({ initial: ["/articles/art-detail-3"] });
    await waitFor(() => {
      expect(screen.getByTestId("article-detail")).toBeInTheDocument();
    });
    const fallback = screen.getAllByTestId("article-detail-back-link").at(-1);
    expect(fallback?.getAttribute("href")).toBe("/articles");
  });
});
