# Project Sentinel -- Setup & Launch Guide

## Prerequisites

- Python 3.10+
- Git

## 1. Clone & Virtual Environment

```bash
git clone <repo-url>
cd project-sentinel

python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
```

## 2. Install Dependencies

```bash
pip install -r requirements.txt
```

## 3. Configure Secrets

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```
# Required for alerts (Phase 5)
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_PHONE_NUMBER=+1XXXXXXXXXX
TWILIO_WHATSAPP_NUMBER=whatsapp:+14155238886
ALERT_PHONE_NUMBER=+48XXXXXXXXX

# Required for classification (Phase 4)
ANTHROPIC_API_KEY=sk-ant-xxxxx

# Optional -- Telegram channel monitoring
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=abcdef1234567890abcdef1234567890
```

### Where to get API keys

| Service | Sign up | What you need |
|---------|---------|---------------|
| **Anthropic** | https://console.anthropic.com | API key (add ~$5 credits) |
| **Twilio** | https://www.twilio.com/console | Account SID, Auth Token, buy a phone number with Voice+SMS |
| **Telegram** | https://my.telegram.org | API ID + API Hash (optional, only for Telegram fetcher) |

GDELT and Google News RSS require no API keys.

See [docs/api-setup.md](docs/api-setup.md) for detailed account setup instructions.

## 4. Configure Application

```bash
cp config/config.example.yaml config/config.yaml
```

The defaults are sensible out of the box. Key settings you may want to customize in `config/config.yaml`:

- **Monitored countries** -- default: Poland, Lithuania, Latvia, Estonia
- **Keywords** -- critical and high-urgency terms in PL/EN/UA/RU
- **RSS sources** -- 13 feeds preconfigured (PAP, TVN24, Defence24, BBC, etc.)
- **Scan interval** -- default: every 15 minutes
- **Corroboration threshold** -- default: 2 independent sources before phone call
- **Urgency routing** -- critical (9-10) = phone call, high (7-8) = SMS, medium (5-6) = WhatsApp, low (1-4) = log only

See [docs/config-reference.md](docs/config-reference.md) for every parameter.

## 5. Verify Setup

```bash
# Run tests
pytest tests/ -v

# Verify config loads
python -c "from sentinel.config import load_config; c = load_config('config/config.yaml'); print('Config OK')"

# Verify database initializes
python -c "from sentinel.database import Database; db = Database('data/sentinel.db'); print('DB OK'); db.close()"
```

## 6. Launch

```bash
# Dry run -- processes pipeline but does NOT send alerts
python sentinel.py --once --dry-run

# Single run -- poll all sources, process, alert if needed, then exit
python sentinel.py --once

# Daemon mode -- continuous monitoring on 15-minute schedule
python sentinel.py

# Test a specific headline
python sentinel.py --test-headline "Russia invades Poland"

# Test headlines from fixture file
python sentinel.py --test-file tests/fixtures/test_headlines.yaml
```

### CLI Options

| Flag | Description |
|------|-------------|
| `--dry-run` | Don't send Twilio alerts, log only |
| `--once` | Run one cycle and exit |
| `--test-headline TEXT` | Classify a single headline |
| `--test-file FILE` | Classify all headlines from a YAML file |
| `--config PATH` | Use a custom config file (default: `config/config.yaml`) |
| `--log-level LEVEL` | Override log level (DEBUG, INFO, WARNING, ERROR) |
| `--health` | Run a health check |

## 7. Logs & Database

Both are created automatically at runtime:

- **Logs:** `logs/sentinel.log` (rotates at 50 MB, keeps 5 backups)
- **Database:** `data/sentinel.db` (SQLite, auto-creates schema on first run)

No manual setup needed for either.

## Files NOT Committed to Git

These are in `.gitignore` -- you must create them locally:

- `.env` -- API keys and secrets
- `config/config.yaml` -- your active configuration
- `data/sentinel.db` -- runtime database
- `logs/` -- log files
- `sentinel_session.session` -- Telegram auth session

## Quick Start Checklist

1. `python3 -m venv venv && source venv/bin/activate`
2. `pip install -r requirements.txt`
3. `cp .env.example .env` -- fill in API keys
4. `cp config/config.example.yaml config/config.yaml`
5. `pytest tests/ -v` -- all tests should pass
6. `python sentinel.py --once --dry-run` -- verify it runs
