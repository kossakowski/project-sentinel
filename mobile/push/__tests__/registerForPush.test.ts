/**
 * registerForPush (3.6a / 3.12). expo-notifications is mocked in jest.setup.js;
 * here we additionally pin expo-device (isDevice=true) and expo-constants
 * (projectId) so the permission + token-minting path runs. Asserts that the
 * permission request carries `ios.allowBadge:true` and that the token is minted
 * with the configured projectId.
 */

jest.mock('expo-device', () => ({ __esModule: true, isDevice: true }));
jest.mock('expo-constants', () => ({
  __esModule: true,
  default: {
    expoConfig: { extra: { eas: { projectId: 'test-project-id' } } },
    easConfig: { projectId: 'test-project-id' },
  },
}));

import * as Notifications from 'expo-notifications';

import { registerForPushNotificationsAsync } from '../registerForPush';

const getPermissions = Notifications.getPermissionsAsync as jest.Mock;
const requestPermissions = Notifications.requestPermissionsAsync as jest.Mock;
const getToken = Notifications.getExpoPushTokenAsync as jest.Mock;

beforeEach(() => {
  getPermissions.mockReset();
  requestPermissions.mockReset();
  getToken.mockReset();
});

describe('registerForPushNotificationsAsync', () => {
  test('test_register_for_push_requests_allowBadge_and_mints', async () => {
    // Permission not yet granted -> requestPermissionsAsync is called.
    getPermissions.mockResolvedValue({ status: 'undetermined' });
    requestPermissions.mockResolvedValue({ status: 'granted' });
    getToken.mockResolvedValue({ data: 'ExponentPushToken[abc]' });

    const result = await registerForPushNotificationsAsync();

    // 3.6a: the request explicitly opts into the badge permission.
    expect(requestPermissions).toHaveBeenCalledTimes(1);
    const arg = requestPermissions.mock.calls[0][0];
    expect(arg.ios.allowBadge).toBe(true);
    expect(arg.ios.allowAlert).toBe(true);
    expect(arg.ios.allowSound).toBe(true);

    // 3.12: token-minting unchanged — getExpoPushTokenAsync with the configured projectId.
    expect(getToken).toHaveBeenCalledWith({ projectId: 'test-project-id' });
    expect(result).toEqual({ token: 'ExponentPushToken[abc]', status: 'granted' });
  });

  test('skips the permission request when already granted, still mints', async () => {
    getPermissions.mockResolvedValue({ status: 'granted' });
    getToken.mockResolvedValue({ data: 'ExponentPushToken[xyz]' });

    const result = await registerForPushNotificationsAsync();

    expect(requestPermissions).not.toHaveBeenCalled();
    expect(getToken).toHaveBeenCalledWith({ projectId: 'test-project-id' });
    expect(result.token).toBe('ExponentPushToken[xyz]');
  });
});
