// Tests for SyncButton — covers req 2.8 (loading + result + refresh) and 2.8a
// (last sync timestamp, "No data — click to sync" fallback).

import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { SyncButton } from "../components/SyncButton";
import { ToastProvider } from "../components/Toast";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

interface Deferred<T> {
  promise: Promise<T>;
  resolve: (value: T) => void;
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

describe("SyncButton", () => {
  // F10 — tunnel mode must disable the button so clicks don't bounce against
  // the backend's 409 response.
  it("disables the button in tunnel mode", async () => {
    const fetchSpy = vi
      .spyOn(global, "fetch")
      .mockImplementation(async (input: RequestInfo | URL) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url === "/api/sync/status") {
          return jsonResponse({ last_sync: null, tunnel_mode: true });
        }
        throw new Error(`Unexpected fetch call to ${url}`);
      });

    try {
      render(
        <ToastProvider>
          <SyncButton />
        </ToastProvider>,
      );

      await waitFor(() => {
        expect(screen.getByTestId("sync-meta").textContent).toBe(
          "Tunnel mode — fresh data on each startup",
        );
      });
      expect(screen.getByTestId("sync-button")).toBeDisabled();
      expect(screen.getByTestId("sync-button")).toHaveAttribute(
        "title",
        "Disabled in tunnel mode",
      );
    } finally {
      fetchSpy.mockRestore();
    }
  });

  // covers 2.8, 2.8a
  it("test_sync_button_flow", async () => {
    const onSyncComplete = vi.fn();
    const user = userEvent.setup();

    // POST /api/sync intentionally hangs on a deferred so we can assert that
    // the spinner is on screen DURING the request, then resolve and verify the
    // success path (req 2.8: loading → result → refresh).
    const postDeferred = deferred<Response>();
    const fetchSpy = vi
      .spyOn(global, "fetch")
      .mockImplementation(async (input: RequestInfo | URL) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url === "/api/sync/status") {
          // First call (on mount) — never synced (req 2.8a fallback path).
          return jsonResponse({ last_sync: null });
        }
        if (url === "/api/sync") {
          return postDeferred.promise;
        }
        throw new Error(`Unexpected fetch call to ${url}`);
      });

    try {
      render(
        <ToastProvider>
          <SyncButton onSyncComplete={onSyncComplete} />
        </ToastProvider>,
      );

      // Initial fetch resolves → "No data — click to sync" (req 2.8a).
      await waitFor(() => {
        expect(screen.getByTestId("sync-meta").textContent).toBe(
          "No data — click to sync",
        );
      });
      expect(fetchSpy).toHaveBeenCalledWith("/api/sync/status", undefined);

      // Click → POST is in flight. Button reads "Syncing…" and a spinner is
      // mounted (req 2.8 loading indicator).
      await user.click(screen.getByTestId("sync-button"));
      expect(screen.getByTestId("sync-button")).toHaveTextContent("Syncing…");
      expect(screen.getByTestId("sync-button")).toBeDisabled();
      expect(screen.getByTestId("sync-spinner")).toBeInTheDocument();

      // Resolve the POST → meta updates with timestamp + count; refresh fires.
      postDeferred.resolve(
        jsonResponse({
          last_sync: "2026-05-22T12:00:00+00:00",
          result: {
            success: true,
            file_size: 42000000,
            article_count: 37500,
            duration: 4.2,
            error: null,
          },
        }),
      );

      await waitFor(() => {
        expect(onSyncComplete).toHaveBeenCalledTimes(1);
      });
      await waitFor(() => {
        expect(screen.getByTestId("sync-meta").textContent).toContain(
          "37,500 articles",
        );
      });
      expect(screen.queryByTestId("sync-spinner")).not.toBeInTheDocument();

      // POST /api/sync was called with method: "POST".
      const postCall = fetchSpy.mock.calls.find(
        ([url]) => url === "/api/sync",
      );
      expect(postCall).toBeDefined();
      expect(postCall?.[1]).toMatchObject({ method: "POST" });
    } finally {
      fetchSpy.mockRestore();
    }
  });
});
