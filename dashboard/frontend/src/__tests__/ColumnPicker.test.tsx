// Tests for ColumnPicker — covers reqs 2.3 (toggle list) and 2.3a (localStorage
// persistence). Persistence is exercised through the useLocalStorage hook so the
// full end-to-end save/load loop is asserted, not just the in-memory state.

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";

import { ColumnPicker } from "../components/ColumnPicker";
import {
  COLUMN_STORAGE_KEY,
  DEFAULT_VISIBLE_COLUMNS,
  type ColumnKey,
} from "../components/columns";
import { useLocalStorage } from "../hooks/useLocalStorage";

function Harness() {
  const [visible, setVisible] = useState<ColumnKey[]>([...DEFAULT_VISIBLE_COLUMNS]);
  return (
    <div>
      <ColumnPicker
        visible={visible}
        onToggle={(key) =>
          setVisible((prev) => {
            const set = new Set(prev);
            if (set.has(key)) set.delete(key);
            else set.add(key);
            return [...set] as ColumnKey[];
          })
        }
      />
      <p data-testid="visible-list">{visible.join(",")}</p>
    </div>
  );
}

function PersistentHarness() {
  // Same shape as ArticlesPage uses — exercises the real localStorage path.
  const [visible, setVisible] = useLocalStorage<ColumnKey[]>(
    COLUMN_STORAGE_KEY,
    [...DEFAULT_VISIBLE_COLUMNS],
  );
  return (
    <div>
      <ColumnPicker
        visible={visible}
        onToggle={(key) =>
          setVisible((prev) => {
            const set = new Set(prev);
            if (set.has(key)) set.delete(key);
            else set.add(key);
            return [...set] as ColumnKey[];
          })
        }
      />
      <p data-testid="visible-list">{visible.join(",")}</p>
    </div>
  );
}

describe("ColumnPicker", () => {
  // covers 2.3
  it("test_column_picker_toggles", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(screen.getByRole("button", { name: /columns/i }));
    // Title checkbox is on by default; clicking should remove it.
    const titleCheckbox = screen.getByRole("checkbox", {
      name: /toggle column title/i,
    });
    expect(titleCheckbox).toBeChecked();
    await user.click(titleCheckbox);
    expect(screen.getByTestId("visible-list").textContent).not.toContain(
      "title",
    );

    // Confidence is OFF by default — toggling should add it.
    const confidenceCheckbox = screen.getByRole("checkbox", {
      name: /toggle column confidence/i,
    });
    expect(confidenceCheckbox).not.toBeChecked();
    await user.click(confidenceCheckbox);
    expect(screen.getByTestId("visible-list").textContent).toContain(
      "confidence",
    );
  });

  // covers 2.3a
  it("test_column_picker_persistence", async () => {
    const user = userEvent.setup();
    // First render — toggle a column off and verify localStorage was written.
    const { unmount } = render(<PersistentHarness />);
    await user.click(screen.getByRole("button", { name: /columns/i }));
    await user.click(
      screen.getByRole("checkbox", { name: /toggle column urgency/i }),
    );
    const raw = window.localStorage.getItem(COLUMN_STORAGE_KEY);
    expect(raw).not.toBeNull();
    const parsed = JSON.parse(raw as string) as string[];
    expect(parsed).not.toContain("urgency_score");

    // Second mount must reload the persisted state — the visible list should
    // omit urgency_score before any user interaction.
    unmount();
    render(<PersistentHarness />);
    expect(screen.getByTestId("visible-list").textContent).not.toContain(
      "urgency_score",
    );
  });
});
