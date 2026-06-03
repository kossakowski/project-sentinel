# Mobile Push App — START HERE

**Worktree branch:** `mobile-push-app` (base: `master` @ df4f6ea). Created 2026-06-01.

## Why this folder exists
Isolated parallel workspace to build the iOS **push-notification** test app, to cut the Twilio bill
(~$150 in May). The MAIN repo — the *paused* classification/alerting redesign + dedup-eval work —
lives at `/home/kossa/code/project-sentinel` on branch `docs-overhaul`. **Don't touch it**; this
separate worktree exists precisely so the two efforts don't interfere.

## Goal & scope
Build/finish a minimal Expo (React Native) iOS app that:
1. registers an **Expo push token** on the owner's iPhone,
2. receives a **test push end-to-end** (token → backend → Expo → phone), then
3. wires push to the alert tiers to **REPLACE Twilio SMS** (event updates + urgency 7–8).

**OUT OF SCOPE / do NOT do:** replacing the urgency **9–10 phone CALL** with push. A normal push is
not a Do-Not-Disturb-bypassing 3am wake-up; Apple **Critical Alerts** is a *separate* entitlement
(special approval, pending). 9–10 stays on Twilio voice.

## What already exists (research it before building)
- **`mobile/`** — an existing Expo app scaffold: `App.tsx`, `app.json`, `eas.json`, `index.ts`,
  `package.json` (+ lockfile), `tsconfig.json`, a **`push/`** dir, `designs/`, `assets/`, plus
  `mobile/AGENTS.md` and `mobile/CLAUDE.md`. **Start here.**
- **Backend** (same repo, eventually deploys): `sentinel/alerts/push_client.py` = `ExpoPushClient` —
  currently a **no-op** (Expo `projectId` not provisioned + push disabled in config under
  `alerts.push`). Reference design: `docs/explanation/mobile-app.md`. Local test path:
  `./run.sh --test-alert push`.

## Unblocker
Apple Developer account became **ACTIVE 2026-06-01** — needed for a real iOS dev build + APNs. Owner
tests on **iPhone (iOS)**, not Android.

## Work split
- **(A) Expo app** — new/isolated, safe to move fast.
- **(B) backend push enablement** — provision the Expo `projectId`, add a token-registration route,
  enable push in config. This touches the **live alert path**: test locally, **do NOT deploy**. The
  owner runs `/deploy` after merge + local verification.

## Gotchas
- This worktree has **no Python `.venv`** (gitignored, not copied). To run the backend here:
  `python -m venv .venv && .venv/bin/pip install -r requirements.txt`, or run the backend from the
  main checkout. Node deps: `cd mobile && npm install`.
- Merge to `master` + `/deploy` **only after local verification**. Never modify the production server directly.

## Suggested flow
`/spec-forge` (it will research `mobile/` + `push_client.py` + `mobile-app.md`) → then
`/workflow-code-refiner` to implement.
