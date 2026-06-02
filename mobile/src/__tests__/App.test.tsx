/**
 * App navigation-shell assembly (3.2).
 *
 * `MessageListScreen.test` / `MessageDetailScreen.test` exercise the screens in
 * isolation; this file mounts the actual `<App/>` and proves the shell WIRING that
 * those screen tests leave to manual MA-1:
 *   - the native stack registers `List` (initial route) and `Detail`;
 *   - `NavigationContainer` receives `navigationRef` and `onReady === flushPendingRoute`
 *     (so a queued cold-start route is flushed when the container is ready);
 *   - the reliable capture + routing + badge paths are wired at the root
 *     (`attachForegroundCapture`, `useNotificationRouting`, `sweepPresented`, `syncBadge`);
 *   - the AppState→active transition triggers a tray-sweep (the de-facto background
 *     capture), but a redundant active→active transition does NOT.
 *
 * Seams: react-navigation native + native-stack are mocked to capture the props
 * (`ref`/`onReady`/`initialRouteName`/screen names) without a real container; the
 * screens, capture/routing/badge modules, and the store are mocked so the test
 * asserts App's assembly, not the leaf behaviors (those have their own suites).
 *
 * `mock`-prefixed names are referenced inside the hoisted `jest.mock` factories
 * (the only out-of-scope identifiers jest permits there).
 */

import { render } from '@testing-library/react-native';
import { AppState, type AppStateStatus, type NativeEventSubscription } from 'react-native';

// SafeAreaProvider defers rendering children until it has frame data, which never
// arrives in the jest env — use the library's official mock so the tree renders
// synchronously (otherwise <App/>'s NavigationContainer never mounts).
jest.mock('react-native-safe-area-context', () =>
  require('react-native-safe-area-context/jest/mock').default,
);

// ---- react-navigation: capture container/navigator/screen props -------------
const mockContainerProps: { onReady?: () => void; refSeen?: boolean } = {};
const mockNavigatorProps: { initialRouteName?: string } = {};
const mockScreenNames: string[] = [];

jest.mock('@react-navigation/native', () => {
  // React is required inside the hoisted factory (cannot close over a top import).
  const React = require('react');
  return {
    __esModule: true,
    NavigationContainer: React.forwardRef(
      (
        props: {
          onReady?: () => void;
          children?: unknown;
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          [k: string]: any;
        },
        ref: unknown,
      ) => {
        mockContainerProps.onReady = props.onReady;
        // The container ref (App passes `ref={navigationRef}`) arrives via forwardRef.
        mockContainerProps.refSeen = ref != null;
        // Mimic the real container firing onReady once mounted/ready.
        React.useEffect(() => {
          props.onReady?.();
        }, []);
        return React.createElement(React.Fragment, null, props.children);
      },
    ),
  };
});

jest.mock('@react-navigation/native-stack', () => {
  const React = require('react');
  return {
    __esModule: true,
    createNativeStackNavigator: () => ({
      Navigator: (props: { initialRouteName?: string; children?: unknown }) => {
        mockNavigatorProps.initialRouteName = props.initialRouteName;
        return React.createElement(React.Fragment, null, props.children);
      },
      Screen: (props: { name: string }) => {
        mockScreenNames.push(props.name);
        return null;
      },
    }),
  };
});

// ---- screens: trivial stand-ins (their own suites cover them) ---------------
jest.mock('../screens/MessageListScreen', () => ({
  __esModule: true,
  default: () => null,
}));
jest.mock('../screens/MessageDetailScreen', () => ({
  __esModule: true,
  default: () => null,
}));

// ---- navigationRef: assert onReady === flushPendingRoute --------------------
// `flushPendingRoute` is defined INSIDE the factory (a top-level const would still
// be in its temporal-dead-zone when the factory closure first dereferences it,
// yielding `undefined` as App's `onReady`); the test reads it back via the import.
jest.mock('../navigation/navigationRef', () => ({
  __esModule: true,
  navigationRef: { current: null, isReady: () => false },
  flushPendingRoute: jest.fn(),
}));

// ---- capture / routing / badge / store: assert the wiring -------------------
// Each module exports a jest.fn() defined INSIDE the factory (top-level consts are
// still in their TDZ when these hoisted factories first run — they would surface
// as `undefined` to App); the test reads them back via the imports below.
const mockDetach = jest.fn();
jest.mock('../notifications/capture', () => ({
  __esModule: true,
  attachForegroundCapture: jest.fn(() => () => undefined),
  sweepPresented: jest.fn(async () => undefined),
}));

jest.mock('../notifications/useNotificationRouting', () => ({
  __esModule: true,
  useNotificationRouting: jest.fn(),
}));

jest.mock('../badge', () => ({
  __esModule: true,
  syncBadge: jest.fn(async () => true),
}));

jest.mock('../messages/store', () => ({
  __esModule: true,
  unreadCount: jest.fn(() => 0),
}));

import { flushPendingRoute } from '../navigation/navigationRef';
import { attachForegroundCapture, sweepPresented } from '../notifications/capture';
import { useNotificationRouting } from '../notifications/useNotificationRouting';
import { syncBadge } from '../badge';
import { unreadCount } from '../messages/store';
import App from '../../App';

const mockFlushPendingRoute = flushPendingRoute as jest.Mock;
const mockAttachForegroundCapture = attachForegroundCapture as jest.Mock;
const mockSweepPresented = sweepPresented as jest.Mock;
const mockUseNotificationRouting = useNotificationRouting as jest.Mock;
const mockSyncBadge = syncBadge as jest.Mock;
const mockUnreadCount = unreadCount as jest.Mock;

beforeEach(() => {
  jest.clearAllMocks();
  mockAttachForegroundCapture.mockReturnValue(mockDetach);
  mockSweepPresented.mockResolvedValue(undefined);
  mockSyncBadge.mockResolvedValue(true);
  mockUnreadCount.mockReturnValue(0);
  mockContainerProps.onReady = undefined;
  mockContainerProps.refSeen = undefined;
  mockNavigatorProps.initialRouteName = undefined;
  mockScreenNames.length = 0;
});

describe('App navigation shell (3.2)', () => {
  test('registers List (initial) and Detail in the native stack', async () => {
    await render(<App />);
    expect(mockNavigatorProps.initialRouteName).toBe('List');
    expect(mockScreenNames).toEqual(['List', 'Detail']);
  });

  test('wires navigationRef and onReady === flushPendingRoute', async () => {
    await render(<App />);
    expect(mockContainerProps.refSeen).toBe(true);
    expect(mockContainerProps.onReady).toBe(mockFlushPendingRoute);
    // The mocked container fired onReady on mount -> the pending route is flushed.
    expect(mockFlushPendingRoute).toHaveBeenCalledTimes(1);
  });

  test('wires the reliable capture + routing + badge paths at the root', async () => {
    await render(<App />);
    expect(mockUseNotificationRouting).toHaveBeenCalledTimes(1);
    expect(mockAttachForegroundCapture).toHaveBeenCalledTimes(1);
    // Initial tray-sweep at launch (the app may open with tray notifications).
    expect(mockSweepPresented).toHaveBeenCalledTimes(1);
    // Badge resync ran at least once (initial sweep .finally(resyncBadge)).
    expect(mockSyncBadge).toHaveBeenCalled();
  });

  test('sweeps the tray on an AppState background->active transition (not active->active)', async () => {
    let appStateCb: ((s: AppStateStatus) => void) | undefined;
    const addSpy = jest
      .spyOn(AppState, 'addEventListener')
      .mockImplementation((event, cb) => {
        if (event === 'change') appStateCb = cb;
        return { remove: jest.fn() } as unknown as NativeEventSubscription;
      });

    await render(<App />);
    // Initial mount sweep.
    expect(mockSweepPresented).toHaveBeenCalledTimes(1);
    expect(typeof appStateCb).toBe('function');

    // background -> active triggers a sweep.
    appStateCb!('background');
    appStateCb!('active');
    expect(mockSweepPresented).toHaveBeenCalledTimes(2);

    // active -> active (redundant) does NOT re-sweep.
    appStateCb!('active');
    expect(mockSweepPresented).toHaveBeenCalledTimes(2);

    addSpy.mockRestore();
  });
});
