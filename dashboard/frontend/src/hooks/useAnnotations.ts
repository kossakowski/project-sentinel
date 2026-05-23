// Annotation data hook for the AnnotationPanel (Phase 4).
//
// Wraps the API client's `fetchAnnotation` / `saveAnnotation` /
// `deleteAnnotation` operations in a request-cancelling stateful hook,
// mirroring the conventions established by `useArticleDetail` /
// `useArticles`:
//
//   * AbortController on cleanup so a navigation away cancels in-flight reqs.
//   * requestIdRef guard against racing responses landing on a stale state.
//   * Error toasts via useToasts (req 2.9a — never silently swallow API errors).
//
// The hook returns the current annotation (null when absent), loading +
// saving flags, the last error encountered, and `save` / `remove` mutators.

import { useCallback, useEffect, useRef, useState } from "react";

import {
  ApiError,
  deleteAnnotation,
  fetchAnnotation,
  saveAnnotation,
} from "../api/client";
import type { Annotation, AnnotationPayload } from "../types";
import { useToasts } from "../components/Toast";

interface UseAnnotationState {
  annotation: Annotation | null;
  loading: boolean;
  saving: boolean;
  error: ApiError | null;
}

interface UseAnnotationResult extends UseAnnotationState {
  /** Upsert the annotation. Resolves with the saved row (no value on error). */
  save: (payload: Omit<AnnotationPayload, "article_id">) => Promise<Annotation | null>;
  /** Delete the annotation for the current article. */
  remove: () => Promise<void>;
}

/** Data hook for the article detail page's annotation panel (req 4.3).
 *
 *  Seeds with `initialAnnotation` (passed by the parent who already has the
 *  article detail in memory) so the form pre-fills synchronously on first
 *  render — avoids a flash of empty inputs while a GET round-trips.
 *  Subsequent saves / deletes mutate local state in place; the dashboard
 *  is single-user so there's no concurrent-writer story to worry about.
 *
 *  When `initialAnnotation` is undefined (caller did not pre-load) the hook
 *  falls back to fetching from /api/annotations/<id> itself. A 404 (no
 *  annotation yet) resolves the state with `annotation = null`, NOT an
 *  error — the spec treats "no annotation" as a normal first-time state.
 */
export function useAnnotation(
  articleId: string | undefined,
  initialAnnotation: Annotation | null | undefined = undefined,
): UseAnnotationResult {
  const [state, setState] = useState<UseAnnotationState>({
    // When the parent supplies `initialAnnotation` (the common case from
    // ArticleDetailPage), trust it immediately so the form pre-fills.
    annotation: initialAnnotation ?? null,
    // Skip the loading phase entirely when the parent pre-loaded.
    loading: initialAnnotation === undefined && Boolean(articleId),
    saving: false,
    error: null,
  });
  const { notify } = useToasts();
  const requestIdRef = useRef(0);

  useEffect(() => {
    if (!articleId) {
      setState({ annotation: null, loading: false, saving: false, error: null });
      return;
    }
    // Parent already provided the annotation (or null) — no fetch needed.
    if (initialAnnotation !== undefined) {
      setState({
        annotation: initialAnnotation,
        loading: false,
        saving: false,
        error: null,
      });
      return;
    }

    const requestId = ++requestIdRef.current;
    const controller = new AbortController();
    setState((prev) => ({ ...prev, loading: true, error: null }));

    fetchAnnotation(articleId, { signal: controller.signal })
      .then((annotation) => {
        if (requestIdRef.current !== requestId) return;
        setState({ annotation, loading: false, saving: false, error: null });
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        if (requestIdRef.current !== requestId) return;
        const apiError = toApiError(error);
        // 404 == "no annotation yet". Spec treats that as a normal state,
        // not an error — clear the slot and stop loading.
        if (apiError.status === 404) {
          setState({ annotation: null, loading: false, saving: false, error: null });
          return;
        }
        setState({ annotation: null, loading: false, saving: false, error: apiError });
        notify(`Failed to load annotation: ${apiError.message}`, "error");
      });

    return () => controller.abort();
  }, [articleId, initialAnnotation, notify]);

  const save = useCallback(
    async (
      payload: Omit<AnnotationPayload, "article_id">,
    ): Promise<Annotation | null> => {
      if (!articleId) return null;
      setState((prev) => ({ ...prev, saving: true, error: null }));
      try {
        const saved = await saveAnnotation({ ...payload, article_id: articleId });
        setState({ annotation: saved, loading: false, saving: false, error: null });
        notify("Annotation saved", "success");
        return saved;
      } catch (error: unknown) {
        const apiError = toApiError(error);
        setState((prev) => ({ ...prev, saving: false, error: apiError }));
        notify(`Failed to save annotation: ${apiError.message}`, "error");
        return null;
      }
    },
    [articleId, notify],
  );

  const remove = useCallback(async () => {
    if (!articleId) return;
    setState((prev) => ({ ...prev, saving: true, error: null }));
    try {
      await deleteAnnotation(articleId);
      setState({ annotation: null, loading: false, saving: false, error: null });
      notify("Annotation deleted", "success");
    } catch (error: unknown) {
      const apiError = toApiError(error);
      setState((prev) => ({ ...prev, saving: false, error: apiError }));
      notify(`Failed to delete annotation: ${apiError.message}`, "error");
    }
  }, [articleId, notify]);

  return { ...state, save, remove };
}

function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error;
  const message = error instanceof Error ? error.message : "Unknown error";
  return new ApiError(message, 0, null, "");
}
