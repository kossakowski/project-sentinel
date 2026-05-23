import { useEffect, useRef, useState } from "react";

import { ApiError, fetchStats } from "../api/client";
import type { StatsResponse } from "../types";
import { useToasts } from "../components/Toast";

interface UseStatsState {
  data: StatsResponse | null;
  loading: boolean;
  error: ApiError | null;
}

/**
 * Data-fetching hook for the aggregate stats endpoint (req 1.6, 3.1).
 *
 * Same shape as `useArticles`: an in-flight request is tracked by
 * `requestIdRef` so a fast refresh (refreshKey bump) doesn't let an older
 * response overwrite a newer one, and errors are surfaced to the toast tray
 * (req 2.9a) while keeping the previously-loaded payload visible so the UI
 * doesn't blank out on a transient failure.
 */
export function useStats(refreshKey = 0): UseStatsState {
  const [state, setState] = useState<UseStatsState>({
    data: null,
    loading: true,
    error: null,
  });
  const { notify } = useToasts();

  // Track which fetch is "current" — if a refreshKey bump fires a second fetch
  // before the first resolves, we ignore the stale one on resolution.
  const requestIdRef = useRef(0);

  useEffect(() => {
    const requestId = ++requestIdRef.current;
    const controller = new AbortController();
    setState((prev) => ({ ...prev, loading: true, error: null }));

    fetchStats({ signal: controller.signal })
      .then((data) => {
        if (requestIdRef.current !== requestId) return;
        setState({ data, loading: false, error: null });
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        if (requestIdRef.current !== requestId) return;
        const apiError = toApiError(error);
        setState((prev) => ({ ...prev, loading: false, error: apiError }));
        notify(`Failed to load stats: ${apiError.message}`, "error");
      });

    return () => controller.abort();
  }, [refreshKey, notify]);

  return state;
}

function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error;
  const message = error instanceof Error ? error.message : "Unknown error";
  return new ApiError(message, 0, null, "");
}
