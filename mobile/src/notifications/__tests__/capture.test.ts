/**
 * Reliable capture (3.5 / 3.14). expo-notifications is mocked (jest.setup.js); the
 * store is the REAL store over the AsyncStorage jest mock so dedup is genuinely
 * exercised (foreground-then-sweep yields one entry).
 */

import AsyncStorage from '@react-native-async-storage/async-storage';
import * as Notifications from 'expo-notifications';

import { attachForegroundCapture, sweepPresented } from '../capture';
import * as store from '../../messages/store';

const addReceived = Notifications.addNotificationReceivedListener as jest.Mock;
const getPresented = Notifications.getPresentedNotificationsAsync as jest.Mock;

/** A foreground/tray notification carrying the given data + body. */
function notif(messageId: string, body = 'b') {
  return {
    request: {
      identifier: `os-${Math.random()}`,
      content: {
        title: '🚨 PROJECT SENTINEL: Test',
        body,
        data: { message_id: messageId, event_id: 'evt', summary_pl: 'S' },
      },
    },
  };
}

beforeEach(async () => {
  await AsyncStorage.clear();
  await store.load();
  addReceived.mockReset();
  getPresented.mockReset();
});

describe('attachForegroundCapture', () => {
  test('test_foreground_listener_ingests', async () => {
    let captured: ((n: unknown) => void) | undefined;
    addReceived.mockImplementation((cb: (n: unknown) => void) => {
      captured = cb;
      return { remove: jest.fn() };
    });

    const onIngest = jest.fn();
    const detach = attachForegroundCapture(onIngest);
    expect(typeof captured).toBe('function');

    // Fire the OS callback once and let the async ingest settle.
    captured!(notif('m1'));
    await new Promise((r) => setTimeout(r, 0));

    const all = await store.load();
    expect(all).toHaveLength(1);
    expect(all[0].message_id).toBe('m1');
    expect(onIngest).toHaveBeenCalledTimes(1);

    detach();
  });

  test('detach removes the subscription without throwing', () => {
    const remove = jest.fn();
    addReceived.mockReturnValue({ remove });
    const detach = attachForegroundCapture();
    detach();
    expect(remove).toHaveBeenCalled();
  });
});

describe('sweepPresented', () => {
  test('test_sweep_presented_ingests_null_guarded', async () => {
    // Two tray entries: one valid, one with content.data undefined.
    getPresented.mockResolvedValueOnce([
      notif('valid'),
      { request: { identifier: 'os-x', content: { title: 't', body: 'b', data: undefined } } },
    ]);

    const onIngest = jest.fn();
    await expect(sweepPresented(onIngest)).resolves.toBeUndefined();

    const all = await store.load();
    expect(all).toHaveLength(1);
    expect(all[0].message_id).toBe('valid');
    expect(onIngest).toHaveBeenCalledTimes(1);
  });

  test('a rejected getPresentedNotificationsAsync is swallowed', async () => {
    getPresented.mockRejectedValueOnce(new Error('tray boom'));
    await expect(sweepPresented()).resolves.toBeUndefined();
    expect(await store.load()).toHaveLength(0);
  });

  test('test_foreground_then_sweep_single_entry', async () => {
    // Same delivery via foreground then via sweep => one stored message (dedup).
    let captured: ((n: unknown) => void) | undefined;
    addReceived.mockImplementation((cb: (n: unknown) => void) => {
      captured = cb;
      return { remove: jest.fn() };
    });
    attachForegroundCapture();

    captured!(notif('same'));
    await new Promise((r) => setTimeout(r, 0));

    getPresented.mockResolvedValueOnce([notif('same')]);
    await sweepPresented();

    const all = await store.load();
    expect(all).toHaveLength(1);
    expect(all[0].message_id).toBe('same');
  });
});
