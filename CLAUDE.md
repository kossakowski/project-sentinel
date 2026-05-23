# Project Sentinel -- Military Alert Monitoring System

## Overview
Real-time monitoring bot that scans media sources (PL/EN/UA/RU) for military attacks or invasions targeting Poland and the Baltic states, and alerts via Twilio phone call. **The application is running in production on a Hetzner VPS** — see [Server Runbook](docs/server-runbook.md) for access, operations, and troubleshooting.

A separate read-only **Article Dashboard** subsystem lives under `dashboard/` (local-only Flask backend + React/Vite/TS frontend over the production SQLite DB, accessed via SCP sync or SSH-tunnel fresh-fetch). It is not part of the monitoring runtime — see [Dashboard Spec](SPEC.md).

## Documentation
- [Architecture](docs/architecture.md) -- system design, data flow, components
- [Pipeline Reference](docs/pipeline.md) -- step-by-step data flow from source collection to phone alert
- [Implementation Phases](docs/phases.md) -- 7-phase build plan with test gates
- [Configuration Reference](docs/config-reference.md) -- every configurable parameter
- [Testing Strategy](docs/testing.md) -- dry run, fixtures, manual testing
- [VPS Security Hardening](docs/security/vps-hardening.md) -- do this BEFORE deployment
- [API Setup Guide](docs/api-setup.md) -- Anthropic, Twilio, Telegram account setup
- [Media Sources Reference](docs/sources.md) -- all monitored sources with URLs/RSS
- [Server Runbook](docs/server-runbook.md) -- production server access, file layout, service management, deployment, troubleshooting. **Read this first for anything server-related.**
- [Dashboard Spec](SPEC.md) -- source of truth for the `dashboard/` subsystem (Phases 1 backend + 2 frontend foundation + 3 analytics/detail pages + 4 annotations complete; later phases spec'd but not yet implemented)

## Quick Reference
- Config: `config/config.yaml` (see `config/config.example.yaml`)
- Run: `./run.sh` (auto-activates venv, forwards all args to `sentinel.py`)
- Run once: `./run.sh --once` (single pipeline cycle, then exit)
- Dry run: `./run.sh --dry-run`
- Continuous dry run: `./run.sh --dry-run` (dual-lane scheduler, no Twilio calls; fast every 3 min, slow every 15 min)
- Test single headline: `./run.sh --test-headline "headline text here"`
- Test headlines file: `./run.sh --test-file tests/fixtures/test_headlines.yaml`
- Test alert: `./run.sh --test-alert` (fire real phone call via Twilio with fake event)
- Test alert SMS: `./run.sh --test-alert sms` (fire real SMS instead of phone call)
- Test alert WhatsApp: `./run.sh --test-alert whatsapp` (fire real WhatsApp instead)
- Diagnostic: `./run.sh --diagnostic` (single cycle, generates `data/diagnostic.html` with all articles)
- Custom config: `./run.sh --config path/to/config.yaml`
- Log level: `./run.sh --log-level DEBUG` (DEBUG, INFO, WARNING, ERROR)
- Health check: `./run.sh --health` (prints `data/health.json`)
- Tests: `.venv/bin/pytest tests/ -v`

## Dashboard (separate subsystem -- local only)
Read-only Flask API + React/Vite/TypeScript frontend over the production SQLite DB. Runs on your local machine; never deployed. See [SPEC.md](SPEC.md) for the full reference.

**Backend (Flask API):**
- Launch: `./dashboard/run-dashboard.sh` (auto-activates venv, forwards args to `python -m dashboard`)
- Sync DB from production then start: `./dashboard/run-dashboard.sh --sync`
- Tunnel mode (SCP-fresh-fetch at startup, LIKE-only search): `./dashboard/run-dashboard.sh --tunnel`
- Custom port (default `5001`): `./dashboard/run-dashboard.sh --port 5005`
- Custom DB path: `./dashboard/run-dashboard.sh --db path/to/sentinel.db`
- Backend tests: `.venv/bin/pytest tests/test_dashboard_api.py tests/test_dashboard_db.py tests/test_dashboard_annotations.py -v`

**Frontend (React/Vite/TS at `dashboard/frontend/`):**
- Install once: `cd dashboard/frontend && npm install`
- Dev server (proxies `/api/*` to Flask on `:5001`): `cd dashboard/frontend && npm run dev` — opens on `:5173`
- Production build into `dashboard/frontend/dist/` (served by Flask when present): `cd dashboard/frontend && npm run build`
- Type-check only: `cd dashboard/frontend && npx tsc --noEmit`
- Frontend tests (vitest + jsdom): `cd dashboard/frontend && npx vitest run`

Routes: `/` Overview (analytics landing — KPI cards, pipeline funnel, time-series, urgency histogram, source breakdown), `/articles` (filterable article list, Phase 2), `/articles/:id` (article detail with side-by-side classifier view + event timeline + annotation panel). Charts use `recharts`; full route + component map in [docs/architecture.md §10](docs/architecture.md).

**Annotations (Phase 4):** User labels (correct / incorrect / uncertain), expected-urgency overrides, and free-text notes live in a SEPARATE local SQLite file at `dashboard/data/annotations.db` so production-DB syncs cannot overwrite labelling work. Four endpoints — `POST /api/annotations` (upsert), `GET /api/annotations` (paginated list with `?label` filter), `GET /api/annotations/<article_id>` (404 on miss), `DELETE /api/annotations/<article_id>` (idempotent 204) — and the article-list response carries a narrow `annotation` field (`{label, expected_urgency, notes}`, or null) joined via cross-DB ATTACH. The article table renders an annotation column (coloured dot per label) in the rightmost default position; the article detail page mounts an `AnnotationPanel` below the classifier view + event timeline. `GET /api/stats.annotation_stats` adds `{total, by_label, average_urgency_deviation}`.

Typical local workflow: run Flask backend in one terminal (`./dashboard/run-dashboard.sh`), Vite dev server in another (`npm run dev`), and open `http://localhost:5173`. For a single-process production-style run, `npm run build` first, then start the Flask backend — it serves `dist/` at `/`.

## Known Issue: Project Rename History
This project was renamed twice (`twilio-playground` → `sentinel` → `project-sentinel`). If imports fail with paths to old names like `twilio-plaground` or `sentinel`, recreate the venv: `rm -rf .venv && python -m venv .venv && pip install -r requirements.txt` and clear `__pycache__` dirs.

## Production Server Policy
- **SSH access:** `ssh -p 2222 deploy@178.104.76.254` — **always use `deploy@`**, never `root@` or `kossa@`. Wrong usernames trigger fail2ban bans.
- **NEVER modify files on the production server** unless the user explicitly asks for it.
- If a task requires changing server files (deploy, config update, etc.), **ask the user for permission first** — do not do it autonomously.
- Run and test code **locally** by default. Use local env vars for Twilio/API credentials when testing.
- The only exception is read-only commands (checking logs, health, DB queries) which are safe to run on the server.

## Development Rules
- **Nothing is hardcoded.** All keywords, sources, countries, thresholds, and URLs live in `config/config.yaml`.
- **Every phase must pass its tests** before starting the next phase.
- **Alerts are in Polish.** Source scanning covers PL, EN, UA, RU.
- **Use Claude Haiku 4.5** (`claude-haiku-4-5-20251001`) for classification -- cost-efficient.
- **No quiet hours.** This is a critical alert system -- call at any hour.
- **Don't spam.** Call once per event, then switch to SMS for updates. WhatsApp is plumbed but disabled in production (see `state_machine.py:190`).
- **Corroboration required.** Phone calls require independent source corroboration (configured via `classification.corroboration_required`; live value is `1`).
- **Corroboration window: 6h default.** Configurable via `classification.corroboration_window_minutes` (default 360 in code, live config still `60`). Similarity thresholds also tunable: `classification.summary_similarity_threshold` (default 40) and `classification.syndication_similarity_threshold` (default 90).
- Config format: YAML. Database: SQLite. Scheduler: APScheduler (dual-lane: fast lane every 3 min for Telegram + priority-1 RSS + Google News, slow lane every 15 min for all sources including GDELT).
