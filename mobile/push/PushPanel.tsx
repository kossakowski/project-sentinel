import { useEffect, useState } from 'react';
import {
  Platform,
  Pressable,
  SafeAreaView,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import * as Clipboard from 'expo-clipboard';
import { registerForPushNotificationsAsync } from './registerForPush';
import type { LastPush } from './usePushReceiver';

const MONO = Platform.select({ ios: 'Menlo', android: 'monospace', default: 'monospace' });

const GREEN = '#3dff9a';
const RED = '#ff2e4a';
const DIM = '#5a5a5a';
const TEXT = '#e8e8e8';
const BG = '#0a0a0a';

type Props = {
  onClose: () => void;
  lastPush?: LastPush | null;
};

export default function PushPanel({ onClose, lastPush = null }: Props) {
  const [token, setToken] = useState<string | null>(null);
  const [status, setStatus] = useState<string>('inicjalizacja...');
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let active = true;
    (async () => {
      const result = await registerForPushNotificationsAsync();
      if (!active) return;
      setToken(result.token);
      setStatus(result.status);
      // Surface the token in Metro logs for the dev build.
      console.log('[push] Expo token:', result.token);
    })();
    return () => {
      active = false;
    };
  }, []);

  const copyToken = async () => {
    if (!token) return;
    await Clipboard.setStringAsync(token);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const granted = status === 'granted' && !!token;

  return (
    <SafeAreaView style={styles.safe}>
      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        <Text style={styles.title}>POWIADOMIENIA PUSH</Text>
        <View style={styles.divider} />

        <Text style={styles.label}>OSTATNI PUSH</Text>
        {lastPush ? (
          <View style={styles.tokenBox}>
            <Text style={styles.pushTitle}>{lastPush.title ?? '(bez tytulu)'}</Text>
            <Text style={styles.pushBody}>{lastPush.body ?? '(bez tresci)'}</Text>
          </View>
        ) : (
          <View style={styles.tokenBox}>
            <Text style={styles.tokenEmpty}>brak (jeszcze nic nie odebrano)</Text>
          </View>
        )}

        <Text style={[styles.label, styles.labelSpaced]}>STATUS</Text>
        <Text style={[styles.status, granted ? styles.statusOk : styles.statusBad]}>
          Status: {status}
        </Text>

        <Text style={[styles.label, styles.labelSpaced]}>TOKEN EXPO PUSH</Text>
        {token ? (
          <View style={styles.tokenBox}>
            <Text style={styles.tokenText} selectable>
              {token}
            </Text>
          </View>
        ) : (
          <View style={styles.tokenBox}>
            <Text style={styles.tokenEmpty}>{status}</Text>
          </View>
        )}

        <Pressable
          onPress={copyToken}
          disabled={!token}
          style={[styles.button, styles.buttonPrimary, !token && styles.buttonDisabled]}
        >
          <Text style={[styles.buttonText, styles.buttonTextPrimary]}>
            {copied ? 'skopiowano' : 'KOPIUJ TOKEN'}
          </Text>
        </Pressable>

        <Text style={styles.hint}>
          Wklej ten token do konfiguracji serwera, aby to urzadzenie otrzymywalo alerty o
          zagrozeniu militarnym.
        </Text>

        <Pressable onPress={onClose} style={[styles.button, styles.buttonGhost]}>
          <Text style={[styles.buttonText, styles.buttonTextGhost]}>ZAMKNIJ</Text>
        </Pressable>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: {
    flex: 1,
    backgroundColor: BG,
  },
  content: {
    padding: 24,
    paddingTop: 60,
  },
  title: {
    color: TEXT,
    fontSize: 22,
    fontFamily: MONO,
    letterSpacing: 3,
    fontWeight: '700',
    marginBottom: 14,
  },
  divider: {
    height: 1,
    backgroundColor: '#222',
    marginBottom: 24,
  },
  label: {
    color: DIM,
    fontSize: 10,
    fontFamily: MONO,
    letterSpacing: 1.5,
    marginBottom: 8,
  },
  labelSpaced: {
    marginTop: 24,
  },
  status: {
    fontSize: 13,
    fontFamily: MONO,
    letterSpacing: 1,
  },
  statusOk: {
    color: GREEN,
  },
  statusBad: {
    color: RED,
  },
  tokenBox: {
    borderWidth: 1,
    borderColor: '#222',
    backgroundColor: '#111',
    borderRadius: 6,
    padding: 12,
  },
  tokenText: {
    color: GREEN,
    fontSize: 11,
    fontFamily: MONO,
    letterSpacing: 0.5,
    lineHeight: 18,
  },
  tokenEmpty: {
    color: DIM,
    fontSize: 12,
    fontFamily: MONO,
    letterSpacing: 0.5,
  },
  pushTitle: {
    color: TEXT,
    fontSize: 13,
    fontFamily: MONO,
    letterSpacing: 0.5,
    fontWeight: '700',
    marginBottom: 6,
  },
  pushBody: {
    color: GREEN,
    fontSize: 12,
    fontFamily: MONO,
    letterSpacing: 0.5,
    lineHeight: 18,
  },
  button: {
    marginTop: 18,
    paddingVertical: 12,
    paddingHorizontal: 16,
    borderRadius: 6,
    alignItems: 'center',
  },
  buttonPrimary: {
    backgroundColor: GREEN,
  },
  buttonDisabled: {
    opacity: 0.4,
  },
  buttonGhost: {
    borderWidth: 1,
    borderColor: '#333',
    backgroundColor: 'transparent',
  },
  buttonText: {
    fontSize: 12,
    fontFamily: MONO,
    letterSpacing: 1.5,
    fontWeight: '700',
  },
  buttonTextPrimary: {
    color: BG,
  },
  buttonTextGhost: {
    color: TEXT,
  },
  hint: {
    color: DIM,
    fontSize: 11,
    fontFamily: MONO,
    letterSpacing: 0.5,
    lineHeight: 17,
    marginTop: 20,
  },
});
