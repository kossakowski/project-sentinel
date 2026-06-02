/**
 * AsyncStorage-backed message store (Appendix B).
 *
 * AsyncStorage is the single source of truth (2.7): the messages live as one JSON
 * array under `STORAGE_KEY`, newest-first by insertion order (2.4). Every mutating
 * operation is a read-modify-write against that key — last-writer-wins — so the
 * foreground path and the headless background task can interleave and any lost
 * duplicate self-heals on the next dedup. The synchronous `all()` / `unreadCount()`
 * accessors return the most recently loaded snapshot for convenience, but they are
 * NOT authoritative: a fresh `load()` always re-reads AsyncStorage, so the store
 * keeps no hidden cache that would survive a simulated reload.
 */

import AsyncStorage from '@react-native-async-storage/async-storage';

import type { StoredMessage } from './types';

export const STORAGE_KEY = '@sentinel/messages';

/** Hard retention cap; oldest are dropped from the tail (2.4c). */
export const MAX_MESSAGES = 200;

/**
 * Snapshot of the last load/write, exposed via `all()`/`unreadCount()`. This is a
 * convenience mirror of AsyncStorage, refreshed on every read/write — it is never
 * treated as the source of truth (2.7).
 */
let snapshot: StoredMessage[] = [];

/** Type guard: a parsed value is a usable message array. */
function isMessageArray(value: unknown): value is StoredMessage[] {
  return Array.isArray(value);
}

/**
 * Read the persisted messages from AsyncStorage (the source of truth). Returns
 * `[]` on missing/corrupted/un-parseable storage and never throws (2.4e); also
 * refreshes the in-memory snapshot.
 */
export async function load(): Promise<StoredMessage[]> {
  try {
    const raw = await AsyncStorage.getItem(STORAGE_KEY);
    if (raw == null) {
      snapshot = [];
      return snapshot;
    }
    const parsed = JSON.parse(raw) as unknown;
    if (!isMessageArray(parsed)) {
      console.warn('[inbox] stored messages were not an array; resetting to []');
      snapshot = [];
      return snapshot;
    }
    snapshot = parsed;
    return snapshot;
  } catch (err) {
    console.warn('[inbox] failed to load messages; returning []', err);
    snapshot = [];
    return snapshot;
  }
}

/** Persist the array and refresh the snapshot. */
async function persist(messages: StoredMessage[]): Promise<void> {
  snapshot = messages;
  await AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(messages));
}

/**
 * The most recently loaded snapshot, newest-first. Call `load()` first (or after a
 * simulated reload) to guarantee it reflects AsyncStorage.
 */
export function all(): StoredMessage[] {
  return snapshot;
}

/** Count of unread messages in the current snapshot. */
export function unreadCount(): number {
  return snapshot.reduce((n, m) => (m.read ? n : n + 1), 0);
}

/**
 * Ingest a parsed message. Dedups on `message_id` (2.4a): an existing id is a
 * no-op on order, on `received_at`, and on all other fields — preserving the
 * existing `read` state. A new id is prepended (newest-first), then the array is
 * capped at `MAX_MESSAGES`, dropping from the tail (2.4c).
 */
export async function ingest(message: StoredMessage): Promise<void> {
  const current = await load();
  if (current.some((m) => m.message_id === message.message_id)) {
    // Existing id: no-op (no duplicate, no reorder, preserve read/received_at).
    return;
  }
  const next = [message, ...current].slice(0, MAX_MESSAGES);
  await persist(next);
}

/** Mark a single message read; persists. No-op if the id is absent. */
export async function markRead(id: string): Promise<void> {
  const current = await load();
  let changed = false;
  const next = current.map((m) => {
    if (m.message_id === id && !m.read) {
      changed = true;
      return { ...m, read: true };
    }
    return m;
  });
  if (changed) {
    await persist(next);
  }
}

/** Mark every message read; persists. */
export async function markAllRead(): Promise<void> {
  const current = await load();
  const next = current.map((m) => (m.read ? m : { ...m, read: true }));
  await persist(next);
}

/** Remove a single message by id; persists. */
export async function remove(id: string): Promise<void> {
  const current = await load();
  const next = current.filter((m) => m.message_id !== id);
  await persist(next);
}

/** Remove every message; persists an empty array. */
export async function clear(): Promise<void> {
  await persist([]);
}

export const store = {
  STORAGE_KEY,
  MAX_MESSAGES,
  load,
  all,
  unreadCount,
  ingest,
  markRead,
  markAllRead,
  remove,
  clear,
};

export default store;
