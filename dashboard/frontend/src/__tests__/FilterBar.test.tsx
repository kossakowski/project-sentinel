// Tests for FilterBar — covers reqs 2.4 (changes update query), 2.4a (URL sync),
// 2.4b (clear-all resets).

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { MemoryRouter, Route, Routes, useLocation, useSearchParams } from "react-router-dom";

import {
  EMPTY_FILTERS,
  FilterBar,
  filterStateToQuery,
  type FilterState,
} from "../components/FilterBar";

function FilterHarness() {
  const [filters, setFilters] = useState<FilterState>({ ...EMPTY_FILTERS });
  const [, setSearchParams] = useSearchParams();
  const location = useLocation();

  function syncToUrl(next: FilterState) {
    const params = filterStateToQuery(next);
    const sp = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v === undefined) continue;
      sp.set(k, String(v));
    }
    setSearchParams(sp, { replace: false });
  }

  return (
    <div>
      <FilterBar
        value={filters}
        sourceOptions={["TVN24", "TASS"]}
        eventTypeOptions={["airspace_violation", "drone_attack"]}
        onChange={(next) => {
          setFilters(next);
          syncToUrl(next);
        }}
        onClear={() => {
          setFilters({ ...EMPTY_FILTERS });
          syncToUrl({ ...EMPTY_FILTERS });
        }}
      />
      <p data-testid="filters-debug">{JSON.stringify(filters)}</p>
      <p data-testid="url-debug">{location.search}</p>
    </div>
  );
}

function renderHarness() {
  return render(
    <MemoryRouter initialEntries={["/articles"]}>
      <Routes>
        <Route path="/articles" element={<FilterHarness />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("FilterBar", () => {
  // covers 2.4, 2.4a
  it("test_filter_bar_updates_query", async () => {
    const user = userEvent.setup();
    renderHarness();

    await user.selectOptions(screen.getByTestId("filter-language"), "pl");
    expect(JSON.parse(screen.getByTestId("filters-debug").textContent!)).toMatchObject({
      language: "pl",
    });
    expect(screen.getByTestId("url-debug").textContent).toContain("language=pl");

    await user.selectOptions(screen.getByTestId("filter-source-type"), "telegram");
    expect(screen.getByTestId("url-debug").textContent).toContain(
      "source_type=telegram",
    );

    // Urgency min sends a number to the API, not a string.
    await user.type(screen.getByTestId("filter-urgency-min"), "5");
    expect(screen.getByTestId("url-debug").textContent).toContain(
      "urgency_min=5",
    );

    await user.click(screen.getByTestId("filter-has-alert"));
    expect(screen.getByTestId("url-debug").textContent).toContain(
      "has_alert=true",
    );
  });

  // covers 2.4b
  it("test_filter_clear_all", async () => {
    const user = userEvent.setup();
    renderHarness();

    // Set some filters first.
    await user.selectOptions(screen.getByTestId("filter-language"), "pl");
    await user.selectOptions(screen.getByTestId("filter-source-type"), "telegram");
    await user.type(screen.getByTestId("filter-urgency-min"), "5");

    expect(screen.getByTestId("url-debug").textContent).toContain("language=pl");

    // Hit Clear all — every filter resets to its default.
    await user.click(screen.getByTestId("filter-clear"));
    const state = JSON.parse(screen.getByTestId("filters-debug").textContent!);
    expect(state).toEqual(EMPTY_FILTERS);
    expect(screen.getByTestId("url-debug").textContent).toBe("");
  });
});
