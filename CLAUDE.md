# Project Sentinel — Military Alert Monitoring System

Last verified: 2026-10-03 (deployed commit 6429124)

Real-time bot that scans PL/EN/UA/RU media for military attacks or invasions that target Poland and
the Baltic states. It runs live in production on a Hetzner VPS.

Live alert routing (per tier in `alerts.urgency_levels` in `config/config.yaml`):
- Urgency 9–10: a Twilio phone call, a confirmation-code SMS and an additive Expo push.
- Urgency 5–8: Expo push to the companion iPhone app only (`channel: push`). The owner switched SMS
  off for these tiers on purpose.
- The owner keeps the Twilio account unfunded on purpose. Since 2026-09-21 every Twilio call and SMS
  fails with HTTP 401 (account not active). This is a known state, not an outage or a bug. Phone
  calls stay configured and return when the owner recharges the account.

A separate read-only Article Dashboard (`dashboard/`) is local-only and not part of the monitoring
runtime. Its rules live in [`dashboard/CLAUDE.md`](dashboard/CLAUDE.md) and load when you work in
that subtree. Mobile app rules: [`mobile/AGENTS.md`](mobile/AGENTS.md).

## Critical rules (always honor)
- ⚠️ **NEVER modify production server files** without explicit user permission — ask first.
  Read-only commands (logs, health, DB queries) on the server are fine.
- ⚠️ **Never miss urgency 9–10.** This is a life-safety alert system: no quiet hours, call at any hour.
- SSH only as `deploy@`: `ssh -p 2222 deploy@178.104.76.254`. `root@` and `kossa@` trigger fail2ban bans.
- Run and test locally by default. Keep credentials in a local `.env` (template `.env.example`):
  Twilio, OpenAI (`OPENAI_API_KEY`) and Telegram. Add `EXPO_PUSH_TOKEN` and `EXPO_ACCESS_TOKEN` by
  hand; the template lacks them (TODO.md). `ANTHROPIC_API_KEY` is only for the legacy Haiku rollback.
- Alerts are in Polish. Source scanning covers PL/EN/UA/RU.
- Don't spam. Each dispatch of an unacknowledged critical event places one round of calls;
  `alerts.acknowledgment.max_call_retries` sets the calls per round. The owner acknowledges it by replying with the SMS confirmation code. An unacknowledged event is called again
  only when a later article joins it (no scheduled re-call; see TODO.md). After acknowledgement, only
  an incident-memory escalation (a new `notification_revision`) sends an update SMS and push.
- Corroboration: today one source is enough to trigger a phone call. The call gate is
  `alerts.urgency_levels.critical.corroboration_required`, which allows a single source;
  `classification.corroboration_required` only sets the event's provisional `alert_status` label
  and does not gate the call. Whether to require a second independent source is an open owner decision in
  TODO.md. Rules: [`.claude/rules/corroboration.md`](.claude/rules/corroboration.md) and the
  [config reference](docs/reference/config-reference.md). Do not restate the numbers here.
- Nothing is hardcoded: keywords, sources, countries, thresholds and URLs live in
  `config/config.yaml`. Known exceptions are the corroborator's urgency cuts, `_MIN_EVENT_URGENCY`
  and `EVENT_COMPATIBILITY` (see corroboration.md).
- Classifier: `classification.provider` and `classification.model` in `config/config.yaml` choose the
  live model. Today that is OpenAI via `sentinel/classification/openai_provider.py`. Anthropic Haiku
  is the legacy rollback path only; it is also the code default in `sentinel/config.py`. Paid calls
  are capped by `classification.budget`; when the cap is used up, classification pauses and articles
  stay pending.
- Every phase passes its tests before the next begins.

## Quick reference
- Config: `config/config.yaml` is tracked and is the live production config. `/deploy` copies it to
  `/etc/sentinel/config.yaml` and stops if the server copy has its own edits. Edit and commit it
  here; never hand-edit the server copy. The repo is public, so secrets appear only as `${VAR}`
  placeholders resolved from `/etc/sentinel/sentinel.env`. Template: `config/config.example.yaml`.
  Code defaults in `sentinel/config.py` differ from the live values, so always check the YAML.
- Local runs: the tracked config uses server paths under `/var/lib/sentinel` and `/var/log/sentinel`.
  Pass `--config <local copy>` with `data/` paths (see getting-started).
- Run: `./run.sh` · once: `--once` · dry run: `--dry-run` · health: `--health` · log level: `--log-level DEBUG`
- Diagnostic: `./run.sh --diagnostic` writes `diagnostic.html` next to the configured database. It
  makes live, paid classifier calls but sends no alerts.
- Test one headline: `./run.sh --test-headline "…"` · headline file (YAML with a `headlines:` list): `--test-file FILE`
- Classifier eval harness: `./run.sh --eval [PATH]` (default `tests/fixtures/eval_set.yaml`). It exits
  non-zero unless every case passes; no CI is configured.
- Test a real alert: `./run.sh --test-alert` (phone call) · `--test-alert sms` · `--test-alert push`.
  Call and SMS fail with 401 while the Twilio account is unfunded.
- Cost: `--eval`, `--test-headline`, `--test-file` and `--diagnostic` spend real OpenAI money.
- Tests: `.venv/bin/pytest tests/ -v` · Full CLI: [docs/reference/cli.md](docs/reference/cli.md)
- Stack: YAML config · SQLite · APScheduler dual-lane (fast lane `scheduler.fast_interval_minutes`:
  Telegram + priority-1 RSS + Google News; slow lane `scheduler.interval_minutes`: all enabled sources).

## Docs (link, don't restate — `docs/` follows Diátaxis)
- Index: [docs/README.md](docs/README.md)
- Server ops / deploy / troubleshooting: [docs/how-to/server-runbook.md](docs/how-to/server-runbook.md) — read first for anything server-related
- Architecture → [docs/explanation/architecture.md](docs/explanation/architecture.md) · Pipeline → [docs/explanation/pipeline.md](docs/explanation/pipeline.md) · Mobile app → [docs/explanation/mobile-app.md](docs/explanation/mobile-app.md)
- Config params → [docs/reference/config-reference.md](docs/reference/config-reference.md) · Sources → [docs/reference/sources.md](docs/reference/sources.md) · CLI → [docs/reference/cli.md](docs/reference/cli.md) · Luna deployment and rollback record → [docs/reference/luna-deployment-20260920.md](docs/reference/luna-deployment-20260920.md)
- Local setup → [docs/tutorials/getting-started.md](docs/tutorials/getting-started.md) · API setup → [docs/how-to/api-setup.md](docs/how-to/api-setup.md) · Testing → [docs/how-to/testing.md](docs/how-to/testing.md) · Model comparison (eval only) → [docs/how-to/model-comparison.md](docs/how-to/model-comparison.md) · Mobile push verification → [docs/how-to/mobile-push-setup.md](docs/how-to/mobile-push-setup.md) · Mobile inbox verification → [docs/how-to/mobile-inbox-verification.md](docs/how-to/mobile-inbox-verification.md) · VPS hardening → [docs/how-to/security/vps-hardening.md](docs/how-to/security/vps-hardening.md)
- Dashboard spec (living) → [SPEC.md](SPEC.md) · Backlog → [TODO.md](TODO.md) · Design notes and plans → [docs/ideas/](docs/ideas/) · Historic specs → [docs/archive/](docs/archive/README.md)

## Gotcha: project rename history
Renamed twice (`twilio-playground` → `sentinel` → `project-sentinel`). If imports fail with old
paths, recreate the venv: `rm -rf .venv && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
and clear `__pycache__` dirs.
