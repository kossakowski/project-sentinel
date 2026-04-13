# Project Sentinel — Implementation Phases

> **All 7 phases complete. System is in production on Hetzner VPS.**
> These specs reflect original design intent; see [architecture.md](architecture.md) for current implementation.

## Phase Status Table

| Phase | Status | Files Created | Key Classes / Functions | Test File |
|-------|--------|---------------|------------------------|-----------|
| 1: Infrastructure | COMPLETE | `sentinel/config.py`, `sentinel/database.py`, `sentinel/models.py`, `sentinel.py`, `config/config.example.yaml` | `SentinelConfig`, `Database`, `Article`, `ClassificationResult`, `Event`, `AlertRecord` | `tests/test_config.py`, `tests/test_database.py`, `tests/test_models.py`, `tests/test_cli.py` |
| 2: Source Fetchers | COMPLETE | `sentinel/fetchers/base.py`, `sentinel/fetchers/rss.py`, `sentinel/fetchers/gdelt.py`, `sentinel/fetchers/google_news.py`, `sentinel/fetchers/telegram.py` | `BaseFetcher`, `RSSFetcher`, `GDELTFetcher`, `GoogleNewsFetcher`, `TelegramFetcher` | `tests/test_rss.py`, `tests/test_gdelt.py`, `tests/test_google_news.py`, `tests/test_telegram.py` |
| 3: Processing Pipeline | COMPLETE | `sentinel/processing/normalizer.py`, `sentinel/processing/deduplicator.py`, `sentinel/processing/keyword_filter.py` | `Normalizer`, `Deduplicator`, `KeywordFilter` | `tests/test_normalizer.py`, `tests/test_deduplicator.py`, `tests/test_keyword_filter.py` |
| 4: Classification Engine | COMPLETE | `sentinel/classification/classifier.py`, `sentinel/classification/corroborator.py` | `Classifier`, `Corroborator` | `tests/test_classifier.py`, `tests/test_corroborator.py` |
| 5: Alert System | COMPLETE | `sentinel/alerts/dispatcher.py`, `sentinel/alerts/twilio_client.py`, `sentinel/alerts/state_machine.py` | `AlertDispatcher`, `TwilioClient`, `AlertStateMachine` | `tests/test_twilio_client.py`, `tests/test_state_machine.py`, `tests/test_dispatcher.py` |
| 6: Scheduler & Integration | COMPLETE | `sentinel/scheduler.py`, `sentinel.py` (full CLI) | `SentinelPipeline`, `SentinelScheduler` | `tests/test_integration.py`, `tests/test_scheduler.py` |
| 7: Deployment | COMPLETE | `deploy/sentinel.service`, `deploy/logrotate.conf` | systemd unit, cron health check | manual acceptance criteria (see spec) |

## Key Design Decisions

- **Dual-lane scheduler:** fast lane every 3 min (Telegram + Google News + priority-1 RSS), slow lane every 15 min (all sources including GDELT). Implemented in `SentinelScheduler`.
- **Corroboration required for phone calls:** 2+ independent sources must confirm an event (urgency ≥ 9) before a phone call is placed. Single-source critical events trigger SMS only.
- **No DTMF confirmation:** call acknowledgment uses an SMS 6-digit reply code, not DTMF keypresses (voicemail causes false positives).
- **Claude Haiku 4.5** (`claude-haiku-4-5-20251001`) used for classification — cost-efficient for continuous polling.
- **Everything configurable:** keywords, sources, thresholds, URLs all live in `config/config.yaml`. Nothing hardcoded.
- **Keyword pre-filter before LLM:** articles pass through `KeywordFilter` first; only ~5-20 per cycle reach the classifier, keeping API costs low.

## Phase Specs (historical)

- [Phase 1: Infrastructure](phase-1-infrastructure.md)
- [Phase 2: Source Fetchers](phase-2-fetchers.md)
- [Phase 3: Processing Pipeline](phase-3-processing.md)
- [Phase 4: Classification Engine](phase-4-classification.md)
- [Phase 5: Alert System](phase-5-alerts.md)
- [Phase 6: Scheduler & Integration](phase-6-scheduler.md)
- [Phase 7: Deployment](phase-7-deployment.md)
