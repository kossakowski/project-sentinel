/**
 * Reliable capture paths (3.5 / 3.14).
 *
 * Two foreground-side capture routes, both fully fault-isolated (a thrown/rejected
 * `getPresentedNotificationsAsync`, `parsePayload`, or `store.ingest` is caught and
 * never crashes the app or the foreground transition):
 *
 *  - `attachForegroundCapture()` — subscribes `addNotificationReceivedListener` so a
 *    push that arrives while the app is foregrounded is parsed and ingested
 *    immediately. Returns an unsubscribe fn.
 *  - `sweepPresented()` — on every `AppState` → 'active', reads the iOS tray via
 *    `getPresentedNotificationsAsync()` and ingests each entry (null-guarding
 *    `content.data`). This is the de-facto background capture (AD-3): a visible push
 *    usually does not wake the headless task, so the tray-sweep on open catches it.
 *
 * Both paths resolve `message_id` identically (via `parsePayload` → `data.message_id`)
 * and dedup in the store, so a push that is foregrounded and then swept yields ONE
 * inbox entry.
 *
 * After a successful ingest each path also `dismissFromTray()`s the OS notification:
 * once a message lives in the store (the source of truth), its tray copy is
 * redundant, and leaving it there is what lets a deleted message resurface — the
 * cold-launch tray sweep would re-ingest the undismissed copy because the store
 * keeps no deletion tombstone.
 */

import * as Notifications from 'expo-notifications';

import { parseForeground } from '../messages/parsePayload';
import * as store from '../messages/store';

/** A callback fired after a successful ingest so the caller can resync the badge. */
export type OnIngest = () => void;

/**
 * Remove a notification from the OS tray once it is safely in the inbox store, so a
 * later cold-launch tray sweep cannot re-ingest a message the user has already
 * triaged (read or deleted). Best-effort and fully fault-isolated: a missing
 * identifier is a no-op and a rejected `dismissNotificationAsync` is swallowed —
 * the store remains the source of truth regardless (3.14).
 */
export async function dismissFromTray(
  identifier: string | null | undefined,
): Promise<void> {
  if (typeof identifier !== 'string' || identifier.length === 0) return;
  try {
    await Notifications.dismissNotificationAsync(identifier);
  } catch (err) {
    console.warn('[inbox] dismiss from tray failed', err);
  }
}

/**
 * Subscribe to foreground-received pushes: parse → ingest. Returns an unsubscribe
 * function. Each received notification is handled in a try/catch so a malformed
 * payload or a failed ingest never crashes the app (3.14).
 */
export function attachForegroundCapture(onIngest?: OnIngest): () => void {
  const subscription = Notifications.addNotificationReceivedListener((notification) => {
    void (async () => {
      try {
        const message = parseForeground(notification);
        await store.ingest(message);
        await dismissFromTray(notification?.request?.identifier);
        onIngest?.();
      } catch (err) {
        console.warn('[inbox] foreground capture failed', err);
      }
    })();
  });
  return () => {
    try {
      subscription.remove();
    } catch {
      // Removing an already-removed subscription must not throw.
    }
  };
}

/**
 * Sweep the iOS notification tray and ingest every presented notification. Called
 * on `AppState` → 'active'. A rejected `getPresentedNotificationsAsync` is
 * swallowed; each entry is parsed/ingested in its own try/catch so one bad tray
 * item cannot abort the rest (3.5 / 3.14). `onIngest` fires once after the sweep if
 * anything was ingested, so the caller can resync the badge a single time.
 */
export async function sweepPresented(onIngest?: OnIngest): Promise<void> {
  let presented: Notifications.Notification[];
  try {
    presented = await Notifications.getPresentedNotificationsAsync();
  } catch (err) {
    console.warn('[inbox] tray sweep failed', err);
    return;
  }
  let ingestedAny = false;
  for (const notification of presented) {
    try {
      const data = notification?.request?.content?.data;
      if (data == null) continue;
      const message = parseForeground(notification);
      await store.ingest(message);
      await dismissFromTray(notification?.request?.identifier);
      ingestedAny = true;
    } catch (err) {
      console.warn('[inbox] tray sweep entry failed', err);
    }
  }
  if (ingestedAny) onIngest?.();
}
