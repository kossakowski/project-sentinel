# Project Sentinel -- Setup & Launch Guide

> **First-time credential setup:** For obtaining Twilio / Anthropic / Telegram credentials and API keys, see [API Setup Guide](docs/api-setup.md).

## Prerequisites

- Python 3.10+
- Git

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

Fill in credentials for Twilio, Anthropic, and Telegram. GDELT and Google News RSS require no API keys. See [API Setup Guide](docs/api-setup.md) for a complete `.env` template and account setup instructions.

## 4. Configure Application

```bash
cp config/config.example.yaml config/config.yaml
```

The defaults are sensible out of the box. Key settings you may want to customize:

- **Monitored countries** -- default: Poland, Lithuania, Latvia, Estonia
- **Keywords** -- critical and high-urgency terms in PL/EN/UA/RU
- **RSS sources** -- 17 feeds preconfigured (PAP, TVN24, Defence24, BBC, etc.)
- **Scan interval** -- dual-lane: fast lane every 3 min (Telegram, Google News, priority-1 RSS), slow lane every 15 min (all sources including GDELT)
- **Corroboration threshold** -- default value in code is 2; live `config.example.yaml` uses 1 (single source triggers phone call)
- **Urgency routing** -- critical (9-10) = phone call, high (7-8) = SMS, medium (5-6) = SMS (WhatsApp tier disabled in production), low (1-4) = log only

See [docs/config-reference.md](docs/config-reference.md) for every parameter.

## 5. Verify Setup

```bash
pytest tests/ -v  # all tests must pass
./run.sh --once --dry-run  # single cycle, no alerts sent
```

## 6. Launch

Use `./run.sh` — it activates the virtual environment automatically. All arguments are forwarded to `sentinel.py`.

```bash
./run.sh --once --dry-run   # dry run: pipeline without alerts
./run.sh --once             # single cycle, then exit
./run.sh                    # daemon mode (fast lane: 3 min, slow lane: 15 min)
```

> **Without the launcher:** `source .venv/bin/activate && python sentinel.py [args]`

### CLI Options

| Flag | Description |
|------|-------------|
| `--dry-run` | Don't send Twilio alerts, log only |
| `--once` | Run one cycle and exit |
| `--test-headline TEXT` | Classify a single headline |
| `--test-file FILE` | Classify all headlines from a YAML file |
| `--test-alert [sms\|whatsapp]` | Fire a real alert with a fake event |
| `--config PATH` | Use a custom config file (default: `config/config.yaml`) |
| `--log-level LEVEL` | Override log level (DEBUG, INFO, WARNING, ERROR) |
| `--health` | Print `data/health.json` |
| `--diagnostic` | Single cycle; generates `data/diagnostic.html` with all articles |

## 7. Logs & Database

- **Logs:** `logs/sentinel.log` (rotates at 50 MB, keeps 5 backups)
- **Database:** `data/sentinel.db` (SQLite, auto-creates schema on first run)

## Files NOT Committed to Git

| File | Purpose |
|------|---------|
| `.env` | API keys and secrets |
| `config/config.yaml` | Your active configuration |
| `data/sentinel.db` | Runtime database |
| `logs/` | Log files |
| `sentinel_session.session` | Telegram auth session |
