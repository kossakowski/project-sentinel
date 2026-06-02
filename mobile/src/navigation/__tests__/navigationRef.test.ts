/**
 * navigationRef cold-start queue (3.3). We mock @react-navigation/native's
 * `createNavigationContainerRef` so `isReady`/`navigate` are controllable jest fns
 * — the queue logic is what we exercise, not React Navigation itself.
 *
 * The mock object is built INSIDE the factory (and the same instance returned on
 * every call) so it is fully initialized when `navigationRef.ts` calls the factory
 * at import time — a top-level `const` would still be in the temporal dead zone at
 * that point and yield `isReady: undefined`.
 */

jest.mock('@react-navigation/native', () => {
  const ref = { isReady: jest.fn(), navigate: jest.fn() };
  return {
    __esModule: true,
    createNavigationContainerRef: () => ref,
  };
});

import { createNavigationContainerRef } from '@react-navigation/native';
import {
  navigate as navHelper,
  flushPendingRoute,
  hasPendingRoute,
  resetPendingRoute,
} from '../navigationRef';

// The single ref instance the mock hands out — its jest fns drive the tests.
const ref = createNavigationContainerRef() as unknown as {
  isReady: jest.Mock;
  navigate: jest.Mock;
};
const mockIsReady = ref.isReady;
const mockNavigate = ref.navigate;

beforeEach(() => {
  mockIsReady.mockReset();
  mockNavigate.mockReset();
  resetPendingRoute();
});

describe('navigationRef', () => {
  test('test_navigation_ref_queues_until_ready', () => {
    // Not ready: navigate() must NOT call the underlying navigator; it queues.
    mockIsReady.mockReturnValue(false);
    navHelper('Detail', { messageId: 'm1' });
    expect(mockNavigate).not.toHaveBeenCalled();
    expect(hasPendingRoute()).toBe(true);

    // Once ready, flushPendingRoute() replays it exactly once.
    mockIsReady.mockReturnValue(true);
    flushPendingRoute();
    expect(mockNavigate).toHaveBeenCalledTimes(1);
    expect(mockNavigate).toHaveBeenCalledWith('Detail', { messageId: 'm1' });
    expect(hasPendingRoute()).toBe(false);

    // A second flush with nothing queued is a no-op.
    flushPendingRoute();
    expect(mockNavigate).toHaveBeenCalledTimes(1);
  });

  test('navigate dispatches immediately when ready', () => {
    mockIsReady.mockReturnValue(true);
    navHelper('Detail', { messageId: 'mX' });
    expect(mockNavigate).toHaveBeenCalledWith('Detail', { messageId: 'mX' });
    expect(hasPendingRoute()).toBe(false);
  });

  test('latest queued route wins before flush', () => {
    mockIsReady.mockReturnValue(false);
    navHelper('Detail', { messageId: 'first' });
    navHelper('Detail', { messageId: 'second' });
    mockIsReady.mockReturnValue(true);
    flushPendingRoute();
    expect(mockNavigate).toHaveBeenCalledTimes(1);
    expect(mockNavigate).toHaveBeenCalledWith('Detail', { messageId: 'second' });
  });
});
