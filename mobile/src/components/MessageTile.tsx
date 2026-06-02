/**
 * One inbox row — an SMS-style tile (3.7).
 *
 * Shows the type emoji (🚨 event / ℹ️ update) + `event_type_pl`, the urgency
 * `X/10`, a one-line `summary_pl` snippet, a relative local timestamp, and — for an
 * unread message — an unread dot (`testID="unread-dot"`). Tapping the tile invokes
 * `onPress` with the message's `message_id` (the List screen navigates to Detail).
 */

import { memo } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import type { StoredMessage } from '../messages/types';
import { relative } from '../utils/datetime';

export type MessageTileProps = {
  message: StoredMessage;
  onPress: (messageId: string) => void;
  /** Injected `now` for deterministic relative-time rendering in tests. */
  nowMs?: number;
};

/** The emoji for a message kind — mirrors the push title prefix (3.7). */
function kindEmoji(kind: StoredMessage['kind']): string {
  return kind === 'update' ? 'ℹ️' : '🚨';
}

function MessageTileImpl({ message, onPress, nowMs }: MessageTileProps) {
  const urgency = message.urgency_score == null ? '—' : `${message.urgency_score}`;
  const snippet = message.summary_pl.replace(/\s+/g, ' ').trim();

  return (
    <Pressable
      testID="message-tile"
      accessibilityRole="button"
      onPress={() => onPress(message.message_id)}
      style={({ pressed }) => [styles.tile, pressed && styles.tilePressed]}
    >
      <View style={styles.leadColumn}>
        {!message.read && <View testID="unread-dot" style={styles.unreadDot} />}
      </View>
      <View style={styles.body}>
        <View style={styles.headerRow}>
          <Text style={styles.title} numberOfLines={1}>
            {kindEmoji(message.kind)} {message.event_type_pl}
          </Text>
          <Text style={styles.time}>{relative(message.received_at, nowMs)}</Text>
        </View>
        <Text style={styles.urgency}>{urgency}/10</Text>
        <Text style={styles.snippet} numberOfLines={1}>
          {snippet}
        </Text>
      </View>
    </Pressable>
  );
}

export const MessageTile = memo(MessageTileImpl);

export default MessageTile;

const styles = StyleSheet.create({
  tile: {
    flexDirection: 'row',
    paddingVertical: 12,
    paddingHorizontal: 14,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: '#222',
  },
  tilePressed: {
    backgroundColor: '#141414',
  },
  leadColumn: {
    width: 16,
    alignItems: 'center',
    paddingTop: 6,
  },
  unreadDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: '#3dff9a',
  },
  body: {
    flex: 1,
  },
  headerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  title: {
    flex: 1,
    color: '#e8e8e8',
    fontSize: 15,
    fontWeight: '600',
    marginRight: 8,
  },
  time: {
    color: '#5a5a5a',
    fontSize: 12,
  },
  urgency: {
    color: '#ff2e4a',
    fontSize: 12,
    fontWeight: '700',
    marginTop: 2,
  },
  snippet: {
    color: '#9a9a9a',
    fontSize: 13,
    marginTop: 2,
  },
});
