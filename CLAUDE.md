# Project Sentinel -- Military Alert Monitoring System

## Overview
Real-time monitoring bot that scans media sources (PL/EN/UA/RU) for military attacks or invasions targeting Poland and the Baltic states, and alerts via Twilio phone call.

## Documentation
- [Architecture](docs/architecture.md) -- system design, data flow, components
- [Implementation Phases](docs/phases.md) -- 7-phase build plan with test gates
- Phase specs: [1-Infrastructure](docs/phase-1-infrastructure.md) | [2-Fetchers](docs/phase-2-fetchers.md) | [3-Processing](docs/phase-3-processing.md) | [4-Classification](docs/phase-4-classification.md) | [5-Alerts](docs/phase-5-alerts.md) | [6-Scheduler](docs/phase-6-scheduler.md) | [7-Deployment](docs/phase-7-deployment.md)
- [Configuration Reference](docs/config-reference.md) -- every configurable parameter
- [Testing Strategy](docs/testing.md) -- dry run, fixtures, manual testing
- [API Setup Guide](docs/api-setup.md) -- Anthropic, Twilio, Telegram account setup
- [Media Sources Reference](docs/sources.md) -- all monitored sources with URLs/RSS

## Quick Reference
- Config: `config/config.yaml` (see `config/config.example.yaml`)
- Run: `./run.sh` (auto-activates venv, forwards all args to `sentinel.py`)
- Dry run: `./run.sh --dry-run`
- Test single headline: `./run.sh --test-headline "headline text here"`
- Tests: `.venv/bin/pytest tests/ -v`

## Known Issue: Project Rename History
This project was renamed twice: `twilio-playground` → `sentinel` → `project-sentinel`. This left stale references baked into:
- **Python venv**: packages/paths may resolve to old directory names (e.g. `/home/kossa/code/twilio-plaground/`)
- **`__pycache__`**, `.pyc` files, egg-info, `.egg-link`, or `.pth` files referencing old paths
- **pip editable installs** (`pip install -e .`) pointing at a now-nonexistent directory

**If imports fail with paths to `twilio-plaground` or `sentinel`**: the fix is to recreate the venv from scratch (`rm -rf .venv && python -m venv .venv && pip install -r requirements.txt`) and clear all `__pycache__` dirs.

## Development Rules
- **Nothing is hardcoded.** All keywords, sources, countries, thresholds, and URLs live in `config/config.yaml`.
- **Every phase must pass its tests** before starting the next phase.
- **Alerts are in Polish.** Source scanning covers PL, EN, UA, RU.
- **Use Claude Haiku 4.5** (`claude-haiku-4-5-20251001`) for classification -- cost-efficient.
- **No quiet hours.** This is a critical alert system -- call at any hour.
- **Don't spam.** Call once per event, then switch to SMS/WhatsApp for updates.
- **Corroboration required.** Phone calls require 2+ independent sources confirming the event.
- Config format: YAML. Database: SQLite. Scheduler: APScheduler.
