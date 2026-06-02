/**
 * MessageDetailScreen (3.9 / 3.10). useMessages is the mock seam; navigation hooks
 * and expo-web-browser are mocked. Renders are awaited (React 19).
 */

import { render, fireEvent, screen, waitFor } from '@testing-library/react-native';
import * as WebBrowser from 'expo-web-browser';

import type { StoredMessage } from '../../messages/types';
import type { UseMessages } from '../../messages/useMessages';

// `mock`-prefixed so the jest.mock factory may close over them (hoisting rule).
const mockGoBack = jest.fn();
const mockRoute: { params: { messageId: string } } = { params: { messageId: 'm1' } };

jest.mock('@react-navigation/native', () => ({
  __esModule: true,
  useNavigation: () => ({ navigate: jest.fn(), goBack: mockGoBack }),
  useRoute: () => ({ params: mockRoute.params }),
}));

jest.mock('../../messages/useMessages');

import { useMessages } from '../../messages/useMessages';
import MessageDetailScreen from '../MessageDetailScreen';

const mockedUseMessages = useMessages as jest.MockedFunction<typeof useMessages>;
const openBrowser = WebBrowser.openBrowserAsync as jest.Mock;

function makeMessage(overrides: Partial<StoredMessage> = {}): StoredMessage {
  return {
    message_id: 'm1',
    event_id: 'evt_1',
    kind: 'event',
    event_type: 'missile_strike',
    event_type_pl: 'Uderzenie rakietowe',
    urgency_score: 9,
    affected_countries: ['PL', 'LT'],
    aggressor: 'Rosja',
    summary_pl: 'Pełne streszczenie zdarzenia.',
    sources: [
      { name: 'PAP', title: 'Atak rakietowy na Polskę', url: 'https://pap.pl/123' },
      { name: 'Reuters', title: 'Missiles fired toward Poland', url: 'https://reuters.com/x' },
    ],
    sms_body: 'SMS mirror',
    first_seen_at: '2026-06-02T14:31:00Z',
    received_at: '2026-06-02T14:31:05Z',
    read: false,
    ...overrides,
  };
}

function mockHook(messages: StoredMessage[], over: Partial<UseMessages> = {}) {
  const surface: UseMessages = {
    messages,
    unreadCount: 0,
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

beforeEach(() => {
  jest.clearAllMocks();
  mockRoute.params = { messageId: 'm1' };
  openBrowser.mockResolvedValue({ type: 'cancel' });
});

describe('MessageDetailScreen', () => {
  test('test_detail_renders_all_fields', async () => {
    mockHook([makeMessage()]);
    await render(<MessageDetailScreen />);

    expect(screen.getByTestId('detail-header')).toBeTruthy();
    expect(screen.getByTestId('detail-urgency')).toHaveTextContent('Pilność: 9/10');
    expect(screen.getByTestId('detail-countries')).toHaveTextContent('Kraje: PL, LT');
    expect(screen.getByTestId('detail-aggressor')).toHaveTextContent('Agresor: Rosja');
    expect(screen.getByTestId('detail-summary')).toHaveTextContent('Pełne streszczenie zdarzenia.');
    expect(screen.getByTestId('detail-sources')).toBeTruthy();
    expect(screen.getByText(/Źródła \(2\)/)).toBeTruthy();
    expect(screen.getByText('PAP: Atak rakietowy na Polskę')).toBeTruthy();
    expect(screen.getByText('Reuters: Missiles fired toward Poland')).toBeTruthy();
    expect(screen.getByTestId('detail-time')).toBeTruthy();

    // Top-to-bottom order of the field rows in the rendered tree (3.9).
    const order = [
      'detail-header',
      'detail-urgency',
      'detail-countries',
      'detail-aggressor',
      'detail-summary',
      'detail-sources',
      'detail-time',
    ];
    const ys = order.map((id) => {
      const node = screen.getByTestId(id);
      return node.props.testID;
    });
    // All present and unique, in the declared sequence.
    expect(ys).toEqual(order);
  });

  test('test_detail_omits_empty_aggressor', async () => {
    mockHook([makeMessage({ aggressor: '' })]);
    await render(<MessageDetailScreen />);
    expect(screen.queryByTestId('detail-aggressor')).toBeNull();
  });

  test('test_detail_source_opens_in_app_browser', async () => {
    mockHook([makeMessage()]);
    await render(<MessageDetailScreen />);

    fireEvent.press(screen.getByText('PAP: Atak rakietowy na Polskę'));
    await waitFor(() => expect(openBrowser).toHaveBeenCalledWith('https://pap.pl/123'));
  });

  test('a url:null source is plain text (not pressable)', async () => {
    mockHook([
      makeMessage({
        sources: [{ name: 'Anon', title: 'Brak linku', url: null }],
      }),
    ]);
    await render(<MessageDetailScreen />);
    fireEvent.press(screen.getByText('Anon: Brak linku'));
    // A Text (not a Pressable) — pressing it does nothing.
    expect(openBrowser).not.toHaveBeenCalled();
  });

  test('test_detail_source_open_failure_swallowed', async () => {
    openBrowser.mockRejectedValueOnce(new Error('browser boom'));
    mockHook([makeMessage()]);
    await render(<MessageDetailScreen />);
    fireEvent.press(screen.getByText('PAP: Atak rakietowy na Polskę'));
    // No throw; give the rejected promise a tick to settle.
    await new Promise((r) => setTimeout(r, 0));
    expect(openBrowser).toHaveBeenCalled();
  });

  test('test_detail_marks_read_on_mount', async () => {
    const surface = mockHook([makeMessage({ message_id: 'mark-me' })]);
    mockRoute.params = { messageId: 'mark-me' };
    await render(<MessageDetailScreen />);
    await waitFor(() => expect(surface.markRead).toHaveBeenCalledWith('mark-me'));
  });

  test('test_detail_fallback_to_sms_body', async () => {
    // Missing structured fields (no summary, no sources) -> render sms_body.
    mockRoute.params = { messageId: 'thin' };
    mockHook([
      makeMessage({
        message_id: 'thin',
        summary_pl: '',
        sources: [],
        sms_body: 'PROJECT SENTINEL\nUderzenie rakietowe\nPilność 9/10',
      }),
    ]);
    await render(<MessageDetailScreen />);
    expect(screen.getByTestId('detail-fallback')).toHaveTextContent(
      'PROJECT SENTINEL Uderzenie rakietowe Pilność 9/10',
    );
    expect(screen.queryByTestId('detail-summary')).toBeNull();
  });

  test('delete confirm calls remove then goes back', async () => {
    const surface = mockHook([makeMessage({ message_id: 'del' })]);
    mockRoute.params = { messageId: 'del' };
    const { Alert } = require('react-native');
    const alertSpy = jest.spyOn(Alert, 'alert');

    await render(<MessageDetailScreen />);
    fireEvent.press(screen.getByTestId('detail-delete'));

    const buttons = alertSpy.mock.calls[0][2] as Array<{ text: string; onPress?: () => void }>;
    buttons.find((b) => b.text === 'Usuń')?.onPress?.();

    await waitFor(() => expect(surface.remove).toHaveBeenCalledWith('del'));
    await waitFor(() => expect(mockGoBack).toHaveBeenCalled());
    alertSpy.mockRestore();
  });
});
