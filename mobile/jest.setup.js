/* eslint-env jest */
// Jest setup: install the official AsyncStorage jest mock and stub the native
// notification modules so importing bootstrap.ts (and anything that pulls in
// expo-notifications / expo-task-manager) does not crash in the Node test env.

// AsyncStorage's official jest mock — use the exact versioned path (2.1a), NOT the
// bare `/jest` path. This provides an in-memory string-keyed singleton.
jest.mock(
  '@react-native-async-storage/async-storage',
  () =>
    require('@react-native-async-storage/async-storage/jest/async-storage-mock'),
);

// expo-notifications and expo-task-manager have native sides that are absent in
// the Node test environment; mock them so module-scope side effects in
// bootstrap.ts (setNotificationHandler / defineTask / registerTaskAsync) resolve
// to jest mock functions instead of touching the missing native modules (2.1a).
// A factory mock is required (a bare auto-mock still loads the real module, which
// calls requireNativeModule('ExpoTaskManager') and throws in Node). The Phase-3
// surface (capture listeners, response listener, badge, cold-tap consume) is
// covered too so importing those modules in tests does not crash.
jest.mock('expo-notifications', () => ({
  __esModule: true,
  setNotificationHandler: jest.fn(),
  registerTaskAsync: jest.fn(async () => null),
  addNotificationReceivedListener: jest.fn(() => ({ remove: jest.fn() })),
  addNotificationResponseReceivedListener: jest.fn(() => ({ remove: jest.fn() })),
  getPresentedNotificationsAsync: jest.fn(async () => []),
  setBadgeCountAsync: jest.fn(async () => true),
  getBadgeCountAsync: jest.fn(async () => 0),
  clearLastNotificationResponseAsync: jest.fn(async () => undefined),
  useLastNotificationResponse: jest.fn(() => null),
  getPermissionsAsync: jest.fn(async () => ({ status: 'granted' })),
  requestPermissionsAsync: jest.fn(async () => ({ status: 'granted' })),
  getExpoPushTokenAsync: jest.fn(async () => ({ data: 'ExponentPushToken[test]' })),
  setNotificationChannelAsync: jest.fn(async () => undefined),
  AndroidImportance: { MAX: 5 },
  DEFAULT_ACTION_IDENTIFIER: 'expo.modules.notifications.actions.DEFAULT',
}));

jest.mock('expo-task-manager', () => ({
  __esModule: true,
  defineTask: jest.fn(),
}));

// expo-web-browser is native; the Detail screen opens article links through it.
// Mock the single function used (openBrowserAsync) so tests can assert calls and
// simulate a rejection without touching SFSafariViewController.
jest.mock('expo-web-browser', () => ({
  __esModule: true,
  openBrowserAsync: jest.fn(async () => ({ type: 'cancel' })),
}));
