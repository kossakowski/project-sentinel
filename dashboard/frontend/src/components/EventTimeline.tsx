// Vertical timeline of events + alert records for an article (req 3.9, 3.9a).
//
// Each event renders its metadata (type, urgency, alert_status, source count,
// first-seen / last-updated) and a nested list of alert_records with
// SMS/call/WhatsApp icons. Empty list → spec-mandated "No events" message.

import type { AlertRecord, EventRecord } from "../types";
import { urgencyClass } from "./badges";
import { formatWarsaw } from "../utils/datetime";

interface EventTimelineProps {
  events: EventRecord[];
}

/** Unicode symbol for each alert channel — keeps the dependency tree tiny.
 *
 *  📱 mobile phone (SMS), 📞 telephone receiver (call), 💬 chat balloon (WhatsApp).
 *  Spec req 3.9 mentions SMS/call/WhatsApp icons; emoji glyphs are accessible
 *  (real Unicode characters, screen readers announce them) and ship with
 *  every modern OS, so no icon library is needed. */
const ALERT_TYPE_ICON: Record<AlertRecord["alert_type"], string> = {
  sms: "📱",
  phone_call: "📞",
  whatsapp: "💬",
};

const ALERT_TYPE_LABEL: Record<AlertRecord["alert_type"], string> = {
  sms: "SMS",
  phone_call: "Phone call",
  whatsapp: "WhatsApp",
};

export function EventTimeline({ events }: EventTimelineProps) {
  if (events.length === 0) {
    // Spec req 3.9a — explicit empty-state message.
    return (
      <section
        className="event-timeline event-timeline-empty"
        aria-label="Event timeline"
        data-testid="event-timeline-empty"
      >
        <h3 className="overview-section-heading">Events</h3>
        <p className="event-timeline-empty-message">
          No events — article did not trigger event creation.
        </p>
      </section>
    );
  }

  return (
    <section
      className="event-timeline"
      aria-label="Event timeline"
      data-testid="event-timeline"
    >
      <h3 className="overview-section-heading">Events</h3>
      <ol className="event-timeline-list">
        {events.map((event) => (
          <li
            key={event.id}
            className="event-timeline-item"
            data-testid={`event-timeline-item-${event.id}`}
          >
            <header className="event-timeline-item-header">
              <span className="event-timeline-event-type">{event.event_type}</span>
              <span
                className={`event-timeline-urgency ${urgencyClass(event.urgency_score) ?? ""}`}
              >
                Urgency {event.urgency_score}
              </span>
              <span
                className="event-timeline-status"
                data-testid={`event-timeline-status-${event.id}`}
              >
                {event.alert_status}
              </span>
            </header>
            <dl className="event-timeline-meta">
              <dt>Sources</dt>
              <dd>{event.source_count}</dd>
              <dt>First seen</dt>
              <dd>{formatWarsaw(event.first_seen_at)}</dd>
              <dt>Last updated</dt>
              <dd>{formatWarsaw(event.last_updated_at)}</dd>
            </dl>
            {event.alert_records.length === 0 ? (
              <p
                className="event-timeline-no-alerts"
                data-testid={`event-timeline-no-alerts-${event.id}`}
              >
                No alert records.
              </p>
            ) : (
              <ul
                className="event-timeline-alerts"
                aria-label="Alert records"
                data-testid={`event-timeline-alerts-${event.id}`}
              >
                {event.alert_records.map((alert) => (
                  <li
                    key={alert.id}
                    className="event-timeline-alert"
                    data-testid={`event-timeline-alert-${alert.id}`}
                  >
                    <span
                      className="event-timeline-alert-icon"
                      aria-label={ALERT_TYPE_LABEL[alert.alert_type] ?? alert.alert_type}
                      role="img"
                    >
                      {ALERT_TYPE_ICON[alert.alert_type] ?? "•"}
                    </span>
                    <span className="event-timeline-alert-type">
                      {ALERT_TYPE_LABEL[alert.alert_type] ?? alert.alert_type}
                    </span>
                    <span className="event-timeline-alert-status">{alert.status}</span>
                    <span className="event-timeline-alert-sent">{formatWarsaw(alert.sent_at)}</span>
                    <span className="event-timeline-alert-attempt">
                      Attempt {alert.attempt_number}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ol>
    </section>
  );
}
