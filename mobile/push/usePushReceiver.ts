import { useEffect, useState } from 'react';
import * as Notifications from 'expo-notifications';

/**
 * The most recently received push, reduced to the three fields the
 * verification panel cares about. `title`/`body` mirror
 * `Notification.request.content.{title,body}` (both nullable per the
 * expo-notifications SDK 54 / v54.0.0 types), and `data` is the opaque
 * payload Sentinel attaches to the push.
 */
export type LastPush = {
  title: string | null;
  body: string | null;
  data: Record<string, unknown>;
};

/**
 * Registers the SDK 54 (v54.0.0) `expo-notifications` listeners for on-device
 * push verification and returns the most recently received push (or `null`
 * until one arrives).
 *
 * It registers both the foreground-received listener
 * (`addNotificationReceivedListener`) and the tap/response listener
 * (`addNotificationResponseReceivedListener`), logs each payload to the Metro
 * console, and removes both subscriptions on unmount via
 * `EventSubscription.remove()` so no listeners leak.
 *
 * This is observability-only; it does not mint or register tokens and does not
 * touch the registration flow in `registerForPush.ts`.
 */
export function usePushReceiver(): LastPush | null {
  const [last, setLast] = useState<LastPush | null>(null);

  useEffect(() => {
    const toLastPush = (notification: Notifications.Notification): LastPush => {
      const content = notification.request.content;
      return { title: content.title, body: content.body, data: content.data };
    };

    // Fires while the app is foregrounded and a push arrives.
    const receivedSub = Notifications.addNotificationReceivedListener((notification) => {
      console.log('[push] received:', notification.request.content);
      setLast(toLastPush(notification));
    });

    // Fires when the user taps a notification (foreground or from the tray).
    const responseSub = Notifications.addNotificationResponseReceivedListener((response) => {
      console.log('[push] response:', response.notification.request.content);
      setLast(toLastPush(response.notification));
    });

    return () => {
      receivedSub.remove();
      responseSub.remove();
    };
  }, []);

  return last;
}
