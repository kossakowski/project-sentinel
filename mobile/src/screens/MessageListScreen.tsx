/**
 * The inbox (3.7 / 3.8).
 *
 * Renders every stored message newest-first as `MessageTile`s in a `FlatList`,
 * with an empty state when there are none. The header shows the title and exposes
 * Settings (the push-token panel), a Clear-all action (confirm → `store.clear`),
 * and a "mark all read" action (3.8 SHOULD). Tapping a tile navigates to Detail
 * for that `message_id`. The store is consumed via `useMessages()` (the mock seam
 * for tests).
 *
 * On focus the list refreshes (a tap/foreground may have ingested a new message)
 * and resyncs the app-icon badge. Every in-screen store mutation (mark-all-read,
 * clear) also resyncs the badge directly from the store's live unread count (3.6),
 * so the icon is correct without waiting for the next focus pass.
 */

import { useCallback, useState } from 'react';
import {
  Alert,
  FlatList,
  Modal,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useFocusEffect, type NavigationProp } from '@react-navigation/native';

import MessageTile from '../components/MessageTile';
import { useMessages } from '../messages/useMessages';
import type { RootStackParamList } from '../navigation/navigationRef';
import { syncBadge } from '../badge';
import * as store from '../messages/store';
import PushPanel from '../../push/PushPanel';

export type MessageListScreenProps = {
  navigation: NavigationProp<RootStackParamList>;
};

export default function MessageListScreen({ navigation }: MessageListScreenProps) {
  const { messages, unreadCount, markAllRead, clear, refresh } = useMessages();
  const [settingsOpen, setSettingsOpen] = useState(false);

  // Refresh + badge resync whenever the list regains focus (a tap/foreground may
  // have ingested while we were on Detail or backgrounded). Read the unread count
  // from the store AFTER refresh — the destructured `unreadCount` is the stale
  // render-time closure value and would badge the pre-refresh count.
  useFocusEffect(
    useCallback(() => {
      void (async () => {
        await refresh();
        void syncBadge(store.unreadCount());
      })();
    }, [refresh]),
  );

  const openDetail = useCallback(
    (messageId: string) => {
      navigation.navigate('Detail', { messageId });
    },
    [navigation],
  );

  const confirmClear = useCallback(() => {
    if (messages.length === 0) return;
    Alert.alert(
      'Wyczyść wszystko',
      'Usunąć wszystkie wiadomości? Tej operacji nie można cofnąć.',
      [
        { text: 'Anuluj', style: 'cancel' },
        {
          text: 'Wyczyść',
          style: 'destructive',
          onPress: () => {
            void (async () => {
              await clear();
              // Resync the badge after the mutation (3.6) — clear() awaits the
              // store's read-modify-write, so unreadCount() is now authoritative.
              void syncBadge(store.unreadCount());
            })();
          },
        },
      ],
    );
  }, [messages.length, clear]);

  const onMarkAllRead = useCallback(() => {
    void (async () => {
      await markAllRead();
      // Resync the badge after the mutation (3.6); marking all read drops it to 0.
      void syncBadge(store.unreadCount());
    })();
  }, [markAllRead]);

  return (
    <SafeAreaView style={styles.safe} edges={['top', 'left', 'right']}>
      <View style={styles.header}>
        <Text style={styles.headerTitle}>SENTINEL</Text>
        <View style={styles.headerActions}>
          <Pressable
            testID="mark-all-read"
            accessibilityRole="button"
            onPress={onMarkAllRead}
            disabled={unreadCount === 0}
            style={styles.headerButton}
          >
            <Text style={[styles.headerButtonText, unreadCount === 0 && styles.disabled]}>
              ✓ ({unreadCount})
            </Text>
          </Pressable>
          <Pressable
            testID="clear-all"
            accessibilityRole="button"
            onPress={confirmClear}
            disabled={messages.length === 0}
            style={styles.headerButton}
          >
            <Text style={[styles.headerButtonText, messages.length === 0 && styles.disabled]}>
              Wyczyść
            </Text>
          </Pressable>
          <Pressable
            testID="open-settings"
            accessibilityRole="button"
            onPress={() => setSettingsOpen(true)}
            style={styles.headerButton}
          >
            <Text style={styles.headerButtonText}>⚙</Text>
          </Pressable>
        </View>
      </View>

      {messages.length === 0 ? (
        <View testID="empty-state" style={styles.empty}>
          <Text style={styles.emptyTitle}>Brak wiadomości</Text>
          <Text style={styles.emptyBody}>
            Alerty pojawią się tutaj, gdy urządzenie odbierze powiadomienie.
          </Text>
        </View>
      ) : (
        <FlatList
          data={messages}
          keyExtractor={(m) => m.message_id}
          renderItem={({ item }) => <MessageTile message={item} onPress={openDetail} />}
        />
      )}

      <Modal
        visible={settingsOpen}
        animationType="slide"
        onRequestClose={() => setSettingsOpen(false)}
      >
        <PushPanel onClose={() => setSettingsOpen(false)} />
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: {
    flex: 1,
    backgroundColor: '#0a0a0a',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 14,
    paddingVertical: 12,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: '#222',
  },
  headerTitle: {
    color: '#e8e8e8',
    fontSize: 18,
    fontWeight: '700',
    letterSpacing: 2,
  },
  headerActions: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  headerButton: {
    paddingHorizontal: 4,
    paddingVertical: 4,
  },
  headerButtonText: {
    color: '#3dff9a',
    fontSize: 14,
    fontWeight: '600',
  },
  disabled: {
    color: '#444',
  },
  empty: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 32,
  },
  emptyTitle: {
    color: '#e8e8e8',
    fontSize: 16,
    fontWeight: '600',
    marginBottom: 8,
  },
  emptyBody: {
    color: '#7a7a7a',
    fontSize: 13,
    textAlign: 'center',
    lineHeight: 19,
  },
});
