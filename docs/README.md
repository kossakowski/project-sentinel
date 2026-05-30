# Project Sentinel — Documentation

This documentation is organized using the [Diátaxis](https://diataxis.fr/) framework, which sorts docs into four types by the need they serve:

- **Tutorials** — learning-oriented. A guided first run for a newcomer.
- **How-to guides** — task-oriented. Recipes that get a specific job done.
- **Reference** — information-oriented. Dry, exhaustive lookup material.
- **Explanation** — understanding-oriented. The "why" and "how it works".

When adding a new doc, decide which of these four needs it serves and place it in the matching folder.

## Tutorials

- [tutorials/getting-started.md](tutorials/getting-started.md) — clone, configure, and run Sentinel locally for the first time.

## How-to guides

- [how-to/api-setup.md](how-to/api-setup.md) — set up Anthropic, Twilio, and Telegram accounts and credentials.
- [how-to/testing.md](how-to/testing.md) — dry runs, test fixtures, the eval harness, and manual alert testing.
- [how-to/server-runbook.md](how-to/server-runbook.md) — production server access, file layout, service management, deployment, and troubleshooting. Read this first for anything server-related.
- [how-to/security/vps-hardening.md](how-to/security/vps-hardening.md) — harden the VPS before deployment. (Index: [how-to/security/README.md](how-to/security/README.md).)

## Reference

- [reference/config-reference.md](reference/config-reference.md) — every configurable parameter in `config/config.yaml`.
- [reference/sources.md](reference/sources.md) — every monitored media source with URLs/RSS.
- [reference/cli.md](reference/cli.md) — every command-line flag for `sentinel.py` and the dashboard CLI.

## Explanation

- [explanation/architecture.md](explanation/architecture.md) — system design, module map, components, and data flow.
- [explanation/pipeline.md](explanation/pipeline.md) — step-by-step data flow from source collection to phone alert.
- [explanation/mobile-app.md](explanation/mobile-app.md) — the `mobile/` Expo companion app and the push-alert channel.

## Archive

- [archive/README.md](archive/README.md) — historic implementation specs, handoffs, and prompt scaffolding. These describe how features were *built*; do not consult them as current truth.

---

Two living documents stay at the repository root: [SPEC.md](../SPEC.md) is the source-of-truth spec for the read-only dashboard subsystem, and [TODO.md](../TODO.md) is the project backlog.
