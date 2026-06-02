import { useEffect, useState } from 'react';
import * as Notifications from 'expo-notifications';

/**
 * The most recently received (or tapped) push, reduced to the three fields the
 * verification panel cares about. `title`/`body` mirror
 * `Notification.request.content.{title,body}` (both nullable per the
 * expo-notifications SDK 54 / v54.0.0 types), and `data` is the opaque payload
 * Sentinel attaches to the push.
 */
export type LastPush = {
  title: string | null;
  body: string | null;
  data: Record<string, unknown>;
};

function toLastPush(notification: Notifications.Notification): LastPush {
  const content = notification.request.content;
  return { title: content.title, body: content.body, data: content.data };
}

/**
 * Registers the SDK 54 (v54.0.0) `expo-notifications` listeners for on-device
 * push verification and returns the most recently received/tapped push (or
 * `null` until one arrives).
 *
 * It registers both the foreground-received listener
 * (`addNotificationReceivedListener`) and the tap/response listener
 * (`addNotificationResponseReceivedListener`), and additionally reads
 * `useLastNotificationResponse()` — the dependable path for a tap that
 * cold-starts a killed app, which the response listener does not reliably
 * deliver. Each payload is logged to the Metro console, and both listener
 * subscriptions are removed on unmount via `EventSubscription.remove()` so no
 * listeners leak.
 *
 * This is observability-only; it does not mint or register tokens and does not
 * touch the registration flow in `registerForPush.ts`.
 */
export function usePushReceiver(): LastPush | null {
  const [last, setLast] = useState<LastPush | null>(null);

  // The notification response that launched/opened the app. Reliable for a tap
  // that cold-starts a killed app (the response listener below is not), so a
  // tapped alert is surfaced even on first launch.
  const lastResponse = Notifications.useLastNotificationResponse();

  useEffect(() => {
    // Fires while the app is foregrounded and a push arrives.
    const receivedSub = Notifications.addNotificationReceivedListener((notification) => {
      console.log('[push] received:', notification.request.content);
      setLast(toLastPush(notification));
    });

    // Fires when the user taps a notification while the app is already running.
    const responseSub = Notifications.addNotificationResponseReceivedListener((response) => {
      console.log('[push] response:', response.notification.request.content);
      setLast(toLastPush(response.notification));
    });

    return () => {
      receivedSub.remove();
      responseSub.remove();
    };
  }, []);

  useEffect(() => {
    // Only a real tap (the default action) surfaces a message — ignore
    // dismissals and custom actions.
    if (lastResponse?.actionIdentifier === Notifications.DEFAULT_ACTION_IDENTIFIER) {
      console.log('[push] launch/tap response:', lastResponse.notification.request.content);
      setLast(toLastPush(lastResponse.notification));
      // Consume it so a later NORMAL launch doesn't re-surface this already-seen
      // tap as if it were a fresh alert.
      void Notifications.clearLastNotificationResponseAsync();
    }
  }, [lastResponse]);

  return last;
}
