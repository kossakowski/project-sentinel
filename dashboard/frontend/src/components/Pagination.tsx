// Page navigation with a page-size selector (req 2.7).
// Allowed page sizes match the backend whitelist in `dashboard/db.py`.

export const ALLOWED_PAGE_SIZES = [25, 50, 100] as const;
export type PageSize = (typeof ALLOWED_PAGE_SIZES)[number];

export function isValidPageSize(value: number): value is PageSize {
  return (ALLOWED_PAGE_SIZES as ReadonlyArray<number>).includes(value);
}

interface PaginationProps {
  page: number;
  totalPages: number;
  total: number;
  pageSize: PageSize;
  onPageChange: (page: number) => void;
  onPageSizeChange: (size: PageSize) => void;
}

export function Pagination({
  page,
  totalPages,
  total,
  pageSize,
  onPageChange,
  onPageSizeChange,
}: PaginationProps) {
  const hasPrev = page > 1;
  // When totalPages is 0 (empty result set) we still want Next disabled.
  const hasNext = page < totalPages;

  return (
    <div className="pagination" role="navigation" aria-label="Pagination">
      <div className="pagination-summary" data-testid="pagination-summary">
        {total.toLocaleString()} articles
      </div>

      <div className="pagination-controls">
        <button
          type="button"
          className="pagination-button"
          disabled={!hasPrev}
          onClick={() => onPageChange(Math.max(1, page - 1))}
          data-testid="pagination-prev"
        >
          ← Previous
        </button>
        <span className="pagination-position" data-testid="pagination-position">
          Page {page} of {Math.max(1, totalPages)}
        </span>
        <button
          type="button"
          className="pagination-button"
          disabled={!hasNext}
          onClick={() => onPageChange(page + 1)}
          data-testid="pagination-next"
        >
          Next →
        </button>
      </div>

      <label className="pagination-page-size">
        <span>Page size</span>
        <select
          value={pageSize}
          onChange={(event) => {
            const next = Number(event.target.value);
            if (isValidPageSize(next)) onPageSizeChange(next);
          }}
          data-testid="pagination-page-size"
        >
          {ALLOWED_PAGE_SIZES.map((size) => (
            <option key={size} value={size}>
              {size}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}
