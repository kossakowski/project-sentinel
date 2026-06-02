/**
 * Typed message model for the in-app inbox.
 *
 * `StoredMessage` is the on-device persisted shape (Appendix B of the spec): the
 * normalized, render-ready alert. `PushPayload` is the raw `data` object that
 * arrives inside an Expo push (Appendix A, Phase 1 contract) — every field is
 * optional/loose because a push may be a full enriched payload or a legacy thin
 * one, so the parser must defend against missing keys rather than trust the shape.
 */

/** A single article source as it renders in the Detail screen. */
export type MessageSource = {
  name: string;
  title: string;
  url: string | null;
};

/**
 * The on-device, render-ready message. The store persists an array of these
 * under a single AsyncStorage key (2.4). `aggressor` is a string (`''` = none),
 * never null — matching the server data model.
 */
export type StoredMessage = {
  message_id: string; // dedup key (data.message_id; fallbacks per 2.3)
  event_id: string | null;
  kind: 'event' | 'update';
  event_type: string | null;
  event_type_pl: string; // display title; falls back to push title or '(alert)'
  urgency_score: number | null;
  affected_countries: string[];
  aggressor: string; // '' means none (never null — matches server model)
  summary_pl: string; // full; falls back to push body / '' (2.3a)
  sources: MessageSource[]; // [] when absent
  sms_body: string; // trimmed SMS mirror; falls back to push body / '' (2.3a)
  first_seen_at: string | null; // UTC ISO from server
  received_at: string; // UTC ISO, set on-device at ingest
  read: boolean; // false on first ingest
};

/**
 * The raw `data` dict carried inside a push (Appendix A). Every field is loose
 * because the payload may be a full enriched push, a legacy thin push, or — in
 * the worst case — `{}`. `parsePayload` is responsible for normalizing this into
 * a `StoredMessage`; it must never assume any key is present.
 */
export type PushPayload = {
  message_id?: unknown;
  event_id?: unknown;
  kind?: unknown;
  event_type?: unknown;
  event_type_pl?: unknown;
  urgency_score?: unknown;
  affected_countries?: unknown;
  aggressor?: unknown;
  summary_pl?: unknown;
  sources?: unknown;
  sms_body?: unknown;
  first_seen_at?: unknown;
  [key: string]: unknown;
};
