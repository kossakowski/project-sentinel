import { useEffect, useRef, useState } from "react";

import { ApiError, fetchArticleDetail } from "../api/client";
import type { ArticleDetail } from "../types";
import { useToasts } from "../components/Toast";

interface UseArticleDetailState {
  data: ArticleDetail | null;
  loading: boolean;
  error: ApiError | null;
}

/**
 * Data-fetching hook for a single article (req 1.5, 3.7).
 *
 * Re-fetches whenever ``articleId`` changes. Same pattern as ``useArticles``:
 * AbortController on cleanup, requestIdRef guard against racing responses,
 * toast on error (req 2.9a). When ``articleId`` is empty/undefined the hook
 * idles in the loading=false state with no data — keeps the detail page
 * render simple in the param-missing edge case.
 */
export function useArticleDetail(articleId: string | undefined): UseArticleDetailState {
  const [state, setState] = useState<UseArticleDetailState>({
    data: null,
    loading: Boolean(articleId),
    error: null,
  });
  const { notify } = useToasts();
  const requestIdRef = useRef(0);

  useEffect(() => {
    if (!articleId) {
      setState({ data: null, loading: false, error: null });
      return;
    }
    const requestId = ++requestIdRef.current;
    const controller = new AbortController();
    setState({ data: null, loading: true, error: null });

    fetchArticleDetail(articleId, { signal: controller.signal })
      .then((data) => {
        if (requestIdRef.current !== requestId) return;
        setState({ data, loading: false, error: null });
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        if (requestIdRef.current !== requestId) return;
        const apiError = toApiError(error);
        setState({ data: null, loading: false, error: apiError });
        notify(`Failed to load article: ${apiError.message}`, "error");
      });

    return () => controller.abort();
  }, [articleId, notify]);

  return state;
}

function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error;
  const message = error instanceof Error ? error.message : "Unknown error";
  return new ApiError(message, 0, null, "");
}
