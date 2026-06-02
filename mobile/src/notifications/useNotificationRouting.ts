/**
 * Tap → Detail routing wiring (3.4).
 *
 * Combines the two tap surfaces:
 *  - warm: `addNotificationResponseReceivedListener` (tap while app is running);
 *  - cold: `useLastNotificationResponse()` (tap that launched a killed app).
 *
 * For each, it acts only on the DEFAULT action (a real tap, not a dismissal/custom
 * action), `store.ingest`s the tapped payload first (so the message exists even if
 * no other capture path saw it), then asks the pure `decideRoute` whether to
 * navigate — collapsing the cold+warm double-fire via an in-memory, in-session
 * last-handled `message_id` (a `useRef`, reset on relaunch, never persisted). The
 * cold response is consumed with `clearLastNotificationResponseAsync()` so a later
 * normal launch does not re-open it. The deprecated synchronous
 * `getLastNotificationResponse()` is never used.
 */

import { useCallback, useEffect, useRef } from 'react';
import * as Notifications from 'expo-notifications';

import { parseForeground } from '../messages/parsePayload';
import * as store from '../messages/store';
import { navigate } from '../navigation/navigationRef';
import { decideRoute } from './routing';

/** Optional callback fired after an ingest so the caller can resync the badge. */
export type OnRouteIngest = () => void;

export function useNotificationRouting(onIngest?: OnRouteIngest): void {
  // In-memory, in-session last-handled message id — collapses cold+warm of one tap.
  // A ref (not state) so updating it never re-renders and it resets on relaunch.
  const lastHandledRef = useRef<string | null>(null);
  const onIngestRef = useRef<OnRouteIngest | undefined>(onIngest);
  onIngestRef.current = onIngest;

  // Ingest the tapped payload, then navigate iff this message_id is new this session.
  const handleResponse = useCallback(async (response: Notifications.NotificationResponse) => {
    try {
      if (response.actionIdentifier !== Notifications.DEFAULT_ACTION_IDENTIFIER) {
        return;
      }
      const message = parseForeground(response.notification);
      await store.ingest(message);
      onIngestRef.current?.();
      const decision = decideRoute(message.message_id, lastHandledRef.current);
      if (decision.navigate && decision.messageId) {
        lastHandledRef.current = decision.handledMessageId ?? decision.messageId;
        navigate('Detail', { messageId: decision.messageId });
      }
    } catch (err) {
      // A tap that fails to ingest/route must not crash the app.
      console.warn('[inbox] tap routing failed', err);
    }
  }, []);

  // Warm path: a tap while the app is already running.
  useEffect(() => {
    const subscription = Notifications.addNotificationResponseReceivedListener((response) => {
      void handleResponse(response);
    });
    return () => {
      subscription.remove();
    };
  }, [handleResponse]);

  // Cold path: the response that launched the app (reliable for a killed-app tap).
  const lastResponse = Notifications.useLastNotificationResponse();
  useEffect(() => {
    if (!lastResponse) return;
    if (lastResponse.actionIdentifier !== Notifications.DEFAULT_ACTION_IDENTIFIER) return;
    void handleResponse(lastResponse).finally(() => {
      // Consume so a later NORMAL launch does not re-open this already-seen tap.
      void Notifications.clearLastNotificationResponseAsync();
    });
  }, [lastResponse, handleResponse]);
}

export default useNotificationRouting;
