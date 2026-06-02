/**
 * App-icon unread badge (3.6).
 *
 * The app is the sole badge authority (the notification handler keeps
 * `shouldSetBadge:false`, 2.8), so `syncBadge` drives the icon count directly:
 * it is called on foreground and after every store mutation/ingest with the
 * current unread total (0 when none unread).
 *
 * On iOS `setBadgeCountAsync` silently returns `false` when `allowBadge` was not
 * granted (no throw); we check that boolean and swallow a `false` so an ungranted
 * badge permission is a silent no-op, and we also catch a rejected promise so a
 * badge failure can never crash a foreground transition (3.14).
 */

import * as Notifications from 'expo-notifications';

/**
 * Set the app-icon badge to `unreadCount`. Tolerates a `false` return (ungranted
 * `allowBadge`) and a rejected call — never throws. Returns whether the OS
 * accepted the count (`false` on no-op/failure), for callers/tests that care.
 */
export async function syncBadge(unreadCount: number): Promise<boolean> {
  try {
    const count = Number.isFinite(unreadCount) && unreadCount > 0 ? Math.floor(unreadCount) : 0;
    const ok = await Notifications.setBadgeCountAsync(count);
    // `false` => allowBadge ungranted; treat as a silent no-op.
    return ok === true;
  } catch (err) {
    // A rejected setBadgeCountAsync must never crash the foreground transition.
    console.warn('[inbox] failed to set app-icon badge', err);
    return false;
  }
}

export default syncBadge;
