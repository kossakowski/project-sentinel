/**
 * Full-message screen (3.9 / 3.10).
 *
 * Re-renders the SAME structured fields the SMS carries — not a byte copy of
 * `sms_body` — in this exact top-to-bottom order (owned by this spec):
 *   (1) detail-header   emoji + event_type_pl
 *   (2) detail-urgency  Pilność: {urgency}/10
 *   (3) detail-countries Kraje: {affected_countries joined}
 *   (4) detail-aggressor Agresor: {aggressor}   (omitted when empty/whitespace)
 *   (5) detail-summary   the full summary_pl
 *   (6) detail-sources   Źródła ({sources.length}) — each {name}: {title}, link
 *                        tappable via WebBrowser.openBrowserAsync (in-app) when url
 *                        is non-null; plain text when null
 *   (7) detail-time      Wykryto: {first_seen_at} in device-local time
 *
 * On mount it marks the message read (`store.markRead`). It provides a delete
 * action (confirm → `store.remove`). Both mutations resync the app-icon badge from
 * the store's live unread count (3.6), so dropping the badge does not wait for the
 * list's next focus pass. When the structured fields are absent (a legacy thin
 * push) it falls back to rendering `sms_body` (or `body`).
 *
 * The store is consumed via `useMessages()` (the mock seam for tests).
 */

import { useCallback, useEffect, useMemo } from 'react';
import {
  Alert,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import * as WebBrowser from 'expo-web-browser';
import {
  useNavigation,
  useRoute,
  type NavigationProp,
  type RouteProp,
} from '@react-navigation/native';

import { useMessages } from '../messages/useMessages';
import * as store from '../messages/store';
import type { MessageSource, StoredMessage } from '../messages/types';
import type { RootStackParamList } from '../navigation/navigationRef';
import { absolute } from '../utils/datetime';
import { syncBadge } from '../badge';

function kindEmoji(kind: StoredMessage['kind']): string {
  return kind === 'update' ? 'ℹ️' : '🚨';
}

/** A message is "structured" when it carries renderable structured content. */
function hasStructuredContent(m: StoredMessage): boolean {
  return m.summary_pl.trim().length > 0 || m.sources.length > 0;
}

/** Open a source link in the in-app browser; swallow any failure (3.10 / 3.14). */
async function openSource(url: string): Promise<void> {
  try {
    await WebBrowser.openBrowserAsync(url);
  } catch (err) {
    // A failed/rejected open must not crash the screen.
    console.warn('[inbox] failed to open source link', err);
  }
}

function SourceRow({ source }: { source: MessageSource }) {
  const label = `${source.name}: ${source.title}`;
  if (source.url == null) {
    return (
      <Text testID="source-row" style={styles.sourcePlain}>
        {label}
      </Text>
    );
  }
  const url = source.url;
  return (
    <Pressable
      testID="source-row"
      accessibilityRole="link"
      onPress={() => {
        void openSource(url);
      }}
    >
      <Text style={styles.sourceLink}>{label}</Text>
    </Pressable>
  );
}

export default function MessageDetailScreen() {
  const navigation = useNavigation<NavigationProp<RootStackParamList>>();
  const route = useRoute<RouteProp<RootStackParamList, 'Detail'>>();
  const { messageId } = route.params;
  const { messages, markRead, remove } = useMessages();

  const message = useMemo(
    () => messages.find((m) => m.message_id === messageId),
    [messages, messageId],
  );

  // Mark read on mount (3.9). Keyed on messageId so revisiting another message marks it too.
  // Resync the badge after the mutation (3.6) — markRead awaits the store write, so
  // unreadCount() then reflects the decremented count.
  useEffect(() => {
    void (async () => {
      await markRead(messageId);
      void syncBadge(store.unreadCount());
    })();
  }, [markRead, messageId]);

  const confirmDelete = useCallback(() => {
    Alert.alert(
      'Usuń wiadomość',
      'Usunąć tę wiadomość?',
      [
        { text: 'Anuluj', style: 'cancel' },
        {
          text: 'Usuń',
          style: 'destructive',
          onPress: () => {
            void (async () => {
              await remove(messageId);
              // Resync the badge after the mutation (3.6); removing an unread
              // message lowers the unread count.
              void syncBadge(store.unreadCount());
              navigation.goBack();
            })();
          },
        },
      ],
    );
  }, [remove, messageId, navigation]);

  if (!message) {
    return (
      <SafeAreaView style={styles.safe} edges={['top', 'left', 'right']}>
        <View style={styles.missing}>
          <Text style={styles.missingText}>Wiadomość niedostępna.</Text>
        </View>
      </SafeAreaView>
    );
  }

  const aggressor = message.aggressor.trim();
  const showAggressor = aggressor.length > 0;
  const urgency = message.urgency_score == null ? '—' : `${message.urgency_score}`;
  const countries = message.affected_countries.join(', ');
  const structured = hasStructuredContent(message);
  // sms_body fallback for a legacy thin push (3.9).
  const fallbackText = message.sms_body.length > 0 ? message.sms_body : message.summary_pl;

  return (
    <SafeAreaView style={styles.safe} edges={['top', 'left', 'right']}>
      <View style={styles.topBar}>
        <Pressable
          testID="detail-back"
          accessibilityRole="button"
          onPress={() => navigation.goBack()}
          style={styles.topButton}
        >
          <Text style={styles.topButtonText}>‹ Wróć</Text>
        </Pressable>
        <Pressable
          testID="detail-delete"
          accessibilityRole="button"
          onPress={confirmDelete}
          style={styles.topButton}
        >
          <Text style={[styles.topButtonText, styles.deleteText]}>Usuń</Text>
        </Pressable>
      </View>

      <ScrollView contentContainerStyle={styles.content}>
        <Text testID="detail-header" style={styles.header}>
          {kindEmoji(message.kind)} {message.event_type_pl}
        </Text>

        {structured ? (
          <>
            <Text testID="detail-urgency" style={styles.field}>
              Pilność: {urgency}/10
            </Text>
            <Text testID="detail-countries" style={styles.field}>
              Kraje: {countries}
            </Text>
            {showAggressor && (
              <Text testID="detail-aggressor" style={styles.field}>
                Agresor: {aggressor}
              </Text>
            )}
            <Text testID="detail-summary" style={styles.summary}>
              {message.summary_pl}
            </Text>
            <View testID="detail-sources" style={styles.sources}>
              <Text style={styles.sourcesHeading}>Źródła ({message.sources.length})</Text>
              {message.sources.map((source, idx) => (
                <SourceRow key={`${source.url ?? 'nourl'}-${idx}`} source={source} />
              ))}
            </View>
            <Text testID="detail-time" style={styles.time}>
              Wykryto: {absolute(message.first_seen_at)}
            </Text>
          </>
        ) : (
          <Text testID="detail-fallback" style={styles.summary}>
            {fallbackText}
          </Text>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: {
    flex: 1,
    backgroundColor: '#0a0a0a',
  },
  topBar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: '#222',
  },
  topButton: {
    paddingHorizontal: 6,
    paddingVertical: 4,
  },
  topButtonText: {
    color: '#3dff9a',
    fontSize: 15,
    fontWeight: '600',
  },
  deleteText: {
    color: '#ff2e4a',
  },
  content: {
    padding: 18,
  },
  header: {
    color: '#e8e8e8',
    fontSize: 20,
    fontWeight: '700',
    marginBottom: 14,
  },
  field: {
    color: '#cfcfcf',
    fontSize: 15,
    marginBottom: 8,
  },
  summary: {
    color: '#e8e8e8',
    fontSize: 16,
    lineHeight: 23,
    marginTop: 8,
    marginBottom: 18,
  },
  sources: {
    marginBottom: 18,
  },
  sourcesHeading: {
    color: '#9a9a9a',
    fontSize: 13,
    fontWeight: '700',
    letterSpacing: 0.5,
    marginBottom: 8,
  },
  sourceLink: {
    color: '#3dff9a',
    fontSize: 14,
    lineHeight: 21,
    marginBottom: 8,
    textDecorationLine: 'underline',
  },
  sourcePlain: {
    color: '#9a9a9a',
    fontSize: 14,
    lineHeight: 21,
    marginBottom: 8,
  },
  time: {
    color: '#7a7a7a',
    fontSize: 13,
  },
  missing: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  missingText: {
    color: '#7a7a7a',
    fontSize: 14,
  },
});
