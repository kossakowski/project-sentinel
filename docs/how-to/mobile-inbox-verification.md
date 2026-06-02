# Mobile inbox — on-device verification (MA-1…MA-7)

This is the manual, on-device checklist for the in-app message inbox (the
`INBOX_APP_SPEC.md` Phase 3 UI). It is **non-gating** — the automated gates are
JS-only (Jest + `tsc`); the behaviours below can only be confirmed on a physical
iPhone running a **fresh dev build** (the navigation + web-browser native modules
mean Expo Go cannot validate this — rebuild with `eas build` / a local dev build).

For server-side push setup and the token-paste flow, see
[`mobile-push-setup.md`](mobile-push-setup.md).

## Before you start

1. Build and install a fresh dev build on the iPhone (native deps were added).
2. Open the app once, go to **⚙ Settings** (top-right of the inbox header), grant
   the notification permission (alert + **badge** + sound), copy the Expo push
   token, and paste it into the server `config/config.yaml` push tokens list.
3. Fire test alerts locally with `./run.sh --test-alert push` (push only),
   `./run.sh --test-alert sms`, or `./run.sh --test-alert` (the urgency 9–10 call).

## Checklist

- **MA-1 — Tap opens Detail.** Run `./run.sh --test-alert push`. A banner appears.
  Tap it → the app opens directly to **that message's Detail screen** (header,
  urgency, countries, aggressor when present, summary, sources, detection time).
  Works both warm (app running) and cold (app killed — the tap launches it).

- **MA-2 — Cold-open tray sweep.** With one or more unread Sentinel alerts sitting
  in the iOS notification tray (received while the app was closed), cold-open the
  app. They appear in the inbox list (captured by the **tray-sweep on open**, not a
  server round-trip).

- **MA-3 — Foreground receive.** With the app foregrounded on the list, send a push
  (`./run.sh --test-alert push`). It appears in the list **immediately** (the
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
  background task as an occasional bonus. The urgency 9–10 Twilio **call** remains the
  guaranteed wake-up — the inbox is visibility + history only.

- **MA-7 — Delete + Clear-all, with confirm, persistent.** In Detail, tap **Usuń**
  (delete) → confirm → the message is removed and you return to the list. On the list,
  tap **Wyczyść** (clear all) → confirm → the list empties. Both actions **survive a
  full app restart** (AsyncStorage is the source of truth).
