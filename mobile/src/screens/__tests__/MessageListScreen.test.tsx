/**
 * MessageListScreen (3.2 / 3.7 / 3.8). The store seam `useMessages` is mocked to
 * inject fixtures; `@react-navigation/native`'s `useFocusEffect` is reduced to a
 * plain effect; PushPanel's deps (registerForPush) are mocked via expo-notifications
 * (jest.setup) + expo-device/constants here. `Alert.alert` is spied so we can drive
 * the confirm button.
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
jest.mock('expo-device', () => ({ __esModule: true, isDevice: false }));
jest.mock('expo-constants', () => ({
  __esModule: true,
  default: { expoConfig: { extra: { eas: { projectId: 'x' } } }, easConfig: { projectId: 'x' } },
}));

import { useMessages } from '../../messages/useMessages';
import MessageListScreen from '../MessageListScreen';

const mockedUseMessages = useMessages as jest.MockedFunction<typeof useMessages>;

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
});
