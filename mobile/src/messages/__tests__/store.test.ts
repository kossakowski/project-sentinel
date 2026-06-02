import AsyncStorage from '@react-native-async-storage/async-storage';

import * as store from '../store';
import type { StoredMessage } from '../types';

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
  // AsyncStorage is the source of truth (2.7): wipe it and reset the snapshot.
  await AsyncStorage.clear();
  await store.load();
});

describe('store', () => {
  test('test_ingest_adds_and_persists', async () => {
    const p = makeMessage({ message_id: 'm1' });
    await store.ingest(p);

    expect(store.all()).toHaveLength(1);

    // Fresh load() re-reads AsyncStorage and returns the same single message.
    const reloaded = await store.load();
    expect(reloaded).toHaveLength(1);
    expect(reloaded[0].message_id).toBe('m1');
  });

  test('test_ingest_dedupes_by_message_id', async () => {
    await store.ingest(makeMessage({ message_id: 'dup' }));
    await store.ingest(makeMessage({ message_id: 'dup' }));
    expect(store.all()).toHaveLength(1);
  });

  test('test_ingest_preserves_read_position_received_at_on_redup', async () => {
    const a = makeMessage({ message_id: 'A', received_at: '2026-06-02T10:00:00Z' });
    const b = makeMessage({ message_id: 'B', received_at: '2026-06-02T11:00:00Z' });
    await store.ingest(a); // A
    await store.ingest(b); // B newest -> [B, A]
    await store.markRead('A');

    // Re-ingest A with a different received_at — must be a no-op on order/fields.
    await store.ingest(
      makeMessage({ message_id: 'A', received_at: '2026-06-02T12:00:00Z', read: false }),
    );

    const all = await store.load();
    expect(all).toHaveLength(2);
    const aStored = all.find((m) => m.message_id === 'A')!;
    expect(aStored.read).toBe(true); // read state preserved
    expect(aStored.received_at).toBe('2026-06-02T10:00:00Z'); // received_at unchanged
    expect(all[1].message_id).toBe('A'); // index unchanged (A is the tail)
  });

  test('test_update_is_separate_message', async () => {
    await store.ingest(makeMessage({ message_id: 'evt1-event', event_id: 'evt1', kind: 'event' }));
    await store.ingest(makeMessage({ message_id: 'evt1-update', event_id: 'evt1', kind: 'update' }));
    expect(store.all()).toHaveLength(2);
  });

  test('test_cap_at_200_keeps_newest', async () => {
    for (let i = 0; i < 205; i += 1) {
      await store.ingest(
        makeMessage({
          message_id: `m${i}`,
          received_at: new Date(1_700_000_000_000 + i * 1000).toISOString(),
        }),
      );
    }
    const all = await store.load();
    expect(all).toHaveLength(200);
    // Newest (m204) at index 0; oldest (m0..m4) dropped.
    expect(all[0].message_id).toBe('m204');
    expect(all.some((m) => m.message_id === 'm0')).toBe(false);
  });

  test('test_sorted_newest_first', async () => {
    await store.ingest(makeMessage({ message_id: 'old', received_at: '2026-06-02T10:00:00Z' }));
    await store.ingest(makeMessage({ message_id: 'new', received_at: '2026-06-02T11:00:00Z' }));
    expect(store.all()[0].message_id).toBe('new');
  });

  test('test_mark_read_all_remove_clear', async () => {
    await store.ingest(makeMessage({ message_id: 'a', received_at: '2026-06-02T10:00:00Z' }));
    await store.ingest(makeMessage({ message_id: 'b', received_at: '2026-06-02T11:00:00Z' }));

    expect(store.unreadCount()).toBe(2);

    await store.markRead('a');
    expect(store.unreadCount()).toBe(1);

    await store.markAllRead();
    expect(store.unreadCount()).toBe(0);

    await store.remove('a');
    expect(store.all()).toHaveLength(1);
    expect(store.all()[0].message_id).toBe('b');

    await store.clear();
    expect(store.all()).toHaveLength(0);

    // Survive a fresh load (AsyncStorage source of truth).
    const reloaded = await store.load();
    expect(reloaded).toHaveLength(0);
  });

  test('test_load_corrupted_returns_empty', async () => {
    await AsyncStorage.setItem('@sentinel/messages', 'not-json');
    const loaded = await store.load();
    expect(loaded).toEqual([]);
  });
});
