// Shared fixtures for frontend unit tests.

import type {
  AlertRecord,
  Article,
  ArticleDetail,
  Classification,
  EventRecord,
  StatsResponse,
} from "../types";

export function makeClassification(
  overrides: Partial<Classification> = {},
): Classification {
  return {
    id: "cls-1",
    is_military_event: true,
    event_type: "airspace_violation",
    urgency_score: 6,
    affected_countries: ["PL"],
    aggressor: "RU",
    is_new_event: true,
    confidence: 0.85,
    summary_pl: "Polskie streszczenie",
    classified_at: "2026-05-22T10:03:05+00:00",
    model_used: "claude-haiku-4-5-20251001",
    input_tokens: 1076,
    output_tokens: 150,
    ...overrides,
  };
}

export function makeArticle(overrides: Partial<Article> = {}): Article {
  return {
    id: "art-1",
    source_name: "TVN24",
    source_url: "https://example.test/article-1",
    source_type: "rss",
    title: "Article one",
    summary: "Body of article one with details.",
    language: "pl",
    published_at: "2026-05-22T10:00:00+00:00",
    fetched_at: "2026-05-22T10:03:00+00:00",
    classification: makeClassification(),
    pipeline_status: "classified",
    has_alert: false,
    ...overrides,
  };
}

export function makeUnclassifiedArticle(
  overrides: Partial<Article> = {},
): Article {
  return makeArticle({
    id: "art-uncls",
    title: "Unclassified article",
    classification: null,
    pipeline_status: "unclassified",
    has_alert: false,
    ...overrides,
  });
}

export function makeAlertRecord(
  overrides: Partial<AlertRecord> = {},
): AlertRecord {
  return {
    id: "ar-1",
    event_id: "ev-1",
    alert_type: "phone_call",
    twilio_sid: "SM-12345",
    status: "sent",
    duration_seconds: 12,
    attempt_number: 1,
    sent_at: "2026-05-22T10:04:30+00:00",
    message_body: "Polski alert: naruszenie przestrzeni",
    ...overrides,
  };
}

export function makeEventRecord(
  overrides: Partial<EventRecord> = {},
): EventRecord {
  return {
    id: "ev-1",
    event_type: "airspace_violation",
    urgency_score: 8,
    affected_countries: ["PL"],
    aggressor: "RU",
    summary_pl: "Naruszenie przestrzeni powietrznej",
    first_seen_at: "2026-05-22T10:04:00+00:00",
    last_updated_at: "2026-05-22T10:05:00+00:00",
    source_count: 2,
    article_ids: ["art-1"],
    alert_status: "sms_sent",
    acknowledged_at: null,
    alert_records: [makeAlertRecord()],
    ...overrides,
  };
}

export function makeArticleDetail(
  overrides: Partial<ArticleDetail> = {},
): ArticleDetail {
  const base = makeArticle();
  return {
    ...base,
    raw_metadata: { keyword_match: "drone" },
    events: [],
    classifier_input:
      "Source: TVN24 (rss)\nLanguage: pl\nPublished: 2026-05-22T10:00:00+00:00\nTitle: Article one\nSummary: Body of article one with details.",
    ...overrides,
  };
}

export function makeStats(overrides: Partial<StatsResponse> = {}): StatsResponse {
  // Build a 30-day calendar so tests that traverse articles_per_day get a
  // realistic length without hard-coding 30 entries everywhere.
  const days: string[] = [];
  const base = new Date("2026-05-22T00:00:00Z").getTime();
  const dayMs = 24 * 60 * 60 * 1000;
  for (let offset = 29; offset >= 0; offset--) {
    const date = new Date(base - offset * dayMs);
    days.push(date.toISOString().slice(0, 10));
  }
  return {
    total_articles: 1000,
    total_classified: 155,
    total_events: 50,
    total_alerts: 35,
    articles_per_day: days.map((date, i) => ({ date, count: 30 + (i % 10) })),
    classified_per_day: days.map((date, i) => ({ date, count: 5 + (i % 3) })),
    urgency_distribution: [
      { urgency_score: 1, count: 50 },
      { urgency_score: 2, count: 40 },
      { urgency_score: 3, count: 30 },
      { urgency_score: 4, count: 10 },
      { urgency_score: 5, count: 12 },
      { urgency_score: 6, count: 8 },
      { urgency_score: 7, count: 3 },
      { urgency_score: 8, count: 1 },
      { urgency_score: 9, count: 1 },
      { urgency_score: 10, count: 0 },
    ],
    source_distribution: [
      { source_name: "Onet", count: 400 },
      { source_name: "TASS", count: 300 },
      { source_name: "TVN24", count: 200 },
      { source_name: "Rzeczpospolita", count: 100 },
    ],
    language_distribution: [
      { language: "pl", count: 600 },
      { language: "en", count: 350 },
      { language: "uk", count: 50 },
    ],
    event_type_distribution: [
      { event_type: "airspace_violation", count: 30 },
      { event_type: "drone_attack", count: 15 },
      { event_type: "troop_movement", count: 5 },
    ],
    pipeline_funnel: {
      collected: 1000,
      classified: 155,
      events_created: 60,
      alerts_sent: 25,
    },
    ...overrides,
  };
}
