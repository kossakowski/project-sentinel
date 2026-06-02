/**
 * MessageListScreen (3.2 / 3.7 / 3.8). The store seam `useMessages` is mocked to
 * inject fixtures; the store module and `syncBadge` are mocked so we can assert the
 * badge is resynced from the store's LIVE unread count (3.6) — on focus after a
 * refresh and after every in-screen mutation (mark-all-read / clear).
 * `@react-navigation/native`'s `useFocusEffect` is reduced to a plain effect;
 * PushPanel's deps (registerForPush) are mocked via expo-notifications (jest.setup)
 * + expo-device/constants here. `Alert.alert` is spied so we can drive the confirm
 * button.
 */

import { Alert } from 'react-native';
import { render, fireEvent, screen, waitFor } from '@testing-library/react-native';

import type { StoredMessage } from '../../messages/types';
import type { UseMessages } from '../../messages/useMessages';

// useFocusEffect -> run the callback once on mount (no real navigation container).
// React is required INSIDE the factory (the hoisted factory cannot close over a
// top-level import).
jest.mock('@react-navigation/native', () => ({
  __esModule: true,
  useFocusEffect: (cb: () => void | (() => void)) => {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const React = require('react');
    // eslint-disable-next-line react-hooks/rules-of-hooks
    React.useEffect(() => cb(), []);
  },
}));

jest.mock('../../messages/useMessages');
// Mock the store so the screen's `store.unreadCount()` (read AFTER refresh/mutation)
// returns a controllable LIVE value, distinct from the hook's render-time count.
jest.mock('../../messages/store', () => ({
  __esModule: true,
  unreadCount: jest.fn(() => 0),
}));
// Mock syncBadge so we can assert what count the screen pushes to the app icon.
jest.mock('../../badge', () => ({
  __esModule: true,
  syncBadge: jest.fn(async () => true),
}));
jest.mock('expo-device', () => ({ __esModule: true, isDevice: false }));
jest.mock('expo-constants', () => ({
  __esModule: true,
  default: { expoConfig: { extra: { eas: { projectId: 'x' } } }, easConfig: { projectId: 'x' } },
}));

import { useMessages } from '../../messages/useMessages';
import * as store from '../../messages/store';
import { syncBadge } from '../../badge';
import MessageListScreen from '../MessageListScreen';

const mockedUseMessages = useMessages as jest.MockedFunction<typeof useMessages>;
const mockedUnreadCount = store.unreadCount as jest.MockedFunction<typeof store.unreadCount>;
const mockedSyncBadge = syncBadge as jest.MockedFunction<typeof syncBadge>;

function makeMessage(overrides: Partial<StoredMessage> = {}): StoredMessage {
  return {
    message_id: 'm1',
    event_id: 'evt_1',
    kind: 'event',
    event_type: 'missile_strike',
    event_type_pl: 'Uderzenie rakietowe',
    urgency_score: 9,
    affected_countries: ['PL'],
    aggressor: 'Rosja',
    summary_pl: 'Streszczenie.',
    sources: [],
    sms_body: 'SMS',
    first_seen_at: '2026-06-02T14:31:00Z',
    received_at: '2026-06-02T14:31:05Z',
    read: false,
    ...overrides,
  };
}

function mockHook(messages: StoredMessage[], over: Partial<UseMessages> = {}) {
  const unread = messages.reduce((n, m) => (m.read ? n : n + 1), 0);
  const surface: UseMessages = {
    messages,
    unreadCount: unread,
    markRead: jest.fn(async () => undefined),
    markAllRead: jest.fn(async () => undefined),
    remove: jest.fn(async () => undefined),
    clear: jest.fn(async () => undefined),
    refresh: jest.fn(async () => undefined),
    ...over,
  };
  mockedUseMessages.mockReturnValue(surface);
  return surface;
}

const navigation = { navigate: jest.fn() } as never;

beforeEach(() => {
  jest.clearAllMocks();
  mockedUnreadCount.mockReturnValue(0);
});

describe('MessageListScreen', () => {
  test('test_list_renders_n_tiles', async () => {
    mockHook([
      makeMessage({ message_id: 'a' }),
      makeMessage({ message_id: 'b' }),
      makeMessage({ message_id: 'c' }),
    ]);
    await render(<MessageListScreen navigation={navigation} />);
    expect(screen.getAllByTestId('message-tile')).toHaveLength(3);
  });

  test('test_list_unread_dot_count', async () => {
    mockHook([
      makeMessage({ message_id: 'a', read: false }),
      makeMessage({ message_id: 'b', read: false }),
      makeMessage({ message_id: 'c', read: true }),
    ]);
    await render(<MessageListScreen navigation={navigation} />);
    expect(screen.getAllByTestId('unread-dot')).toHaveLength(2);
  });

  test('test_list_empty_state', async () => {
    mockHook([]);
    await render(<MessageListScreen navigation={navigation} />);
    expect(screen.getByTestId('empty-state')).toBeTruthy();
  });

  test('test_list_clear_all_confirms_and_clears', async () => {
    const surface = mockHook([makeMessage({ message_id: 'a' })]);
    const alertSpy = jest.spyOn(Alert, 'alert');

    await render(<MessageListScreen navigation={navigation} />);
    fireEvent.press(screen.getByTestId('clear-all'));

    // Drive the destructive "Wyczyść" confirm button from the Alert.alert spy.
    expect(alertSpy).toHaveBeenCalledTimes(1);
    const buttons = alertSpy.mock.calls[0][2] as Array<{ text: string; onPress?: () => void }>;
    const confirm = buttons.find((b) => b.text === 'Wyczyść');
    confirm?.onPress?.();

    await waitFor(() => expect(surface.clear).toHaveBeenCalledTimes(1));
    alertSpy.mockRestore();
  });

  test('tapping a tile navigates to Detail with the message_id', async () => {
    mockHook([makeMessage({ message_id: 'open-me' })]);
    await render(<MessageListScreen navigation={navigation} />);
    fireEvent.press(screen.getByTestId('message-tile'));
    expect((navigation as unknown as { navigate: jest.Mock }).navigate).toHaveBeenCalledWith(
      'Detail',
      { messageId: 'open-me' },
    );
  });

  test('mark-all-read invokes the store action', async () => {
    const surface = mockHook([makeMessage({ message_id: 'a', read: false })]);
    await render(<MessageListScreen navigation={navigation} />);
    fireEvent.press(screen.getByTestId('mark-all-read'));
    await waitFor(() => expect(surface.markAllRead).toHaveBeenCalledTimes(1));
  });

  test('on focus the badge is synced to the LIVE store count after refresh (not the stale hook count)', async () => {
    // The hook reports 2 unread at render time; after refresh() the store's live
    // count is 1. The focus effect must badge the LIVE count (3.6), not the stale
    // render-time closure value.
    mockedUnreadCount.mockReturnValue(1);
    const surface = mockHook(
      [makeMessage({ message_id: 'a', read: false }), makeMessage({ message_id: 'b', read: false })],
      { unreadCount: 2 },
    );
    await render(<MessageListScreen navigation={navigation} />);

    await waitFor(() => expect(surface.refresh).toHaveBeenCalled());
    await waitFor(() => expect(mockedSyncBadge).toHaveBeenCalledWith(1));
    // Never badged with the stale render-time count.
    expect(mockedSyncBadge).not.toHaveBeenCalledWith(2);
  });

  test('mark-all-read resyncs the badge from the live store count', async () => {
    mockedUnreadCount.mockReturnValue(0);
    mockHook([makeMessage({ message_id: 'a', read: false })], { unreadCount: 1 });
    await render(<MessageListScreen navigation={navigation} />);
    mockedSyncBadge.mockClear();

    fireEvent.press(screen.getByTestId('mark-all-read'));
    // Marking all read drops the live unread count to 0 — the badge must follow.
    await waitFor(() => expect(mockedSyncBadge).toHaveBeenCalledWith(0));
  });

  test('clear-all resyncs the badge from the live store count', async () => {
    mockedUnreadCount.mockReturnValue(0);
    const surface = mockHook([makeMessage({ message_id: 'a', read: false })], { unreadCount: 1 });
    const alertSpy = jest.spyOn(Alert, 'alert');
    await render(<MessageListScreen navigation={navigation} />);
    mockedSyncBadge.mockClear();

    fireEvent.press(screen.getByTestId('clear-all'));
    const buttons = alertSpy.mock.calls[0][2] as Array<{ text: string; onPress?: () => void }>;
    buttons.find((b) => b.text === 'Wyczyść')?.onPress?.();

    await waitFor(() => expect(surface.clear).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(mockedSyncBadge).toHaveBeenCalledWith(0));
    alertSpy.mockRestore();
  });
});
