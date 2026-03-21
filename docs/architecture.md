# Project Sentinel -- System Architecture

## 1. System Purpose

Project Sentinel is an automated early-warning system that continuously monitors media sources across multiple languages (Polish, English, Ukrainian, Russian) for signals of military attacks or invasions targeting Poland and the Baltic states (Lithuania, Latvia, Estonia) by Russia, Belarus, or their allies.

When a credible threat is detected, Project Sentinel calls the user's phone immediately (any hour), speaks the alert in Polish, and follows up with SMS/WhatsApp for ongoing updates.

## 2. High-Level Data Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    SCHEDULER (APScheduler)                   │
│                   Fires every 15 minutes                     │
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
│    - Require 2+ sources for phone call trigger              │
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
│  │ NEW ──► CALLING ──► ANSWERED ──► ACKNOWLEDGED         │  │
│  │              │          │                              │  │
│  │              ▼          ▼                              │  │
│  │         NO_ANSWER   CALL_SHORT ──► RETRY (max 3)      │  │
│  │              │                        │               │  │
│  │              ▼                        ▼               │  │
│  │         RETRY (max 3) ──────► SMS_FALLBACK            │  │
│  │                                                       │  │
│  │ After acknowledgment: updates via SMS/WhatsApp only   │  │
│  │ Cooldown: no re-call for same event for 6 hours       │  │
│  └──────────────────────────────────────────────────────┘   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## 3. Component Overview

| Component | Responsibility | Key Dependencies |
|---|---|---|
| **Config Loader** | Load and validate `config/config.yaml` | `pyyaml`, `pydantic` |
| **Database** | Store articles, events, alert state | `sqlite3` (stdlib) |
| **RSS Fetcher** | Poll RSS feeds from configured sources | `feedparser`, `httpx` |
| **GDELT Fetcher** | Query GDELT DOC 2.0 API for conflict events | `httpx` |
| **Google News Fetcher** | Poll Google News keyword RSS feeds | `feedparser`, `httpx` |
| **Telegram Fetcher** | Listen to configured Telegram channels | `telethon` |
| **Normalizer** | Convert all fetcher outputs to unified Article format | -- |
| **Deduplicator** | Reject already-seen articles | `rapidfuzz`, `sqlite3` |
| **Keyword Filter** | Match articles against bilingual keyword lists | -- |
| **Classifier** | Score articles using Claude Haiku 4.5 | `anthropic` |
| **Corroborator** | Count independent sources for same event | `sqlite3` |
| **Alert Dispatcher** | Send calls/SMS/WhatsApp via Twilio | `twilio` |
| **Call State Machine** | Track call status, retries, acknowledgment | `sqlite3` |
| **Scheduler** | Orchestrate the pipeline on intervals | `apscheduler` |
| **CLI** | Parse arguments (`--dry-run`, `--test-headline`, etc.) | `argparse` (stdlib) |

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
Most sources (RSS, GDELT, Google News) don't support streaming/webhooks. Telegram does support real-time events, so the Telegram fetcher runs as a background listener that buffers messages between poll cycles. Everything else is polled every 15 minutes -- matching GDELT's update frequency.

### 6.2 Why corroboration before phone call?
A single source could be wrong, hacked, or misinterpreted. Requiring 2+ independent sources before triggering a phone call dramatically reduces false positives. For lower-severity alerts (SMS, WhatsApp), a single source suffices.

### 6.3 Why call duration as acknowledgment?
The simplest approach that doesn't require the monitoring server to be publicly accessible (no inbound webhooks needed). If a call is answered and lasts >15 seconds, the user heard the message. This avoids needing to expose the VPS to inbound Twilio webhooks, reducing attack surface and complexity.

### 6.4 Why SQLite, not Postgres?
At the expected volume (~100-500 articles/day, ~1-5 events/day), SQLite is more than sufficient. It's zero-configuration, single-file (easy backup), and has no network overhead. If the system scales beyond a single instance, migrate to Postgres then.

### 6.5 Why Claude Haiku, not keyword-only?
Keywords alone produce too many false positives. "Military exercise near Polish border" matches military + Polish + border but is not an attack. An LLM understands context, negation, and can distinguish exercises from actual attacks. At ~$2/month for Haiku, it's worth it.

### 6.6 Why YAML config, not environment variables?
The configuration is complex (nested lists of sources, keyword lists in 4 languages, multiple threshold levels). Environment variables can't express this cleanly. YAML is human-readable and diffable. Secrets (API keys, phone numbers) still come from `.env` and are referenced in YAML via `${VARIABLE_NAME}` syntax.

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
├── sentinel.py                  # Main entry point + CLI
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
│   ├── processing/              # (Phase 3 -- not yet implemented)
│   │   └── ...
│   ├── classification/          # (Phase 4 -- not yet implemented)
│   │   └── ...
│   ├── alerts/                  # (Phase 5 -- not yet implemented)
│   │   └── ...
│   └── scheduler.py             # (Phase 6 -- not yet implemented)
├── tests/                       # Flat structure (all test files at top level)
│   ├── __init__.py
│   ├── conftest.py              # Shared fixtures
│   ├── fixtures/
│   │   └── test_headlines.yaml  # Test headlines with expected scores
│   ├── test_config.py           # Phase 1
│   ├── test_database.py         # Phase 1
│   ├── test_models.py           # Phase 1
│   ├── test_cli.py              # Phase 1
│   ├── test_rss.py              # Phase 2
│   ├── test_gdelt.py            # Phase 2
│   ├── test_google_news.py      # Phase 2
│   └── test_telegram.py         # Phase 2
└── logs/                        # Created at runtime
    └── sentinel.log
```
