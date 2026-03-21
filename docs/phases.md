# Project Sentinel -- Implementation Phases

## Overview

The system is built in 7 phases. Each phase has clear deliverables, acceptance tests, and must be fully tested before the next phase begins. Phases are designed so each can be implemented by an independent agent team.

## Phase Dependency Graph

```
Phase 1: Infrastructure ─────────────────────────────────┐
    │                                                     │
    ├──► Phase 2: Source Fetchers                         │
    │        │                                            │
    │        ▼                                            │
    ├──► Phase 3: Processing Pipeline                     │
    │        │                                            │
    │        ▼                                            │
    ├──► Phase 4: Classification Engine                   │
    │        │                                            │
    │        ▼                                            │
    └──► Phase 5: Alert System ◄──────────────────────────┘
             │
             ▼
         Phase 6: Scheduler & Integration
             │
             ▼
         Phase 7: Deployment
```

## Phase Summary

### Phase 1: Infrastructure
**Goal:** Project skeleton, config system, database, logging, CLI framework.
**Deliverables:** `sentinel/config.py`, `sentinel/database.py`, `sentinel/models.py`, `sentinel.py` (CLI entry point), `config/config.example.yaml`.
**Tests:** Config loads and validates, DB schema creates correctly, models serialize/deserialize, CLI parses arguments.
**Spec:** [phase-1-infrastructure.md](phase-1-infrastructure.md)

### Phase 2: Source Fetchers
**Goal:** Fetch articles from all configured sources: RSS, GDELT, Google News, Telegram.
**Deliverables:** `sentinel/fetchers/rss.py`, `sentinel/fetchers/gdelt.py`, `sentinel/fetchers/google_news.py`, `sentinel/fetchers/telegram.py`.
**Tests:** Each fetcher returns valid Article objects from real sources (live integration tests) and from fixtures (unit tests).
**Spec:** [phase-2-fetchers.md](phase-2-fetchers.md)
**Depends on:** Phase 1 (models, config)

### Phase 3: Processing Pipeline
**Goal:** Normalize, deduplicate, and keyword-filter articles from all fetchers.
**Deliverables:** `sentinel/processing/normalizer.py`, `sentinel/processing/deduplicator.py`, `sentinel/processing/keyword_filter.py`.
**Tests:** Normalizer handles all fetcher output formats, deduplicator correctly identifies duplicates by URL and fuzzy title, keyword filter matches expected articles in all 4 languages and excludes false positives.
**Spec:** [phase-3-processing.md](phase-3-processing.md)
**Depends on:** Phase 1 (models, DB), Phase 2 (fetcher output format)

### Phase 4: Classification Engine
**Goal:** Classify pre-filtered articles using Claude Haiku 4.5, score urgency, and detect corroboration across sources.
**Deliverables:** `sentinel/classification/classifier.py`, `sentinel/classification/corroborator.py`.
**Tests:** Sample headlines are classified with expected urgency scores (using test fixtures). Corroborator correctly groups articles about the same event from different sources. Dry-run mode logs classifications without triggering alerts.
**Spec:** [phase-4-classification.md](phase-4-classification.md)
**Depends on:** Phase 1 (models, DB), Phase 3 (filtered articles)

### Phase 5: Alert System
**Goal:** Dispatch alerts via Twilio (phone call, SMS, WhatsApp) based on urgency score, manage call state and retries, prevent alert spam.
**Deliverables:** `sentinel/alerts/dispatcher.py`, `sentinel/alerts/twilio_client.py`, `sentinel/alerts/state_machine.py`.
**Tests:** Alert dispatcher routes to correct channel by score. Call state machine handles all transitions (answered, no-answer, retry, fallback). Twilio client sends calls/SMS/WhatsApp correctly (tested with Twilio test credentials). Cooldown prevents repeated calls for same event.
**Spec:** [phase-5-alerts.md](phase-5-alerts.md)
**Depends on:** Phase 1 (models, DB, config), Phase 4 (classification output)

### Phase 6: Scheduler & Integration
**Goal:** Wire all components together, run the full pipeline on a 15-minute schedule, handle errors gracefully.
**Deliverables:** `sentinel/scheduler.py`, updated `sentinel.py` (full CLI).
**Tests:** Full end-to-end pipeline runs with test data. Scheduler fires at correct intervals. Errors in one fetcher don't crash the pipeline. Health check reports component status. Dry-run mode works end-to-end.
**Spec:** [phase-6-scheduler.md](phase-6-scheduler.md)
**Depends on:** All previous phases

### Phase 7: Deployment
**Goal:** Deploy to Hetzner VPS with systemd, configure monitoring, set up log rotation.
**Deliverables:** `deploy/sentinel.service` (systemd unit), `deploy/logrotate.conf`, deployment documentation.
**Tests:** Service starts on boot, auto-restarts on crash, logs rotate correctly, health check endpoint responds.
**Spec:** [phase-7-deployment.md](phase-7-deployment.md)
**Depends on:** Phase 6

## Testing Philosophy

1. **Each phase has its own test suite** in `tests/`.
2. **Unit tests** use mocked dependencies (no network, no API calls).
3. **Integration tests** hit real APIs (marked with `@pytest.mark.integration` so they can be skipped in CI).
4. **A phase is not complete until all its tests pass.**
5. **Dry-run mode** allows the full pipeline to run without triggering any Twilio calls.
6. **Test headline mode** allows feeding specific headlines to see how the system classifies them.
7. **Test fixtures** (`tests/fixtures/test_headlines.yaml`) contain known headlines with expected urgency scores, used for regression testing.

## Estimated Effort Per Phase

| Phase | Complexity | Approximate Scope |
|---|---|---|
| 1. Infrastructure | Low | Config loader, DB schema, models, CLI skeleton |
| 2. Fetchers | Medium | 4 fetcher implementations, HTTP handling, Telegram auth |
| 3. Processing | Low-Medium | Normalization, dedup logic, keyword matching |
| 4. Classification | Medium | LLM prompt engineering, corroboration logic |
| 5. Alerts | Medium | Twilio integration, state machine, retry logic |
| 6. Integration | Medium | Wiring, scheduler, error handling, E2E tests |
| 7. Deployment | Low | VPS setup, systemd, monitoring |
