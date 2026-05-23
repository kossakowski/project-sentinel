// TypeScript types mirroring the Flask backend responses (req 2.1b).
//
// Field names match the JSON keys returned by `dashboard/api/articles.py`,
// `dashboard/api/stats.py`, `dashboard/api/sync.py`, and the underlying
// dict-builders in `dashboard/db.py` exactly. Do not rename without updating
// the backend in lockstep.

/** Pipeline stage reached by an article (req 1.4b). */
export type PipelineStatus =
  | "unclassified"
  | "classified"
  | "event_created"
  | "alert_sent";

/** Source ingestion type stored on each article. */
export type SourceType = "rss" | "google_news" | "telegram";

/** Article language codes used in the production DB. */
export type Language = "pl" | "en" | "uk";

/** Sort direction parameter for list/search endpoints. */
export type SortOrder = "asc" | "desc";

/** Whitelisted sort columns the backend accepts on /api/articles. */
export type SortColumn =
  | "published_at"
  | "fetched_at"
  | "urgency_score"
  | "source_name"
  | "title"
  | "confidence";

/** Nested classification block on an article. Null when unclassified. */
export interface Classification {
  id: string;
  is_military_event: boolean;
  // sentinel/database.py:54 declares `event_type TEXT` (nullable). The
  // dashboard mirrors that — an unclassified-but-row-present edge case
  // would leave this NULL, so the frontend must handle it.
  event_type: string | null;
  urgency_score: number;
  affected_countries: string[];
  aggressor: string | null;
  is_new_event: boolean | null;
  confidence: number;
  summary_pl: string | null;
  classified_at: string;
  model_used: string;
  input_tokens: number | null;
  output_tokens: number | null;
}

/** Per-article alert record (phone/SMS/WhatsApp). */
export interface AlertRecord {
  id: string;
  event_id: string;
  alert_type: "sms" | "phone_call" | "whatsapp";
  twilio_sid: string | null;
  status: string;
  duration_seconds: number | null;
  attempt_number: number;
  sent_at: string;
  message_body: string | null;
}

/** Event linked to one or more articles. */
export interface EventRecord {
  id: string;
  event_type: string;
  urgency_score: number;
  affected_countries: string[];
  aggressor: string | null;
  summary_pl: string;
  first_seen_at: string;
  last_updated_at: string;
  source_count: number;
  article_ids: string[];
  alert_status: string;
  acknowledged_at: string | null;
  alert_records: AlertRecord[];
}

/** Article row as returned by GET /api/articles (req 1.4a). */
export interface Article {
  id: string;
  source_name: string;
  source_url: string;
  source_type: SourceType | string;
  title: string;
  summary: string | null;
  language: Language | string;
  published_at: string;
  fetched_at: string;
  classification: Classification | null;
  pipeline_status: PipelineStatus;
  has_alert: boolean;
}

/** Article detail returned by GET /api/articles/<id> (req 1.5). */
export interface ArticleDetail extends Article {
  raw_metadata: Record<string, unknown>;
  events: EventRecord[];
  classifier_input: string;
}

/** Paginated response wrapper used by /api/articles. */
export interface ArticleListResponse {
  articles: Article[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

/** Query params for /api/articles. */
export interface ArticleQueryParams {
  page?: number;
  page_size?: number;
  sort?: SortColumn;
  order?: SortOrder;
  // Multi-select (req 2.4): a list emits repeated ``?source_name=`` URL
  // params; a single string keeps the legacy single-source behaviour.
  source_name?: string | string[];
  source_type?: string;
  language?: string;
  urgency_min?: number;
  urgency_max?: number;
  date_from?: string;
  date_to?: string;
  pipeline_status?: PipelineStatus | "all";
  event_type?: string;
  has_alert?: boolean;
  q?: string;
}

/** Per-day articles count entry from /api/stats. */
export interface ArticlesPerDay {
  date: string;
  count: number;
}

/** Urgency-score histogram bucket. */
export interface UrgencyBucket {
  urgency_score: number;
  count: number;
}

/** Per-source count entry. */
export interface SourceBucket {
  source_name: string;
  count: number;
}

/** Per-language count entry. */
export interface LanguageBucket {
  language: string;
  count: number;
}

/** Per-event-type count entry. */
export interface EventTypeBucket {
  event_type: string;
  count: number;
}

/** Pipeline funnel counts from /api/stats. */
export interface PipelineFunnel {
  collected: number;
  classified: number;
  events_created: number;
  alerts_sent: number;
}

/** Full /api/stats response (req 1.6). */
export interface StatsResponse {
  total_articles: number;
  total_classified: number;
  total_events: number;
  total_alerts: number;
  articles_per_day: ArticlesPerDay[];
  urgency_distribution: UrgencyBucket[];
  source_distribution: SourceBucket[];
  language_distribution: LanguageBucket[];
  event_type_distribution: EventTypeBucket[];
  pipeline_funnel: PipelineFunnel;
}

/** Per-call result returned by POST /api/sync (matches SyncResult.to_dict). */
export interface SyncResult {
  success: boolean;
  file_size: number;
  article_count: number;
  duration: number;
  error: string | null;
}

/** GET /api/sync/status response (req 1.7a). */
export interface SyncStatus {
  last_sync: string | null;
  result?: SyncResult;
  tunnel_mode?: boolean;
}

/** POST /api/sync response: last_sync timestamp plus the SyncResult. */
export interface SyncTriggerResponse {
  last_sync: string;
  result: SyncResult;
}
