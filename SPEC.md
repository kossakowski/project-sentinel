# Article Dashboard — Implementation Specification

## Overview

When complete, the Article Dashboard will be a locally-running web application that
connects to Project Sentinel's production SQLite database (synced via SCP or queried
via SSH tunnel) and presents all articles, classifications, events, and alerts in an
interactive React-based interface. The user can browse, sort, filter, and search
37,000+ articles, inspect what the classifier saw and how it scored each article,
view pipeline analytics (funnels, time series, distributions), and annotate articles
with correctness labels and expected urgency scores for classifier calibration — all
from a single `dashboard/` subfolder within the existing project-sentinel repository.

## Goals

- Give the user full visibility into every article the production pipeline touches —
  including the ~85% that get filtered out before classification
- Enable analysis of classification quality by showing classifier input alongside output
- Support keyword search across all articles (FTS5 on synced DB, LIKE fallback on tunnel)
- Provide pipeline health analytics: funnel, time series, urgency distribution, source breakdown
- Allow annotation of articles (correct/incorrect, expected urgency, notes) in a local DB
  that survives production DB re-syncs
- Run entirely locally — no changes to the production server

## Non-Goals

- **Modifying production data** — The dashboard is strictly read-only against the production DB.
- **Deploying on the server** — This runs on the user's local machine only.
- **Real-time streaming** — Data is refreshed by manual sync or SSH tunnel queries, not WebSocket/SSE.
- **Article content fetching/caching** — Anti-scraping measures make this unreliable. Link-only.
- **Annotation export** — Annotations stay in local SQLite. YAML export for calibration can be added later.
- **Authentication/HTTPS** — Single-user localhost tool. No auth needed.
- **Mobile or responsive design** — Desktop browser only.

## Technical Context

### Existing Project

- **Language:** Python 3.12, Flask already in `requirements.txt`
- **Database:** SQLite at `/var/lib/sentinel/sentinel.db` on production (42 MB, ~37.5K articles)
- **Server:** `deploy@178.104.76.254:2222` (SSH), read-only access is safe per project policy
- **Project structure:** Python package at `sentinel/`, entry point `sentinel.py`, config at `config/`
- **Existing models:** `sentinel/models.py` defines `Article`, `ClassificationResult`, `Event`, `AlertRecord` dataclasses
- **Existing DB layer:** `sentinel/database.py` provides `Database` class with SQLite operations
- **Test framework:** pytest, tests in `tests/`
- **Linting:** Project uses Python standard tooling

### Production Database Schema

```sql
-- 37,542 rows, ~1,200-1,500/day weekdays
CREATE TABLE articles (
    id TEXT PRIMARY KEY,                -- UUID
    source_name TEXT NOT NULL,          -- e.g. "TVN24", "TASS", "GoogleNews:site:pap.pl"
    source_url TEXT NOT NULL,           -- Original article URL
    source_type TEXT NOT NULL,          -- "rss" | "google_news" | "telegram"
    title TEXT NOT NULL,                -- Original headline
    summary TEXT,                       -- Body text or snippet (may be enriched)
    language TEXT NOT NULL,             -- "pl" | "en" | "uk"
    published_at TEXT NOT NULL,         -- ISO 8601 UTC
    fetched_at TEXT NOT NULL,           -- ISO 8601 UTC
    url_hash TEXT NOT NULL,             -- SHA256(source_url)
    title_normalized TEXT NOT NULL,     -- Lowercase, no diacritics, alphanumeric only
    raw_metadata TEXT                   -- JSON blob: keyword_match, enrichment info, tags
);

-- 5,812 rows (15.5% of articles reach classification)
CREATE TABLE classifications (
    id TEXT PRIMARY KEY,                -- UUID
    article_id TEXT NOT NULL,           -- FK → articles(id)
    is_military_event INTEGER NOT NULL, -- 0 or 1
    event_type TEXT NOT NULL,           -- "none"|"drone_attack"|"airspace_violation"|...
    urgency_score INTEGER NOT NULL,     -- 1-10
    affected_countries TEXT NOT NULL,   -- JSON array: ["PL", "LT", ...]
    aggressor TEXT,                     -- "RU"|"BY"|"UA"|"unknown"|"none"
    is_new_event INTEGER NOT NULL,      -- 0 or 1
    confidence REAL NOT NULL,           -- 0.0-1.0
    summary_pl TEXT,                    -- Polish summary for alerts
    classified_at TEXT NOT NULL,        -- ISO 8601 UTC
    model_used TEXT NOT NULL,           -- "claude-haiku-4-5-20251001"
    input_tokens INTEGER,              -- API cost tracking
    output_tokens INTEGER              -- API cost tracking
);

-- 501 rows
CREATE TABLE events (
    id TEXT PRIMARY KEY,                -- UUID
    event_type TEXT NOT NULL,
    urgency_score INTEGER NOT NULL,
    affected_countries TEXT NOT NULL,   -- JSON array
    aggressor TEXT,
    summary_pl TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,        -- ISO 8601 UTC
    last_updated_at TEXT NOT NULL,      -- ISO 8601 UTC
    source_count INTEGER NOT NULL DEFAULT 1,
    article_ids TEXT NOT NULL,          -- JSON array of article UUIDs
    alert_status TEXT NOT NULL DEFAULT 'pending',
    acknowledged_at TEXT               -- ISO 8601 UTC, nullable
);

-- 365 rows
CREATE TABLE alert_records (
    id TEXT PRIMARY KEY,                -- UUID
    event_id TEXT NOT NULL,             -- FK → events(id)
    alert_type TEXT NOT NULL,           -- "sms"|"phone_call"|"whatsapp"
    twilio_sid TEXT,
    status TEXT NOT NULL,               -- "sent"|"completed"|"failed"|...
    duration_seconds INTEGER,           -- For phone calls
    attempt_number INTEGER NOT NULL DEFAULT 1,
    sent_at TEXT NOT NULL,              -- ISO 8601 UTC
    message_body TEXT                   -- Full alert text
);
```

### Pipeline Stage Context

Each article passes through these stages (relevant for the "pipeline status" display):

1. **Collected** — Fetched from source (all 37.5K articles)
2. **Deduplicated** — Passed URL hash + fuzzy title dedup
3. **Keyword-filtered** — Matched critical/high keywords (or bypassed for Telegram/Defence24)
4. **Enriched** — Summary augmented via body fetch (if original was vague)
5. **Classified** — Sent to Claude Haiku, received urgency score (5,812 articles)
6. **Event created** — Urgency ≥ 5, grouped by corroborator (501 events)
7. **Alert sent** — SMS/call dispatched via Twilio (365 alert records)

An article's pipeline status is determined by joins:
- Has a row in `classifications` → classified
- Classification's `article_id` appears in any `events.article_ids` JSON → event created
- That event has rows in `alert_records` → alert sent
- No classification row → unclassified (filtered out before classification)

### Data Distribution (informing UI design)

- **Sources:** 37 feeds. Top: Onet (4,435), TASS (4,036), Rzeczpospolita (3,776)
- **Languages:** PL 54.7%, EN 40.4%, UK 4.9%
- **Source types:** RSS 69.5%, Google News 27.9%, Telegram 2.6%
- **Urgency scores:** 48.5% score 1, 38.9% score 2, 4% score 3, then long tail to 9
- **Event types:** airspace_violation 55%, drone_attack 27%, other 5%, troop_movement 4%
- **Alert status:** sms_sent 49%, whatsapp 33%, sms 13%, retry_pending 2%

## Architecture Decisions

- **Decision:** Flask API backend + React SPA frontend, both in `dashboard/` subfolder.
  **Rationale:** Flask is already a project dependency. React + Vite provides the interactive
  table/chart experience the user wants. During development, Vite serves at 5173 and proxies
  API calls to Flask at 5001. For usage, Flask serves the built React static files + API on
  port 5001.

- **Decision:** Two data access modes — SCP sync (primary) + SSH tunnel (backup).
  **Rationale:** SCP sync is simple and works offline. SSH tunnel provides live data when
  needed. FTS5 search only works in sync mode; tunnel mode falls back to LIKE.

- **Decision:** Annotations stored in a separate local SQLite database (`dashboard/data/annotations.db`).
  **Rationale:** Production DB syncs must not overwrite user's annotation work. Separate DB
  means annotations persist independently. Joined at query time via article_id.

- **Decision:** FTS5 virtual table built automatically on each DB sync.
  **Rationale:** FTS5 provides fast, ranked full-text search across 37K+ articles. Building
  the index takes <5 seconds and is triggered automatically after SCP sync completes.

- **Decision:** Port 5001 for Flask API.
  **Rationale:** Avoids conflicts with default Flask port 5000 (used by AirPlay on macOS,
  and avoids collision if the user runs other Flask apps). Vite dev server uses its default 5173.

## Assumptions

- Node.js (18+) and npm are available locally for the React build
- SSH key-based auth to the production server is configured (user already has this)
- The production DB schema will not change without updating the dashboard accordingly
- The user's browser is a modern desktop browser (Chrome, Firefox, Edge)
- Python 3.12 venv at `.venv/` in project root is the active environment

---

## Phase 1 — Backend Foundation

Flask API server, database access layer, SCP sync command, and core API endpoints
for articles with filtering, sorting, pagination, and search.

### Deliverables

- `dashboard/__init__.py` — Package marker (create)
- `dashboard/app.py` — Flask application factory, CORS config, static file serving (create)
- `dashboard/config.py` — Dashboard configuration (DB paths, server SSH details, port) (create)
- `dashboard/db.py` — Database access layer: connection management, query builders, FTS5 index (create)
- `dashboard/sync.py` — SCP sync logic + FTS5 index rebuild (create)
- `dashboard/api/__init__.py` — API blueprint package marker (create)
- `dashboard/api/articles.py` — Article list/detail/search endpoints (create)
- `dashboard/api/stats.py` — Statistics and aggregation endpoints (create)
- `dashboard/api/sync.py` — Sync trigger and status endpoints (create)
- `dashboard/cli.py` — CLI entry point: `python -m dashboard` or `./run-dashboard.sh` (create)
- `dashboard/run-dashboard.sh` — Shell script to launch the dashboard (create)
- `tests/test_dashboard_api.py` — API endpoint tests (create)
- `tests/test_dashboard_db.py` — Database layer tests (create)
- `requirements.txt` — Add `flask-cors` dependency (modify existing)

### Requirements

**1.1 — Flask Application:** The Flask app MUST be created via an application factory
pattern in `dashboard/app.py`. It MUST register API blueprints under the `/api/` prefix.
It MUST serve the built React frontend from `dashboard/frontend/dist/` when the directory
exists, falling back to a JSON message `{"status": "frontend not built"}` at `/` otherwise.

**1.1a** — The app MUST enable CORS for `http://localhost:5173` (Vite dev server) in
development mode, using `flask-cors`.

**1.1b** — The app MUST accept a `--db` flag to specify the path to the sentinel SQLite
database, defaulting to `dashboard/data/sentinel.db`.

**1.1c** — The app MUST accept a `--tunnel` flag that, when provided, fetches a fresh
copy of the production database over SSH on each dashboard startup instead of using the
locally-synced file. The fetch MUST target
`deploy@178.104.76.254:2222:/var/lib/sentinel/sentinel.db`. This mode provides
fresher-than-last-sync data; FTS5 is not built for the temporary copy, so search falls
back to LIKE. (The production database is a plain SQLite file with no network service,
so a port-forward to a live DB connection is not possible.)

**1.2 — Database Access Layer:** `dashboard/db.py` MUST provide a `DashboardDB` class
that wraps SQLite connections for read-only access to the sentinel database.

**1.2a** — `DashboardDB` MUST support two connection modes: local file (default) and
tunnel (fresh-fetch). In local mode, it opens the SQLite file directly with `?mode=ro`
(read-only). In tunnel mode, it MUST use `subprocess` to invoke `scp` over SSH to copy
the production database to a temporary local file, open that temporary file read-only,
and remove it on close. No port-forwarding (`ssh -L`) is used: the production database
is a plain file with no remote query service, so port-forwarding would target nothing.

**1.2b** — `DashboardDB` MUST provide a method `get_articles(filters, sort, page, page_size)`
that returns paginated, sorted, filtered article rows with LEFT JOINs to classifications.
Supported filters: `source_name`, `source_type`, `language`, `urgency_min`, `urgency_max`,
`date_from`, `date_to`, `pipeline_status` ("all", "classified", "unclassified"),
`event_type`, `has_alert` (boolean). The `pipeline_status` filter MAY additionally accept
the output values `"event_created"` and `"alert_sent"` (defined in req 1.4b) as inputs,
narrowing results to articles that reached those later pipeline stages. Supported sort
columns: `published_at`, `fetched_at`, `urgency_score`, `source_name`, `title`,
`confidence`. Sort direction: `asc` or `desc`.

**1.2c** — `DashboardDB` MUST provide a method `get_article_detail(article_id)` that
returns the full article row joined with its classification (if any), linked events (by
checking `events.article_ids` JSON), and alert records for those events.

**1.2d** — `DashboardDB` MUST provide a method `search_articles(query, page, page_size)`
that performs FTS5 full-text search when an FTS5 index exists, falling back to
`title LIKE '%query%' OR summary LIKE '%query%'` otherwise. FTS5 results MUST be
ordered by relevance rank.

**1.2e** — `DashboardDB` MUST provide a method `get_stats()` that returns aggregate
statistics: total articles, total classified, total events, total alerts, articles per
day (last 30 days), urgency distribution, source distribution, language distribution,
event type distribution, pipeline funnel counts.

**1.3 — SCP Sync:** `dashboard/sync.py` MUST provide a `sync_db()` function that copies
the production database from `deploy@178.104.76.254:2222:/var/lib/sentinel/sentinel.db`
to `dashboard/data/sentinel.db` via SCP.

**1.3a** — After a successful SCP copy, `sync_db()` MUST automatically build (or rebuild)
an FTS5 virtual table `articles_fts` indexing `title` and `summary` columns from the
`articles` table. The FTS5 table MUST be created in a separate database file
(`dashboard/data/sentinel_fts.db`) attached to the main database, so the synced file
remains unmodified.

**1.3b** — `sync_db()` MUST return a result object containing: success boolean, file size
in bytes, article count, sync duration in seconds, and any error message.

**1.3c** — The `dashboard/data/` directory MUST be created automatically if it does not exist.

**1.4 — Articles API Endpoint:** `GET /api/articles` MUST accept query parameters:
`page` (int, default 1), `page_size` (int, default 50, allowed: 25/50/100),
`sort` (string, default "published_at"), `order` (string, default "desc"),
`source_name`, `source_type`, `language`, `urgency_min`, `urgency_max`,
`date_from`, `date_to`, `pipeline_status`, `event_type`, `has_alert`, `q` (search query).

**1.4a** — The response MUST be JSON with shape:
```json
{
  "articles": [
    {
      "id": "uuid",
      "source_name": "TVN24",
      "source_url": "https://...",
      "source_type": "rss",
      "title": "Article headline",
      "summary": "Article body...",
      "language": "pl",
      "published_at": "2026-05-22T10:00:00+00:00",
      "fetched_at": "2026-05-22T10:03:00+00:00",
      "classification": {
        "urgency_score": 7,
        "event_type": "airspace_violation",
        "is_military_event": true,
        "confidence": 0.92,
        "affected_countries": ["PL"],
        "aggressor": "RU",
        "summary_pl": "Polish summary...",
        "classified_at": "2026-05-22T10:03:05+00:00",
        "input_tokens": 1076,
        "output_tokens": 150
      },
      "pipeline_status": "classified",
      "has_alert": false
    }
  ],
  "total": 37542,
  "page": 1,
  "page_size": 50,
  "total_pages": 751
}
```
_(Normative: response shape is required. Field names must match exactly.)_

**1.4b** — When `classification` is null (article was not classified), the `pipeline_status`
field MUST be `"unclassified"`. When classified but no event, `"classified"`. When event
exists, `"event_created"`. When alert exists, `"alert_sent"`.

**1.4c** — When `q` is provided, it MUST compose with all filter parameters and `sort`/
`order`. A request like `?q=drone&pipeline_status=unclassified&sort=published_at&order=desc`
MUST return unclassified articles whose title or summary matches "drone", ordered by
`published_at` descending. FTS5 rank ordering is used only as the DEFAULT sort when no
explicit `sort` is provided; an explicit `sort` parameter overrides FTS rank.

**1.5 — Article Detail API Endpoint:** `GET /api/articles/<article_id>` MUST return the
full article with classification, classifier input reconstruction, linked events, and
alert records.

**1.5a** — The response MUST include a `classifier_input` field containing the reconstructed
text that was sent to the classifier, formatted as:
```
Source: {source_name} ({source_type})
Language: {language}
Published: {published_at}
Title: {title}
Summary: {summary}
```
This reconstruction matches the format used by `sentinel/classification/classifier.py`.

**1.5b** — The response MUST include an `events` array containing all events whose
`article_ids` JSON array contains this article's ID, each with their `alert_records`.

**1.6 — Statistics API Endpoint:** `GET /api/stats` MUST return the aggregate statistics
from `DashboardDB.get_stats()` as JSON.

**1.6a** — The `articles_per_day` field MUST contain date and count pairs for the last
30 days, including days with zero articles.

**1.6b** — The `pipeline_funnel` field MUST contain counts for each stage: collected,
classified, events_created, alerts_sent.

**1.7 — Sync API Endpoint:** `POST /api/sync` MUST trigger a database sync from
production and return the sync result. The sync MUST run synchronously (the DB is only
42 MB, SCP takes <10 seconds).

**1.7a** — `GET /api/sync/status` MUST return the timestamp and result of the last sync,
or `{"last_sync": null}` if no sync has been performed.

**1.8 — CLI Entry Point:** `dashboard/cli.py` MUST provide a CLI that starts the Flask
server. It MUST support `--port` (default 5001), `--db` (path to sentinel.db),
`--tunnel` (use SSH tunnel), and `--sync` (sync DB before starting).

**1.8a** — `dashboard/run-dashboard.sh` MUST activate the project venv and run
`python -m dashboard` with all passed arguments, similar to the existing `run.sh` pattern.

### Acceptance Tests

1. `test_app_factory_creates_app` — (unit) [1.1] App factory returns a Flask app with API blueprint registered
2. `test_app_cors_dev_mode` — (unit) [1.1a] CORS headers present for localhost:5173
3. `test_db_get_articles_pagination` — (unit) [1.2b, 1.4] Query with page=2, page_size=25 returns correct slice
4. `test_db_get_articles_filters` — (unit) [1.2b] Filter by source_type="telegram" returns only telegram articles
5. `test_db_get_articles_sort` — (unit) [1.2b] Sort by urgency_score desc returns highest first
6. `test_db_get_articles_pipeline_status` — (unit) [1.2b, 1.4b] Filter by pipeline_status="unclassified" returns articles without classifications
7. `test_db_get_article_detail` — (unit) [1.2c, 1.5] Detail includes classification, events, and alerts
8. `test_db_get_article_detail_unclassified` — (unit) [1.2c, 1.5] Unclassified article has null classification
9. `test_db_search_fts5` — (unit) [1.2d] FTS5 search returns ranked results matching query
10. `test_db_search_like_fallback` — (unit) [1.2d] Without FTS5 index, LIKE search returns matching results
11. `test_db_get_stats` — (unit) [1.2e, 1.6] Stats include all required aggregations
12. `test_sync_result_shape` — (unit) [1.3b] Sync result contains success, file_size, article_count, duration
13. `test_fts_index_creation` — (integration) [1.3a] After sync, FTS5 table exists and is queryable
14. `test_api_articles_endpoint` — (integration) [1.4, 1.4a] GET /api/articles returns correct JSON shape
15. `test_api_articles_search` — (integration) [1.4, 1.2d] GET /api/articles?q=drone returns matching articles
16. `test_api_article_detail_endpoint` — (integration) [1.5, 1.5a, 1.5b] GET /api/articles/<id> returns classifier_input and events
17. `test_api_stats_endpoint` — (integration) [1.6, 1.6a, 1.6b] GET /api/stats returns all stat fields
18. `test_api_sync_endpoint` — (integration) [1.7, 1.7a] POST /api/sync triggers sync; GET /api/sync/status returns result
19. `test_classifier_input_reconstruction` — (unit) [1.5a] Classifier input matches expected format from classifier.py
20. `test_api_articles_search_with_filters` — (integration) [1.4c] GET /api/articles?q=drone&pipeline_status=unclassified returns only unclassified articles matching "drone"; explicit sort overrides FTS rank
21. `test_db_tunnel_mode` — (unit) [1.1c, 1.2a] Tunnel mode invokes scp with the correct argv (deploy@178.104.76.254, port 2222, BatchMode=yes, remote /var/lib/sentinel/sentinel.db), opens the temp copy read-only, and removes it on close — subprocess monkeypatched, no real network

### Gate Criteria

- `pip install flask-cors && pip freeze > /dev/null` — Dependency installs successfully
- `python -c "from dashboard.app import create_app; app = create_app(); print('OK')"` — App factory works
- `python -c "from dashboard.db import DashboardDB; print('OK')"` — DB layer imports
- `python -c "from dashboard.sync import sync_db; print('OK')"` — Sync module imports
- `.venv/bin/pytest tests/test_dashboard_api.py tests/test_dashboard_db.py -v` — All tests pass

---

## Phase 2 — React Frontend Foundation

React + Vite setup, article table component with configurable columns, sorting,
filtering, pagination, filter tabs, and keyword search.

### Dependencies on Previous Phases

- Requires Phase 1's Flask API endpoints to be functional (`/api/articles`, `/api/stats`, `/api/sync`)
- The Vite dev server proxies API calls to Flask at port 5001

### Deliverables

- `dashboard/frontend/package.json` — React + Vite + TypeScript project config (create)
- `dashboard/frontend/vite.config.ts` — Vite config with API proxy to Flask (create)
- `dashboard/frontend/tsconfig.json` — TypeScript configuration (create)
- `dashboard/frontend/index.html` — SPA entry point (create)
- `dashboard/frontend/src/main.tsx` — React entry point (create)
- `dashboard/frontend/src/App.tsx` — Root component with routing (create)
- `dashboard/frontend/src/api/client.ts` — API client for Flask backend (create)
- `dashboard/frontend/src/types.ts` — TypeScript interfaces matching API response shapes (create)
- `dashboard/frontend/src/components/ArticleTable.tsx` — Main article table with sorting, pagination (create)
- `dashboard/frontend/src/components/ColumnPicker.tsx` — Column visibility toggle (create)
- `dashboard/frontend/src/components/FilterBar.tsx` — Filter controls (source, language, urgency, date range, pipeline status) (create)
- `dashboard/frontend/src/components/FilterTabs.tsx` — All | Classified | Unclassified tabs (create)
- `dashboard/frontend/src/components/SearchBar.tsx` — Keyword search input with debounce (create)
- `dashboard/frontend/src/components/Pagination.tsx` — Page controls with configurable page size (create)
- `dashboard/frontend/src/components/SyncButton.tsx` — Trigger DB sync from UI (create)
- `dashboard/frontend/src/pages/ArticlesPage.tsx` — Main articles page composing all components (create)
- `dashboard/frontend/src/hooks/useArticles.ts` — Data fetching hook for articles (create)
- `dashboard/frontend/src/styles/index.css` — Global styles (create)

### Requirements

**2.1 — Project Setup:** The React project MUST be created with Vite, React 18+, and
TypeScript. The `vite.config.ts` MUST proxy `/api/*` requests to `http://localhost:5001`.

**2.1a** — `package.json` MUST include scripts: `dev` (start Vite dev server on 5173),
`build` (production build to `dist/`), `preview` (serve production build locally).

**2.1b** — TypeScript interfaces in `types.ts` MUST match the API response shapes defined
in Phase 1 requirements 1.4a, 1.5, and 1.6. Field names MUST be identical.

**2.2 — Article Table:** `ArticleTable` MUST render articles in a table with clickable
column headers for sorting. Clicking a column header MUST toggle sort direction. The
first click of an unsorted column sorts descending (highest value / newest first);
subsequent clicks of the same column alternate between asc and desc. The currently
sorted column MUST show a directional indicator (▲ or ▼); when no column is explicitly
sorted (e.g. when an FTS search controls the ordering), no indicator is shown.

**2.2a** — Default visible columns MUST be: published date, title, source name, language,
urgency score, event type, pipeline status. These defaults MUST be overridable via the
column picker.

**2.2b** — Each table row MUST be expandable by clicking an expand icon. The expanded
section MUST show: full summary text, classification details (if any), source URL as
clickable link, and raw_metadata parsed from JSON.

**2.2c** — Each table row MUST have a clickable title that navigates to the article
detail page at `/articles/<article_id>`.

**2.2d** — Urgency score cells MUST be color-coded: 1-4 gray/neutral, 5-6 yellow/warning,
7-8 orange/high, 9-10 red/critical. Cells with no classification MUST show a dash (—).

**2.2e** — Pipeline status cells MUST show a badge/chip: "Unclassified" (gray),
"Classified" (blue), "Event" (orange), "Alert" (red).

**2.3 — Column Picker:** `ColumnPicker` MUST render a dropdown/popover listing all
available columns with checkboxes. Available columns: published_at, fetched_at, title,
source_name, source_type, source_url, language, urgency_score, event_type, confidence,
aggressor, affected_countries, pipeline_status, summary_pl, is_military_event.

**2.3a** — Column visibility state MUST persist in `localStorage` so the user's
preferences survive page reloads.

**2.4 — Filter Bar:** `FilterBar` MUST provide filter controls for: source name
(multi-select dropdown populated from available sources), source type (dropdown:
all/rss/google_news/telegram), language (dropdown: all/pl/en/uk), urgency range
(min/max number inputs), date range (from/to date pickers), event type (dropdown
populated from available types), has alert (checkbox).

**2.4a** — Changing any filter MUST immediately update the article list (no separate
"Apply" button). Filters MUST be reflected in the URL query string so filtered views
are bookmarkable/shareable.

**2.4b** — A "Clear all filters" button MUST reset all filters to their defaults.

**2.5 — Filter Tabs:** `FilterTabs` MUST render three tabs above the table: "All",
"Classified", "Unclassified". Selecting a tab MUST filter articles by pipeline status.
The active tab MUST show the count of matching articles.

**2.5a** — The "Classified" tab MUST include articles with any pipeline_status other
than "unclassified" (i.e., classified, event_created, alert_sent).

**2.6 — Search Bar:** `SearchBar` MUST provide a text input for keyword search.
Typing MUST trigger a search after a 300ms debounce delay. The search query MUST be
sent as the `q` parameter to the articles API.

**2.6a** — When a search is active, the search bar MUST show a clear (×) button to
reset the search. The current search query MUST be shown in the URL query string.

**2.7 — Pagination:** `Pagination` MUST render page navigation controls: previous/next
buttons, current page number, total pages, and a page size selector (25, 50, 100).

**2.7a** — Page size selection MUST persist in `localStorage`.

**2.7b** — Changing page size MUST reset to page 1.

**2.8 — Sync Button:** `SyncButton` MUST trigger `POST /api/sync` when clicked. It MUST
show a loading spinner during sync. On completion, it MUST display the sync result
(success/failure, article count, duration) and refresh the current view.

**2.8a** — On page load, the sync button MUST show the last sync timestamp (from
`GET /api/sync/status`). If no sync has been performed, it MUST show "No data — click
to sync".

**2.9 — API Client:** `client.ts` MUST provide typed functions for all API endpoints:
`fetchArticles(params)`, `fetchArticleDetail(id)`, `fetchStats()`, `triggerSync()`,
`fetchSyncStatus()`. All functions MUST handle HTTP errors and return typed responses
matching the TypeScript interfaces.

**2.9a** — API errors MUST be surfaced to the user via a toast/notification component,
not silently swallowed.

### Acceptance Tests

1. `test_vite_project_builds` — (e2e) [2.1, 2.1a] `npm run build` in `dashboard/frontend/` succeeds without errors
2. `test_typescript_compiles` — (e2e) [2.1b] `npx tsc --noEmit` passes with no type errors
3. `test_article_table_renders` — (unit) [2.2] ArticleTable renders rows matching provided data
4. `test_column_sorting` — (unit) [2.2] Clicking column header calls sort handler with correct column/direction
5. `test_default_columns` — (unit) [2.2a] Default visible columns match spec
6. `test_expandable_row` — (unit) [2.2b] Clicking expand icon shows classification details
7. `test_urgency_color_coding` — (unit) [2.2d] Urgency cells have correct CSS classes for each range
8. `test_pipeline_status_badges` — (unit) [2.2e] Pipeline status renders correct badge variant
9. `test_column_picker_toggles` — (unit) [2.3] Toggling a column updates table visibility
10. `test_column_picker_persistence` — (unit) [2.3a] Column state saved to and loaded from localStorage
11. `test_filter_bar_updates_query` — (unit) [2.4, 2.4a] Changing a filter updates URL params and triggers fetch
12. `test_filter_clear_all` — (unit) [2.4b] Clear button resets all filters
13. `test_filter_tabs` — (unit) [2.5, 2.5a] Tab selection filters by pipeline status
14. `test_search_debounce` — (unit) [2.6] Search input debounces at 300ms
15. `test_pagination_controls` — (unit) [2.7, 2.7a, 2.7b] Page size change resets to page 1 and persists
16. `test_sync_button_flow` — (unit) [2.8, 2.8a] Sync button shows loading, then result, then refreshes
17. `test_api_client_error_handling` — (unit) [2.9, 2.9a] API client surfaces errors, doesn't swallow them

### Gate Criteria

- `cd dashboard/frontend && npm install` — Dependencies install
- `cd dashboard/frontend && npm run build` — Production build succeeds
- `cd dashboard/frontend && npx tsc --noEmit` — TypeScript compiles without errors
- `cd dashboard/frontend && npx vitest run` — All frontend tests pass

---

## Phase 3 — Analytics Overview & Article Detail Pages

Overview page with pipeline funnel, time series charts, urgency distribution,
source breakdown. Article detail page with side-by-side classifier view.

### Dependencies on Previous Phases

- Requires Phase 1's `/api/stats` and `/api/articles/<id>` endpoints
- Requires Phase 2's routing, API client, and component patterns
- Uses the same TypeScript interfaces from Phase 2

### Deliverables

- `dashboard/frontend/src/pages/OverviewPage.tsx` — Analytics overview page (create)
- `dashboard/frontend/src/pages/ArticleDetailPage.tsx` — Full article detail page (create)
- `dashboard/frontend/src/components/PipelineFunnel.tsx` — Funnel visualization (create)
- `dashboard/frontend/src/components/TimeSeriesChart.tsx` — Articles per day line chart (create)
- `dashboard/frontend/src/components/UrgencyHistogram.tsx` — Urgency score distribution bar chart (create)
- `dashboard/frontend/src/components/SourceBreakdown.tsx` — Source/language breakdown charts (create)
- `dashboard/frontend/src/components/ClassifierView.tsx` — Side-by-side classifier input/output (create)
- `dashboard/frontend/src/components/EventTimeline.tsx` — Event and alert history for an article (create)
- `dashboard/frontend/src/components/StatsCards.tsx` — KPI number cards (create)
- `dashboard/frontend/src/components/ViewToggle.tsx` — Switch between overview modes (create)
- `dashboard/frontend/src/hooks/useStats.ts` — Data fetching hook for stats (create)
- `dashboard/frontend/src/hooks/useArticleDetail.ts` — Data fetching hook for article detail (create)
- `dashboard/frontend/package.json` — Add chart library dependency (modify existing)

### Requirements

**3.1 — Overview Page Layout:** The overview page MUST be the landing page at route `/`.
It MUST display a stats cards row at the top, followed by charts below.

**3.1a** — The overview page MUST support two view modes switchable via `ViewToggle`:
"Pipeline" (funnel + time series) and "Analytics" (urgency histogram + source breakdown
+ language breakdown). The user MUST be able to switch between modes without page reload.

**3.2 — Stats Cards:** `StatsCards` MUST display four KPI cards in a horizontal row:
Total Articles (with daily average), Total Classified (with percentage of total),
Total Events, Total Alerts. Each card MUST show the current number prominently.

**3.3 — Pipeline Funnel:** `PipelineFunnel` MUST render a horizontal or vertical funnel
visualization showing: Collected → Classified → Events Created → Alerts Sent, with
counts and percentage drop-off at each stage.

**3.3a** — Each funnel stage MUST be clickable, navigating to the Articles page filtered
to that pipeline status.

**3.4 — Time Series Chart:** `TimeSeriesChart` MUST render a line chart showing articles
per day for the last 30 days. The x-axis MUST show dates, y-axis MUST show article count.

**3.4a** — The chart SHOULD show two series: total articles collected and articles classified,
so the user can see the filtering ratio over time.

**3.4b** — The chart library MUST be `recharts` (React-native charting, no D3 dependency,
lightweight).

**3.5 — Urgency Histogram:** `UrgencyHistogram` MUST render a bar chart showing the count
of classifications at each urgency score (1-10). Bars MUST use the same color coding as
the table (gray for 1-4, yellow for 5-6, orange for 7-8, red for 9-10).

**3.6 — Source Breakdown:** `SourceBreakdown` MUST render a horizontal bar chart showing
article count per source, sorted by count descending. It MUST also show a smaller chart
or chip group for language distribution (PL/EN/UK percentages).

**3.7 — Article Detail Page:** The article detail page at route `/articles/:id` MUST
display the full article information in a structured layout.

**3.7a** — The page MUST show an article header section with: title, source name (linked
to source URL), published date, fetched date, language badge, pipeline status badge.

**3.7b** — Below the header, the page MUST show the `ClassifierView` component.

**3.7c** — Below the classifier view, the page MUST show the `EventTimeline` component
if the article is linked to any events.

**3.8 — Classifier View:** `ClassifierView` MUST render a side-by-side layout. Left side:
"Classifier Input" showing the reconstructed text sent to Claude (from `classifier_input`
field). Right side: "Classifier Output" showing urgency score (color-coded), event type,
confidence (as percentage), affected countries, aggressor, summary_pl, is_military_event,
is_new_event, model used, token counts.

**3.8a** — A toggle button labeled "Raw JSON" MUST switch the output side to show the
raw classification JSON (all fields as formatted JSON). Default view is the formatted
display.

**3.8b** — If the article has no classification (was filtered out), the ClassifierView
MUST show a message: "This article was not classified (filtered out before classification
stage)" with a gray background.

**3.9 — Event Timeline:** `EventTimeline` MUST show a vertical timeline of events linked
to this article, each showing: event type, urgency score, alert status badge, source
count, first seen / last updated timestamps. For each event, it MUST list its alert
records with: alert type (SMS/call/WhatsApp icon), status, sent timestamp, and attempt
number.

**3.9a** — If the article is not linked to any events, the section MUST show
"No events — article did not trigger event creation."

**3.10 — Navigation:** The overview page MUST have a navigation link to the Articles
page. The articles page MUST have a link back to the overview. The article detail page
MUST have a "Back to articles" link that preserves the previous filter/sort/page state.

### Acceptance Tests

1. `test_overview_page_renders` — (unit) [3.1] Overview page renders stats cards and charts
2. `test_view_toggle_switches` — (unit) [3.1a] ViewToggle switches between Pipeline and Analytics modes
3. `test_stats_cards_display` — (unit) [3.2] StatsCards shows four KPIs with correct values
4. `test_pipeline_funnel_counts` — (unit) [3.3] Funnel shows correct counts at each stage
5. `test_funnel_stage_navigation` — (unit) [3.3a] Clicking a funnel stage navigates to filtered articles
6. `test_time_series_renders` — (unit) [3.4, 3.4a] TimeSeriesChart renders with two series
7. `test_urgency_histogram_colors` — (unit) [3.5] Histogram bars use correct colors per urgency range
8. `test_source_breakdown_sorted` — (unit) [3.6] Sources sorted by count descending
9. `test_article_detail_header` — (unit) [3.7a] Detail page shows title, source, dates, badges
10. `test_classifier_view_side_by_side` — (unit) [3.8] Left side shows input, right side shows output
11. `test_classifier_view_raw_json_toggle` — (unit) [3.8a] Toggle switches to raw JSON view
12. `test_classifier_view_unclassified` — (unit) [3.8b] Unclassified articles show appropriate message
13. `test_event_timeline_with_alerts` — (unit) [3.9] Timeline shows events and their alert records
14. `test_event_timeline_empty` — (unit) [3.9a] No-events message shown when article has none
15. `test_navigation_back_preserves_state` — (unit) [3.10] Back link preserves previous filter state

### Gate Criteria

- `cd dashboard/frontend && npm run build` — Production build succeeds with new pages
- `cd dashboard/frontend && npx tsc --noEmit` — TypeScript compiles without errors
- `cd dashboard/frontend && npx vitest run` — All frontend tests pass (Phases 2 + 3)

---

## Phase 4 — Annotation System

Local annotation database for labeling articles with correctness judgments, expected
urgency scores, and free-text notes. Annotations persist in a separate SQLite file
that is independent of production DB syncs.

### Dependencies on Previous Phases

- Requires Phase 1's database layer and Flask API
- Requires Phase 2's article table (adds annotation indicators)
- Requires Phase 3's article detail page (adds annotation panel)

### Deliverables

- `dashboard/annotations.py` — Annotation database layer: create, read, update, list (create)
- `dashboard/api/annotations.py` — Annotation API endpoints (create)
- `dashboard/frontend/src/components/AnnotationPanel.tsx` — Annotation form and display (create)
- `dashboard/frontend/src/components/AnnotationBadge.tsx` — Inline badge for article table (create)
- `dashboard/frontend/src/hooks/useAnnotations.ts` — Annotation data hooks (create)
- `dashboard/frontend/src/types.ts` — Add annotation types (modify existing)
- `dashboard/frontend/src/components/ArticleTable.tsx` — Add annotation column/badge (modify existing)
- `dashboard/frontend/src/pages/ArticleDetailPage.tsx` — Add annotation panel (modify existing)
- `dashboard/api/articles.py` — Include annotation data in article responses (modify existing)
- `dashboard/db.py` — Add annotation DB connection management (modify existing)
- `tests/test_dashboard_annotations.py` — Annotation API and DB tests (create)

### Requirements

**4.1 — Annotation Database:** `dashboard/annotations.py` MUST manage a separate SQLite
database at `dashboard/data/annotations.db` with a single table:

```sql
CREATE TABLE annotations (
    id TEXT PRIMARY KEY,                -- UUID
    article_id TEXT NOT NULL UNIQUE,    -- References articles(id) in sentinel DB
    label TEXT NOT NULL,                -- "correct" | "incorrect" | "uncertain"
    expected_urgency INTEGER,           -- 1-10, nullable (user's assessment)
    notes TEXT,                         -- Free-text notes, nullable
    created_at TEXT NOT NULL,           -- ISO 8601 UTC
    updated_at TEXT NOT NULL            -- ISO 8601 UTC
);
```

**4.1a** — The annotation database MUST be created automatically on first access if it
does not exist.

**4.1b** — The `article_id` column MUST have a UNIQUE constraint — one annotation per
article. Updating an annotation MUST use upsert semantics (INSERT OR REPLACE).

**4.2 — Annotation API:** `POST /api/annotations` MUST accept JSON body:
```json
{
  "article_id": "uuid",
  "label": "correct",
  "expected_urgency": 5,
  "notes": "Seems correctly classified but urgency should be higher"
}
```
and create or update the annotation, returning the saved annotation with its `id`,
`created_at`, and `updated_at`.

**4.2a** — `GET /api/annotations/<article_id>` MUST return the annotation for the given
article, or HTTP 404 if no annotation exists.

**4.2b** — `GET /api/annotations` MUST return all annotations with pagination, supporting
`?label=correct` filter and `?sort=updated_at` sorting. The response MUST include the
article's title and classification urgency for context (joined from the sentinel DB).

**4.2c** — `DELETE /api/annotations/<article_id>` MUST delete the annotation and return
HTTP 204.

**4.2d** — The `label` field MUST be validated: only "correct", "incorrect", or "uncertain"
are accepted. Invalid values MUST return HTTP 400 with `{"error": "Invalid label"}`.

**4.2e** — The `expected_urgency` field MUST be validated: only integers 1-10 or null
are accepted. Out-of-range values MUST return HTTP 400.

**4.3 — Annotation Panel:** `AnnotationPanel` on the article detail page MUST render
below or beside the classifier view. It MUST show a form with: label selector (three
buttons: Correct ✓, Incorrect ✗, Uncertain ?), expected urgency slider or number input
(1-10), and a notes textarea.

**4.3a** — If an annotation already exists for the article, the form MUST be pre-filled
with the existing values. A "Last updated" timestamp MUST be shown.

**4.3b** — Submitting the form MUST save via `POST /api/annotations` and show a success
confirmation. The form MUST remain on screen (no navigation away).

**4.3c** — A "Delete annotation" button MUST be shown only when an annotation exists.
Clicking it MUST confirm with the user before deleting.

**4.4 — Annotation Badge in Table:** The article table MUST show an annotation indicator
column. Articles with annotations MUST show a small colored badge: green dot for
"correct", red dot for "incorrect", yellow dot for "uncertain". Articles without
annotations MUST show no badge.

**4.4a** — The annotation badge column MUST be included in the default visible columns.

**4.5 — Annotation-Aware Article API:** The articles list API (`GET /api/articles`) MUST
include an `annotation` field in each article object (null if no annotation exists,
otherwise `{label, expected_urgency, notes}`).

**4.5a** — The articles API MUST support filtering by annotation status: `has_annotation`
(boolean) and `annotation_label` ("correct", "incorrect", "uncertain") query parameters.

**4.6 — Annotation Stats:** The `GET /api/stats` endpoint MUST include annotation
statistics: total annotated, count by label (correct/incorrect/uncertain), and average
urgency deviation (absolute difference between `classification.urgency_score` and
`annotation.expected_urgency` for articles that have both).

### Acceptance Tests

1. `test_annotation_db_auto_create` — (unit) [4.1, 4.1a] Database and table created on first access
2. `test_annotation_upsert` — (unit) [4.1b] Creating annotation twice for same article updates instead of duplicating
3. `test_create_annotation` — (integration) [4.2] POST /api/annotations creates and returns annotation
4. `test_get_annotation` — (integration) [4.2a] GET /api/annotations/<id> returns existing annotation
5. `test_get_annotation_404` — (integration) [4.2a] GET returns 404 for non-existent annotation
6. `test_list_annotations_with_filter` — (integration) [4.2b] GET /api/annotations?label=incorrect returns filtered list
7. `test_delete_annotation` — (integration) [4.2c] DELETE removes annotation, returns 204
8. `test_annotation_label_validation` — (integration) [4.2d] Invalid label returns 400
9. `test_annotation_urgency_validation` — (integration) [4.2e] Out-of-range urgency returns 400
10. `test_annotation_panel_prefill` — (unit) [4.3a] Panel pre-fills with existing annotation values
11. `test_annotation_badge_colors` — (unit) [4.4] Badge shows correct color for each label
12. `test_articles_include_annotation` — (integration) [4.5] Articles API includes annotation field
13. `test_articles_filter_by_annotation` — (integration) [4.5a] Filter by has_annotation and annotation_label works
14. `test_annotation_stats` — (integration) [4.6] Stats include annotation counts and urgency deviation

### Gate Criteria

- `python -c "from dashboard.annotations import AnnotationDB; print('OK')"` — Annotation DB imports
- `.venv/bin/pytest tests/test_dashboard_annotations.py -v` — All annotation tests pass
- `.venv/bin/pytest tests/test_dashboard_api.py tests/test_dashboard_db.py tests/test_dashboard_annotations.py -v` — Full backend test suite passes
- `cd dashboard/frontend && npm run build` — Frontend builds with annotation components
- `cd dashboard/frontend && npx tsc --noEmit` — TypeScript compiles without errors
- `cd dashboard/frontend && npx vitest run` — All frontend tests pass
