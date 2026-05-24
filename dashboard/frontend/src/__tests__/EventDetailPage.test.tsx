// Tests for EventDetailPage — SPEC_ALERT_GROUPING.md Phase 2 acceptance tests
// #10 (renders known event), #11 (404 → not-found UI), #12 (back link uses
// history, not a hardcoded path).

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

import { ApiError } from "../api/client";
import * as client from "../api/client";
import { EventDetailPage } from "../pages/EventDetailPage";
import { ToastProvider } from "../components/Toast";
import { routerFutureFlags } from "../utils/routerFutureFlags";
import {
  makeAlertRecord,
  makeArticle,
  makeEventDetail,
} from "./fixtures";

function LocationProbe() {
  const location = useLocation();
  return (
    <span data-testid="location-pathname">{location.pathname}</span>
  );
}

/** Helper page rendered at ``/articles`` that programmatically navigates
 *  into ``/events/:id`` — used to seed the MemoryRouter history stack with
 *  TWO entries so the "← Back" button's ``navigate(-1)`` has somewhere to
 *  go (test #12). */
function NavigatePushPage({ targetId }: { targetId: string }) {
  const navigate = useNavigate();
  return (
    <button
      type="button"
      data-testid="navigate-to-event"
      onClick={() => navigate(`/events/${targetId}`)}
    >
      Open event
    </button>
  );
}

function renderEventPage(opts: {
  initialEntries?: string[];
  withStartPage?: boolean;
  targetId?: string;
} = {}) {
  const {
    initialEntries = ["/events/ev-1"],
    withStartPage = false,
    targetId = "ev-1",
  } = opts;
  return render(
    <MemoryRouter initialEntries={initialEntries} future={routerFutureFlags}>
      <ToastProvider>
        <Routes>
          <Route
            path="/articles"
            element={
              withStartPage ? (
                <NavigatePushPage targetId={targetId} />
              ) : (
                <div data-testid="articles-landing">Articles list</div>
              )
            }
          />
          <Route
            path="/articles/:id"
            element={<div data-testid="article-detail-page" />}
          />
          <Route path="/events/:id" element={<EventDetailPage />} />
        </Routes>
        <LocationProbe />
      </ToastProvider>
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("EventDetailPage", () => {
  // covers spec 2.4 / 2.4a / 2.5 / 2.5a / 2.5b / 2.5c — full happy-path
  // render: metadata block, article list, alert timeline.
  it("test_event_detail_page_renders_known_event", async () => {
    vi.spyOn(client, "fetchEvent").mockResolvedValue(
      makeEventDetail({
        id: "ev-known-1",
        event_type: "airspace_violation",
        urgency_score: 7,
        affected_countries: ["LV"],
        aggressor: "RU",
        summary_pl: "Polskie podsumowanie zdarzenia.",
        first_seen_at: "2026-05-23T11:01:28+00:00",
        last_updated_at: "2026-05-23T11:23:46+00:00",
        source_count: 4,
        alert_status: "sms_sent",
        articles: [
          makeArticle({
            id: "art-aa",
            title: "First article in time",
            published_at: "2026-05-23T11:00:00+00:00",
            source_name: "TVN24",
            language: "pl",
            event_id: "ev-known-1",
          }),
          makeArticle({
            id: "art-bb",
            title: "Second article in time",
            published_at: "2026-05-23T11:10:00+00:00",
            source_name: "Reuters",
            language: "en",
            event_id: "ev-known-1",
          }),
        ],
        alert_records: [
          makeAlertRecord({
            id: "alert-aa",
            alert_type: "sms",
            status: "sent",
            sent_at: "2026-05-23T11:24:00+00:00",
            message_body: "Polish SMS body, short enough to render fully.",
          }),
        ],
      }),
    );

    renderEventPage({ initialEntries: ["/events/ev-known-1"] });

    await waitFor(() => {
      expect(screen.getByTestId("event-detail")).toBeInTheDocument();
    });

    // Metadata block (spec 2.5a).
    expect(screen.getByTestId("event-detail-id").textContent).toBe("ev-known-1");
    expect(screen.getByTestId("event-detail-type").textContent).toBe(
      "airspace_violation",
    );
    expect(screen.getByTestId("event-detail-urgency").textContent).toContain("7");
    expect(screen.getByTestId("event-detail-country-LV")).toBeInTheDocument();
    expect(screen.getByTestId("event-detail-aggressor").textContent).toBe("RU");
    expect(screen.getByTestId("event-detail-summary").textContent).toBe(
      "Polskie podsumowanie zdarzenia.",
    );
    // Times rendered in Europe/Warsaw (UTC+2 CEST on 2026-05-23).
    expect(screen.getByTestId("event-detail-first-seen").textContent).toBe(
      "2026-05-23 13:01",
    );
    expect(screen.getByTestId("event-detail-last-updated").textContent).toBe(
      "2026-05-23 13:23",
    );
    expect(screen.getByTestId("event-detail-source-count").textContent).toBe("4");
    expect(screen.getByTestId("event-detail-alert-status").textContent).toBe(
      "sms_sent",
    );

    // Article list (spec 2.5b) — both articles present, each title links to
    // /articles/<id>.
    expect(screen.getByTestId("event-detail-articles")).toBeInTheDocument();
    expect(
      screen.getByTestId("event-detail-article-art-aa"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("event-detail-article-art-bb"),
    ).toBeInTheDocument();
    const firstArticleLink = screen.getByTestId(
      "event-detail-article-link-art-aa",
    );
    expect(firstArticleLink.getAttribute("href")).toBe("/articles/art-aa");

    // Alert timeline (spec 2.5c) — one record rendered with its metadata.
    expect(
      screen.getByTestId("event-detail-alert-timeline"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("event-detail-alert-alert-aa"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("event-detail-alert-body-alert-aa").textContent,
    ).toContain("Polish SMS body");
  });

  // covers spec 2.4b — 404 from the API renders the not-found UI.
  it("test_event_detail_page_renders_not_found_for_404", async () => {
    vi.spyOn(client, "fetchEvent").mockRejectedValue(
      new ApiError("404 event not found", 404, { error: "event not found" }, "/api/events/missing"),
    );

    renderEventPage({ initialEntries: ["/events/missing"] });

    await waitFor(() => {
      expect(screen.getByTestId("event-detail-not-found")).toBeInTheDocument();
    });
    // The not-found UI mentions the missing id so the user can copy/paste it.
    expect(
      screen.getByTestId("event-detail-not-found").textContent,
    ).toContain("missing");
    // The standard rendered-event testid is NOT present.
    expect(screen.queryByTestId("event-detail")).not.toBeInTheDocument();
  });

  // covers spec 2.5d — "← Back" uses navigate(-1), not a Link with a
  // hardcoded path. We test this BEHAVIOURALLY: seed the router with two
  // entries (start at /articles → push to /events/<id>), click Back, and
  // assert we land back on /articles.
  it("test_event_detail_page_back_link_uses_history", async () => {
    vi.spyOn(client, "fetchEvent").mockResolvedValue(
      makeEventDetail({ id: "ev-history" }),
    );

    const user = userEvent.setup();
    renderEventPage({
      initialEntries: ["/articles"],
      withStartPage: true,
      targetId: "ev-history",
    });

    // Programmatically navigate from the start page to the event detail —
    // adds a second entry to the history stack (so navigate(-1) has somewhere
    // to go back to, mimicking the production flow where the user clicked an
    // event indicator from /articles).
    await user.click(screen.getByTestId("navigate-to-event"));

    await waitFor(() => {
      expect(screen.getByTestId("event-detail")).toBeInTheDocument();
    });

    const backButton = screen.getByTestId("event-detail-back-link");
    // The back link MUST be a <button>, NOT an <a> with a hardcoded href —
    // spec 2.5d says it uses history.back semantics. An anchor would have a
    // tagname of "a" and an href attribute.
    expect(backButton.tagName.toLowerCase()).toBe("button");
    expect(backButton.hasAttribute("href")).toBe(false);

    // Clicking the back button should pop the history stack, landing us at
    // /articles.
    await user.click(backButton);
    await waitFor(() => {
      expect(screen.getByTestId("location-pathname").textContent).toBe(
        "/articles",
      );
    });
  });
});
