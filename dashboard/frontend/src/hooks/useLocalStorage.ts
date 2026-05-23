import { useCallback, useEffect, useState } from "react";

/**
 * Persistent state hook backed by localStorage. The stored value is JSON
 * serialised and restored on mount. Used for column visibility (req 2.3a) and
 * page size (req 2.7a). When localStorage is unavailable (private mode, SSR
 * tests with a mocked global, etc.) the hook falls back to in-memory state
 * silently.
 *
 * Optional ``validator`` runs against any value read from storage. When the
 * validator rejects the value, the hook falls back to ``initialValue`` AND
 * clears the bad key so corrupted state cannot crash downstream consumers
 * (e.g. ArticleTable's visibleColumns.includes call). The default validator
 * accepts anything that JSON.parse produced — preserving the previous
 * behaviour for callers that don't care.
 */
export function useLocalStorage<T>(
  key: string,
  initialValue: T,
  validator?: (value: unknown) => value is T,
): [T, (value: T | ((prev: T) => T)) => void] {
  const [stored, setStored] = useState<T>(() =>
    readFromStorage(key, initialValue, validator),
  );

  // Re-read when the key changes (rare but covers tests that swap keys).
  useEffect(() => {
    setStored(readFromStorage(key, initialValue, validator));
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

function readFromStorage<T>(
  key: string,
  fallback: T,
  validator?: (value: unknown) => value is T,
): T {
  let raw: string | null;
  try {
    raw = window.localStorage.getItem(key);
  } catch {
    return fallback;
  }
  if (raw === null) return fallback;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    // Garbage in storage (manual devtools edit, partial write, version bump).
    // Clear the key so we don't keep tripping over it on every mount.
    removeKey(key);
    return fallback;
  }
  if (validator && !validator(parsed)) {
    // Valid JSON but wrong shape — same hostile state as bad JSON; clear it.
    removeKey(key);
    return fallback;
  }
  return parsed as T;
}

function removeKey(key: string): void {
  try {
    window.localStorage.removeItem(key);
  } catch {
    // Storage may be unavailable; ignore — fallback still applies.
  }
}
