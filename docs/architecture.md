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

## 9. Detailed Pipeline Reference

A complete stage-by-stage reference showing every decision point, data transformation, and what resources each component receives.

```
╔══════════════════════════════════════════════════════════════════════════════════════╗
║                         PROJECT SENTINEL — FULL PIPELINE                            ║
║                         From raw internet → phone call at 3 AM                      ║
╚══════════════════════════════════════════════════════════════════════════════════════╝


┌─────────────────────────────────────────────────────────────────────────────────────┐
│  SCHEDULER (APScheduler)                                                             │
│                                                                                      │
│  FAST LANE ─── every 3 min (+jitter) ──→ Telegram, RSS priority-1, Google News      │
│  SLOW LANE ─── every 15 min (+jitter) ─→ ALL sources (+ GDELT + lower-priority RSS) │
│                                                                                      │
│  Both lanes run the same 7-stage pipeline below.                                     │
│  max_instances=1, coalesce=True — prevents overlapping runs.                         │
└──────────────────────────────────────────┬──────────────────────────────────────────┘
                                           │
                                           ▼

═══════════════════════════════════════════════════════════════════════════════════════
 STAGE 1: FETCH                                              ~1000 articles/cycle
═══════════════════════════════════════════════════════════════════════════════════════

 ┌───────────────┐  ┌───────────────┐  ┌───────────────┐  ┌───────────────────┐
 │  RSS Feeds    │  │  Google News  │  │    GDELT      │  │    Telegram       │
 │  19 sources   │  │  16 queries   │  │  DOC 2.0 API  │  │  4 channels       │
 │  (feedparser) │  │  (RSS URLs)   │  │  (REST JSON)  │  │  (Telethon)       │
 └───────┬───────┘  └───────┬───────┘  └───────┬───────┘  └─────────┬─────────┘
         │                  │                   │                     │
         │  title           │  title            │  title              │  first 200ch
         │  summary         │  summary          │  ⚠ NO summary      │  first 500ch
         │  link            │  link             │  url                │  t.me/ch/id
         │  published_at    │  published_at     │  seendate           │  message.date
         │  language (cfg)  │  language (cfg)   │  language (auto)    │  language (cfg)
         │  tags            │                   │  full GDELT JSON    │  views/forwards
         │                  │                   │                     │
         └─────────┬────────┴─────────┬─────────┴───────────┬────────┘
                   │                  │                      │
                   ▼                  ▼                      ▼

       ┌──────────────────────────────────────────────────────────────┐
       │  Article object created for each:                            │
       │                                                              │
       │  id .................. UUID (auto-generated)                 │
       │  source_name ......... "BBC World", "GoogleNews:Rosja atak" │
       │  source_type ......... rss | google_news | gdelt | telegram │
       │  source_url .......... full URL to original article         │
       │  title ............... headline text                        │
       │  summary ............. description/snippet (may be empty)   │
       │  language ............ en | pl | uk | ru                    │
       │  published_at ........ datetime (from source)               │
       │  fetched_at .......... now() (when we grabbed it)           │
       │  url_hash ............ SHA256(source_url)                   │
       │  title_normalized .... NFKD + lowercase + strip non-alnum   │
       │  raw_metadata ........ fetcher-specific extras (dict)       │
       │                                                              │
       │  ⚠ No article body content is ever fetched or stored.       │
       │    The summary is whatever the source provides (RSS          │
       │    <description>, Telegram message text, etc.)               │
       └──────────────────────────────┬───────────────────────────────┘
                                      │
                                      ▼

═══════════════════════════════════════════════════════════════════════════════════════
 STAGE 2: NORMALIZE                                        same count, cleaner data
═══════════════════════════════════════════════════════════════════════════════════════

 What happens to each article:

 title/summary ....... HTML entities decoded → tags stripped → whitespace collapsed
                       title capped at 500 chars, summary at 1000 chars

 source_url .......... domain lowercased → www. stripped → tracking params removed
                       (utm_*, fbclid, gclid) → fragment (#) stripped

 published_at ........ timezone-aware enforced → future timestamps capped to now()
                       None → fallback to fetched_at

 language ............ full names mapped to ISO codes:
                       "english" → "en", "polish" → "pl", "ukrainian" → "uk"

                                      │
                                      ▼

═══════════════════════════════════════════════════════════════════════════════════════
 STAGE 3: DEDUPLICATE                                      drops ~50-70% of articles
═══════════════════════════════════════════════════════════════════════════════════════

 Three checks, in order:

 ① EXACT URL HASH ──→ SHA256(url) already exists in DB?
    YES → skip ("URL already seen")

 ② FUZZY TITLE MATCH ──→ rapidfuzz.fuzz.ratio() against DB titles from last 60 min
    Same source + ≥85% similar  → skip ("same-source republication")
    Cross source + ≥95% similar → skip ("syndicated content")

 ③ BATCH-INTERNAL ──→ same url_hash already in this batch?
    YES → skip ("batch-internal duplicate")

 ✅ Unique articles → inserted into DB (articles table)

                                      │
                                      ▼

═══════════════════════════════════════════════════════════════════════════════════════
 STAGE 4: KEYWORD FILTER                      drops ~85% — THIS IS THE MAIN GATE
═══════════════════════════════════════════════════════════════════════════════════════

 ┌────────────────────────────────────────────────────────────────────────────────┐
 │  INPUT: article.title + " " + article.summary  (concatenated, lowercased)     │
 │                                                                                │
 │  Matching strategy depends on language:                                        │
 │  • Slavic (PL, UK, RU): substring match — "dron" matches "drony", "dronem"   │
 │  • English & others:    \bword\b regex — "drone" matches "drone" only         │
 │                                                                                │
 │  Keywords configured per language in config.yaml at three levels:              │
 │  • CRITICAL: unconditional pass (overrides excludes)                          │
 │  • HIGH: pass unless an EXCLUDE keyword also matches                          │
 │  • EXCLUDE: blocks HIGH matches (but cannot block CRITICAL)                   │
 └────────────────────────────────────────────────────────────────────────────────┘

 Decision tree for each article:

             ┌──────────────────────┐
             │ Source has            │
             │ keyword_bypass=true?  │──── YES ──→ ✅ PASS (level: "bypass")
             └──────────┬───────────┘              Defence24, Defence24 EN,
                        │ NO                       all 4 Telegram channels
                        ▼
             ┌──────────────────────┐
             │ Any CRITICAL keyword │
             │ matched in title     │──── YES ──→ ✅ PASS (level: "critical")
             │ or summary?          │              Excludes IGNORED
             └──────────┬───────────┘
                        │ NO
                        ▼
             ┌──────────────────────┐
             │ Any EXCLUDE keyword  │
             │ matched?             │──── YES ──→ ❌ FILTERED OUT (silent drop)
             └──────────┬───────────┘              "exercise", "film", etc.
                        │ NO
                        ▼
             ┌──────────────────────┐
             │ Any HIGH keyword     │
             │ matched?             │──── YES ──→ ✅ PASS (level: "high")
             └──────────┬───────────┘
                        │ NO
                        ▼
                   ❌ FILTERED OUT
                   (never seen by classifier)

 Output annotation on passing articles:

   article.raw_metadata["keyword_match"] = {
       "level": "critical" | "high" | "bypass",
       "matched_keywords": ["drone", "airspace violation", ...],
       "language_matched": "en"
   }

 ⚠ Articles filtered out HERE are stored in the DB (articles table) but have
   NO entry in the classifications table. They are never evaluated by the LLM.
   This is the daily audit's primary target for missed threats.

                                      │
                                      ▼

═══════════════════════════════════════════════════════════════════════════════════════
 STAGE 5: CLASSIFY (Claude Haiku 4.5)                      ~10-30 articles/cycle
═══════════════════════════════════════════════════════════════════════════════════════

 ┌────────────────────────────────────────────────────────────────────────────────┐
 │  WHAT HAIKU RECEIVES (per article — one API call each):                       │
 │                                                                                │
 │  System prompt (~350 tokens, constant):                                       │
 │    "You are a military intelligence analyst monitoring media for               │
 │     signs of military attacks or invasions targeting Poland,                   │
 │     Lithuania, Latvia, or Estonia..."                                          │
 │    + rules: what IS vs ISN'T an attack                                        │
 │    + instruction: do NOT infer countries from source name                     │
 │    + urgency 9-10 ONLY for direct attacks on PL/LT/LV/EE                    │
 │    + urgency scale with examples                                              │
 │                                                                                │
 │  User message — ONLY these 6 fields from the article:                         │
 │  ┌────────────────────────────────────────────────────────────────────────┐   │
 │  │  Source: GoogleNews:drone incursion Poland (google_news)              │   │
 │  │  Language: en                                                         │   │
 │  │  Published: 2026-03-29T15:22:45+00:00                                │   │
 │  │  Title: Russian drone violates Polish airspace                       │   │
 │  │  Summary: A military drone entered Polish airspace over the eastern  │   │
 │  │           border region near Lublin early Sunday morning...          │   │
 │  └────────────────────────────────────────────────────────────────────────┘   │
 │                                                                                │
 │  ⚠ NOT sent to Haiku:                                                         │
 │    source_url, fetched_at, raw_metadata, id, url_hash,                        │
 │    title_normalized, keyword_match results, article body content               │
 │                                                                                │
 │  API parameters:                                                               │
 │    model ......... claude-haiku-4-5-20251001                                  │
 │    max_tokens .... 512                                                         │
 │    temperature ... 0.0 (deterministic)                                         │
 │                                                                                │
 │  Avg input: ~1,000 tokens | Avg output: ~148 tokens                           │
 │  Cost: ~$0.14/day (~$4.20/month) at ~100 articles/day                         │
 └────────────────────────────────────────────────────────────────────────────────┘

 ┌────────────────────────────────────────────────────────────────────────────────┐
 │  WHAT HAIKU RETURNS (strict JSON, no markdown):                               │
 │                                                                                │
 │  {                                                                             │
 │    "is_military_event": true/false,                                           │
 │    "event_type": "drone_attack",          ← from fixed enum:                 │
 │                                              invasion, airstrike,             │
 │                                              missile_strike, border_crossing, │
 │                                              airspace_violation, naval_block, │
 │                                              cyber_attack, troop_movement,    │
 │                                              artillery_shelling, drone_attack,│
 │                                              other, none                      │
 │    "urgency_score": 7,                    ← clamped to 1-10                  │
 │    "affected_countries": ["PL"],          ← only explicitly mentioned        │
 │    "aggressor": "RU",                     ← RU | BY | unknown | none        │
 │    "is_new_event": true,                  ← vs. follow-up coverage           │
 │    "confidence": 0.85,                    ← clamped to 0.0-1.0              │
 │    "summary_pl": "Rosyjski dron naruszył  ← Polish, 1-2 sentences           │
 │                   polską przestrzeń..."      for phone alert TTS             │
 │  }                                                                             │
 │                                                                                │
 │  Urgency scale:                                                                │
 │    1-2: Routine military news, no threat                                      │
 │    3-4: Minor incident, low concern                                           │
 │    5-6: Notable (airspace violation, border provocation, troop movement)      │
 │    7-8: Serious (shots fired, large airspace violation, cyberattack)          │
 │    9-10: Active attack/invasion on PL/LT/LV/EE territory (ONLY)             │
 └────────────────────────────────────────────────────────────────────────────────┘

 Stored in DB: classifications table
   (all Haiku fields + classified_at, model_used, input_tokens, output_tokens)

 Error handling: 1 retry with 5s delay on API error, then skip article.
 Token tracking: daily input/output totals logged with estimated cost.

                                      │
                                      ▼

═══════════════════════════════════════════════════════════════════════════════════════
 STAGE 6: CORROBORATE                                      groups into events
═══════════════════════════════════════════════════════════════════════════════════════

 ENTRY GATE: only classifications with is_military_event=true AND urgency >= 5
             (lower urgency: stored in DB for auditing, but no event created)

 For each qualifying classification, try to match to an existing event:

 ┌────────────────────────────────────────────────────────────────────────────────┐
 │  ALL FOUR CRITERIA must pass to match:                                        │
 │                                                                                │
 │  ① Event type compatible?                                                     │
 │     e.g. missile_strike <-> airstrike = YES (compatible types defined in map) │
 │          cyber_attack <-> naval_blockade = NO                                 │
 │                                                                                │
 │  ② Shared affected country?                                                  │
 │     set(new.countries) ∩ set(event.countries) must not be empty               │
 │                                                                                │
 │  ③ Within time window?                                                        │
 │     |classified_at - event.first_seen_at| <= 60 min (configurable)            │
 │                                                                                │
 │  ④ Summary similarity >= 55%?                                                 │
 │     rapidfuzz.fuzz.token_sort_ratio(new.summary_pl, event.summary_pl)         │
 └────────────────────────────────────────────────────────────────────────────────┘

 Match found → UPDATE existing event:
   • Append article_id to event.article_ids
   • Check source independence:
     - Same domain (URL)?       → NOT independent (source_count unchanged)
     - Title similarity >= 90%? → syndication, NOT independent
     - Otherwise                → source_count += 1
   • urgency_score = max(existing, new)
   • Merge affected_countries (union)

 No match → CREATE new event (source_count = 1)

 Alert status determination:

    urgency >= 9  AND  sources >= 2  ──→  phone_call
    urgency >= 9  AND  sources < 2   ──→  sms  (waiting for corroboration)
    urgency 7-8   (any sources)      ──→  sms
    urgency 5-6   (any sources)      ──→  sms
    urgency < 5                      ──→  log_only

                                      │
                                      ▼

═══════════════════════════════════════════════════════════════════════════════════════
 STAGE 7: ALERT                                            phone / SMS / log
═══════════════════════════════════════════════════════════════════════════════════════

 ┌────────────────────────────────────────────────────────────────────────────────┐
 │  PRE-FLIGHT CHECKS (per event):                                               │
 │                                                                                │
 │  • Already acknowledged + within 6h cooldown? → skip entirely                 │
 │  • Acknowledged but has new sources?          → send UPDATE SMS only          │
 │  • Phone call currently in progress?          → skip (prevent duplicates)     │
 └────────────────────────────────────────────────────────────────────────────────┘

 ┌────────────────────────────────────────────────────────────────────────────────┐
 │                                                                                │
 │  SMS FLOW                                                                      │
 │  ─────────                                                                     │
 │  Formatted message sent via Twilio:                                            │
 │                                                                                │
 │    PROJECT SENTINEL: Atak dronow                                              │
 │    Pilnosc: 8/10                                                               │
 │    Kraje: PL                                                                   │
 │    Agresor: RU                                                                 │
 │                                                                                │
 │    Rosyjski dron naruszyl polska przestrzen powietrzna...                     │
 │                                                                                │
 │    Zrodla (2):                                                                 │
 │    - Defence24: Rosyjski dron nad Polska                                      │
 │      https://defence24.pl/...                                                  │
 │    - RMF24: Dron naruszyl przestrzen powietrzna RP                            │
 │      https://rmf24.pl/...                                                      │
 │                                                                                │
 │    Wykryto: 2026-03-30 15:22 UTC                                              │
 │                                                                                │
 │  → Recorded in alert_records table → Done                                      │
 │                                                                                │
 └────────────────────────────────────────────────────────────────────────────────┘

 ┌────────────────────────────────────────────────────────────────────────────────┐
 │                                                                                │
 │  PHONE CALL FLOW (urgency 9-10 + 2+ independent sources)                     │
 │  ───────────────                                                               │
 │                                                                                │
 │  Step 1: Send SMS with 6-digit confirmation code                              │
 │                                                                                │
 │    PROJECT SENTINEL: Uderzenie rakietowe                                      │
 │                                                                                │
 │    Rakiety uderzyly w terytorium Polski...                                    │
 │                                                                                │
 │    Odpowiedz kodem aby potwierdzic odbior alertu: 356222                     │
 │    Telefon bedzie dzwonil dopoki nie potwierdzisz.                            │
 │                                                                                │
 │  Step 2: Call retry loop (up to 3 attempts per round)                         │
 │                                                                                │
 │    ┌──────────┐      ┌───────────────┐      ┌──────────────────┐             │
 │    │ Check    │ NO   │ Place call    │      │ Wait up to 90s   │             │
 │    │ SMS      │─────→│ via Twilio    │─────→│ Poll SMS every   │             │
 │    │ reply?   │      │ (TTS Polish)  │      │ 5s for code      │             │
 │    └────┬─────┘      └───────────────┘      └───────┬──────────┘             │
 │         │ YES                                        │                        │
 │         ▼                                            ▼                        │
 │    ACKNOWLEDGED                            Code received?                     │
 │    • event.acknowledged_at = now()           YES → ACKNOWLEDGED               │
 │    • send confirmation SMS                   NO  → wait 10s → next attempt   │
 │    • stop calling                                  (up to 3 attempts)         │
 │                                                                                │
 │  After 3 failed attempts in this round:                                       │
 │    → event.alert_status = "retry_pending"                                     │
 │    → retry after 5 min interval on next pipeline cycle                        │
 │    → NEVER gives up until SMS confirmation code received                      │
 │                                                                                │
 │  Call message (spoken twice in Polish via Polly.Ewa TTS):                     │
 │    "Uwaga! Alert systemu Project Sentinel.                                    │
 │     Uderzenie rakietowe wykryte. {summary_pl}.                                │
 │     Zrodla potwierdzajace: 2. Pilnosc: 10 na 10.                             │
 │     Powtarzam. [message repeated]                                             │
 │     Potwierdz odbior alertu. Odpisz na SMS kodem, ktory otrzymales."         │
 │                                                                                │
 └────────────────────────────────────────────────────────────────────────────────┘

                                      │
                                      ▼

═══════════════════════════════════════════════════════════════════════════════════════
 POST-CYCLE                                                cleanup + health
═══════════════════════════════════════════════════════════════════════════════════════

 • Check pending calls from previous cycles (poll Twilio for status)
 • Cleanup: delete articles older than 30 days, events older than 90 days
 • Write data/health.json:
     is_healthy, last_cycle_at, last_cycle_duration_seconds,
     consecutive_failures, fetcher_status (per-fetcher health)
 • Log daily summary at day rollover


═══════════════════════════════════════════════════════════════════════════════════════
 DATA REDUCTION FUNNEL (typical numbers from production)
═══════════════════════════════════════════════════════════════════════════════════════

 ~1000 articles fetched
   │
   ├── DEDUP ────────→ ~300-500 unique          (50-70% dropped)
   │
   ├── KEYWORDS ─────→ ~10-30 relevant          (85-95% dropped)  ← MAIN GATE
   │
   ├── CLASSIFY ─────→ ~5-15 military=true      (50-70% not military)
   │
   ├── CORROBORATE ──→ ~1-5 events              (grouped, urgency >= 5)
   │
   └── ALERT ────────→ 0-2 SMS, rare phone call


═══════════════════════════════════════════════════════════════════════════════════════
 KEY INSIGHT
═══════════════════════════════════════════════════════════════════════════════════════

 Haiku only sees 6 fields: source_name, source_type, language, published_at,
 title, summary. It never sees the URL, keyword match results, article body,
 or any other data.

 The keyword filter is the brutal gatekeeper — 85%+ of articles never reach
 Haiku at all. This is why keyword gaps are the most dangerous failure mode:
 a missing keyword means a relevant article is silently dropped before the
 AI ever evaluates it.

 The article body content is never fetched or stored by any stage. The
 "summary" field is whatever snippet the source provides — an RSS
 <description> tag, the first 500 chars of a Telegram message, or nothing
 at all (GDELT provides no summary). ~47% of classified articles have
 summaries under 150 characters.
```
