/**
 * Tap-routing wiring integration test (3.4).
 *
 * `routing.test.ts` covers the pure `decideRoute`; this file mounts the actual
 * `useNotificationRouting` hook and proves the load-bearing 3.4 glue that
 * `decideRoute` alone cannot:
 *   - it acts ONLY on `DEFAULT_ACTION_IDENTIFIER` (a dismissal/custom action is ignored);
 *   - it `store.ingest`s the tapped payload BEFORE navigating (ordering);
 *   - it consumes the cold response with `clearLastNotificationResponseAsync()`;
 *   - it collapses the cold+warm double-fire of ONE physical tap into a SINGLE
 *     navigation (the in-session `lastHandledRef` guard).
 *
 * Seams: `expo-notifications` is mocked (jest.setup.js); the warm listener callback
 * is captured from `addNotificationResponseReceivedListener` and the cold response
 * is driven through `useLastNotificationResponse`. `../navigation/navigationRef` is
 * mocked so we can assert `navigate(...)`. The store is the REAL store over the
 * AsyncStorage jest mock, so ingest-before-navigate is genuinely exercised (not a
 * stub) and the same `message_id` from cold + warm dedups to one stored entry.
 */

import { renderHook, act } from '@testing-library/react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as Notifications from 'expo-notifications';

// Mock the navigation ref so we can observe navigate() without a real container.
jest.mock('../../navigation/navigationRef', () => ({
  __esModule: true,
  navigate: jest.fn(),
}));

import { navigate } from '../../navigation/navigationRef';
import * as store from '../../messages/store';
import { useNotificationRouting } from '../useNotificationRouting';

const DEFAULT = Notifications.DEFAULT_ACTION_IDENTIFIER;
const navigateMock = navigate as jest.Mock;
const addResponse = Notifications.addNotificationResponseReceivedListener as jest.Mock;
const useLastResponse = Notifications.useLastNotificationResponse as jest.Mock;
const clearLast = Notifications.clearLastNotificationResponseAsync as jest.Mock;

type WarmCb = (response: unknown) => void;

/** Build a tap response carrying the given message_id and actionIdentifier. */
function tapResponse(messageId: string, actionIdentifier: string = DEFAULT) {
  return {
    actionIdentifier,
    notification: {
      request: {
        identifier: `os-${Math.random()}`,
        content: {
          title: '🚨 PROJECT SENTINEL: Test',
          body: 'b',
          data: { message_id: messageId, event_id: 'evt', summary_pl: 'S' },
        },
      },
    },
  };
}

/** A microtask flush so awaited ingest + finally callbacks settle. */
async function flush() {
  await act(async () => {
    await new Promise((r) => setTimeout(r, 0));
  });
}

let warmCb: WarmCb | undefined;

beforeEach(async () => {
  await AsyncStorage.clear();
  await store.load();
  navigateMock.mockReset();
  addResponse.mockReset();
  clearLast.mockReset();
  clearLast.mockResolvedValue(undefined);
  useLastResponse.mockReset();
  useLastResponse.mockReturnValue(null);
  warmCb = undefined;
  addResponse.mockImplementation((cb: WarmCb) => {
    warmCb = cb;
    return { remove: jest.fn() };
  });
});

describe('useNotificationRouting (warm path)', () => {
  test('ingests then navigates to Detail for a DEFAULT-action tap', async () => {
    renderHook(() => useNotificationRouting());
    expect(typeof warmCb).toBe('function');

    await act(async () => {
      warmCb!(tapResponse('warm-1'));
    });
    await flush();

    // Ingested into the real store...
    const all = await store.load();
    expect(all).toHaveLength(1);
    expect(all[0].message_id).toBe('warm-1');
    // ...and navigated to Detail for that message.
    expect(navigateMock).toHaveBeenCalledTimes(1);
    expect(navigateMock).toHaveBeenCalledWith('Detail', { messageId: 'warm-1' });
  });

  test('ingest happens BEFORE navigate (ordering, 3.4)', async () => {
    // Spy on the real store.ingest to capture call ordering vs navigate.
    const calls: string[] = [];
    const ingestSpy = jest
      .spyOn(store, 'ingest')
      .mockImplementation(async () => {
        calls.push('ingest');
      });
    navigateMock.mockImplementation(() => {
      calls.push('navigate');
    });

    renderHook(() => useNotificationRouting());
    await act(async () => {
      warmCb!(tapResponse('order-1'));
    });
    await flush();

    expect(calls).toEqual(['ingest', 'navigate']);
    ingestSpy.mockRestore();
  });

  test('ignores a non-DEFAULT actionIdentifier (dismissal/custom action)', async () => {
    renderHook(() => useNotificationRouting());
    await act(async () => {
      warmCb!(tapResponse('dismiss-1', 'some.custom.action'));
    });
    await flush();

    expect(navigateMock).not.toHaveBeenCalled();
    expect(await store.load()).toHaveLength(0);
  });

  test('fires onIngest after a tap ingest (badge resync seam)', async () => {
    const onIngest = jest.fn();
    renderHook(() => useNotificationRouting(onIngest));
    await act(async () => {
      warmCb!(tapResponse('warm-2'));
    });
    await flush();
    expect(onIngest).toHaveBeenCalledTimes(1);
  });
});

describe('useNotificationRouting (cold path)', () => {
  test('navigates for the launch response and consumes it via clearLastNotificationResponseAsync', async () => {
    useLastResponse.mockReturnValue(tapResponse('cold-1'));

    renderHook(() => useNotificationRouting());
    await flush();

    expect(navigateMock).toHaveBeenCalledTimes(1);
    expect(navigateMock).toHaveBeenCalledWith('Detail', { messageId: 'cold-1' });
    // The cold response MUST be consumed so a later normal launch does not re-open it.
    expect(clearLast).toHaveBeenCalledTimes(1);

    const all = await store.load();
    expect(all).toHaveLength(1);
    expect(all[0].message_id).toBe('cold-1');
  });

  test('a non-DEFAULT cold response does not navigate', async () => {
    useLastResponse.mockReturnValue(tapResponse('cold-x', 'some.custom.action'));
    renderHook(() => useNotificationRouting());
    await flush();
    expect(navigateMock).not.toHaveBeenCalled();
  });
});

describe('useNotificationRouting (cold + warm collapse, 3.4)', () => {
  test('one physical tap surfaced via BOTH cold and warm navigates exactly once and stores one entry', async () => {
    // Same delivery: the cold hook returns it AND the warm listener re-fires it.
    const cold = tapResponse('tap-collapse');
    useLastResponse.mockReturnValue(cold);

    renderHook(() => useNotificationRouting());
    // Let the cold effect run (navigate + ingest + clear).
    await flush();

    // Warm listener re-delivers the SAME message_id (a different OS identifier).
    await act(async () => {
      warmCb!(tapResponse('tap-collapse'));
    });
    await flush();

    // Collapsed to a single navigation by the in-session last-handled guard...
    expect(navigateMock).toHaveBeenCalledTimes(1);
    expect(navigateMock).toHaveBeenCalledWith('Detail', { messageId: 'tap-collapse' });
    // ...and a single stored message (store dedup on message_id).
    const all = await store.load();
    expect(all).toHaveLength(1);
    expect(all[0].message_id).toBe('tap-collapse');
  });

  test('two DISTINCT taps each navigate (the guard does not over-collapse)', async () => {
    renderHook(() => useNotificationRouting());
    await act(async () => {
      warmCb!(tapResponse('first'));
    });
    await flush();
    await act(async () => {
      warmCb!(tapResponse('second'));
    });
    await flush();

    expect(navigateMock).toHaveBeenCalledTimes(2);
    expect(navigateMock).toHaveBeenNthCalledWith(1, 'Detail', { messageId: 'first' });
    expect(navigateMock).toHaveBeenNthCalledWith(2, 'Detail', { messageId: 'second' });
  });

  test('a failed ingest is swallowed (a bad tap never crashes the app)', async () => {
    const ingestSpy = jest
      .spyOn(store, 'ingest')
      .mockRejectedValueOnce(new Error('ingest boom'));
    // The hook logs the swallowed failure via console.warn — silence the expected
    // line so the suite output stays clean while still asserting no throw/navigate.
    const warnSpy = jest.spyOn(console, 'warn').mockImplementation(() => undefined);

    renderHook(() => useNotificationRouting());
    // Must not throw out of the warm callback.
    await act(async () => {
      warmCb!(tapResponse('boom'));
    });
    await flush();

    expect(navigateMock).not.toHaveBeenCalled();
    expect(warnSpy).toHaveBeenCalled();
    warnSpy.mockRestore();
    ingestSpy.mockRestore();
  });
});
