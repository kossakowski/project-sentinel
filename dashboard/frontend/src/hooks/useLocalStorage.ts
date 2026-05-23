import { useCallback, useEffect, useState } from "react";

/**
 * Persistent state hook backed by localStorage. The stored value is JSON
 * serialised and restored on mount. Used for column visibility (req 2.3a) and
 * page size (req 2.7a). When localStorage is unavailable (private mode, SSR
 * tests with a mocked global, etc.) the hook falls back to in-memory state
 * silently.
 */
export function useLocalStorage<T>(
  key: string,
  initialValue: T,
): [T, (value: T | ((prev: T) => T)) => void] {
  const [stored, setStored] = useState<T>(() => readFromStorage(key, initialValue));

  // Re-read when the key changes (rare but covers tests that swap keys).
  useEffect(() => {
    setStored(readFromStorage(key, initialValue));
    // We intentionally do not depend on `initialValue` — only the key controls
    // re-reads, otherwise every render with a new object literal would reset.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const update = useCallback(
    (value: T | ((prev: T) => T)) => {
      setStored((prev) => {
        const next =
          typeof value === "function"
            ? (value as (p: T) => T)(prev)
            : value;
        try {
          window.localStorage.setItem(key, JSON.stringify(next));
        } catch {
          // localStorage may be unavailable; silently keep in-memory state.
        }
        return next;
      });
    },
    [key],
  );

  return [stored, update];
}

function readFromStorage<T>(key: string, fallback: T): T {
  try {
    const raw = window.localStorage.getItem(key);
    if (raw === null) return fallback;
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}
