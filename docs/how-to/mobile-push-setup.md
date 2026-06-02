# How-to: Provision and verify the mobile push end-to-end

This runbook walks the owner through proving that an Expo push leaves the Sentinel backend,
travels through the Expo push service, and lands on the physical iPhone — token to backend to
Expo to phone. It is the manual companion to the in-app **PushPanel** (which mints the token and
now also shows the most recently received push for on-device confirmation).

> **Why this is a manual runbook.** Steps 1–2 below require interactive `eas`/Apple logins tied
> to the owner's own Expo and Apple Developer accounts. The automated implementation loop does
> **not** and **cannot** perform them: it has no credentials, cannot complete an interactive
> login, and must not hardcode a real `projectId` into source. Everything in steps 1–2 is the
> owner's to run by hand on their own machine and device. Steps 3–7 are likewise run by the
> owner, on the device and against the owner-controlled config.

## Prerequisites

- An **Expo account** and the Expo CLI available via `npx` (no global install needed).
- An **active Apple Developer account** (required to build a development build to a physical
  iPhone).
- A physical **iPhone** — push tokens are not issued on the iOS simulator (the app reports
  `must-use-physical-device`).
- The Sentinel backend checked out locally, with its `config.yaml` (the runbook edits the config
  the backend actually reads; on the production server that is `/etc/sentinel/config.yaml`, not a
  repo copy — see [server-runbook.md](server-runbook.md)).

---

## Step 1 — Provision a real EAS `projectId` (MANUAL, interactive)

`mobile/app.json` ships a **placeholder** `extra.eas.projectId`
(`00000000-0000-0000-0000-000000000000`). Without a real one the Expo push service cannot mint a
token. Replace it by letting `eas` write it for you — do **not** hand-edit a real id into source.

```bash
# From the mobile/ directory, on the owner's machine:
npx eas login                 # interactive — Expo account credentials
npx eas init                  # creates the EAS project and writes the real projectId
# (or, on an already-linked project: npx eas build:configure)
```

`eas init` updates `app.json`'s `extra.eas.projectId` in place with the real value. This is an
**interactive, credential-bound step the automated loop cannot do** — the placeholder is replaced
by `eas`, never hardcoded by the spec or by an agent.

## Step 2 — Build a development build to the iPhone and grant permission (MANUAL, interactive)

```bash
# From mobile/, on the owner's machine — interactive Apple login + device provisioning:
npx eas build --profile development --platform ios
```

Install the resulting development build on the physical iPhone, open it, and **grant the
notification permission** when prompted. (This step is interactive and Apple-credential-bound; the
automated loop cannot perform it.)

## Step 3 — Copy the Expo push token from the PushPanel

In the running app, tap **PUSH** to open the PushPanel. Once permission is granted the panel shows
the `ExponentPushToken[...]` value. Tap **KOPIUJ TOKEN** to copy it (it is also logged to the Metro
console as `[push] Expo token: ...`).

## Step 4 — Paste the token into the config and enable push

Edit the config the backend reads (locally `config/config.yaml`; on the server
`/etc/sentinel/config.yaml`) and set the `alerts.push` block:

```yaml
alerts:
  push:
    enabled: true
    tokens:
      - "ExponentPushToken[xxxxxxxxxxxxxxxxxxxxxx]"   # the token copied in Step 3
```

While `enabled: false` or `tokens` is empty, the backend no-ops on push (this is the shipped,
behavior-preserving default — SMS only).

## Step 5 — Set the desired per-tier `channel`

Choose how each SMS tier is delivered. The `channel` field on each `urgency_levels` entry takes
`sms`, `push`, or `both` (default `both`). It applies to the `high` (7–8) and `medium` (5–6)
tiers; it is ignored for `critical` (9–10, which always places the call plus an additive push) and
for `log_only` (1–4).

```yaml
alerts:
  urgency_levels:
    high:
      channel: push     # route this tier to push only (cuts its Twilio SMS cost), or "both"/"sms"
    medium:
      channel: both
```

See [config-reference.md](../reference/config-reference.md) for the full field description.

## Step 6 — Fire a test push from the backend

```bash
./run.sh --test-alert push
```

This sends a real Expo push to every token in `alerts.push.tokens`. If push is not configured the
command exits with a message telling you to set `alerts.push.enabled: true` and add a token first.

## Step 7 — Confirm receipt on the phone and in the panel

Confirm that:

1. A push notification **appears on the iPhone** (banner / lock screen), and
2. Opening the PushPanel shows the same push under **OSTATNI PUSH** (title + body) — the in-app
   surface fed by the received-notification listener.

If both happen, the full path — token → backend → Expo → phone → in-app panel — is verified.

> **Foreground vs. background.** The **OSTATNI PUSH** panel is fed by the foreground
> received-notification listener, so a push that arrives while the app is **open** shows in the
> panel immediately. A push delivered while the app is **backgrounded or closed** reaches the panel
> only after you **tap** the notification (handled by the response listener). To verify cleanly,
> keep the app open when you fire Step 6 — or tap the notification before checking the panel, so an
> empty panel is not mistaken for a delivery failure.

---

## Notes and caveats

- A normal Expo push does **not** bypass silent mode / Do-Not-Disturb. For the urgency 9–10 path
  the Twilio **voice call remains the primary wake-up**; the push is **additive** (extra
  visibility). A DND-bypassing alert would require Apple **Critical Alerts**, a separate
  entitlement that is out of scope here.
- This procedure exercises Phase 1 backend routing. Run it only after the per-tier `channel`
  routing is in place and push is enabled per the steps above.
- Token entry is **manual copy-paste** by design (single owner, single device): there is no
  HTTP token-registration endpoint and no server ingress is opened for this.
