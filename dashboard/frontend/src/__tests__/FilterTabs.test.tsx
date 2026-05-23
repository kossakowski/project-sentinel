// Tests for FilterTabs — covers reqs 2.5 (tab filter) and 2.5a ("Classified"
// includes event_created + alert_sent, handled by the backend mapping).

import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import {
  FilterTabs,
  tabToPipelineStatus,
} from "../components/FilterTabs";

describe("FilterTabs", () => {
  // covers 2.5, 2.5a
  it("test_filter_tabs", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();

    render(
      <FilterTabs
        value="all"
        counts={{ all: 37542, classified: 5812, unclassified: 31730 }}
        onChange={onChange}
      />,
    );

    // All three tabs render and show their counts (req 2.5).
    expect(screen.getByTestId("filter-tab-all")).toBeInTheDocument();
    expect(screen.getByTestId("filter-tab-classified")).toBeInTheDocument();
    expect(screen.getByTestId("filter-tab-unclassified")).toBeInTheDocument();
    const counts = screen.getAllByTestId("filter-tab-count").map((n) => n.textContent);
    expect(counts).toEqual(["37,542", "5,812", "31,730"]);

    // Active tab marked via aria-selected.
    expect(screen.getByTestId("filter-tab-all")).toHaveAttribute(
      "aria-selected",
      "true",
    );

    // Click Classified — handler is called with "classified".
    await user.click(screen.getByTestId("filter-tab-classified"));
    expect(onChange).toHaveBeenCalledWith("classified");

    await user.click(screen.getByTestId("filter-tab-unclassified"));
    expect(onChange).toHaveBeenLastCalledWith("unclassified");

    // Spec req 2.5a: passing "classified" to the backend maps it through. The
    // backend (dashboard/db.py) already treats pipeline_status=classified as
    // "any article that reached classification, including event_created and
    // alert_sent". Our translator just forwards the value, which is the
    // intended documented behaviour.
    expect(tabToPipelineStatus("classified")).toBe("classified");
    expect(tabToPipelineStatus("unclassified")).toBe("unclassified");
    expect(tabToPipelineStatus("all")).toBeUndefined();
  });
});
