# Dashboard subsystem (local-only, read-only)

Read-only Flask API + React/Vite/TypeScript frontend over the **production** SQLite DB. Runs on
your local machine; **never deployed** and not part of the monitoring runtime. Source of truth for
this subsystem: [`../SPEC.md`](../SPEC.md). Architecture + full route/component map:
[`../docs/explanation/architecture.md`](../docs/explanation/architecture.md).

The API is a Flask **blueprint package** under `dashboard/api/` (articles, events, stats, sync,
annotations), with `cli.py`, `config.py`, `db.py`, `sync.py`, `annotations.py`, and
`classifier_input.py` modules — not a single `api.py`.

## Backend (Flask API)
- Launch: `./dashboard/run-dashboard.sh` (venv-bootstrap wrapper → `python -m dashboard`)
- Sync DB from production then start: `--sync` (SCP + rebuild FTS5 index)
- Tunnel mode (one SCP fresh-fetch at startup; LIKE-only search, no FTS): `--tunnel`
- Custom port (default `5001`): `--port 5005` · custom DB: `--db path/to/sentinel.db`
- Tests: `.venv/bin/pytest tests/test_dashboard_api.py tests/test_dashboard_db.py tests/test_dashboard_annotations.py -v`

## Frontend (`dashboard/frontend/`)
- Install once: `npm install` · dev server (proxies `/api/*` to Flask `:5001`, opens `:5173`): `npm run dev`
- Build into `dist/` (Flask serves it at `/` when present): `npm run build` · type-check: `npx tsc --noEmit`
- Tests (vitest + jsdom): `npx vitest run`
- Typical workflow: Flask in one terminal, `npm run dev` in another, open `http://localhost:5173`.

Routes: `/` Overview (KPI cards, pipeline funnel, time-series, urgency histogram, source breakdown),
`/articles` (filterable list), `/articles/:id` (classifier view + event timeline + annotation panel),
`/events/:id` (event detail: metadata header + article list + alert timeline). Charts use `recharts`.

## Annotations (Phase 4)
User labels (correct / incorrect / uncertain), expected-urgency overrides, and notes live in a
SEPARATE local SQLite file `dashboard/data/annotations.db` so production-DB syncs can't overwrite
labelling work. Endpoints: `POST /api/annotations` (upsert), `GET /api/annotations` (paginated,
`?label` filter), `GET /api/annotations/<article_id>` (404 on miss), `DELETE` (idempotent 204). The
article-list rows carry a narrow `annotation` field joined via cross-DB ATTACH; `GET /api/stats`
adds `annotation_stats`.

## Event grouping (dashboard side)
Every article-list row carries an `event_id` (the retained event whose `article_ids` JSON contains
it, or null), via a correlated subquery scoped to the last `EVENT_ID_RETENTION_DAYS` days — a
**dashboard-side code constant in `dashboard/db.py` (default 30), NOT a `config/config.yaml` key**;
override via `DashboardDB(event_id_retention_days=…)` or `app.config["EVENT_ID_RETENTION_DAYS"]`. The
article table does a single-pass visual grouping over consecutive same-event rows (chevron +
member-count linking to `/events/<id>`; continuation rows get faded background + coloured left
border). `GET /api/events/<event_id>` returns `{event, articles[], alert_records[]}` (404 on unknown id).

The implemented event-grouping spec is archived at
[`../docs/archive/SPEC_ALERT_GROUPING.md`](../docs/archive/SPEC_ALERT_GROUPING.md) (historic;
current behaviour is in `../SPEC.md` and the architecture doc). Source comments cite it by name.

## Datetime
Store UTC, render Europe/Warsaw. Util surfaces: `dashboard/frontend/src/utils/datetime.ts` (and the
runtime's `sentinel/utils/datetime.py`).
