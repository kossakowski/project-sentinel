// Tests for Pagination — covers reqs 2.7 (controls), 2.7a (persistence via
// localStorage), 2.7b (page-size change resets to page 1).

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";

import {
  ALLOWED_PAGE_SIZES,
  Pagination,
  type PageSize,
} from "../components/Pagination";
import { useLocalStorage } from "../hooks/useLocalStorage";
import { PAGE_SIZE_STORAGE_KEY } from "../components/columns";

function PaginationHarness() {
  const [page, setPage] = useState(2);
  const [pageSize, setPageSize] = useLocalStorage<PageSize>(
    PAGE_SIZE_STORAGE_KEY,
    50,
  );
  return (
    <div>
      <Pagination
        page={page}
        totalPages={20}
        total={965}
        pageSize={pageSize}
        onPageChange={setPage}
        onPageSizeChange={(size) => {
          // req 2.7b — page size change resets to page 1.
          setPage(1);
          setPageSize(size);
        }}
      />
      <p data-testid="state-debug">page={page} size={pageSize}</p>
    </div>
  );
}

describe("Pagination", () => {
  // covers 2.7, 2.7a, 2.7b
  it("test_pagination_controls", async () => {
    const user = userEvent.setup();
    const { unmount } = render(<PaginationHarness />);

    // Sanity: allowed page sizes are 25, 50, 100 (spec req 2.7).
    expect(ALLOWED_PAGE_SIZES).toEqual([25, 50, 100]);

    // Next / prev change the page.
    await user.click(screen.getByTestId("pagination-next"));
    expect(screen.getByTestId("state-debug").textContent).toContain("page=3");

    await user.click(screen.getByTestId("pagination-prev"));
    expect(screen.getByTestId("state-debug").textContent).toContain("page=2");

    // Changing page size resets to page 1 (req 2.7b) AND persists to localStorage (req 2.7a).
    await user.selectOptions(screen.getByTestId("pagination-page-size"), "100");
    expect(screen.getByTestId("state-debug").textContent).toContain("page=1");
    expect(screen.getByTestId("state-debug").textContent).toContain("size=100");
    expect(window.localStorage.getItem(PAGE_SIZE_STORAGE_KEY)).toBe("100");

    // Remount — persisted size is restored.
    unmount();
    render(<PaginationHarness />);
    expect(screen.getByTestId("state-debug").textContent).toContain("size=100");
  });
});
