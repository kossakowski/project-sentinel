# Project Sentinel -- System Architecture

## 1. System Purpose

Project Sentinel is an automated early-warning system that continuously monitors media sources across multiple languages (Polish, English, Ukrainian, Russian) for signals of military attacks or invasions targeting Poland and the Baltic states (Lithuania, Latvia, Estonia) by Russia, Belarus, or their allies.

When a credible threat is detected, Project Sentinel calls the user's phone immediately (any hour), speaks the alert in Polish, and follows up with SMS/WhatsApp for ongoing updates.

## 2. High-Level Data Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    SCHEDULER (APScheduler)                   │
│          Fast lane: every 3 min (Telegram, Google            │
│          News, priority-1 RSS)                               │
│          Slow lane: every 15 min (all sources incl. GDELT)   │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│                    SOURCE FETCHERS                           │
│                                                             │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────────┐  │
│  │ RSS      │ │ GDELT    │ │ Google   │ │ Telegram      │  │
│  │ Feeds    │ │ API      │ │ News RSS │ │ Channels      │  │
│  │ (PAP,    │ │ (DOC 2.0)│ │ (keyword │ │ (UA Air Force,│  │
│  │  TVN24,  │ │          │ │  feeds)  │ │  NEXTA, etc.) │  │
│  │  RMF24,  │ │          │ │          │ │               │  │
│  │  ERR...) │ │          │ │          │ │               │  │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └──────┬────────┘  │
│       │             │            │               │           │
└───────┼─────────────┼────────────┼───────────────┼──────────┘
        │             │            │               │
        └─────────────┼────────────┼───────────────┘
                      │            │
                      ▼            ▼
┌─────────────────────────────────────────────────────────────┐
│                 PROCESSING PIPELINE                          │
│                                                             │
│  1. Normalize ──► 2. Deduplicate ──► 3. Keyword Pre-filter  │
│     (extract       (URL hash +        (bilingual keyword    │
│      title,         title fuzzy        match in PL/EN/UA/RU │
│      source,        match via          + negative keyword   │
│      timestamp,     rapidfuzz +        exclusion)           │
│      language)      SQLite)                                 │
│                                                             │
└─────────────────────────────┬───────────────────────────────┘
                              │
                   Only articles matching
                   military/conflict keywords
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                CLASSIFICATION ENGINE                         │
│                                                             │
│  Claude Haiku 4.5 via Anthropic API                         │
│                                                             │
│  Input: article title + summary + source metadata           │
│  Output:                                                    │
│    - is_military_event: bool                                │
│    - event_type: invasion | airstrike | missile_strike |    │
│                  border_crossing | airspace_violation |     │
│                  naval_blockade | cyber_attack | other      │
│    - urgency_score: 1-10                                    │
│    - affected_countries: [list]                             │
│    - aggressor: string                                      │
│    - is_new_event: bool (vs. ongoing coverage)              │
│    - confidence: 0.0-1.0                                    │
│    - summary_pl: string (Polish-language summary)           │
│                                                             │
│  Corroboration check:                                       │
│    - Count independent sources reporting same event         │
│    - Independence checked across ALL source types            │
│    - Title similarity (>=90%) + domain match detects         │
│      syndication (prevents false triggers)                  │
│    - Require 2+ independent sources for phone call trigger  │
│                                                             │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    ALERT ROUTER                              │
│                                                             │
│  Score 9-10 (CRITICAL): ──► Twilio PHONE CALL (Polish TTS) │
│    invasion, active attack     + SMS with details           │
│    2+ sources confirmed        + event logged               │
│                                                             │
│  Score 7-8 (HIGH): ──────► Twilio SMS                       │
│    major escalation,           + event logged               │
│    significant incident                                     │
│                                                             │
│  Score 5-6 (MEDIUM): ────► WhatsApp message                 │
│    concerning development      + event logged               │
│                                                             │
│  Score 1-4 (LOW): ───────► Log only                         │
│    routine military news       (database record)            │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ CALL STATE MACHINE                                    │  │
│  │                                                       │  │
│  │ WhatsApp 6-digit confirmation code sent before calls  │  │
│  │                                                       │  │
│  │ NEW ──► CALL_PLACED ──► CHECK_STATUS                  │  │
│  │                             │                         │  │
│  │              ┌──────────────┼──────────────┐          │  │
│  │              ▼              ▼              ▼          │  │
│  │     WHATSAPP_CONFIRMED  NO_ANSWER    NO_ANSWER       │  │
│  │              │              │              │          │  │
│  │              ▼              ▼              ▼          │  │
│  │        ACKNOWLEDGED    RETRY (up to 5)  RETRY_PENDING│  │
│  │                             │              │          │  │
│  │                             ▼              ▼          │  │
│  │                       RETRY_PENDING   SMS_FALLBACK    │  │
│  │                                                       │  │
│  │ Calls: up to 5 attempts (max_call_retries), 10s apart│  │
│  │ After each call: check WhatsApp for correct code      │  │
│  │ Code received → ACKNOWLEDGED, follow-up SMS + links   │  │
│  │ All calls exhausted → RETRY_PENDING, retry after      │  │
│  │   retry_interval_minutes (default 5)                  │  │
│  │ After acknowledgment: cooldown (6h), SMS updates only │  │
│  └──────────────────────────────────────────────────────┘   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## 3. Component Overview

| Component | Responsibility | Key Dependencies |
|---|---|---|
| **Config Loader** | Load and validate `config/config.yaml` | `pyyaml`, `pydantic` |
| **Database** | Store articles, events, alert state | `sqlite3` (stdlib) |
| **RSS Fetcher** | Poll RSS feeds from configured sources (concurrently via `asyncio.gather()`) | `feedparser`, `httpx` |
| **GDELT Fetcher** | Query GDELT DOC 2.0 API for conflict events | `httpx` |
| **Google News Fetcher** | Poll Google News keyword RSS feeds (concurrently via `asyncio.gather()`) | `feedparser`, `httpx` |
| **Telegram Fetcher** | Listen to configured Telegram channels | `telethon` |
| **Normalizer** | Convert all fetcher outputs to unified Article format | -- |
| **Deduplicator** | Reject already-seen articles | `rapidfuzz`, `sqlite3` |
| **Keyword Filter** | Match articles against bilingual keyword lists | -- |
| **Classifier** | Classify articles via Claude Haiku 4.5, extract structured event data, track token usage | `anthropic` |
| **Corroborator** | Group classifications into events, check source independence, determine alert level | `rapidfuzz`, `sqlite3` |
| **Twilio Client** | Transport layer: place calls (Polish TTS via Polly.Ewa), send SMS (1600-char truncation), send WhatsApp, check call status | `twilio` |
| **Alert State Machine** | Alert lifecycle: decision matrix routing, WhatsApp 6-digit code confirmation, calls up to 5 attempts (10s apart), retry_pending after exhaustion, 6h cooldown, corroboration upgrade, config-driven Polish templates | `sqlite3` |
| **Alert Dispatcher** | Route events sorted by urgency to state machine, support dry-run mode | -- |
| **Pipeline** | Orchestrate full fetch→process→classify→alert cycle, error isolation per component, cycle statistics tracking | -- |
| **Scheduler** | Dual-lane pipeline: fast lane (3 min, Telegram + Google News + priority-1 RSS) and slow lane (15 min, all sources incl. GDELT), both with max_instances=1, coalesce=True, jitter, health monitoring to `data/health.json`, daily summary logging, self-healing SMS on repeated failures | `apscheduler` |
| **CLI** | Parse arguments (`--dry-run`, `--once`, `--health`, `--test-headline`, `--test-file`, `--test-alert`, `--diagnostic`, `--config`, `--log-level`), continuous and single-cycle modes, graceful Ctrl+C shutdown | `argparse` (stdlib) |

## 4. Data Models

### Article (normalized fetcher output)

```
Article:
  id: str (UUID)
  source_name: str ("PAP", "TVN24", "GDELT", ...)
  source_url: str (article URL)
  source_type: str ("rss" | "gdelt" | "google_news" | "telegram")
  title: str
  summary: str (first ~500 chars of content, if available)
  language: str ("pl" | "en" | "uk" | "ru")
  published_at: datetime (UTC)
  fetched_at: datetime (UTC)
  raw_metadata: dict (source-specific fields: GDELT tone, CAMEO code, etc.)
```

### ClassificationResult (LLM output)

```
ClassificationResult:
  article_id: str (FK to Article)
  is_military_event: bool
  event_type: str
  urgency_score: int (1-10)
  affected_countries: list[str]
  aggressor: str
  is_new_event: bool
  confidence: float (0.0-1.0)
  summary_pl: str (Polish-language summary for TTS)
  classified_at: datetime (UTC)
  model_used: str
  input_tokens: int
  output_tokens: int
```

### Event (corroborated incident)

```
Event:
  id: str (UUID)
  event_type: str
  urgency_score: int (max across corroborating articles)
  affected_countries: list[str]
  aggressor: str
  summary_pl: str
  first_seen_at: datetime (UTC)
  last_updated_at: datetime (UTC)
  source_count: int (number of independent sources)
  article_ids: list[str] (FKs to Articles)
  alert_status: str ("pending" | "calling" | "acknowledged" | "expired")
  acknowledged_at: datetime | null
```

### AlertRecord (call/SMS/WhatsApp log)

```
AlertRecord:
  id: str (UUID)
  event_id: str (FK to Event)
  alert_type: str ("phone_call" | "sms" | "whatsapp")
  twilio_sid: str
  status: str ("initiated" | "ringing" | "answered" | "completed" | "no_answer" | "busy" | "failed")
  duration_seconds: int | null
  attempt_number: int
  sent_at: datetime (UTC)
  message_body: str
```

## 5. Technology Stack

| Layer | Technology | Rationale |
|---|---|---|
| Language | Python 3.11+ | Best library ecosystem for this use case |
| Config | YAML + Pydantic | Human-readable config, validated at startup |
| Database | SQLite | Zero-ops, sufficient for this volume, single-file backup |
| HTTP Client | httpx | Async-capable, modern, timeout handling |
| RSS Parsing | feedparser | Battle-tested, handles malformed feeds |
| Fuzzy Matching | rapidfuzz | Fast C-based fuzzy string matching for dedup |
| LLM | Anthropic API (Claude Haiku 4.5) | Cheapest model sufficient for classification |
| Phone/SMS | Twilio SDK | Already integrated in existing app |
| Telegram | telethon | Mature async Telegram client |
| Scheduler | APScheduler | In-process scheduler, no external dependencies |
| Testing | pytest + pytest-mock + pytest-asyncio | Standard Python testing with async support |
| Deployment | systemd on Hetzner VPS | Simple, reliable, low-cost |

## 6. Key Design Decisions

### 6.1 Why polling, not streaming?
Most sources (RSS, GDELT, Google News) don't support streaming/webhooks. Telegram does support real-time events, so the Telegram fetcher runs as a background listener that buffers messages between poll cycles. The scheduler uses a dual-lane architecture: a **fast lane** (every 3 minutes) polls Telegram, Google News, and priority-1 RSS feeds for rapid detection, while a **slow lane** (every 15 minutes) polls all sources including GDELT and lower-priority RSS -- matching GDELT's update frequency. Both lanes use `max_instances=1, coalesce=True` to prevent overlapping runs. Intervals are configurable via `scheduler.fast_interval_minutes` (fast) and `scheduler.interval_minutes` (slow).

### 6.2 Why corroboration before phone call?
A single source could be wrong, hacked, or misinterpreted. Requiring 2+ independent sources before triggering a phone call dramatically reduces false positives. For lower-severity alerts (SMS, WhatsApp), a single source suffices. Source independence is checked across **all** source types (not just within the same type) using title similarity (>= 90% fuzzy match via rapidfuzz) and domain matching to detect syndication. This prevents false phone call triggers from syndicated content republished across multiple outlets.

### 6.3 Why WhatsApp confirmation codes?
Before placing calls, the system sends a 6-digit confirmation code via WhatsApp. After each call attempt (up to 5, configurable via `max_call_retries`), the system checks WhatsApp for the correct code reply. This is more reliable than call-duration heuristics and doesn't require the monitoring server to be publicly accessible (no inbound webhooks needed). If the code is received, the event is acknowledged, and a follow-up SMS with article links is sent via WhatsApp. If all call attempts are exhausted without confirmation, the event is marked `retry_pending` and retried after `retry_interval_minutes` (default 5). After acknowledgment, a cooldown period (default 6 hours) prevents re-calling for the same event; new sources for an acknowledged event trigger SMS updates only.

### 6.4 Why SQLite, not Postgres?
At the expected volume (~100-500 articles/day, ~1-5 events/day), SQLite is more than sufficient. It's zero-configuration, single-file (easy backup), and has no network overhead. If the system scales beyond a single instance, migrate to Postgres then.

### 6.5 Why Claude Haiku, not keyword-only?
Keywords alone produce too many false positives. "Military exercise near Polish border" matches military + Polish + border but is not an attack. An LLM understands context, negation, and can distinguish exercises from actual attacks. At ~$2/month for Haiku, it's worth it.

### 6.6 Why YAML config, not environment variables?
The configuration is complex (nested lists of sources, keyword lists in 4 languages, multiple threshold levels). Environment variables can't express this cleanly. YAML is human-readable and diffable. Secrets (API keys, phone numbers) still come from `.env` and are referenced in YAML via `${VARIABLE_NAME}` syntax.

### 6.7 Why three-layer alert architecture?
The alert system is split into three layers: **TwilioClient** (transport -- places calls, sends SMS/WhatsApp, checks call status), **AlertStateMachine** (lifecycle logic -- decision matrix, retries, acknowledgment, cooldown, corroboration upgrade), and **AlertDispatcher** (routing -- sorts events by urgency, supports dry-run). This separation keeps transport concerns out of business logic and makes each layer independently testable.

### 6.8 Why error isolation in the pipeline?
Each pipeline component (fetchers, classifier, corroborator) is wrapped in try/except so a failure in one does not crash the entire cycle. A failing fetcher still allows other fetchers to contribute articles. A classifier failure still allows the cycle to complete (with zero classifications). This resilience is critical for an unattended monitoring system.

## 7. Security Considerations

- **API keys** stored in `.env`, never in config.yaml or version control
- `.env` is in `.gitignore`
- Twilio calls are outbound-only -- no inbound webhook exposure needed
- SQLite database file should have restricted permissions (chmod 600)
- The VPS should have SSH key auth only, no password login
- Use `fail2ban` on the VPS
- The Telegram client uses a personal account -- protect the session file
- No web interface exposed -- the bot is a background daemon only

## 8. File Structure

```
project-sentinel/
├── CLAUDE.md
├── sentinel.py                  # Main entry point + CLI (--once, --dry-run, --health, etc.)
├── run.sh                       # Launcher (auto-activates venv)
├── app.py                       # Existing Flask app (manual testing)
├── requirements.txt             # All dependencies
├── .env                         # Secrets (not in git)
├── .env.example                 # Template for .env
├── .gitignore
├── config/
│   ├── config.yaml              # Active configuration
│   └── config.example.yaml      # Template with all options documented
├── docs/
│   ├── architecture.md          # This file
│   ├── phases.md                # Implementation phases overview
│   ├── phase-1-infrastructure.md
│   ├── phase-2-fetchers.md
│   ├── phase-3-processing.md
│   ├── phase-4-classification.md
│   ├── phase-5-alerts.md
│   ├── phase-6-scheduler.md
│   ├── phase-7-deployment.md
│   ├── config-reference.md
│   ├── testing.md
│   ├── api-setup.md
│   └── sources.md
├── sentinel/                    # Main package
│   ├── __init__.py
│   ├── config.py                # Config loader + validation (Pydantic)
│   ├── database.py              # SQLite schema + access layer
│   ├── models.py                # Data models (Article, Event, etc.)
│   ├── fetchers/
│   │   ├── __init__.py
│   │   ├── base.py              # Abstract base fetcher
│   │   ├── rss.py               # RSS feed fetcher
│   │   ├── gdelt.py             # GDELT DOC 2.0 API fetcher
│   │   ├── google_news.py       # Google News RSS fetcher
│   │   └── telegram.py          # Telegram channel listener
│   ├── processing/
│   │   ├── __init__.py          # Pipeline entry point (process_articles)
│   │   ├── normalizer.py        # HTML/URL/timestamp cleaning, language mapping
│   │   ├── deduplicator.py      # URL hash + fuzzy title dedup via rapidfuzz
│   │   └── keyword_filter.py    # Language-aware keyword matching + exclusion
│   ├── classification/
│   │   ├── __init__.py          # Exports Classifier, Corroborator
│   │   ├── classifier.py        # Claude Haiku 4.5 article classification
│   │   └── corroborator.py      # Event grouping, source independence, alert levels
│   ├── alerts/
│   │   ├── __init__.py          # Exports AlertDispatcher, AlertStateMachine, TwilioClient
│   │   ├── twilio_client.py     # Twilio SDK wrapper: calls (Polish TTS), SMS, WhatsApp
│   │   ├── state_machine.py     # Alert lifecycle: retries, acknowledgment, cooldown
│   │   └── dispatcher.py        # Routes events by urgency, dry-run support
│   └── scheduler.py             # Pipeline orchestrator + APScheduler wrapper + health monitoring
├── tests/                       # Flat structure (all test files at top level)
│   ├── __init__.py
│   ├── conftest.py              # Shared fixtures
│   ├── fixtures/
│   │   └── test_headlines.yaml  # Test headlines with expected scores
│   ├── test_config.py           # Phase 1
│   ├── test_database.py         # Phase 1
│   ├── test_models.py           # Phase 1
│   ├── test_cli.py              # Phase 1 + Phase 6
│   ├── test_rss.py              # Phase 2
│   ├── test_gdelt.py            # Phase 2
│   ├── test_google_news.py      # Phase 2
│   ├── test_telegram.py         # Phase 2
│   ├── test_normalizer.py       # Phase 3
│   ├── test_deduplicator.py     # Phase 3
│   ├── test_keyword_filter.py   # Phase 3
│   ├── test_classifier.py       # Phase 4
│   ├── test_corroborator.py     # Phase 4
│   ├── test_twilio_client.py    # Phase 5
│   ├── test_state_machine.py    # Phase 5
│   ├── test_dispatcher.py       # Phase 5
│   ├── test_scheduler.py        # Phase 6
│   └── test_integration.py      # Phase 6 (end-to-end pipeline tests)
├── data/                        # Created at runtime
│   ├── sentinel.db              # SQLite database
│   └── health.json              # Health status (written after each cycle)
└── logs/                        # Created at runtime
    └── sentinel.log
```
