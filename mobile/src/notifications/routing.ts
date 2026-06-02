/**
 * Pure tap-routing decision (3.4).
 *
 * One physical notification tap can surface twice in a single session: once via
 * the cold `useLastNotificationResponse()` hook and once via the warm
 * `addNotificationResponseReceivedListener`. The OS `request.identifier` is a
 * fresh UUID per delivery so it cannot collapse them; instead we track the
 * **last-handled `message_id`** (in-memory, in-session — never persisted) and
 * suppress a second navigation for the same id.
 *
 * This module is intentionally a pure function so it is trivially testable: the
 * caller (`useNotificationRouting`) owns the in-memory state and the side effect
 * (navigating + ingesting).
 */

/** The decision `decideRoute` returns for a candidate tap. */
export type RouteDecision = {
  /** Whether the caller should navigate to Detail. */
  navigate: boolean;
  /** The message to open (present only when `navigate` is true). */
  messageId?: string;
  /** The new value the caller should store as last-handled (only when navigating). */
  handledMessageId?: string;
};

/**
 * Decide whether a tapped `messageId` should drive a navigation, given the last
 * message id this session already navigated for. A missing/empty `messageId` or a
 * repeat of `lastHandledMessageId` yields `{navigate:false}` (collapses the
 * cold+warm double-fire); anything new yields a navigation plus the id to record.
 */
export function decideRoute(
  messageId: string | null | undefined,
  lastHandledMessageId: string | null | undefined,
): RouteDecision {
  if (typeof messageId !== 'string' || messageId.length === 0) {
    return { navigate: false };
  }
  if (messageId === lastHandledMessageId) {
    return { navigate: false };
  }
  return { navigate: true, messageId, handledMessageId: messageId };
}
