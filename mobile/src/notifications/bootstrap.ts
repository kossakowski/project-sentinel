/**
 * Module-scope notification bootstrap (2.5 / 2.8).
 *
 * Importing this module for its side effects (which `index.ts` does before
 * `registerRootComponent`) does three things at app load — including headless
 * launches — without mounting the React tree:
 *
 *  1. Registers the single `setNotificationHandler` (2.8): the app foreground
 *     display policy. This is the sole handler registration; the old one in
 *     `registerForPush.ts` is removed in Phase 3 so `bootstrap.ts` owns it.
 *  2. Defines the background notification task (`TaskManager.defineTask`) that, on
 *     a headless receipt, extracts the payload via the headless adapter, parses it,
 *     and ingests it into the store — catching/swallowing every error so a failure
 *     never crashes the headless launch (AD-3; best-effort, non-gating).
 *  3. Registers that task with `Notifications.registerTaskAsync`.
 *
 * The task callback is exported so tests can invoke it directly without the OS.
 */

import * as Notifications from 'expo-notifications';
import * as TaskManager from 'expo-task-manager';

import { parseHeadless, type HeadlessShape } from '../messages/parsePayload';
import * as store from '../messages/store';

/** Task name registered with expo-task-manager / expo-notifications. */
export const BACKGROUND_NOTIFICATION_TASK = 'SENTINEL_BACKGROUND_NOTIFICATION_TASK';

// 1. Foreground display policy — the single handler registration (2.8).
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowBanner: true,
    shouldShowList: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
  }),
});

/**
 * Headless background-task callback (2.5). Extracts the payload via the headless
 * adapter, parses it, and ingests it — swallowing all errors so the headless
 * launch can never crash. The `data` argument shape is assumed-from-docs and
 * handled defensively inside `parseHeadless`.
 */
export async function handleBackgroundNotification(args: {
  data?: unknown;
  error?: unknown;
}): Promise<void> {
  try {
    const message = parseHeadless((args?.data ?? undefined) as HeadlessShape | undefined);
    await store.ingest(message);
  } catch (err) {
    // Best-effort, non-gating: never let a headless failure surface (AD-3).
    console.warn('[inbox] background notification task failed', err);
  }
}

// 2. Define the task in module scope so it is registered at app load.
TaskManager.defineTask(BACKGROUND_NOTIFICATION_TASK, handleBackgroundNotification);

// 3. Register the task with expo-notifications. Swallow registration errors so a
//    failure here cannot crash app startup.
void Notifications.registerTaskAsync(BACKGROUND_NOTIFICATION_TASK).catch((err: unknown) => {
  console.warn('[inbox] failed to register background notification task', err);
});
