/**
 * syncBadge (3.6). expo-notifications is mocked in jest.setup.js; we assert the
 * call and that a `false` return / a rejection is tolerated without throwing.
 */

import * as Notifications from 'expo-notifications';

import { syncBadge } from '../badge';

const setBadgeCountAsync = Notifications.setBadgeCountAsync as jest.Mock;

beforeEach(() => {
  setBadgeCountAsync.mockReset();
  setBadgeCountAsync.mockResolvedValue(true);
});

describe('syncBadge', () => {
  test('test_sync_badge_sets_unread_count', async () => {
    await syncBadge(3);
    expect(setBadgeCountAsync).toHaveBeenCalledWith(3);

    await syncBadge(0);
    expect(setBadgeCountAsync).toHaveBeenCalledWith(0);
  });

  test('tolerates a false return (allowBadge ungranted)', async () => {
    setBadgeCountAsync.mockResolvedValueOnce(false);
    await expect(syncBadge(2)).resolves.toBe(false);
  });

  test('tolerates a rejected setBadgeCountAsync (no throw)', async () => {
    setBadgeCountAsync.mockRejectedValueOnce(new Error('boom'));
    await expect(syncBadge(5)).resolves.toBe(false);
  });

  test('clamps a negative / non-finite count to 0', async () => {
    await syncBadge(-4);
    expect(setBadgeCountAsync).toHaveBeenCalledWith(0);
    await syncBadge(Number.NaN);
    expect(setBadgeCountAsync).toHaveBeenLastCalledWith(0);
  });
});
