import { useEffect, useRef, useState } from "react";

import { ApiError, fetchArticles } from "../api/client";
import type { ArticleListResponse, ArticleQueryParams } from "../types";
import { useToasts } from "../components/Toast";

interface UseArticlesState {
  data: ArticleListResponse | null;
  loading: boolean;
  error: ApiError | null;
}

/**
 * Data fetching hook for the paginated articles endpoint.
 *
 * `params` is serialised as a stable string so the hook only re-fetches when
 * the user-visible filters actually change (a fresh literal each render would
 * trigger an infinite loop otherwise). The optional `refreshKey` lets callers
 * force a refetch after a sync without changing any filter.
 *
 * Errors are surfaced via the toast tray (req 2.9a) and also returned via the
 * `error` field so the UI can render a fallback.
 */
export function useArticles(
  params: ArticleQueryParams,
  refreshKey = 0,
): UseArticlesState {
  const [state, setState] = useState<UseArticlesState>({
    data: null,
    loading: true,
    error: null,
  });
  const { notify } = useToasts();
  const serialised = stableStringify(params);

  // Track whether the latest fetch is still relevant when params change fast
  // enough that an older response would otherwise overwrite a newer one.
  const requestIdRef = useRef(0);

  useEffect(() => {
    const requestId = ++requestIdRef.current;
    const controller = new AbortController();
    setState((prev) => ({ ...prev, loading: true, error: null }));

    fetchArticles(params, { signal: controller.signal })
      .then((data) => {
        if (requestIdRef.current !== requestId) return;
        setState({ data, loading: false, error: null });
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        if (requestIdRef.current !== requestId) return;
        const apiError = toApiError(error);
        setState({ data: null, loading: false, error: apiError });
        notify(`Failed to load articles: ${apiError.message}`, "error");
      });

    return () => controller.abort();
    // We depend on the serialised form of params (not the object reference)
    // so identical-content rerenders do not refetch. refreshKey is a manual
    // bump used to force a refresh after sync.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serialised, refreshKey]);

  return state;
}

/** Stable JSON serialisation with sorted keys for deterministic dependencies. */
function stableStringify(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  const entries = Object.entries(value as Record<string, unknown>)
    .filter(([, v]) => v !== undefined)
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
  return JSON.stringify(Object.fromEntries(entries));
}

function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error;
  const message = error instanceof Error ? error.message : "Unknown error";
  return new ApiError(message, 0, null, "");
}
