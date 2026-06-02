/**
 * Navigation ref + cold-start pending-route queue (3.3).
 *
 * A notification tap can resolve *before* `NavigationContainer` is mounted and
 * ready (a cold launch from a killed app). Calling `navigate` then would be a
 * no-op and the tapped message would never open. So `navigate` guards on
 * `navigationRef.isReady()`: when not ready it stores the call in a module-level
 * pending slot, and `flushPendingRoute()` — wired to the container's `onReady` —
 * replays it exactly once.
 *
 * The pending slot holds only the most recent route (the latest tap wins) and is
 * cleared on flush so a later normal launch never re-navigates.
 */

import { createNavigationContainerRef } from '@react-navigation/native';

/** Route params for the two-screen native stack. */
export type RootStackParamList = {
  List: undefined;
  Detail: { messageId: string };
};

/** Names of the stack routes (the `navigate` target). */
export type RouteName = keyof RootStackParamList;

/** The shared container ref consumed by `App.tsx` (`ref={navigationRef}`). */
export const navigationRef = createNavigationContainerRef<RootStackParamList>();

type PendingRoute =
  | { name: 'List'; params: undefined }
  | { name: 'Detail'; params: { messageId: string } };

/** The most recent route requested before the container was ready (latest wins). */
let pendingRoute: PendingRoute | null = null;

/**
 * Navigate to a stack route. When the container is ready, dispatch immediately;
 * otherwise queue the call so `flushPendingRoute()` can replay it once the
 * container mounts. Overloaded so `Detail` requires its `messageId` param while
 * `List` takes none.
 */
export function navigate(name: 'List'): void;
export function navigate(name: 'Detail', params: { messageId: string }): void;
export function navigate(name: RouteName, params?: { messageId: string }): void {
  if (navigationRef.isReady()) {
    if (name === 'Detail' && params) {
      navigationRef.navigate('Detail', params);
    } else {
      navigationRef.navigate('List');
    }
    return;
  }
  // Not ready yet (cold start): stash the latest route for onReady to replay.
  if (name === 'Detail' && params) {
    pendingRoute = { name: 'Detail', params };
  } else {
    pendingRoute = { name: 'List', params: undefined };
  }
}

/**
 * Replay a queued route, if any. Called from `NavigationContainer`'s `onReady`.
 * Clears the slot so the replay happens exactly once.
 */
export function flushPendingRoute(): void {
  if (!pendingRoute) return;
  if (!navigationRef.isReady()) return;
  const route = pendingRoute;
  pendingRoute = null;
  if (route.name === 'Detail') {
    navigationRef.navigate('Detail', route.params);
  } else {
    navigationRef.navigate('List');
  }
}

/** Test-only: whether a route is currently queued. */
export function hasPendingRoute(): boolean {
  return pendingRoute !== null;
}

/** Test-only: clear any queued route (reset between cases). */
export function resetPendingRoute(): void {
  pendingRoute = null;
}
