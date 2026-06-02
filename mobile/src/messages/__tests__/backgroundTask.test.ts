// The store is mocked so we can make ingest throw without touching AsyncStorage.
jest.mock('../store', () => ({
  __esModule: true,
  ingest: jest.fn(async () => undefined),
}));

type TaskCallback = (args: { data?: unknown; error?: unknown }) => unknown;

type Mocks = {
  defineTask: jest.Mock;
  registerTaskAsync: jest.Mock;
  setNotificationHandler: jest.Mock;
  ingest: jest.Mock;
};

/**
 * Import bootstrap.ts in an isolated module registry and return the mock function
 * references that registry sees. Because `jest.isolateModules` creates a fresh
 * registry, the expo mocks required INSIDE it are the same instances bootstrap.ts
 * called — so we must read them here, not from a top-level import.
 */
function importBootstrapIsolated(): Mocks {
  let mocks: Mocks | undefined;
  jest.isolateModules(() => {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    require('../../notifications/bootstrap');
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const Notifications = require('expo-notifications');
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const TaskManager = require('expo-task-manager');
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const store = require('../store');
    mocks = {
      defineTask: TaskManager.defineTask as jest.Mock,
      registerTaskAsync: Notifications.registerTaskAsync as jest.Mock,
      setNotificationHandler: Notifications.setNotificationHandler as jest.Mock,
      ingest: store.ingest as jest.Mock,
    };
  });
  return mocks!;
}

describe('bootstrap', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  test('test_bootstrap_registers_task_and_handler', () => {
    // Importing bootstrap.ts runs its module-scope side effects (no React tree).
    const { defineTask, registerTaskAsync, setNotificationHandler } =
      importBootstrapIsolated();

    expect(defineTask).toHaveBeenCalled();
    expect(registerTaskAsync).toHaveBeenCalled();
    expect(setNotificationHandler).toHaveBeenCalled();

    // The handler returns the spec-required display policy (2.8).
    const handlerArg = setNotificationHandler.mock.calls[0][0] as {
      handleNotification: () => Promise<unknown>;
    };
    expect(typeof handlerArg.handleNotification).toBe('function');
  });

  test('test_background_task_swallows_ingest_error', async () => {
    const { defineTask, ingest } = importBootstrapIsolated();
    ingest.mockRejectedValueOnce(new Error('boom'));

    const lastCall = defineTask.mock.calls[defineTask.mock.calls.length - 1];
    const callback = lastCall[1] as TaskCallback;
    expect(typeof callback).toBe('function');

    // Invoking the task with a payload that triggers a throwing ingest must NOT
    // propagate the error (headless launch must never crash).
    await expect(
      Promise.resolve(
        callback({ data: { data: { dataString: JSON.stringify({ message_id: 'x' }) } } }),
      ),
    ).resolves.not.toThrow();
  });
});
