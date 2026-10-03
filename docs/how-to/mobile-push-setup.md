# How-to: Provision and verify the mobile push end-to-end

Last verified: 2026-10-03 (deployed commit 6429124)

This runbook walks the owner through proving that an Expo push leaves the Sentinel backend,
travels through the Expo push service, and lands on the physical iPhone — token to backend to
Expo to phone. Push has been live in production since 2026-06-03, so most steps are already
done. Use this page to re-check delivery, to put a new device token in place after a reinstall
or a new phone, or to re-provision from scratch. For background, see
[mobile-app.md](../explanation/mobile-app.md).

> **Why this is a manual runbook.** Steps 1–3 need interactive `eas` and Apple logins tied to
> the owner's own Expo and Apple Developer accounts, and the physical phone. An agent has no
> such credentials and cannot complete an interactive login. Step 4 on the server is a write
> to a production secrets file, which only the owner does or explicitly permits.

Contents: [Prerequisites](#prerequisites) · [1. EAS link](#step-1--eas-project-link-already-done) ·
[2. Build](#step-2--build-install-and-grant-permission) · [3. Token](#step-3--copy-the-expo-push-token) ·
[4. Environment](#step-4--put-the-token-into-the-environment-not-into-config) ·
[5. Channel](#step-5--per-tier-channel-no-action-needed-in-production) ·
[6. Test push](#step-6--fire-a-test-push-from-the-local-machine) ·
[7. Receipt](#step-7--confirm-receipt-on-the-phone) · [Notes](#notes-and-caveats)

## Prerequisites

- The Expo account that owns the EAS project (`owner` in `mobile/app.json`), and the Expo
  CLI via `npx` (no global install needed).
- An active Apple Developer account (needed to build to a physical iPhone).
- A physical iPhone. Push tokens are not issued on the iOS simulator (the app reports
  `must-use-physical-device`).
- A local config for test runs: `config/config.yaml` is the production config and cannot run
  on a workstation (server-only log and DB paths). Copy the template to the git-ignored
  `data/config.local.yaml` (`cp config/config.example.yaml data/config.local.yaml`); Step 6
  enables push in it.
- A local checkout whose `.env` defines `EXPO_PUSH_TOKEN` (the device token) and
  `EXPO_ACCESS_TOKEN` (the Expo robot access token; see
  [api-setup.md](api-setup.md), section "Expo Push"). Without
  `EXPO_PUSH_TOKEN`, every `./run.sh` command that loads `config/config.yaml` fails at config
  load with `Error: Environment variable 'EXPO_PUSH_TOKEN' is not set (referenced as ${EXPO_PUSH_TOKEN} in config)`. `.env.example` does not
  list these keys yet (tracked in `TODO.md`). Check that both keys exist without printing
  their values:

  ```bash
  grep -c -E '^(EXPO_PUSH_TOKEN|EXPO_ACCESS_TOKEN)=' .env    # expected: 2
  ```

---

## Step 1 — EAS project link (already done)

`mobile/app.json` has been linked to the EAS project since 2026-06-02 (commit 7181f16):
`extra.eas.projectId` holds the real project id and `owner` is `beepbeepjeep`. Do not run
`eas init` on this checkout; it is unnecessary and could re-link the project.

Check the link:

```bash
grep -n -E '"projectId"|"owner"' mobile/app.json   # expected: a non-zero UUID and "beepbeepjeep"
```

Only if you re-provision from scratch (new Expo account or project), run from `mobile/` on the
owner's machine:

```bash
npx eas login    # interactive — Expo account credentials
npx eas init     # creates the EAS project and writes the projectId into app.json
```

Never hand-edit a project id into source; let `eas` write it.

## Step 2 — Build, install and grant permission

1. From `mobile/`, build the standalone build the owner uses:

   ```bash
   npx eas build --profile preview --platform ios
   ```

   For a development client instead, use `--profile development`; that build loads JS from
   Metro (`npm start`).
2. Install the build on the iPhone and open it.
3. Grant the notification permission (alert + badge + sound) when prompted.

## Step 3 — Copy the Expo push token

1. On the inbox screen, tap ⚙ at the top right of the header. The push panel
   "POWIADOMIENIA PUSH" opens.
2. Once permission is granted, the panel shows the `ExponentPushToken[...]` value.
3. Tap "KOPIUJ TOKEN" to copy it. A development build also logs it to the Metro console as
   `[push] Expo token: ...`.

Treat the token as a secret: do not paste it into chat, docs, commits or issues.

## Step 4 — Put the token into the environment, not into config

The tracked `config/config.yaml` already has `alerts.push.enabled: true` and
`tokens: ["${EXPO_PUSH_TOKEN}"]`. `sentinel/config.py` replaces the placeholder with the
environment value at load time. Do not change that block. Never paste a literal token into
`config/config.yaml`: the repo is public, and `tests/test_config.py` asserts the placeholder.

1. Local runs: set `EXPO_PUSH_TOKEN=<the copied token>` in `.env`. Verify with the `grep`
   command under Prerequisites (expected: 2).
2. Server (owner only — this writes a production secrets file and needs the owner's explicit
   permission): set `EXPO_PUSH_TOKEN` in `/etc/sentinel/sentinel.env`, then restart the
   service so systemd reloads the file.

   ```bash
   sudo nano /etc/sentinel/sentinel.env
   sudo systemctl restart sentinel
   sudo sed 's/=.*//' /etc/sentinel/sentinel.env   # key names only; expect EXPO_PUSH_TOKEN and EXPO_ACCESS_TOKEN
   sudo systemctl is-active sentinel               # expected: active
   ```

   `/deploy` never touches `sentinel.env`. Never hand-edit `/etc/sentinel/config.yaml`:
   config changes go through `config/config.yaml`, a commit and `/deploy`, and `/deploy`
   step 6a stops on server-only edits. See [server-runbook.md](server-runbook.md#secrets).

If push is disabled or no token is set, tiers with `channel: push` deliver nothing, and the
urgency 9–10 push is skipped.

## Step 5 — Per-tier `channel` (no action needed in production)

Each `alerts.urgency_levels` entry for the SMS tiers takes `channel: sms | push | both`. It
applies to `high` (7–8) and `medium` (5–6). It is ignored for `critical` (9–10, which always
places the call plus an additive push) and for `log_only` (1–4).

Production sets both `high` and `medium` to `push`, so tiers 5–8 are push-only by owner
decision; SMS for them is switched off on purpose. The code default and the template use
`both`. To change a tier, edit `config/config.yaml`, commit, and run `/deploy`. See
[config-reference.md](../reference/config-reference.md) for the field description.

## Step 6 — Fire a test push from the local machine

Run the test against the local config from Prerequisites, not against `config/config.yaml`.
Without `--config`, `sentinel.py` loads the production config, whose log and DB paths
(`/var/log/sentinel`, `/var/lib/sentinel`) do not exist on a workstation, so the command fails
before any push is sent.

1. In `data/config.local.yaml` (git-ignored, never committed), enable push:

   ```yaml
   alerts:
     push:
       enabled: true
       tokens: ["${EXPO_PUSH_TOKEN}"]
   ```

2. Send the test push:

   ```bash
   ./run.sh --config data/config.local.yaml --test-alert push
   ```

This sends one real Expo push to the token resolved from `EXPO_PUSH_TOKEN`. It bypasses the
per-tier routing of the alert state machine (it calls the push method directly), so it does
not test per-tier routing. It writes a synthetic `[TEST]` article and event to the DB of the
loaded config (`data/sentinel.db` for the template). Do not run it on the server: there it
writes `[TEST]` rows into the production DB, which needs the owner's explicit permission.
The last line of the expected output starts with `Test alert dispatched.` If push is disabled or no token is set, it
prints `Push is not configured. ...` and sends nothing.

## Step 7 — Confirm receipt on the phone

1. A push notification appears on the iPhone (banner or lock screen).
2. The push appears as a new tile at the top of the inbox list. With the app open, this
   happens at once (foreground capture). With the app closed, it appears after you reopen the
   app (tray sweep).
3. Tapping the banner opens that message's Detail screen.

Once the message is in the inbox, the app removes the notification from the iOS
Notification Center (`dismissFromTray`). That is expected, not a delivery failure. The
"OSTATNI PUSH" section of the push panel is inert and always shows
"brak (jeszcze nic nie odebrano)"; ignore it. The full inbox checklist is
[mobile-inbox-verification.md](mobile-inbox-verification.md) (MA-1 and MA-3 cover this step).

For a real production alert, the server log shows each send (read-only):

```bash
sudo grep 'push_client' /var/log/sentinel/sentinel.log | tail -5   # expected: "Push sent for event … to 1 token(s)"
```

`Expo push failed` or `no tickets accepted` means the send was rejected; check that both
Expo keys exist in `sentinel.env`.

---

## Notes and caveats

- A normal Expo push does not bypass silent mode or Do Not Disturb. By design, the Twilio
  voice call is the primary wake-up for urgency 9–10 and the push is additive. A
  DND-bypassing alert would need Apple Critical Alerts, a separate entitlement that is
  pending.
- Known state: the owner deliberately leaves the Twilio account unfunded. Since 2026-09-21
  every call and SMS fails with HTTP 401, so the push is the only delivery that reaches the
  phone. Calls return when the owner recharges the account. See
  [server-runbook.md](server-runbook.md#troubleshooting).
- According to the owner's record from 2026-06-04, Expo "Enhanced Security for Push
  Notifications" is on for the EAS project, so a send without `EXPO_ACCESS_TOKEN` is
  rejected.
- Token entry is a manual copy by design (single owner, single device): there is no HTTP
  token-registration endpoint and no server ingress is opened for this.
