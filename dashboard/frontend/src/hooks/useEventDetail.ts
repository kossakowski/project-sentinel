// Data-fetching hook for a single event (SPEC_ALERT_GROUPING.md req 2.4, 2.5).
//
// Mirrors ``useArticleDetail`` 1:1 so the EventDetailPage can render in the
// same loading / error / 404 patterns the article-detail page already uses.
// Re-fetches whenever ``eventId`` changes, aborts in-flight requests on
// unmount, guards against racing responses via a requestId ref, and surfaces
// fetch errors as toasts.

import { useEffect, useRef, useState } from "react";

import { ApiError, fetchEvent } from "../api/client";
import type { EventDetail } from "../types";
import { useToasts } from "../components/Toast";

interface UseEventDetailState {
  data: EventDetail | null;
  loading: boolean;
  error: ApiError | null;
}

export function useEventDetail(eventId: string | undefined): UseEventDetailState {
  const [state, setState] = useState<UseEventDetailState>({
    data: null,
    loading: Boolean(eventId),
    error: null,
  });
  const { notify } = useToasts();
  const requestIdRef = useRef(0);

  useEffect(() => {
    if (!eventId) {
      setState({ data: null, loading: false, error: null });
      return;
    }
    const requestId = ++requestIdRef.current;
    const controller = new AbortController();
    setState({ data: null, loading: true, error: null });

    fetchEvent(eventId, { signal: controller.signal })
      .then((data) => {
        if (requestIdRef.current !== requestId) return;
        setState({ data, loading: false, error: null });
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        if (requestIdRef.current !== requestId) return;
        const apiError = toApiError(error);
        setState({ data: null, loading: false, error: apiError });
        // 404 is an expected "event not found" outcome (spec req 2.4b) — the
        // page renders a not-found UI inline. Don't bother the user with a
        // toast for that case; toast everything else (network failure, 5xx).
        if (apiError.status !== 404) {
          notify(`Failed to load event: ${apiError.message}`, "error");
        }
      });

    return () => controller.abort();
  }, [eventId, notify]);

  return state;
}

function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error;
  const message = error instanceof Error ? error.message : "Unknown error";
  return new ApiError(message, 0, null, "");
}
