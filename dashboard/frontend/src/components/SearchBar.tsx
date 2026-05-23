import { useEffect, useRef, useState } from "react";

interface SearchBarProps {
  /** Initial value seeded from the URL or persisted state. */
  initialValue: string;
  /** Fired after the 300ms debounce settles (req 2.6). */
  onDebouncedChange: (query: string) => void;
  /** Debounce window in milliseconds. Spec mandates 300 for production use. */
  debounceMs?: number;
  /** Optional placeholder copy. */
  placeholder?: string;
}

const DEFAULT_DEBOUNCE_MS = 300;

/**
 * Keyword search input with debounced firing (req 2.6) and a clear button
 * (req 2.6a). Owns its own raw input state so typing remains snappy regardless
 * of how fast the API responds; the debounced value is what feeds back upward.
 */
export function SearchBar({
  initialValue,
  onDebouncedChange,
  debounceMs = DEFAULT_DEBOUNCE_MS,
  placeholder = "Search title or summary…",
}: SearchBarProps) {
  const [value, setValue] = useState(initialValue);

  // Track the last value we emitted so we never spam identical callbacks (a
  // re-render with the same debounced value should be a no-op for the parent).
  const lastEmittedRef = useRef<string>(initialValue);

  // Sync from external initialValue changes (e.g. URL navigation). When the
  // parent passes in a different initial we adopt it without firing a debounce.
  useEffect(() => {
    setValue(initialValue);
    lastEmittedRef.current = initialValue;
  }, [initialValue]);

  useEffect(() => {
    const trimmed = value.trim();
    if (trimmed === lastEmittedRef.current.trim()) return;
    const handle = setTimeout(() => {
      lastEmittedRef.current = trimmed;
      onDebouncedChange(trimmed);
    }, debounceMs);
    return () => clearTimeout(handle);
  }, [value, debounceMs, onDebouncedChange]);

  function handleClear() {
    setValue("");
    lastEmittedRef.current = "";
    onDebouncedChange("");
  }

  return (
    <div className="search-bar">
      <label className="search-bar-label" htmlFor="dashboard-search">
        Search
      </label>
      <div className="search-bar-input-wrap">
        <input
          id="dashboard-search"
          className="search-bar-input"
          type="search"
          placeholder={placeholder}
          value={value}
          onChange={(event) => setValue(event.target.value)}
          data-testid="search-input"
        />
        {value && (
          <button
            type="button"
            className="search-bar-clear"
            aria-label="Clear search"
            onClick={handleClear}
            data-testid="search-clear"
          >
            ×
          </button>
        )}
      </div>
    </div>
  );
}
