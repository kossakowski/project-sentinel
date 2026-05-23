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
import { routerFutureFlags } from "../utils/routerFutureFlags";

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
    // Multi-select source_names is serialised as repeated params — matches
    // the URL contract the API consumes via getlist (req 2.4).
    for (const source of next.source_names) {
      if (source) sp.append("source_name", source);
    }
    setSearchParams(sp, { replace: false });
  }

  return (
    <div>
      <FilterBar
        value={filters}
        sourceOptions={["TVN24", "TASS", "Onet"]}
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
    <MemoryRouter initialEntries={["/articles"]} future={routerFutureFlags}>
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

  // covers 2.4 (multi-select source filter)
  // Clicking the source trigger opens a popover with one checkbox per option.
  // Ticking N boxes serialises N repeated ?source_name= URL params and stores
  // the list in component state — this is the contract the backend's
  // ``request.args.getlist("source_name")`` reads.
  it("test_filter_bar_source_multiselect", async () => {
    const user = userEvent.setup();
    renderHarness();

    // The trigger shows "All sources" when no source is selected.
    const trigger = screen.getByTestId("filter-source");
    expect(trigger).toHaveTextContent("All sources");

    // Open the popover and tick TVN24 + Onet.
    await user.click(trigger);
    await user.click(screen.getByTestId("filter-source-option-TVN24"));
    await user.click(screen.getByTestId("filter-source-option-Onet"));

    // Both repeated params should be present in the URL.
    const urlDebug = screen.getByTestId("url-debug").textContent ?? "";
    expect(urlDebug).toContain("source_name=TVN24");
    expect(urlDebug).toContain("source_name=Onet");

    // Component state should hold both selections.
    const state = JSON.parse(screen.getByTestId("filters-debug").textContent!);
    expect(state.source_names).toEqual(["TVN24", "Onet"]);

    // Trigger label updates to reflect the count.
    expect(trigger).toHaveTextContent("2 sources");

    // Unticking one removes only that selection — not the other.
    await user.click(screen.getByTestId("filter-source-option-TVN24"));
    const finalState = JSON.parse(
      screen.getByTestId("filters-debug").textContent!,
    );
    expect(finalState.source_names).toEqual(["Onet"]);
    const finalUrl = screen.getByTestId("url-debug").textContent ?? "";
    expect(finalUrl).toContain("source_name=Onet");
    expect(finalUrl).not.toContain("source_name=TVN24");
  });

  // covers 2.4b
  it("test_filter_clear_all", async () => {
    const user = userEvent.setup();
    renderHarness();

    // Set some filters first, including a multi-source pick.
    await user.click(screen.getByTestId("filter-source"));
    await user.click(screen.getByTestId("filter-source-option-TVN24"));
    await user.click(screen.getByTestId("filter-source-option-Onet"));
    await user.selectOptions(screen.getByTestId("filter-language"), "pl");
    await user.selectOptions(screen.getByTestId("filter-source-type"), "telegram");
    await user.type(screen.getByTestId("filter-urgency-min"), "5");

    expect(screen.getByTestId("url-debug").textContent).toContain("language=pl");
    expect(screen.getByTestId("url-debug").textContent).toContain(
      "source_name=TVN24",
    );

    // Hit Clear all — every filter resets to its default.
    await user.click(screen.getByTestId("filter-clear"));
    const state = JSON.parse(screen.getByTestId("filters-debug").textContent!);
    expect(state).toEqual(EMPTY_FILTERS);
    expect(state.source_names).toEqual([]);
    expect(screen.getByTestId("url-debug").textContent).toBe("");
  });
});
