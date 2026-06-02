/** MessageTile (3.7). RNTL 13 + React 19 — renders are awaited. */

import { render, fireEvent, screen } from '@testing-library/react-native';

import MessageTile from '../MessageTile';
import type { StoredMessage } from '../../messages/types';

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
    summary_pl: 'Rosja wystrzeliła rakiety w kierunku Polski.',
    sources: [],
    sms_body: 'SMS body',
    first_seen_at: '2026-06-02T14:31:00Z',
    received_at: '2026-06-02T14:31:05Z',
    read: false,
    ...overrides,
  };
}

describe('MessageTile', () => {
  const now = new Date('2026-06-02T14:33:05Z').getTime(); // 2 min after received

  test('test_tile_shows_title_urgency_snippet_time', async () => {
    await render(
      <MessageTile message={makeMessage()} onPress={jest.fn()} nowMs={now} />,
    );

    expect(screen.getByText(/Uderzenie rakietowe/)).toBeTruthy();
    expect(screen.getByText('9/10')).toBeTruthy();
    expect(
      screen.getByText('Rosja wystrzeliła rakiety w kierunku Polski.'),
    ).toBeTruthy();
    // Relative time: 2 minutes after received_at -> "2m".
    expect(screen.getByText('2m')).toBeTruthy();
  });

  test('renders an unread dot only when unread', async () => {
    const { rerender } = await render(
      <MessageTile message={makeMessage({ read: false })} onPress={jest.fn()} nowMs={now} />,
    );
    expect(screen.queryByTestId('unread-dot')).toBeTruthy();

    await rerender(
      <MessageTile message={makeMessage({ read: true })} onPress={jest.fn()} nowMs={now} />,
    );
    expect(screen.queryByTestId('unread-dot')).toBeNull();
  });

  test('onPress is invoked with the message_id', async () => {
    const onPress = jest.fn();
    await render(
      <MessageTile message={makeMessage({ message_id: 'tap-me' })} onPress={onPress} nowMs={now} />,
    );
    fireEvent.press(screen.getByTestId('message-tile'));
    expect(onPress).toHaveBeenCalledWith('tap-me');
  });

  test('shows the update emoji for an update', async () => {
    await render(
      <MessageTile
        message={makeMessage({ kind: 'update', event_type_pl: 'Aktualizacja' })}
        onPress={jest.fn()}
        nowMs={now}
      />,
    );
    expect(screen.getByText(/ℹ️ Aktualizacja/)).toBeTruthy();
  });
});
