// Tests for SearchBar — covers req 2.6 (300ms debounce).

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";

import { SearchBar } from "../components/SearchBar";

describe("SearchBar", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  // covers 2.6
  it("test_search_debounce", () => {
    const onChange = vi.fn();
    render(<SearchBar initialValue="" onDebouncedChange={onChange} />);

    const input = screen.getByTestId("search-input") as HTMLInputElement;

    // Three keystrokes inside the debounce window should still only fire one
    // call — after the last keystroke + 300ms.
    fireEvent.change(input, { target: { value: "d" } });
    act(() => {
      vi.advanceTimersByTime(100);
    });
    expect(onChange).not.toHaveBeenCalled();

    fireEvent.change(input, { target: { value: "dr" } });
    act(() => {
      vi.advanceTimersByTime(100);
    });
    expect(onChange).not.toHaveBeenCalled();

    fireEvent.change(input, { target: { value: "drone" } });
    act(() => {
      vi.advanceTimersByTime(299);
    });
    expect(onChange).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith("drone");

    // Another wait without further keystrokes does NOT fire a second call.
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(onChange).toHaveBeenCalledTimes(1);

    // Clear button immediately fires onChange(""), no debounce required.
    fireEvent.click(screen.getByTestId("search-clear"));
    expect(onChange).toHaveBeenCalledTimes(2);
    expect(onChange).toHaveBeenLastCalledWith("");
  });
});
