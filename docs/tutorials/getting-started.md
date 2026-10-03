# Project Sentinel -- Setup & Launch Guide

Last verified: 2026-10-03 (deployed commit 6429124)

This tutorial sets up a local copy of the bot for development and testing. Production runs on the VPS; see the [server runbook](../how-to/server-runbook.md) for that.

> **First-time credential setup:** For obtaining OpenAI, Twilio, Telegram and Expo credentials, see [API Setup Guide](../how-to/api-setup.md).

Contents: [Prerequisites](#prerequisites) · [1. Clone](#1-clone--virtual-environment) · [2. Install](#2-install-dependencies) · [3. Secrets](#3-configure-secrets) · [4. Local config](#4-create-a-local-config) · [5. Telegram](#5-decide-on-telegram) · [6. Verify](#6-verify-setup) · [7. Launch](#7-launch) · [8. Logs & database](#8-logs--database) · [Files not committed](#files-not-committed-to-git)

## Prerequisites

- Python 3.11+ (the code uses `datetime.UTC` and `asyncio.timeout`, which Python 3.10 lacks)
- Git
- A paid OpenAI API project key. Even a dry run classifies articles with paid OpenAI calls (see step 6).

## 1. Clone & Virtual Environment

```bash
git clone <repo-url>
cd project-sentinel

python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
```

## 2. Install Dependencies

```bash
pip install -r requirements.txt
```

## 3. Configure Secrets

```bash
cp .env.example .env
```

- Fill in `OPENAI_API_KEY` first. The live classifier uses the OpenAI provider (`classification.provider: openai`). Without the key every classification fails and articles stay pending.
- Fill in the Twilio and Telegram values if you want to test those channels.
- `ANTHROPIC_API_KEY` is only for the legacy Haiku rollback. `OPENROUTER_API_KEY` is only for offline model comparison.
- Keep a value (a placeholder is fine) for every variable the config references as `${VAR}`. An unset variable stops the config from loading.
- GDELT and Google News RSS need no keys.

See [API Setup Guide](../how-to/api-setup.md) for the complete `.env` template and account setup.

## 4. Create a Local Config

```bash
cp config/config.example.yaml data/config.local.yaml
```

Do not overwrite `config/config.yaml`. It is tracked in git and is the production config: `/deploy` copies it to the server as `/etc/sentinel/config.yaml`. It uses server paths under `/var/lib/sentinel` and `/var/log/sentinel` and reads `${EXPO_PUSH_TOKEN}`, so it does not run on a workstation as-is. (`.gitignore` lists it, but that has no effect on a file git already tracks.)

The `data/` folder is git-ignored, so `data/config.local.yaml` stays private. Pass it with `--config data/config.local.yaml` on every command below; without the flag, `sentinel.py` loads `config/config.yaml`.

The template is not a copy of production. To see the differences, run `diff config/config.example.yaml config/config.yaml`. Settings you may want to look at:

- **Monitored countries and keywords** -- `monitoring.target_countries` and `monitoring.keywords` (PL/EN/UA/RU terms).
- **Sources** -- `sources.rss`, `sources.gdelt`, `sources.google_news`, `sources.telegram`; each feed has its own `enabled` flag. Production disables GDELT because of IP-level throttling.
- **Scan intervals** -- `scheduler.fast_interval_minutes` (Telegram, Google News, priority-1 RSS) and `scheduler.interval_minutes` (all enabled sources).
- **Corroboration** -- `alerts.urgency_levels.critical.corroboration_required` gates the phone call; `classification.corroboration_required` only sets the event's provisional `alert_status` label. Both the template and production set the call gate to a single source, so one article can trigger a phone call.
- **Urgency routing** -- critical (9-10) = phone call + confirmation SMS + an additive Expo push; high (7-8) and medium (5-6) follow a per-tier `channel` (`sms` / `push` / `both`); low (1-4) = log only. The template keeps push disabled, so it sends SMS only. Production enables push and routes tiers 5-8 to push only.

See [Configuration Reference](../reference/config-reference.md) for every parameter.

## 5. Decide on Telegram

The template enables Telegram. On the first run with no session file, the Telegram client stops and asks for a phone number and a login code. Choose one:

- Run the one-time Telegram authentication in [API Setup §4](../how-to/api-setup.md#4-telegram-api-channel-monitoring). It creates `sentinel_session.session` in the repo folder.
- Or set `sources.telegram.enabled: false` in `data/config.local.yaml`.

## 6. Verify Setup

```bash
.venv/bin/pytest tests/ -v  # all tests must pass
./run.sh --config data/config.local.yaml --once --dry-run  # one cycle, no alerts sent
```

A dry run sends no alert for the events it finds: no call, no SMS, no push. (It still checks phone calls left pending in the database by an earlier real run; a fresh local database has none.) It still fetches sources, classifies articles with paid OpenAI calls and runs the article-quality gate. It writes to the local database and to the model budget ledger (`classification.budget`). So it needs a funded `OPENAI_API_KEY` and spends a small amount of real money.

## 7. Launch

Use `./run.sh` — it activates the virtual environment automatically. All arguments are forwarded to `sentinel.py`.

```bash
./run.sh --config data/config.local.yaml --once --dry-run   # dry run: no alerts sent
./run.sh --config data/config.local.yaml --once             # single cycle, then exit
./run.sh --config data/config.local.yaml                    # daemon mode (fast and slow lanes)
```

> **Without the launcher:** `source .venv/bin/activate && python sentinel.py [args]`

### CLI Options

| Flag | Description |
|------|-------------|
| `--dry-run` | Suppress all alert delivery (call, SMS, push), log only. Classification still makes paid OpenAI calls. |
| `--once` | Run one cycle and exit |
| `--test-headline TEXT` | Classify a single headline (paid API call) |
| `--test-file FILE` | Classify all headlines from a YAML file (paid API calls) |
| `--eval [PATH]` | Score the classifier against a YAML eval set (default `tests/fixtures/eval_set.yaml`); paid live API calls; saves a report to `data/eval/` |
| `--test-alert [phone_call\|sms\|push]` | Fire a real alert with a fake event (no-arg defaults to `phone_call`) |
| `--config PATH` | Use a custom config file (default: `config/config.yaml`, the production config) |
| `--log-level LEVEL` | Override log level (DEBUG, INFO, WARNING, ERROR) |
| `--health` | Print `health.json` from the database folder (`data/health.json` with the template) |
| `--diagnostic` | Single cycle; writes `diagnostic.html` with all articles to the database folder (`data/` with the template) |

Full details: [CLI Reference](../reference/cli.md).

## 8. Logs & Database

With the template config:

- **Logs:** `logs/sentinel.log` (rotation set by `logging.max_size_mb` and `logging.backup_count`)
- **Database:** `data/sentinel.db` (SQLite, auto-creates schema on first run)

Production paths are in the [server runbook](../how-to/server-runbook.md).

## Files NOT Committed to Git

| File | Purpose |
|------|---------|
| `.env` | API keys and secrets |
| `data/` | Local config copy, runtime database, model budget ledger, health file |
| `logs/` | Log files |
| `sentinel_session.session` | Telegram auth session |

`config/config.yaml` is committed. It matches the production config, so change it only for a deliberate production change.
