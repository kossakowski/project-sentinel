# Project Sentinel -- Military Alert Monitoring System

## Overview
Real-time monitoring bot that scans media sources (PL/EN/UA/RU) for military attacks or invasions targeting Poland and the Baltic states, and alerts via Twilio phone call. **The application is running in production on a Hetzner VPS** — see [Server Runbook](docs/server-runbook.md) for access, operations, and troubleshooting.

## Documentation
- [Architecture](docs/architecture.md) -- system design, data flow, components
- [Implementation Phases](docs/phases.md) -- 7-phase build plan with test gates
- Phase specs: [1-Infrastructure](docs/phase-1-infrastructure.md) | [2-Fetchers](docs/phase-2-fetchers.md) | [3-Processing](docs/phase-3-processing.md) | [4-Classification](docs/phase-4-classification.md) | [5-Alerts](docs/phase-5-alerts.md) | [6-Scheduler](docs/phase-6-scheduler.md) | [7-Deployment](docs/phase-7-deployment.md)
- [Configuration Reference](docs/config-reference.md) -- every configurable parameter
- [Testing Strategy](docs/testing.md) -- dry run, fixtures, manual testing
- [VPS Security Hardening](docs/security/vps-hardening.md) -- do this BEFORE deployment
- [API Setup Guide](docs/api-setup.md) -- Anthropic, Twilio, Telegram account setup
- [Media Sources Reference](docs/sources.md) -- all monitored sources with URLs/RSS
- [Server Runbook](docs/server-runbook.md) -- production server access, file layout, service management, deployment, troubleshooting. **Read this first for anything server-related.**

## Quick Reference
- Config: `config/config.yaml` (see `config/config.example.yaml`)
- Run: `./run.sh` (auto-activates venv, forwards all args to `sentinel.py`)
- Run once: `./run.sh --once` (single pipeline cycle, then exit)
- Dry run: `./run.sh --dry-run`
- Continuous dry run: `./run.sh --dry-run` (default mode, dual-lane: fast every 3 min, slow every 15 min)
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

## Known Issue: Project Rename History
This project was renamed twice: `twilio-playground` → `sentinel` → `project-sentinel`. This left stale references baked into:
- **Python venv**: packages/paths may resolve to old directory names (e.g. `/home/kossa/code/twilio-plaground/`)
- **`__pycache__`**, `.pyc` files, egg-info, `.egg-link`, or `.pth` files referencing old paths
- **pip editable installs** (`pip install -e .`) pointing at a now-nonexistent directory

**If imports fail with paths to `twilio-plaground` or `sentinel`**: the fix is to recreate the venv from scratch (`rm -rf .venv && python -m venv .venv && pip install -r requirements.txt`) and clear all `__pycache__` dirs.

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
- **Don't spam.** Call once per event, then switch to SMS/WhatsApp for updates.
- **Corroboration required.** Phone calls require 2+ independent sources confirming the event.
- Config format: YAML. Database: SQLite. Scheduler: APScheduler (dual-lane: fast lane every 3 min for Telegram + priority-1 RSS + Google News, slow lane every 15 min for all sources including GDELT).
