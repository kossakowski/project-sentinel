# Mobile inbox — on-device verification (MA-1…MA-7)

Last verified: 2026-10-03 (deployed commit 6429124)

This is the manual, on-device checklist for the in-app message inbox (the
`INBOX_APP_SPEC.md` Phase 3 UI). It is non-gating: the automated gates are
JS-only (`npm test` and `npm run typecheck` from `mobile/`). The behaviours below
can only be confirmed on a physical iPhone running a build that includes the
navigation + web-browser native modules; Expo Go cannot validate this. The inbox
has been live since 2026-06-03; re-run this checklist after every new build.

For server-side push setup and token handling, see
[`mobile-push-setup.md`](mobile-push-setup.md).

## Before you start

1. Build and install a fresh build on the iPhone:
   `npx eas build --profile preview --platform ios` (from `mobile/`) is the
   standalone build the owner uses. `--profile development` gives a dev-client
   build that needs Metro (`npm start`).
2. Open the app once and tap ⚙ (top-right of the inbox header). Grant the
   notification permission (alert + badge + sound) and copy the Expo push token.
   Set `EXPO_PUSH_TOKEN` to this token in the local `.env` (and, owner only, in
   `/etc/sentinel/sentinel.env` on the server). `config/config.yaml` already
   references `${EXPO_PUSH_TOKEN}`; never paste the token into it, because the
   repo is public. Details: [`mobile-push-setup.md`](mobile-push-setup.md) Step 4.
3. Make sure the local `.env` also defines `EXPO_ACCESS_TOKEN`. Without
   `EXPO_PUSH_TOKEN`, every `./run.sh` command that loads `config/config.yaml`
   fails at config load. Check
   without printing values:
   `grep -c -E '^(EXPO_PUSH_TOKEN|EXPO_ACCESS_TOKEN)=' .env` (expected: 2).
4. Prepare a local config with push enabled: copy the template to the git-ignored
   `data/config.local.yaml` and enable push there, as in
   [`mobile-push-setup.md`](mobile-push-setup.md) Step 6. Do not run the tests
   without `--config`: the default `config/config.yaml` is the production config,
   and its server-only log and DB paths make the command fail on a workstation.
   Do not run them on the server either; there they write `[TEST]` rows into the
   production DB.
5. Fire test alerts with `./run.sh --config data/config.local.yaml --test-alert push`;
   every MA check needs only push. Known state: the owner deliberately leaves the
   Twilio account unfunded, so `--test-alert sms` and `--test-alert` (the urgency
   9–10 call) return HTTP 401 until the owner recharges the account.

## Checklist

- **MA-1 — Tap opens Detail.** Run `./run.sh --config data/config.local.yaml --test-alert push`. A banner appears.
  Tap it → the app opens directly to **that message's Detail screen** (header,
  urgency, countries, aggressor when present, summary, sources, detection time).
  Works both warm (app running) and cold (app killed — the tap launches it).

- **MA-2 — Cold-open tray sweep.** With one or more unread Sentinel alerts sitting
  in the iOS notification tray (received while the app was closed), cold-open the
  app. They appear in the inbox list (captured by the **tray-sweep on open**, not a
  server round-trip), and the app removes them from the Notification Center once
  they are stored (`dismissFromTray`).

- **MA-3 — Foreground receive.** With the app foregrounded on the list, send a push
  (`./run.sh --config data/config.local.yaml --test-alert push`). It appears in the list **immediately** (the
  foreground-received capture path), newest at the top.

- **MA-4 — In-app browser link.** Open a message in Detail and tap a source row that
  has a link → the article opens in the **in-app browser** (SFSafariViewController);
  tapping **Done** returns to Detail. A source with no URL renders as plain
  (non-tappable) text.

- **MA-5 — App-icon badge.** The app-icon **unread count badge** reflects the number
  of unread messages, and **clears** as messages are read (opening a message marks
  it read; "✓" marks all read). _If the badge never appears, re-check that the badge
  permission was granted — an ungranted `allowBadge` makes the badge a silent no-op._

- **MA-6 — Background receive _(best-effort; mostly via the tray-sweep)_.** Receive a
  push while the app is **backgrounded**, do **not** tap it, then reopen the app → it
  appears in the list. **This is best-effort.** Because the push is **visible**
  (title + body present), iOS will **usually not** run the headless background task,
  and Apple throttles silent wakes and will not wake a force-quit app; in practice
  this capture comes from the **tray-sweep on app open** (MA-2/MA-3 paths), with the
  background task as an occasional bonus. By design the urgency 9–10 Twilio call is
  the wake-up and the inbox is visibility + history only; while the Twilio account is
  unfunded, the push is the only alert that reaches the phone.

- **MA-7 — Delete + Clear-all, with confirm, persistent.** In Detail, tap **Usuń**
  (delete) → confirm → the message is removed and you return to the list. On the list,
  tap **Wyczyść** (clear all) → confirm → the list empties. Both actions **survive a
  full app restart** (AsyncStorage is the source of truth).
