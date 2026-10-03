# Project Sentinel

Last verified: 2026-10-03 (deployed commit 6429124)

Project Sentinel is a real-time monitoring bot that scans PL/EN/UA/RU media sources for military attacks or invasions targeting Poland and the Baltic states. It classifies what it finds with an LLM. Production uses OpenAI (Anthropic Haiku is a legacy rollback path only); the choice is set by `classification.provider` and `classification.model` in `config/config.yaml`. For urgency 9–10 it places a Twilio phone call, plus a confirmation SMS and an app push; urgency 5–8 goes to the companion iPhone app as an Expo push only. Today a single source is enough to trigger a call. The owner keeps the Twilio account unfunded on purpose, so calls and SMS currently fail with HTTP 401 until it is recharged; this is a known state, described in [CLAUDE.md](CLAUDE.md). It runs in production on a Hetzner VPS.

## Start here

- [docs/README.md](docs/README.md) — documentation index (Diátaxis tree: tutorials, how-to, reference, explanation)
- [docs/tutorials/getting-started.md](docs/tutorials/getting-started.md) — local development setup, first run
- [docs/explanation/architecture.md](docs/explanation/architecture.md) — system design, modules, data flow
- [docs/how-to/server-runbook.md](docs/how-to/server-runbook.md) — production server access and operations

See also [CLAUDE.md](CLAUDE.md) for project conventions and development rules, [SPEC.md](SPEC.md) for the dashboard subsystem, and [TODO.md](TODO.md) for the backlog.
