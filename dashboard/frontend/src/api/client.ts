// Typed wrapper around the Flask backend (req 2.9).
//
// All endpoints are called with relative URLs so they go through the Vite dev
// proxy in development (configured in `vite.config.ts`) and resolve to the
// same origin in production (Flask serves the built bundle and the API on a
// single port). No hard-coded base URL.

import type {
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
 * user actually set.
 */
function buildSearchParams(
  params: Record<string, string | number | boolean | undefined | null>,
): URLSearchParams {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    search.set(key, String(value));
  }
  return search;
}

/** GET /api/articles with paging / sort / filters / search (req 2.9). */
export function fetchArticles(
  params: ArticleQueryParams = {},
  init?: RequestInit,
): Promise<ArticleListResponse> {
  const search = buildSearchParams(
    params as Record<string, string | number | boolean | undefined | null>,
  );
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

// Re-export Article so consumers can `import { Article } from "../api/client"`
// without reaching into types.ts directly. Kept here for the public surface.
export type { Article };
