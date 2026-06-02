/**
 * React hook over the AsyncStorage-backed message store (2.6).
 *
 * Exposes the current messages (newest-first), the unread count, and the mutating
 * operations. Every mutation re-reads the store afterwards so the returned state
 * stays consistent with AsyncStorage (the source of truth). The screens in Phase 3
 * consume this hook; Phase-3 tests mock it to inject fixtures.
 */

import { useCallback, useEffect, useState } from 'react';

import * as store from './store';
import type { StoredMessage } from './types';

export type UseMessages = {
  messages: StoredMessage[];
  unreadCount: number;
  markRead: (id: string) => Promise<void>;
  markAllRead: () => Promise<void>;
  remove: (id: string) => Promise<void>;
  clear: () => Promise<void>;
  refresh: () => Promise<void>;
};

export function useMessages(): UseMessages {
  const [messages, setMessages] = useState<StoredMessage[]>([]);
  const [unread, setUnread] = useState<number>(0);

  const refresh = useCallback(async () => {
    const loaded = await store.load();
    setMessages(loaded);
    setUnread(store.unreadCount());
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const markRead = useCallback(
    async (id: string) => {
      await store.markRead(id);
      await refresh();
    },
    [refresh],
  );

  const markAllRead = useCallback(async () => {
    await store.markAllRead();
    await refresh();
  }, [refresh]);

  const remove = useCallback(
    async (id: string) => {
      await store.remove(id);
      await refresh();
    },
    [refresh],
  );

  const clear = useCallback(async () => {
    await store.clear();
    await refresh();
  }, [refresh]);

  return {
    messages,
    unreadCount: unread,
    markRead,
    markAllRead,
    remove,
    clear,
    refresh,
  };
}

export default useMessages;
