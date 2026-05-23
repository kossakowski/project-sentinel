// Tests for the API client — covers reqs 2.9 (typed wrappers) and 2.9a (errors
// must be surfaced, not silently swallowed).

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  fetchArticles,
  fetchArticleDetail,
  fetchStats,
  fetchSyncStatus,
  triggerSync,
} from "../api/client";

afterEach(() => {
  vi.restoreAllMocks();
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("API client", () => {
  // covers 2.9, 2.9a
  it("test_api_client_error_handling", async () => {
    // Happy path: fetchArticles returns the typed shape without modification.
    let spy = vi.spyOn(global, "fetch").mockResolvedValueOnce(
      jsonResponse({
        articles: [],
        total: 0,
        page: 1,
        page_size: 50,
        total_pages: 0,
      }),
    );
    const result = await fetchArticles({ page: 1 });
    expect(result.total).toBe(0);
    // Query params are URL-encoded onto the request URL.
    expect(spy).toHaveBeenCalledWith("/api/articles?page=1", undefined);
    spy.mockRestore();

    // Non-2xx response surfaces an ApiError with status + body — not swallowed.
    spy = vi.spyOn(global, "fetch").mockResolvedValueOnce(
      jsonResponse({ error: "Invalid ISO date(s)" }, 400),
    );
    await expect(fetchArticles({ date_from: "2026-13-01" })).rejects.toThrow(
      ApiError,
    );
    // The thrown error carries the parsed body for the UI to surface.
    spy = vi.spyOn(global, "fetch").mockResolvedValueOnce(
      jsonResponse({ error: "boom" }, 500),
    );
    try {
      await fetchStats();
      throw new Error("Expected fetchStats() to throw");
    } catch (caught) {
      expect(caught).toBeInstanceOf(ApiError);
      const err = caught as ApiError;
      expect(err.status).toBe(500);
      expect(err.body).toEqual({ error: "boom" });
      expect(err.message).toContain("boom");
    }
    spy.mockRestore();

    // Network-level failure (no Response object) also propagates as ApiError
    // with status 0 — the toast layer downstream needs SOMETHING to show.
    spy = vi
      .spyOn(global, "fetch")
      .mockRejectedValueOnce(new TypeError("Failed to fetch"));
    try {
      await fetchArticleDetail("abc");
      throw new Error("Expected fetchArticleDetail() to throw");
    } catch (caught) {
      expect(caught).toBeInstanceOf(ApiError);
      expect((caught as ApiError).status).toBe(0);
    }
    spy.mockRestore();

    // triggerSync sends POST.
    spy = vi.spyOn(global, "fetch").mockResolvedValueOnce(
      jsonResponse({
        last_sync: "2026-05-22T12:00:00+00:00",
        result: {
          success: true,
          file_size: 1,
          article_count: 1,
          duration: 0.1,
          error: null,
        },
      }),
    );
    await triggerSync();
    expect(spy).toHaveBeenCalledWith(
      "/api/sync",
      expect.objectContaining({ method: "POST" }),
    );
    spy.mockRestore();

    // fetchSyncStatus is a plain GET that returns the raw response body.
    spy = vi.spyOn(global, "fetch").mockResolvedValueOnce(
      jsonResponse({ last_sync: null }),
    );
    const status = await fetchSyncStatus();
    expect(status.last_sync).toBeNull();
    spy.mockRestore();
  });
});
