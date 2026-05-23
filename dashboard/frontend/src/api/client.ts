// Typed wrapper around the Flask backend (req 2.9).
//
// All endpoints are called with relative URLs so they go through the Vite dev
// proxy in development (configured in `vite.config.ts`) and resolve to the
// same origin in production (Flask serves the built bundle and the API on a
// single port). No hard-coded base URL.

import type {
  Annotation,
  AnnotationLabel,
  AnnotationListResponse,
  AnnotationPayload,
  Article,
  ArticleDetail,
  ArticleListResponse,
  ArticleQueryParams,
  StatsResponse,
  SyncStatus,
  SyncTriggerResponse,
} from "../types";

/** Error raised by the API client when a request fails. */
export class ApiError extends Error {
  status: number;
  body: unknown;
  url: string;

  constructor(message: string, status: number, body: unknown, url: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
    this.url = url;
  }
}

/** Best-effort parse of a JSON body; falls back to text or null. */
async function parseBody(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

/** Extract a human-readable error message from a parsed body. */
function bodyMessage(body: unknown): string | null {
  if (body && typeof body === "object" && "error" in body) {
    const value = (body as { error: unknown }).error;
    if (typeof value === "string") return value;
  }
  if (typeof body === "string" && body.trim()) return body.trim();
  return null;
}

/**
 * Core fetch wrapper. Throws `ApiError` on non-2xx responses or network
 * failures so callers (or the UI's error boundary / toast) can surface the
 * problem — req 2.9a forbids silently swallowing API errors.
 */
async function request<T>(url: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, init);
  } catch (cause) {
    const message =
      cause instanceof Error ? cause.message : "Network request failed";
    throw new ApiError(`Network error: ${message}`, 0, null, url);
  }

  const body = await parseBody(response);

  if (!response.ok) {
    const reason = bodyMessage(body) ?? response.statusText ?? "Request failed";
    throw new ApiError(
      `${response.status} ${reason}`,
      response.status,
      body,
      url,
    );
  }

  return body as T;
}

/**
 * Build a `URLSearchParams` instance from a partial params object, skipping
 * undefined / null / empty-string values so the backend sees only filters the
 * user actually set. Array values are serialised as repeated params, which
 * matches Flask's ``request.args.getlist`` contract — required by the
 * multi-select source filter (req 2.4).
 */
type ParamValue = string | number | boolean | string[] | undefined | null;

function buildSearchParams(params: Record<string, ParamValue>): URLSearchParams {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) {
      for (const item of value) {
        if (item === undefined || item === null || item === "") continue;
        search.append(key, String(item));
      }
      continue;
    }
    search.set(key, String(value));
  }
  return search;
}

/** GET /api/articles with paging / sort / filters / search (req 2.9). */
export function fetchArticles(
  params: ArticleQueryParams = {},
  init?: RequestInit,
): Promise<ArticleListResponse> {
  const search = buildSearchParams(params as Record<string, ParamValue>);
  const qs = search.toString();
  const url = qs ? `/api/articles?${qs}` : "/api/articles";
  return request<ArticleListResponse>(url, init);
}

/** GET /api/articles/<id> — full article detail with classifier input. */
export function fetchArticleDetail(
  articleId: string,
  init?: RequestInit,
): Promise<ArticleDetail> {
  return request<ArticleDetail>(
    `/api/articles/${encodeURIComponent(articleId)}`,
    init,
  );
}

/** GET /api/stats — aggregate dashboard statistics (req 1.6). */
export function fetchStats(init?: RequestInit): Promise<StatsResponse> {
  return request<StatsResponse>("/api/stats", init);
}

/** POST /api/sync — trigger a fresh DB sync from production (req 1.7). */
export function triggerSync(init?: RequestInit): Promise<SyncTriggerResponse> {
  return request<SyncTriggerResponse>("/api/sync", {
    method: "POST",
    ...(init ?? {}),
  });
}

/** GET /api/sync/status — last sync timestamp + result (req 1.7a). */
export function fetchSyncStatus(init?: RequestInit): Promise<SyncStatus> {
  return request<SyncStatus>("/api/sync/status", init);
}

// ---------------------------------------------------------------------------
// Annotation endpoints (Phase 4, req 4.2/4.2a/4.2b/4.2c)
// ---------------------------------------------------------------------------

/** GET /api/annotations/<id> — single annotation; rejects with ApiError(404)
 *  when no annotation exists. Callers that want "null on missing" should
 *  catch the 404 specifically (mirrors how the spec separates the absent and
 *  error cases — see useAnnotations). */
export function fetchAnnotation(
  articleId: string,
  init?: RequestInit,
): Promise<Annotation> {
  return request<Annotation>(
    `/api/annotations/${encodeURIComponent(articleId)}`,
    init,
  );
}

/** GET /api/annotations — paginated list with optional `label` filter. */
export function fetchAnnotations(
  params: {
    label?: AnnotationLabel;
    sort?: "updated_at" | "created_at" | "label" | "expected_urgency";
    order?: "asc" | "desc";
    page?: number;
    page_size?: number;
  } = {},
  init?: RequestInit,
): Promise<AnnotationListResponse> {
  const search = buildSearchParams(params as Record<string, ParamValue>);
  const qs = search.toString();
  const url = qs ? `/api/annotations?${qs}` : "/api/annotations";
  return request<AnnotationListResponse>(url, init);
}

/** POST /api/annotations — create or update (upsert) an annotation. */
export function saveAnnotation(
  payload: AnnotationPayload,
  init?: RequestInit,
): Promise<Annotation> {
  return request<Annotation>("/api/annotations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    ...(init ?? {}),
  });
}

/** DELETE /api/annotations/<id> — remove an annotation; resolves on 204. */
export function deleteAnnotation(
  articleId: string,
  init?: RequestInit,
): Promise<void> {
  // request() returns null on empty bodies (204 No Content); the void cast
  // makes the call site cleaner than threading a `null` through callers.
  return request<void>(`/api/annotations/${encodeURIComponent(articleId)}`, {
    method: "DELETE",
    ...(init ?? {}),
  });
}

// Re-export Article so consumers can `import { Article } from "../api/client"`
// without reaching into types.ts directly. Kept here for the public surface.
export type { Article };
