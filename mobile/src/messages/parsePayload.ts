/**
 * Payload parsing: normalize a push `data` object (Appendix A) into a render-ready
 * `StoredMessage` (Appendix B), plus adapters that extract `data` from each of the
 * two capture shapes the app sees.
 *
 * Design rules (spec 2.3 / 2.3a / 2.3b):
 *  - `parsePayload` MUST NEVER throw and MUST always produce a non-empty
 *    `message_id`.
 *  - The dedup id is `data.message_id`, falling back to `data.event_id`, then
 *    `meta.osIdentifier`, then a per-delivery synthesized key.
 *  - When structured fields are present they are used; when absent (a legacy thin
 *    push) the message still renders via documented fallbacks.
 *  - The headless background shape is assumed-from-docs and unverified on-device,
 *    so its adapter is fully defensive and logs the raw shape on first invocation.
 */

import type { MessageSource, PushPayload, StoredMessage } from './types';

/** Metadata the caller supplies alongside the raw `data`. */
export type ParseMeta = {
  /** Push title (`request.content.title`) — may be null. */
  title: string | null;
  /** Push body (`request.content.body`) — may be null. */
  body: string | null;
  /** OS-generated delivery identifier, used only as a dedup fallback. */
  osIdentifier?: string | null;
  /** Ingest timestamp in ms; defaults to `Date.now()`. */
  receivedAtMs?: number;
};

/** Monotonic-ish counter to disambiguate two synth keys minted in the same ms. */
let synthCounter = 0;

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0;
}

function asString(value: unknown, fallback: string): string {
  return typeof value === 'string' ? value : fallback;
}

function asStringOrNull(value: unknown): string | null {
  return typeof value === 'string' ? value : null;
}

function asNumberOrNull(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((v): v is string => typeof v === 'string');
}

function asKind(value: unknown): 'event' | 'update' {
  return value === 'update' ? 'update' : 'event';
}

/** Coerce a raw `data.sources` value into a clean `MessageSource[]`. */
function asSources(value: unknown): MessageSource[] {
  if (!Array.isArray(value)) return [];
  const out: MessageSource[] = [];
  for (const raw of value) {
    if (raw === null || typeof raw !== 'object') continue;
    const obj = raw as Record<string, unknown>;
    out.push({
      name: asString(obj.name, ''),
      title: asString(obj.title, ''),
      url: asStringOrNull(obj.url),
    });
  }
  return out;
}

/** A per-delivery, non-stable dedup key (a payload with no identity will not dedup). */
function synthesizeId(receivedAtMs: number): string {
  synthCounter = (synthCounter + 1) % Number.MAX_SAFE_INTEGER;
  const rand = Math.random().toString(36).slice(2, 8);
  return `synth:${receivedAtMs}:${rand}${synthCounter}`;
}

/**
 * Normalize a raw push `data` object into a `StoredMessage`. Never throws; always
 * yields a non-empty `message_id`. `data` may be `undefined`/`{}` (thin push), in
 * which case structured fields fall back to the push title/body per 2.3a.
 */
export function parsePayload(
  data: PushPayload | undefined | null,
  meta: ParseMeta,
): StoredMessage {
  const safeData: PushPayload = data && typeof data === 'object' ? data : {};
  const receivedAtMs =
    typeof meta.receivedAtMs === 'number' ? meta.receivedAtMs : Date.now();

  // Body/title fallbacks for thin pushes (2.3a).
  const body = typeof meta.body === 'string' ? meta.body : '';
  const title = typeof meta.title === 'string' ? meta.title : '';

  // Dedup id resolution (2.3): message_id -> event_id -> osIdentifier -> synth.
  let messageId: string;
  if (isNonEmptyString(safeData.message_id)) {
    messageId = safeData.message_id;
  } else if (isNonEmptyString(safeData.event_id)) {
    messageId = safeData.event_id;
  } else if (isNonEmptyString(meta.osIdentifier)) {
    messageId = meta.osIdentifier;
  } else {
    messageId = synthesizeId(receivedAtMs);
  }

  const eventId = asStringOrNull(safeData.event_id);

  const eventTypePl = isNonEmptyString(safeData.event_type_pl)
    ? safeData.event_type_pl
    : isNonEmptyString(title)
      ? title
      : '(alert)';

  const summaryPl = isNonEmptyString(safeData.summary_pl)
    ? (safeData.summary_pl as string)
    : body;

  const smsBody = isNonEmptyString(safeData.sms_body)
    ? (safeData.sms_body as string)
    : body;

  return {
    message_id: messageId,
    event_id: eventId,
    kind: asKind(safeData.kind),
    event_type: asStringOrNull(safeData.event_type),
    event_type_pl: eventTypePl,
    urgency_score: asNumberOrNull(safeData.urgency_score),
    affected_countries: asStringArray(safeData.affected_countries),
    aggressor: asString(safeData.aggressor, ''),
    summary_pl: summaryPl,
    sources: asSources(safeData.sources),
    sms_body: smsBody,
    first_seen_at: asStringOrNull(safeData.first_seen_at),
    received_at: new Date(receivedAtMs).toISOString(),
    read: false,
  };
}

/**
 * Foreground / response / tray capture shape. `data` is
 * `notification.request.content.data` — typed non-null but it may be `{}`.
 */
export type ForegroundShape = {
  request?: {
    identifier?: string | null;
    content?: {
      title?: string | null;
      body?: string | null;
      data?: PushPayload | null;
    } | null;
  } | null;
};

/** Parse a foreground/response/tray notification into a `StoredMessage`. */
export function parseForeground(
  notification: ForegroundShape,
  receivedAtMs?: number,
): StoredMessage {
  const request = notification?.request ?? undefined;
  const content = request?.content ?? undefined;
  return parsePayload(content?.data ?? undefined, {
    title: content?.title ?? null,
    body: content?.body ?? null,
    osIdentifier: request?.identifier ?? null,
    receivedAtMs,
  });
}

/**
 * Headless background-task shape. Per Expo docs the custom payload arrives as a
 * JSON **string** at `data.data.dataString` with `data.notification === null`.
 * This shape is assumed-from-docs/unverified on-device, so this adapter handles a
 * missing/wrong shape defensively (never throws) and logs the raw shape once.
 */
export type HeadlessShape = {
  data?:
    | {
        dataString?: unknown;
        [key: string]: unknown;
      }
    | null
    | undefined;
  notification?: unknown;
  [key: string]: unknown;
};

let headlessShapeLogged = false;

/** Parse a headless background-task payload into a `StoredMessage`. */
export function parseHeadless(
  taskData: HeadlessShape | undefined | null,
  receivedAtMs?: number,
): StoredMessage {
  if (!headlessShapeLogged) {
    headlessShapeLogged = true;
    try {
      // First-invocation visibility into the real on-device shape (2.3b).
      console.log('[inbox] headless task payload shape:', JSON.stringify(taskData));
    } catch {
      console.log('[inbox] headless task payload shape: <unserializable>');
    }
  }

  let parsed: PushPayload | undefined;
  let title: string | null = null;
  let body: string | null = null;

  try {
    const inner = taskData?.data;
    const dataString = inner?.dataString;
    if (typeof dataString === 'string') {
      const obj = JSON.parse(dataString) as unknown;
      if (obj && typeof obj === 'object') {
        parsed = obj as PushPayload;
      }
    } else if (inner && typeof inner === 'object') {
      // Defensive: some shapes may carry the payload object directly.
      parsed = inner as PushPayload;
    }
  } catch {
    // Malformed dataString — fall through to a fallback message (no throw).
    parsed = undefined;
  }

  return parsePayload(parsed, {
    title,
    body,
    osIdentifier: null,
    receivedAtMs,
  });
}
