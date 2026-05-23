// Tests for EventTimeline — covers tests #13 (req 3.9) and #14 (req 3.9a).

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { EventTimeline } from "../components/EventTimeline";
import { makeAlertRecord, makeEventRecord } from "./fixtures";

describe("EventTimeline", () => {
  // covers test #13 (req 3.9) — timeline renders events with metadata AND
  // their alert_records (SMS / call / WhatsApp glyphs).
  it("test_event_timeline_with_alerts", () => {
    const events = [
      makeEventRecord({
        id: "ev-1",
        event_type: "airspace_violation",
        urgency_score: 8,
        source_count: 3,
        alert_status: "sms_sent",
        first_seen_at: "2026-05-22T10:04:00+00:00",
        last_updated_at: "2026-05-22T10:08:00+00:00",
        alert_records: [
          makeAlertRecord({
            id: "ar-1",
            alert_type: "phone_call",
            status: "completed",
            attempt_number: 1,
            sent_at: "2026-05-22T10:04:30+00:00",
          }),
          makeAlertRecord({
            id: "ar-2",
            alert_type: "sms",
            status: "sent",
            attempt_number: 2,
            sent_at: "2026-05-22T10:05:00+00:00",
          }),
          makeAlertRecord({
            id: "ar-3",
            alert_type: "whatsapp",
            status: "delivered",
            attempt_number: 1,
            sent_at: "2026-05-22T10:06:00+00:00",
          }),
        ],
      }),
    ];

    render(<EventTimeline events={events} />);

    // Wrapper present.
    expect(screen.getByTestId("event-timeline")).toBeInTheDocument();
    const item = screen.getByTestId("event-timeline-item-ev-1");
    expect(item).toBeInTheDocument();
    // Event metadata (type, urgency, status, source count, dates).
    expect(item.textContent).toContain("airspace_violation");
    expect(item.textContent).toContain("Urgency 8");
    expect(item.textContent).toContain("sms_sent");
    expect(item.textContent).toContain("3");
    expect(item.textContent).toContain("2026-05-22T10:04:00+00:00");

    // Alert records visible, one per type.
    const alerts = screen.getByTestId("event-timeline-alerts-ev-1");
    expect(alerts).toBeInTheDocument();
    const ar1 = screen.getByTestId("event-timeline-alert-ar-1");
    const ar2 = screen.getByTestId("event-timeline-alert-ar-2");
    const ar3 = screen.getByTestId("event-timeline-alert-ar-3");
    expect(ar1.textContent).toMatch(/Phone call/);
    expect(ar1.textContent).toMatch(/completed/);
    expect(ar1.textContent).toMatch(/Attempt 1/);
    expect(ar2.textContent).toMatch(/SMS/);
    expect(ar2.textContent).toMatch(/Attempt 2/);
    expect(ar3.textContent).toMatch(/WhatsApp/);

    // Channel glyphs visible.
    expect(ar1.textContent).toContain("📞");
    expect(ar2.textContent).toContain("📱");
    expect(ar3.textContent).toContain("💬");
  });

  // covers test #14 (req 3.9a) — empty events list renders the spec-verbatim
  // "No events" message.
  it("test_event_timeline_empty", () => {
    render(<EventTimeline events={[]} />);

    const empty = screen.getByTestId("event-timeline-empty");
    expect(empty).toBeInTheDocument();
    expect(empty.textContent).toMatch(
      /No events — article did not trigger event creation\./,
    );
    // Timeline item nodes MUST NOT render in this case.
    expect(screen.queryByTestId("event-timeline")).not.toBeInTheDocument();
  });
});
