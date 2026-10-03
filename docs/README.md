# Project Sentinel — Documentation

Last verified: 2026-10-03 (deployed commit 6429124)

This documentation is organized using the [Diátaxis](https://diataxis.fr/) framework, which sorts docs into four types by the need they serve:

- **Tutorials** — learning-oriented. A guided first run for a newcomer.
- **How-to guides** — task-oriented. Recipes that get a specific job done.
- **Reference** — information-oriented. Dry, exhaustive lookup material.
- **Explanation** — understanding-oriented. The "why" and "how it works".

When adding a new doc, decide which of these four needs it serves and place it in the matching folder. Plans, evaluation records and design notes that fit none of the four go in `ideas/`. Completed or superseded material goes in `archive/`.

## Tutorials

- [tutorials/getting-started.md](tutorials/getting-started.md) — clone, configure, and run Sentinel locally for the first time.

## How-to guides

- [how-to/api-setup.md](how-to/api-setup.md) — set up the direct OpenAI API (Luna, the live classifier), Twilio, Expo Push and Telegram credentials. GDELT and Google News need no setup. Anthropic is the legacy rollback provider only.
- [how-to/testing.md](how-to/testing.md) — dry runs, test fixtures, the eval harness, and manual alert testing.
- [how-to/mobile-push-setup.md](how-to/mobile-push-setup.md) — verify a push end-to-end (token → backend → Expo → phone), put a new device token in place, or re-provision from scratch. Push is live; the EAS project is already linked.
- [how-to/mobile-inbox-verification.md](how-to/mobile-inbox-verification.md) — on-device checklist (MA-1…MA-7) for the in-app message inbox: tap-to-Detail, tray-sweep, foreground receive, in-app source links, the app-icon badge, and delete/clear persistence.
- [how-to/model-comparison.md](how-to/model-comparison.md) — run the offline, evaluation-only comparison of candidate classifier models (fixtures, validation without a key, paid runs). It sends no alerts and does not change production.
- [how-to/server-runbook.md](how-to/server-runbook.md) — production server access, file layout, service management, deployment, and troubleshooting. Read this first for anything server-related.
- [how-to/security/vps-hardening.md](how-to/security/vps-hardening.md) — harden the VPS before deployment. (Index: [how-to/security/README.md](how-to/security/README.md).)

## Reference

- [reference/config-reference.md](reference/config-reference.md) — every configurable parameter in `config/config.yaml`.
- [reference/sources.md](reference/sources.md) — every monitored media source with URLs/RSS.
- [reference/cli.md](reference/cli.md) — every command-line flag for `sentinel.py` and the dashboard CLI.

## Explanation

- [explanation/architecture.md](explanation/architecture.md) — system design, module map, components, and data flow.
- [explanation/pipeline.md](explanation/pipeline.md) — step-by-step data flow from source collection through classification and corroboration to alert delivery (push, phone call, SMS).
- [explanation/mobile-app.md](explanation/mobile-app.md) — the `mobile/` Expo companion app: the push-alert channel and the in-app message inbox.

## Records (dated, not current truth)

- [reference/luna-deployment-20260920.md](reference/luna-deployment-20260920.md) — the 2026-09-20 Luna deployment and rollback record. Production has moved on since then. Use the [server runbook](how-to/server-runbook.md) for the current state. The file stays in `reference/` because the runbook links to it there.

## Ideas, plans and evaluation records

- [`ideas/`](ideas/) — dated working notes: feature plans, a handoff prompt, model-comparison plans, label reviews and run records, and design notes. They are append-only and are not current truth. Some describe features that are now live, but their status lines may be out of date. On any conflict, the living docs above and the code win. Living docs cite these files:
  - [ideas/polish-summary-guard.md](ideas/polish-summary-guard.md) and [ideas/incident-memory-plan.md](ideas/incident-memory-plan.md) — design and verification notes cited by the config reference.
  - [ideas/luna-direct-api-migration-plan.md](ideas/luna-direct-api-migration-plan.md) — the Luna migration plan cited by the API setup guide.
  - [ideas/model-comparison-labels.md](ideas/model-comparison-labels.md) and [ideas/model-comparison-v2-plan.md](ideas/model-comparison-v2-plan.md) — label inventory and evaluation plan cited by the model-comparison guide.

## Archive

- [archive/README.md](archive/README.md) — historic implementation specs, handoffs (including the obsolete June 2026 mobile worktree brief), and prompt scaffolding. These describe how features were *built*; do not consult them as current truth.

---

Two living documents stay at the repository root: [SPEC.md](../SPEC.md) is the source-of-truth spec for the read-only dashboard subsystem, and [TODO.md](../TODO.md) is the project backlog. Where the code has moved on, dated `[AMENDMENT]` banners in SPEC.md say so; read them before the section they sit above.

Other root and `mobile/` files are dated records, not current truth: [DECISIONS.md](../DECISIONS.md) (decision log of the unmerged July 2026 redesign run), `review_report_pending.md` (an untracked local review of an unmerged branch, present only in some checkouts), and [mobile/PUSH_APP_SPEC.md](../mobile/PUSH_APP_SPEC.md) and [mobile/INBOX_APP_SPEC.md](../mobile/INBOX_APP_SPEC.md) (completed specs). For current mobile behaviour, read [explanation/mobile-app.md](explanation/mobile-app.md).
