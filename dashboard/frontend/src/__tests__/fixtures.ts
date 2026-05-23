// Shared fixtures for frontend unit tests.

import type { Article, Classification } from "../types";

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
