> ⚠️ **HISTORIC — archived 2026-05-30.** Describes a completed implementation effort; do not consult as current truth. See [docs/archive/README.md](README.md) and the living docs it points to.

# Alert Grouping — Implementation Specification

## Overview

When complete, Project Sentinel will absorb the multi-article incident pattern that produced 12 SMS alerts for one drone-lake event on 2026-05-23. Three coordinated changes accomplish this: (1) the corroborator's matching window widens from 60 to 360 minutes (6h) so articles arriving over a longer span join the same `Event` row; (2) two similarity thresholds (summary and syndication) move from hardcoded constants to config-driven values, with the summary threshold dropped from 55% to 40% so phrasing variants like "Kolejny dron" / "Another drone" still match an existing event; (3) the read-only dashboard surfaces this grouping by exposing `event_id` on the article list, grouping consecutive same-event rows visually, and providing a dedicated `/events/:id` page that consolidates an event's articles, classifications, and alert history. The `/sentinel-audit` skill groups its per-article audit output by `event_id` so the morning report shows one block per incident instead of one block per article.

The within-event SMS spam (worth 7 of the 12 Latvia alerts) is handled by a separate hotfix on the `hotfix-sms-dedup` branch (PR #1) which is a strict prerequisite for this spec.

## Goals

- Articles describing the same real-world incident over a multi-hour window collapse into one `Event` row, producing one alert rather than N.
- Operators can tune corroboration window and similarity thresholds via `config/config.yaml` without code changes.
- The dashboard surfaces event grouping so the cross-event fragmentation that did occur (and edge cases that still will) is immediately legible without reading the database.
- Each event has a permanent URL (`/events/:id`) usable as a debugging entry point or shareable reference.
- The morning `/sentinel-audit` report is event-centric, not article-centric, so reviewing classifier quality requires reading O(events) lines instead of O(articles).

## Non-Goals

- **Backfilling existing fragmented events.** The 5 Latvia events from 2026-05-23 stay as 5 rows. The wider window applies only to classifications processed AFTER deploy.
- **A separate "thread" or "incident" table on top of Events.** The widened Event IS the grouping. No new schema table is added by this spec.
- **Manual event merge/split UI on the dashboard.** The dashboard is read-only per CLAUDE.md and stays read-only.
- **A per-incident alerting-policy backstop (the original three-policy ask).** Dropped after analysis showed the post-hotfix + widened-window combination handles the Latvia case fully. Policies can be added in a future spec if real-world data demonstrates need.
- **Modifying the `_MIN_EVENT_URGENCY = 5` constant in `corroborator.py`.** It is internal classification logic, not corroboration tuning, and is left as a local constant.
- **Authentication/permissions on the new dashboard event endpoints.** They inherit the dashboard's existing "local-only, no auth" model.

## Technical Context

### Existing Project

- **Backend production runtime**: Python 3.12, SQLite, APScheduler (dual-lane: fast 3min, slow 15min). See `CLAUDE.md` and `docs/architecture.md`.
- **Classifier**: Claude Haiku 4.5 (`claude-haiku-4-5-20251001`), one call per article, returns JSON with `event_type`, `urgency_score`, `affected_countries`, `aggressor`, `confidence`, `summary_pl`.
- **Corroborator** (`sentinel/classification/corroborator.py`): groups classifications into `Event` rows via event-type compatibility table + shared affected country + time window + summary similarity. Source-independence check uses domain equality + title similarity.
- **Dashboard subsystem**: Flask backend (`dashboard/`) + React/Vite/TS frontend (`dashboard/frontend/`), read-only over the production SQLite DB via SCP-sync or tunnel mode. See `SPEC.md` for the existing dashboard reference.
- **`/sentinel-audit` skill**: `.claude/skills/sentinel-audit/SKILL.md`. Daily quality audit pulling articles + classifications + events from prod DB; iterates flat by `fetched_at`.

### Current Database Schema (unchanged by this spec)

```sql
CREATE TABLE articles (
    id TEXT PRIMARY KEY, source_name TEXT NOT NULL, source_url TEXT NOT NULL,
    source_type TEXT NOT NULL, title TEXT NOT NULL, summary TEXT,
    language TEXT NOT NULL, published_at TEXT NOT NULL, fetched_at TEXT NOT NULL,
    url_hash TEXT NOT NULL, title_normalized TEXT NOT NULL, raw_metadata TEXT
);
CREATE TABLE classifications (
    id TEXT PRIMARY KEY, article_id TEXT NOT NULL REFERENCES articles(id),
    is_military_event INTEGER NOT NULL, event_type TEXT, urgency_score INTEGER NOT NULL,
    affected_countries TEXT, aggressor TEXT, is_new_event INTEGER NOT NULL,
    confidence REAL NOT NULL, summary_pl TEXT, classified_at TEXT NOT NULL,
    model_used TEXT NOT NULL, input_tokens INTEGER, output_tokens INTEGER
);
CREATE TABLE events (
    id TEXT PRIMARY KEY, event_type TEXT NOT NULL, urgency_score INTEGER NOT NULL,
    affected_countries TEXT NOT NULL, aggressor TEXT, summary_pl TEXT NOT NULL,
    first_seen_at TEXT NOT NULL, last_updated_at TEXT NOT NULL,
    source_count INTEGER NOT NULL DEFAULT 1, article_ids TEXT NOT NULL,
    alert_status TEXT NOT NULL DEFAULT 'pending', acknowledged_at TEXT
);
CREATE TABLE alert_records (
    id TEXT PRIMARY KEY, event_id TEXT NOT NULL REFERENCES events(id),
    alert_type TEXT NOT NULL, twilio_sid TEXT, status TEXT NOT NULL,
    duration_seconds INTEGER, attempt_number INTEGER NOT NULL DEFAULT 1,
    sent_at TEXT NOT NULL, message_body TEXT
);
```

`events.article_ids` is a JSON-encoded array. There is no `articles.event_id` foreign-key column — the membership relation lives in `events.article_ids`. Phase 2 needs to compute `event_id` per article via a JSON-membership join, not via a column lookup.

### Architecture Decisions

- **Decision**: Widen `corroboration_window_minutes` default from 60 → 360 minutes (6 hours).
  **Rationale**: The Latvia drone-lake incident on 2026-05-23 spanned 1h54m of article publication and produced 5 events because the corroborator's 60-minute window measured from `first_seen_at`. A 6h window would have merged 4 of those 5. Larger windows (24h) risk over-merging unrelated incidents that share keywords (e.g., two unrelated drone events in the same country on the same day). 6h is the smallest value that handles realistic incident publication spans without compromising the corroborator's "this is fresh, related news" semantics.

- **Decision**: Lower the summary-similarity threshold default from 55% → 40%.
  **Rationale**: Latvia event `68693b86` split off the original event because article 4 ("Kolejny dron nad Łotwą" / "Another drone over Latvia") had a summary explicitly framed as a sequel, dropping the token-sort-ratio similarity below 55%. Empirical inspection of the prod summaries showed the lowest correct-merge score in the Latvia set sat in the 40-50% range. 40% is the conservative edge of the empirical band; 35% would risk over-merging.

- **Decision**: Move the two similarity thresholds to `config.classification` as configurable keys.
  **Rationale**: Operational tuning without redeploy. Production data will reveal whether 40% / 90% are correct; pinning them in code forces every adjustment through a release cycle.

- **Decision**: Expose `event_id` on the article-list response via a JSON-membership LEFT JOIN, not via a new `articles.event_id` column.
  **Rationale**: Adding a column requires a migration on the live production DB and breaks the corroborator's existing "events own articles" model. JSON membership joins are slower but the article list is paginated to ≤100 rows per request, so the cost is bounded.

- **Decision**: The new `/api/events/<id>` endpoint reuses the existing article-detail event-shape contract, returning `{event, articles[], alert_records[]}` rather than introducing a new shape.
  **Rationale**: Frontend types already exist for `EventRecord` (in `dashboard/frontend/src/types.ts:122-136`); reuse maintains type consistency and minimizes the diff surface.

## Assumptions

- The hotfix on PR #1 (`hotfix-sms-dedup`) is merged to master and deployed BEFORE Phase 1 of this spec ships. Phase 1's acceptance tests assume `_user_already_notified` exists in `state_machine.py`.
- The classifier emits `summary_pl` regardless of source language (PL/EN/UA/RU). Cross-language matching works because comparisons happen on `summary_pl` directly. No explicit cross-language requirement is needed.
- Existing `Event.article_ids` JSON storage stays as JSON; no schema migration is in scope.
- Dashboard tests use the existing `_build_sentinel_db()` fixture pattern (`tests/test_dashboard_api.py:fixture sentinel_db_path`). New Phase 2 tests follow the same pattern.
- `config/config.yaml` and `config/config.example.yaml` use top-level snake_case keys (existing convention). New keys follow.
- Frontend test framework is vitest + @testing-library/react + jsdom (per `dashboard/frontend/` setup). New Phase 2 frontend tests use the existing per-component file convention.

---

## Phase 1 — Production Runtime: Widen Window, Configurable Thresholds

### Deliverables

- `sentinel/classification/corroborator.py` — replace module-level constants `_SUMMARY_SIMILARITY_THRESHOLD` and `_SYNDICATION_SIMILARITY_THRESHOLD` with `self.config.classification.*` reads; remove the constants (modify existing)
- `sentinel/config.py` — extend `ClassificationConfig` with three new optional fields (modify existing)
- `config/config.example.yaml` — add three new keys to the `classification:` block with documenting comments (modify existing)
- `tests/test_corroborator.py` — add 4 new tests covering the wider window, lowered threshold, configurable thresholds, and backward-compat defaults (modify existing)
- `docs/architecture.md` — update §3 (or the corresponding pipeline section) to note the 6h corroboration window and that thresholds are now config-driven (modify existing)
- `docs/config-reference.md` — document the three new keys with defaults, units, and acceptable ranges (modify existing)
- `CLAUDE.md` — bump the one-line reference to corroboration if any exists (modify existing)

### Requirements

**1.1** — Configurable corroboration window:
**1.1a** — `ClassificationConfig` MUST gain a field `corroboration_window_minutes: int` (already present; default value changes from 60 to 360).
**1.1b** — `config/config.example.yaml`'s `classification.corroboration_window_minutes` MUST be set to `360` with a comment explaining "wider than the 1h corroboration default to absorb multi-hour incident reporting windows; lowering this risks fragmenting one real incident into multiple Event rows".
**1.1c** — Existing user-config files (production `config.yaml`) without this key MUST continue to work; the loaded value defaults to 360.
**1.1d** — Corroborator behaviour MUST use the loaded value (already does at `corroborator.py:91`), with no further code change required for the value plumbing.

**1.2** — Configurable summary-similarity threshold:
**1.2a** — `ClassificationConfig` MUST gain a field `summary_similarity_threshold: int` with default value `40`. Range: `0..100`.
**1.2b** — `corroborator.py` MUST replace the hardcoded `_SUMMARY_SIMILARITY_THRESHOLD = 55` constant with a read from `self.config.classification.summary_similarity_threshold` inside `_find_matching_event`. The module-level constant MUST be removed.
**1.2c** — `config/config.example.yaml` MUST document the new key with default `40` and a comment explaining "fuzzy token_sort_ratio for matching two summaries to the same event; lower = more aggressive grouping; range 0-100".

**1.3** — Configurable syndication-similarity threshold:
**1.3a** — `ClassificationConfig` MUST gain a field `syndication_similarity_threshold: int` with default value `90`. Range: `0..100`.
**1.3b** — `corroborator.py` MUST replace the hardcoded `_SYNDICATION_SIMILARITY_THRESHOLD = 90` with `self.config.classification.syndication_similarity_threshold` inside `_is_independent_source` (or wherever the constant is referenced). The module-level constant MUST be removed.
**1.3c** — `config/config.example.yaml` MUST document the new key with default `90` and a comment explaining the meaning (title similarity threshold above which two articles are treated as syndicated copies of one source).

**1.4** — Regression: Latvia-like case merges into one event:
**1.4a** — A new test MUST process three classifications with `classified_at` spaced at 0min / 35min / 115min, all with `event_type="airspace_violation"`, all with `affected_countries=["LV"]`, all with summary tokens overlapping at ~50% token_sort_ratio (one summary using "Kolejny dron" style framing). With the default config values from this spec, the corroborator MUST group all three into ONE event with `source_count >= 2` and `article_ids` length 3.

**1.5** — Independent over-merge guard:
**1.5a** — A new test MUST verify that with the lowered 40% threshold, two events with similar event-type but DIFFERENT affected countries (e.g., LV vs LT) STILL produce two separate events. Country isolation is the safety rail that keeps the similarity drop safe.
**1.5b** — A new test MUST verify that with the lowered 40% threshold, two events with the same event-type and country but summaries with token_sort_ratio below 30% (e.g., totally different incidents) produce two separate events.

**1.6** — Backwards compatibility:
**1.6a** — Loading a YAML file with the OLD `classification:` block (no `summary_similarity_threshold`, no `syndication_similarity_threshold`) MUST NOT raise. The `ClassificationConfig` defaults MUST fill in.
**1.6b** — A new test MUST exercise this path: load a config-dict missing the two new keys, assert the loaded config has `summary_similarity_threshold == 40` and `syndication_similarity_threshold == 90`.

### Acceptance Tests

1. `test_latvia_six_hour_window_merges` — (unit) [1.4, 1.4a] Three classifications spaced 0/35/115 min, same type+country, ~50% summary overlap → one event, source_count ≥ 2, three article_ids.
2. `test_summary_threshold_configurable` — (unit) [1.2, 1.2a, 1.2b] Override `summary_similarity_threshold=80` in a test config, verify two summaries at 50% similarity now produce TWO events (proving threshold is read from config).
3. `test_summary_threshold_default_is_40` — (unit) [1.2a, 1.6, 1.6a, 1.6b] Load `ClassificationConfig` with no `summary_similarity_threshold` key in dict, assert loaded value == 40.
4. `test_syndication_threshold_configurable` — (unit) [1.3, 1.3a, 1.3b] Override `syndication_similarity_threshold=50`, verify two cross-source articles with 60% title similarity are now flagged as syndicated (not independent).
5. `test_syndication_threshold_default_is_90` — (unit) [1.3a, 1.6, 1.6a, 1.6b] Load `ClassificationConfig` without the key, assert loaded value == 90.
6. `test_corroboration_window_default_is_360` — (unit) [1.1, 1.1a, 1.1c] Load `ClassificationConfig` without the key, assert loaded value == 360.
7. `test_country_isolation_under_lowered_threshold` — (unit) [1.5, 1.5a] Two articles, same event_type, same summary text, DIFFERENT affected countries → two separate events even at 40% threshold.
8. `test_very_different_summaries_not_merged` — (unit) [1.5, 1.5b] Two articles, same event_type, same country, but summaries with token_sort_ratio < 30 → two separate events.

### Gate Criteria

- `.venv/bin/pytest tests/test_corroborator.py tests/test_config.py -v` — All tests pass, including the 8 new tests from this phase and all previously passing tests.
- `.venv/bin/pytest tests/ -v` — Full project test suite passes (zero regressions; the hotfix from PR #1 is already merged so `tests/test_state_machine.py::test_sms_not_resent_when_new_article_added` is also passing).
- `.venv/bin/ruff check sentinel/classification/corroborator.py sentinel/config.py tests/test_corroborator.py` — Clean (no new errors introduced; pre-existing repo-wide ruff findings unrelated to this phase are out of scope).
- `python -c "from sentinel.config import load_config; cfg = load_config('config/config.example.yaml'); assert cfg.classification.corroboration_window_minutes == 360; assert cfg.classification.summary_similarity_threshold == 40; assert cfg.classification.syndication_similarity_threshold == 90"` — Loading the example config produces the new defaults.

---

## Phase 2 — Dashboard: Event Grouping in Article List + Event Detail Page

### Dependencies on Previous Phases

- Requires Phase 1 to be merged. The new `event_id` exposure in the article-list response and the `/api/events/<id>` endpoint do not strictly require the widened window, but the user-facing value of grouping presumes Phase 1 has reduced fragmentation.

### Deliverables

- `dashboard/api/events.py` — new Flask blueprint serving `GET /api/events/<event_id>` (create)
- `dashboard/api/__init__.py` — register the new blueprint (modify existing)
- `dashboard/db.py` — add a `get_event_with_articles(event_id)` method; extend `list_articles` to include `event_id` per row (computed via JSON-membership join) (modify existing)
- `dashboard/frontend/src/api/client.ts` — add `fetchEvent(eventId)` helper (modify existing)
- `dashboard/frontend/src/types.ts` — add `EventDetail` type (extends existing `EventRecord` with `articles: Article[]` and `alert_records[]`); add `event_id: string | null` to `Article` (modify existing)
- `dashboard/frontend/src/pages/EventDetailPage.tsx` — new page rendering event metadata + article list + alert timeline (create)
- `dashboard/frontend/src/App.tsx` — register the new route `/events/:id` (modify existing)
- `dashboard/frontend/src/components/ArticleTable.tsx` — render consecutive same-`event_id` rows visually grouped: a chevron / left-border / event-count badge on the first row; subsequent rows in the same event indented or color-banded (modify existing)
- `tests/test_dashboard_api.py` — add tests for the new event endpoint AND the `event_id` field on the article list (modify existing)
- `dashboard/frontend/src/__tests__/EventDetailPage.test.tsx` — new page test (create)
- `dashboard/frontend/src/__tests__/ArticleTable.test.tsx` — extend existing test (or create if missing) to cover same-`event_id` grouping rendering (modify existing or create)

### Requirements

**2.1** — Event detail API endpoint:
**2.1a** — `GET /api/events/<event_id>` MUST return HTTP 200 with body shape:

_Normative example:_
```json
{
  "id": "d4585e99-1a1c-494b-a827-1c93dfba0187",
  "event_type": "airspace_violation",
  "urgency_score": 5,
  "affected_countries": ["LV"],
  "aggressor": "unknown",
  "summary_pl": "...",
  "first_seen_at": "2026-05-23T11:01:28.975727+00:00",
  "last_updated_at": "2026-05-23T11:23:46.988332+00:00",
  "source_count": 4,
  "article_ids": ["...", "...", "...", "..."],
  "alert_status": "sms_sent",
  "acknowledged_at": null,
  "articles": [{"id": "...", "source_name": "...", "title": "...", ...}],
  "alert_records": [{"id": "...", "alert_type": "sms", "status": "sent", "sent_at": "...", ...}]
}
```

The `articles` array MUST include the same Article fields the existing `GET /api/articles/<id>` returns at the top level (id, source_name, source_url, source_type, title, summary, language, published_at, fetched_at, classification), in `published_at` ascending order.

**2.1b** — `GET /api/events/<event_id>` MUST return HTTP 404 with body `{"error": "event not found"}` for unknown IDs.
**2.1c** — The endpoint MUST be read-only — only `GET` is exposed; `POST`/`PUT`/`DELETE` MUST return 405.

**2.2** — Article-list includes event_id:
**2.2a** — `GET /api/articles` response objects MUST include a `event_id: string | null` field on every Article row. Articles not in any event have `event_id: null`.
**2.2b** — The implementation MUST compute `event_id` via a LEFT JOIN of `events.article_ids` (parsed JSON array) against `articles.id`. The query MUST scope the join to events with `first_seen_at` within the article-retention window (default 30 days) so the JSON membership scan stays bounded.
**2.2c** — When an article belongs to multiple events (theoretical edge case — corroborator should prevent but does not enforce uniqueness), the lowest `event.first_seen_at` event SHOULD be returned. The endpoint MUST NOT raise.

**2.3** — Article-list visual grouping:
**2.3a** — `ArticleTable.tsx` MUST render consecutive rows sharing the same `event_id` with a visual group indicator on the first row (e.g., a chevron, a colored left-border, or an event-count badge such as "Event: 4 articles"). The exact UI element is implementation freedom; a single MUST-present indicator suffices.
**2.3b** — Subsequent rows in the same event group MUST be visually distinguishable from a fresh row (e.g., faded color, indented, or a small connector line). Distinguishability MUST be at least 2 visual changes (color + indent, color + border, etc.) for accessibility — color alone is insufficient.
**2.3c** — Rows with `event_id: null` MUST render in their existing default style — the grouping styling is additive, not destructive.
**2.3d** — Clicking the event-group indicator (chevron, badge, etc.) on the first row MUST navigate to `/events/<event_id>`.
**2.3e** — Sorting and pagination MUST continue to work; visual grouping is a render-time pass over the response, not a re-query.

**2.4** — `/events/:id` route:
**2.4a** — `App.tsx` MUST register the route `/events/:id` mapping to `EventDetailPage`.
**2.4b** — Hitting `/events/<unknown-id>` MUST render a "Event not found" UI matching the existing `<NotFound>` component pattern used for missing articles.

**2.5** — EventDetailPage content:
**2.5a** — The page MUST render: event ID, event type (PL-translated using existing translation map IF feasible from frontend code; otherwise raw value), urgency score badge, affected countries chips, aggressor string, summary_pl, first_seen_at / last_updated_at, source_count, and alert_status badge.
**2.5b** — Below the metadata, the page MUST list every article in the event with its title (clickable to `/articles/:id`), source_name, published_at, language, and classification urgency badge. Ordering MUST be `published_at` ascending.
**2.5c** — Below the article list, the page MUST render a "Alert timeline" section listing every `alert_record` with `sent_at`, `alert_type`, `status`, and message_body (truncated to 200 chars with expand-on-click for the full body). Ordering MUST be `sent_at` ascending.
**2.5d** — The page MUST include a "← Back" link that respects React Router's history (uses `history.back()` semantics, not a hardcoded path).

**2.6** — Frontend types:
**2.6a** — `types.ts` MUST add `event_id?: string | null` to the `Article` interface. The existing `Article` interface in `dashboard/frontend/src/types.ts` MUST be extended in place.
**2.6b** — `types.ts` MUST add an `EventDetail` interface that extends `EventRecord` with `articles: Article[]`. The existing `EventRecord` MUST remain unchanged.

### Acceptance Tests

1. `test_event_detail_returns_200_with_full_shape` — (integration) [2.1, 2.1a] Hit `/api/events/<known-id>` against the test DB, assert 200 + every required field present + `articles[]` and `alert_records[]` populated.
2. `test_event_detail_returns_404_for_unknown_id` — (integration) [2.1b] Hit with a random UUID, assert 404 + error body.
3. `test_event_detail_rejects_non_get_methods` — (integration) [2.1c] POST/PUT/DELETE return 405.
4. `test_article_list_includes_event_id` — (integration) [2.2, 2.2a] Hit `/api/articles?page_size=50` against the test DB, assert every Article row has the `event_id` key (null or string). At least one row with non-null `event_id` exists in the fixture.
5. `test_article_list_event_id_for_non_event_article` — (integration) [2.2a] An article inserted with NO event row referencing it returns `event_id: null` in the article list.
6. `test_article_list_event_id_for_event_member` — (integration) [2.2, 2.2b] An article whose UUID appears in some `events.article_ids` JSON returns that event's `id` in the list response.
7. `test_event_id_join_scoped_to_retention_window` — (integration) [2.2b] An article that was once in an event row that has since been pruned (event row deleted) returns `event_id: null`. (Stub: insert article, do not insert event.)
8. `test_article_table_renders_event_group_indicator` — (unit, vitest) [2.3, 2.3a, 2.3d] Render `ArticleTable` with fixture data of 3 rows sharing one `event_id` and 1 standalone row; assert a single event-group indicator is present on the first grouped row and clicking it navigates to `/events/<id>`.
9. `test_article_table_standalone_row_unchanged` — (unit, vitest) [2.3c] Render with only standalone rows; assert no event-group styling is added.
10. `test_event_detail_page_renders_known_event` — (unit, vitest) [2.4, 2.4a, 2.5, 2.5a, 2.5b, 2.5c] Mount `EventDetailPage` with a mocked API response; assert metadata, article list, and alert timeline are rendered.
11. `test_event_detail_page_renders_not_found_for_404` — (unit, vitest) [2.4b] Mock the API to return 404; assert the not-found UI renders.
12. `test_event_detail_page_back_link_uses_history` — (unit, vitest) [2.5d] Mount with a memory router with a non-empty history stack; assert the "← Back" link triggers a history navigation rather than `/`-href.

### Gate Criteria

- `.venv/bin/pytest tests/test_dashboard_api.py tests/test_dashboard_db.py -v` — All backend dashboard tests pass, including the 7 new integration tests from this phase.
- `cd dashboard/frontend && npx vitest run` — All frontend tests pass, including the 5 new component/page tests from this phase.
- `cd dashboard/frontend && npx tsc --noEmit` — Type-check clean. The new `event_id` field on `Article` must not produce any unresolved type errors in existing components.
- `cd dashboard/frontend && npm run build` — Production build succeeds; the new `EventDetailPage` is included in the dist bundle.
- `.venv/bin/ruff check dashboard/api/events.py dashboard/api/__init__.py dashboard/db.py` — Clean on touched files.
- `python -c "from dashboard.app import create_app; app = create_app(); rules = {r.rule for r in app.url_map.iter_rules()}; assert '/api/events/<event_id>' in rules"` — The new route is registered.

---

## Phase 3 — Audit Skill: Group by event_id

### Dependencies on Previous Phases

- Requires Phase 1 to be merged (relies on the widened window having reduced the events-per-incident ratio so the grouped report is shorter and useful).
- Independent of Phase 2 (the audit skill talks to the DB directly, not the dashboard API).

### Deliverables

- `.claude/skills/sentinel-audit/SKILL.md` — modify the article iteration / report structure to group by `event_id` where present; standalone (event_id-less) articles continue to appear as individual rows under a "Standalone classified articles" section (modify existing)
- `tests/test_sentinel_audit_skill.py` — new pytest module that reads the SKILL.md and asserts the structural changes are present (string presence checks); runnable from project root (create)

### Requirements

**3.1** — Event-grouped audit report:
**3.1a** — The audit report MUST organize the "Classified articles" section (and any other per-article iteration) into two groups: (a) articles belonging to an event, grouped under one block per `event_id`; (b) articles not in any event, listed flat under a separate "Standalone classified articles" sub-heading.
**3.1b** — Each event-block MUST show: event_id (8-char prefix), event_type, urgency_score, affected_countries, source_count, `first_seen_at` → `last_updated_at` span, alert_status, then a bullet-list of the constituent articles (title, source_name, published_at).
**3.1c** — Within each event-block, articles MUST be listed in `published_at` ascending order.
**3.1d** — Event blocks MUST be ordered by `urgency_score` descending then `first_seen_at` descending (highest-stakes events at the top).

**3.2** — Unchanged audit obligations:
**3.2a** — The keyword-filter audit (Step 2 of the existing skill) and source-health audit (Step 4) MUST continue to operate identically; they iterate articles, not events, and are out of scope of this grouping.
**3.2b** — The audit timestamp logic (`.last-audit-timestamp`) MUST NOT change.
**3.2c** — The output format (markdown report) MUST remain a single markdown file in the existing location.

**3.3** — Schema documentation:
**3.3a** — The skill's "Database schema" preamble MUST document that `events.article_ids` is a JSON array and that the audit script needs to either parse it directly (in SQL via `json_each`) or do a Python join.

### Acceptance Tests

The audit skill is a markdown-driven LLM prompt rather than Python code, so its automated acceptance tests are structural string-presence checks. Runtime behaviour is verified in the "Manual Verification" section below.

1. `test_skill_md_documents_event_grouping` — (unit) [3.1, 3.1a, 3.1b] Read `.claude/skills/sentinel-audit/SKILL.md`; assert it contains the literal strings `event_id`, `events.article_ids`, `Standalone classified articles`, and a description of the per-event block layout (event_id prefix, event_type, urgency_score, source_count, time span).
2. `test_skill_md_documents_ordering` — (unit) [3.1d] Same file MUST contain a sentence stating that event blocks are ordered by `urgency_score` descending then `first_seen_at` descending.
3. `test_skill_md_preserves_unchanged_sections` — (unit) [3.2, 3.2a, 3.2b, 3.2c] Same file MUST still contain the keyword-filter audit section (Step 2) and the source-health section (Step 4) substantially unchanged — verified by string presence of distinctive phrases from those steps.
4. `test_skill_md_documents_json_array_format` — (unit) [3.3, 3.3a] Same file MUST mention either `json_each` (SQLite extension) or a Python-side JSON parse for the `events.article_ids` array.

### Gate Criteria

- `.venv/bin/pytest tests/test_sentinel_audit_skill.py -v` — Tests 1-4 above pass (the test file is a new deliverable of this phase, runnable from the project root; it simply reads the SKILL.md and asserts string presence).
- `grep -q 'Standalone classified articles' .claude/skills/sentinel-audit/SKILL.md` — Exit 0; the new section heading is present.
- `grep -q 'json_each\|json\.loads' .claude/skills/sentinel-audit/SKILL.md` — Exit 0; the article-ids parsing strategy is documented.

### Manual Verification

These steps are NOT gate criteria — they are validation tasks the PR author performs before merge and records as a checkbox in the PR description:

- [ ] Invoke `/sentinel-audit` against the prod DB with a 24h window covering 2026-05-23 (the day that produced the 5 Latvia events). Verify the report groups multiple articles under one event block, lists at least one block per existing event from that window, and emits a "Standalone classified articles" section for articles with no event.
- [ ] Verify event blocks at the top of the report have higher `urgency_score` than blocks lower down; ties broken by `first_seen_at` descending.
- [ ] No article appears twice (in both an event block AND the standalone section).

---

## Glossary

- **Event** — A SQLite row in the `events` table representing one corroborator-grouped real-world incident. Holds 1..N article IDs in a JSON array. After Phase 1, events span up to 6 hours of article arrivals.
- **Article** — A SQLite row in the `articles` table representing one normalized fetched headline+summary from one source.
- **Corroboration** — The corroborator's job of grouping similar classifications into a shared event row and counting independent sources.
- **Independent source** — Two articles whose `(domain, title-similarity<syndication_threshold)` indicates they come from different newsrooms, not syndicated copies of one wire story.
- **Source count** — `events.source_count`, the count of independent newsrooms that have published an article in this event. Drives the corroboration_required threshold for phone-call escalation.
- **Alert** — One Twilio dispatch (SMS, WhatsApp routed to SMS, or phone call) for one event. Logged in `alert_records`.
- **Cross-event fragmentation** — The bug pattern where one real incident produces multiple Event rows because the corroborator's matching window expired or the similarity threshold was too strict. Phase 1 reduces this.
- **Within-event SMS spam** — The hotfix-PR-1 bug where the state machine re-fired SMS for every new article attached to an already-alerted SMS event. Not in scope of THIS spec; assumed fixed by PR #1.
