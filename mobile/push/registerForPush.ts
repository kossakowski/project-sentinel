import { Platform } from 'react-native';
import * as Notifications from 'expo-notifications';
import * as Device from 'expo-device';
import Constants from 'expo-constants';

// Show notifications even when the app is in the foreground. The
// NotificationBehavior shape changed across expo-notifications versions; for the
// SDK 54 line (expo-notifications 0.32.x) the banner/list flags are required and
// shouldShowAlert is deprecated.
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowBanner: true,
    shouldShowList: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
  }),
});

export type PushRegistrationResult = {
  token: string | null;
  status: string;
};

/**
 * Registers the device for Expo push notifications and returns the resulting
 * Expo push token (or null with a descriptive status when registration cannot
 * complete). Safe to call on simulators — it short-circuits with a clear status.
 */
export async function registerForPushNotificationsAsync(): Promise<PushRegistrationResult> {
  // Android requires an explicit notification channel. Use MAX importance so a
  // critical military-threat alert breaks through with sound + heads-up banner.
  if (Platform.OS === 'android') {
    await Notifications.setNotificationChannelAsync('alerts', {
      name: 'alerts',
      importance: Notifications.AndroidImportance.MAX,
    });
  }

  // Push tokens are not issued on simulators/emulators.
  if (!Device.isDevice) {
    return { token: null, status: 'must-use-physical-device' };
  }

  const { status: existingStatus } = await Notifications.getPermissionsAsync();
  let finalStatus = existingStatus;
  if (existingStatus !== 'granted') {
    const { status } = await Notifications.requestPermissionsAsync();
    finalStatus = status;
  }
  if (finalStatus !== 'granted') {
    return { token: null, status: 'denied' };
  }

  // The EAS project id is sourced from app.json (extra.eas.projectId), never
  // hardcoded here. Without it the Expo push service cannot mint a token.
  const projectId =
    Constants.expoConfig?.extra?.eas?.projectId ?? Constants.easConfig?.projectId;

  try {
    const tokenResponse = await Notifications.getExpoPushTokenAsync({ projectId });
    return { token: tokenResponse.data, status: 'granted' };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return { token: null, status: `error: ${message}` };
  }
}
