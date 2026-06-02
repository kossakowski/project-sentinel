/**
 * useMessages hook (2.6). Exercises the REAL hook against the REAL store and the
 * official AsyncStorage jest mock — no store mocking — so the hook's wiring is
 * genuinely covered here. (Phase-3 screen tests mock this hook to inject fixtures,
 * so this file is the only place its re-read-after-mutation behavior is proven.)
 *
 * RNTL 13 + React 19: `renderHook` is synchronous but `result.current` is populated
 * by a post-commit effect, and the hook's mount effect re-reads the store
 * asynchronously — so reads are awaited via `waitFor` and mutations via `act`.
 */

import AsyncStorage from '@react-native-async-storage/async-storage';
import { act, renderHook, waitFor } from '@testing-library/react-native';

import * as store from '../store';
import type { StoredMessage } from '../types';
import { useMessages } from '../useMessages';

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
    summary_pl: 'Pełne streszczenie.',
    sources: [],
    sms_body: 'SMS body',
    first_seen_at: '2026-06-02T14:31:00Z',
    received_at: '2026-06-02T14:31:05Z',
    read: false,
    ...overrides,
  };
}

beforeEach(async () => {
  // AsyncStorage is the source of truth (2.7): wipe it and reset the store snapshot.
  await AsyncStorage.clear();
  await store.load();
});

describe('useMessages', () => {
  test('test_use_messages_loads_and_exposes_surface', async () => {
    await store.ingest(makeMessage({ message_id: 'a', received_at: '2026-06-02T10:00:00Z' }));
    await store.ingest(makeMessage({ message_id: 'b', received_at: '2026-06-02T11:00:00Z' }));

    const { result } = renderHook(() => useMessages());

    // The mount effect re-reads the store asynchronously (2.6).
    await waitFor(() => expect(result.current.messages).toHaveLength(2));
    expect(result.current.messages[0].message_id).toBe('b'); // newest-first (2.4)
    expect(result.current.unreadCount).toBe(2);

    // The full surface is exposed (2.6).
    expect(typeof result.current.markRead).toBe('function');
    expect(typeof result.current.markAllRead).toBe('function');
    expect(typeof result.current.remove).toBe('function');
    expect(typeof result.current.clear).toBe('function');
    expect(typeof result.current.refresh).toBe('function');
  });

  test('test_use_messages_rereads_after_each_mutation', async () => {
    await store.ingest(makeMessage({ message_id: 'a', received_at: '2026-06-02T10:00:00Z' }));
    await store.ingest(makeMessage({ message_id: 'b', received_at: '2026-06-02T11:00:00Z' }));

    const { result } = renderHook(() => useMessages());
    await waitFor(() => expect(result.current.messages).toHaveLength(2));
    expect(result.current.unreadCount).toBe(2);

    // markRead re-reads the store -> unread count drops.
    await act(async () => {
      await result.current.markRead('a');
    });
    await waitFor(() => expect(result.current.unreadCount).toBe(1));

    // markAllRead re-reads -> nothing unread.
    await act(async () => {
      await result.current.markAllRead();
    });
    await waitFor(() => expect(result.current.unreadCount).toBe(0));

    // remove re-reads -> the message is gone.
    await act(async () => {
      await result.current.remove('a');
    });
    await waitFor(() => expect(result.current.messages).toHaveLength(1));
    expect(result.current.messages[0].message_id).toBe('b');

    // clear re-reads -> the list is empty.
    await act(async () => {
      await result.current.clear();
    });
    await waitFor(() => expect(result.current.messages).toHaveLength(0));
    expect(result.current.unreadCount).toBe(0);
  });

  test('test_use_messages_refresh_picks_up_external_writes', async () => {
    const { result } = renderHook(() => useMessages());
    await waitFor(() => expect(result.current.messages).toHaveLength(0));

    // A write that bypasses the hook (e.g. the headless background-task path);
    // refresh() must re-read AsyncStorage and surface it (2.6/2.7).
    await store.ingest(makeMessage({ message_id: 'x' }));
    await act(async () => {
      await result.current.refresh();
    });
    await waitFor(() => expect(result.current.messages).toHaveLength(1));
    expect(result.current.messages[0].message_id).toBe('x');
    expect(result.current.unreadCount).toBe(1);
  });
});
