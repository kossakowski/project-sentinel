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
// calls requireNativeModule('ExpoTaskManager') and throws in Node).
jest.mock('expo-notifications', () => ({
  __esModule: true,
  setNotificationHandler: jest.fn(),
  registerTaskAsync: jest.fn(async () => null),
  DEFAULT_ACTION_IDENTIFIER: 'expo.modules.notifications.actions.DEFAULT',
}));

jest.mock('expo-task-manager', () => ({
  __esModule: true,
  defineTask: jest.fn(),
}));
