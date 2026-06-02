/**
 * App entry — the navigation shell (3.2).
 *
 * Renders `SafeAreaProvider` → `NavigationContainer` (`ref={navigationRef}`,
 * `onReady` flushes any pending cold-start route) → a native-stack with `List`
 * (initial) and `Detail`. The design-showcase is no longer the entry (designs/
 * stay in the repo, unused — Non-Goals).
 *
 * At the root it wires the reliable capture + routing paths:
 *  - `attachForegroundCapture()` — foreground-received push → ingest;
 *  - tray-sweep on `AppState` → 'active' (`sweepPresented`) — the de-facto
 *    background capture (AD-3);
 *  - `useNotificationRouting()` — warm + cold tap → ingest → navigate to Detail;
 *  - `syncBadge(unread)` — badge resync on foreground and after every ingest.
 * The notification handler + headless background task are registered in
 * `index.ts` → `bootstrap.ts` (2.5 / 2.8) before this tree mounts.
 */

import { useCallback, useEffect, useRef } from 'react';
import { AppState, type AppStateStatus } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { NavigationContainer } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';

import { navigationRef, flushPendingRoute, type RootStackParamList } from './src/navigation/navigationRef';
import { attachForegroundCapture, sweepPresented } from './src/notifications/capture';
import { useNotificationRouting } from './src/notifications/useNotificationRouting';
import { syncBadge } from './src/badge';
import * as store from './src/messages/store';
import MessageListScreen from './src/screens/MessageListScreen';
import MessageDetailScreen from './src/screens/MessageDetailScreen';

const Stack = createNativeStackNavigator<RootStackParamList>();

export default function App() {
  // Resync the badge from the store's current unread count (after an ingest/foreground).
  const resyncBadge = useCallback(() => {
    void syncBadge(store.unreadCount());
  }, []);

  // Tap → Detail routing (warm + cold), ingesting before navigating.
  useNotificationRouting(resyncBadge);

  // Foreground capture: a push received while foregrounded → ingest → badge.
  useEffect(() => {
    const detach = attachForegroundCapture(resyncBadge);
    return detach;
  }, [resyncBadge]);

  // Tray-sweep on every foreground transition + once on mount (de-facto background
  // capture). Also resync the badge on foreground.
  const appState = useRef<AppStateStatus>(AppState.currentState);
  useEffect(() => {
    // Initial sweep at launch (the app may open with tray notifications present).
    void sweepPresented(resyncBadge).finally(resyncBadge);

    const subscription = AppState.addEventListener('change', (next) => {
      const prev = appState.current;
      appState.current = next;
      if (next === 'active' && prev !== 'active') {
        void sweepPresented(resyncBadge).finally(resyncBadge);
      }
    });
    return () => {
      subscription.remove();
    };
  }, [resyncBadge]);

  return (
    <SafeAreaProvider>
      <NavigationContainer ref={navigationRef} onReady={flushPendingRoute}>
        <Stack.Navigator initialRouteName="List" screenOptions={{ headerShown: false }}>
          <Stack.Screen name="List" component={MessageListScreen} />
          <Stack.Screen name="Detail" component={MessageDetailScreen} />
        </Stack.Navigator>
      </NavigationContainer>
      <StatusBar style="light" />
    </SafeAreaProvider>
  );
}
