/**
 * Date/time rendering for the inbox (3.11).
 *
 * Project convention: store UTC, render device-local. The server stamps
 * `first_seen_at`/`received_at` as UTC ISO-8601; these helpers convert to the
 * device's local zone (which equals Europe/Warsaw for the owner, but is not
 * hardcoded — `Date`/`Intl` use the device TZ).
 *
 * `relative` takes an injected `nowMs` so tests are deterministic; its boundaries
 * are floors, matching the spec exactly.
 */

const SECOND = 1000;
const MINUTE = 60 * SECOND;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/** Device-local date-time formatter (24h). Uses the device's own time zone. */
const ABSOLUTE_FMT = new Intl.DateTimeFormat('en-CA', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
});

/**
 * A compact relative-age label for a UTC ISO timestamp, computed against an
 * injected `nowMs` (defaults to `Date.now()`). Boundaries (floor):
 *   `<60s` → "now"; `60s..<3600s` → "Nm"; `3600s..<86400s` → "Nh";
 *   `>=86400s` → "Nd". A future timestamp or an unparseable input renders "now".
 */
export function relative(iso: string | null | undefined, nowMs: number = Date.now()): string {
  if (!iso) return 'now';
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return 'now';
  const diff = nowMs - t;
  if (diff < MINUTE) return 'now';
  if (diff < HOUR) return `${Math.floor(diff / MINUTE)}m`;
  if (diff < DAY) return `${Math.floor(diff / HOUR)}h`;
  return `${Math.floor(diff / DAY)}d`;
}

/**
 * A device-local absolute date-time string ("YYYY-MM-DD HH:mm") for a UTC ISO
 * timestamp. Returns "—" for missing input and echoes the raw string if it does
 * not parse. (`en-CA` emits "YYYY-MM-DD, HH:mm"; the comma is dropped to match the
 * dashboard convention.)
 */
export function absolute(iso: string | null | undefined): string {
  if (!iso) return '—';
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return iso;
  return ABSOLUTE_FMT.format(parsed).replace(', ', ' ');
}
