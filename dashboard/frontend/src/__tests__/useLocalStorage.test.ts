// Tests for useLocalStorage — covers the F9 shape-validation behaviour
// (corrupted storage falls back to initialValue AND the bad key is cleared).

import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { act, renderHook } from "@testing-library/react";

import { useLocalStorage } from "../hooks/useLocalStorage";

const KEY = "dashboard.test.localstorage";

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  window.localStorage.clear();
});

describe("useLocalStorage", () => {
  it("uses the initial value when storage is empty", () => {
    const { result } = renderHook(() =>
      useLocalStorage<number[]>(KEY, [1, 2, 3]),
    );
    expect(result.current[0]).toEqual([1, 2, 3]);
  });

  it("hydrates from valid stored JSON", () => {
    window.localStorage.setItem(KEY, JSON.stringify(["a", "b"]));
    const { result } = renderHook(() =>
      useLocalStorage<string[]>(KEY, []),
    );
    expect(result.current[0]).toEqual(["a", "b"]);
  });

  it("falls back to the initial value when stored JSON is malformed", () => {
    window.localStorage.setItem(KEY, "not-json{");
    const { result } = renderHook(() =>
      useLocalStorage<string[]>(KEY, ["fallback"]),
    );
    expect(result.current[0]).toEqual(["fallback"]);
    // Bad key is cleared so subsequent reads don't re-trip it.
    expect(window.localStorage.getItem(KEY)).toBeNull();
  });

  it("falls back to the initial value when the validator rejects the shape", () => {
    // Valid JSON but wrong shape (string instead of array). The validator
    // protects ArticleTable.visibleColumns.includes from crashing.
    window.localStorage.setItem(KEY, JSON.stringify("definitely-not-an-array"));
    const isStringArray = (value: unknown): value is string[] =>
      Array.isArray(value) && value.every((v) => typeof v === "string");

    const { result } = renderHook(() =>
      useLocalStorage<string[]>(KEY, ["fallback"], isStringArray),
    );
    expect(result.current[0]).toEqual(["fallback"]);
    // Bad key is cleared so a future mount doesn't repeat the rejection.
    expect(window.localStorage.getItem(KEY)).toBeNull();
  });

  it("accepts values that pass the validator", () => {
    window.localStorage.setItem(KEY, JSON.stringify(["x", "y"]));
    const isStringArray = (value: unknown): value is string[] =>
      Array.isArray(value) && value.every((v) => typeof v === "string");

    const { result } = renderHook(() =>
      useLocalStorage<string[]>(KEY, [], isStringArray),
    );
    expect(result.current[0]).toEqual(["x", "y"]);
  });

  it("persists updates to localStorage", () => {
    const { result } = renderHook(() =>
      useLocalStorage<string[]>(KEY, []),
    );
    act(() => result.current[1](["new", "value"]));
    expect(JSON.parse(window.localStorage.getItem(KEY) ?? "null")).toEqual([
      "new",
      "value",
    ]);
  });
});
