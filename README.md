# Project Sentinel

Project Sentinel is a real-time monitoring bot that scans PL/EN/UA/RU media sources for military attacks or invasions targeting Poland and the Baltic states. It classifies what it finds with Claude Haiku 4.5 and, when a corroborated high-urgency threat is detected, alerts via a Twilio phone call and SMS — with an optional Expo push channel for a companion mobile app. It runs in production on a Hetzner VPS.

## Start here

- [docs/README.md](docs/README.md) — documentation index (Diátaxis tree: tutorials, how-to, reference, explanation)
- [docs/tutorials/getting-started.md](docs/tutorials/getting-started.md) — local development setup, first run
- [docs/explanation/architecture.md](docs/explanation/architecture.md) — system design, modules, data flow
- [docs/how-to/server-runbook.md](docs/how-to/server-runbook.md) — production server access and operations

See also [CLAUDE.md](CLAUDE.md) for project conventions and development rules, [SPEC.md](SPEC.md) for the dashboard subsystem, and [TODO.md](TODO.md) for the backlog.
