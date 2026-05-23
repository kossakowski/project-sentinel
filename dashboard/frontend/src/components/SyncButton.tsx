import { useCallback, useEffect, useState } from "react";

import { ApiError, fetchSyncStatus, triggerSync } from "../api/client";
import type { SyncStatus, SyncTriggerResponse } from "../types";
import { useToasts } from "./Toast";

interface SyncButtonProps {
  /** Called after a successful sync so the parent can refresh the article list. */
  onSyncComplete?: () => void;
}

interface SyncDisplayState {
  loading: boolean;
  status: SyncStatus | null;
  lastResult: SyncTriggerResponse | null;
}

/** Sync trigger button with last-sync timestamp + spinner (req 2.8, 2.8a). */
export function SyncButton({ onSyncComplete }: SyncButtonProps) {
  const [state, setState] = useState<SyncDisplayState>({
    loading: false,
    status: null,
    lastResult: null,
  });
  const { notify } = useToasts();

  useEffect(() => {
    let cancelled = false;
    fetchSyncStatus()
      .then((status) => {
        if (cancelled) return;
        setState((prev) => ({ ...prev, status }));
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        const message = error instanceof Error ? error.message : "Unknown error";
        notify(`Failed to load sync status: ${message}`, "error");
      });
    return () => {
      cancelled = true;
    };
  }, [notify]);

  const onClick = useCallback(async () => {
    setState((prev) => ({ ...prev, loading: true }));
    try {
      const result = await triggerSync();
      setState({
        loading: false,
        status: {
          last_sync: result.last_sync,
          result: result.result,
        },
        lastResult: result,
      });
      if (result.result.success) {
        notify(
          `Synced ${result.result.article_count.toLocaleString()} articles in ${result.result.duration.toFixed(1)}s`,
          "success",
        );
        onSyncComplete?.();
      } else {
        notify(`Sync failed: ${result.result.error ?? "Unknown error"}`, "error");
      }
    } catch (error: unknown) {
      const message =
        error instanceof ApiError
          ? error.message
          : error instanceof Error
            ? error.message
            : "Sync request failed";
      notify(`Sync error: ${message}`, "error");
      setState((prev) => ({ ...prev, loading: false }));
    }
  }, [notify, onSyncComplete]);

  const description = describe(state);

  return (
    <div className="sync-button-wrap">
      <button
        type="button"
        className="sync-button"
        disabled={state.loading}
        onClick={onClick}
        data-testid="sync-button"
        aria-busy={state.loading}
      >
        {state.loading ? "Syncing…" : "Sync database"}
      </button>
      <span className="sync-button-meta" data-testid="sync-meta">
        {description}
      </span>
      {state.loading && (
        <span className="sync-spinner" data-testid="sync-spinner" aria-hidden />
      )}
    </div>
  );
}

function describe(state: SyncDisplayState): string {
  if (state.loading) return "Sync in progress…";
  const status = state.status;
  if (!status || status.last_sync === null) {
    if (status?.tunnel_mode) {
      return "Tunnel mode — fresh data on each startup";
    }
    return "No data — click to sync";
  }
  const stamp = formatTimestamp(status.last_sync);
  const result = status.result;
  if (!result) return `Last sync: ${stamp}`;
  if (result.success) {
    return `Last sync: ${stamp} (${result.article_count.toLocaleString()} articles)`;
  }
  return `Last sync failed: ${result.error ?? "Unknown error"}`;
}

function formatTimestamp(iso: string): string {
  try {
    const parsed = new Date(iso);
    if (Number.isNaN(parsed.getTime())) return iso;
    return parsed.toLocaleString();
  } catch {
    return iso;
  }
}
