# The Mobile Companion App (`mobile/`)

Last verified: 2026-10-03 (deployed commit 6429124)

Status: shipped and live since 2026-06-03. The owner's iPhone runs a standalone EAS `preview`
build, and server push is enabled (see [`TODO.md`](../../TODO.md), mobile inbox section).

**Contents:** [Purpose](#purpose) · [Push channel](#how-it-relates-to-the-push-channel-in-the-runtime) ·
[Current known state](#current-known-state-twilio-unfunded) ·
[Stack](#stack--key-components) · [Running it](#running-it) ·
[What this app is NOT](#what-this-app-is-not) · [Known limitations](#known-limitations) ·
[See also](#see-also)

> **Diátaxis: explanation.** This page explains *what* the `mobile/` app is and *why* it
> exists. It is not the monitoring runtime — it never collects sources, classifies, or
> decides to alert. It is a companion app whose operational jobs are to hand the server a
> device's Expo push token and to receive, store, and display the push alerts the server
> sends as an in-app message inbox.

## Purpose

Project Sentinel's monitoring runtime gained an Expo **push** alert channel (push
notifications) alongside the existing phone call and SMS channels. Each SMS urgency tier
(5–8) carries a per-tier `channel` setting (`sms` / `push` / `both`) that selects how that
tier is delivered. The code default and the template use `both`; production uses `push`, so
tiers 5–8 are push-only (see [Configuration in production](#configuration-in-production)).
The urgency 9–10 call path additionally fires a push — see the push section in
[`architecture.md`](architecture.md). To deliver a push, the server
needs the target device's **Expo push token**, and that token can only be minted *on the
device*.

The `mobile/` app exists to solve that bootstrap problem **and** to give the owner an in-app,
SMS-equivalent history of the alerts that land on the phone. It:

1. Registers the physical device for Expo push notifications and **surfaces the resulting
   Expo push token** (in the Settings/token panel) so you can copy it. The token then goes
   into the environment variable `EXPO_PUSH_TOKEN` (on the server in
   `/etc/sentinel/sentinel.env`), never into a tracked config file — see
   [mobile-push-setup.md](../how-to/mobile-push-setup.md) Step 4.
2. **Receives push alerts** once the token is registered server-side. On Android it uses a
   MAX-importance notification channel so a critical military-threat alert breaks through with
   sound and a heads-up banner. On **iOS** a normal Expo push does **not** bypass silent mode
   or Do Not Disturb — it lands as an ordinary notification respecting the phone's ringer/DND
   state. Breaking through silent mode on iOS requires Apple **Critical Alerts** (a separate
   entitlement, pending). By design the Twilio phone call is the primary 9–10 wake-up and
   the push is supplementary. Today the push is the only alert that reaches the phone (see
   [Current known state](#current-known-state-twilio-unfunded)).
3. **Captures each alert into a persistent on-device inbox** and presents it as a List of
   SMS-style tiles plus a structured Detail screen — the in-app equivalent of the alert SMS,
   surviving restarts and viewable offline. An unread **app-icon badge** tracks unread
   messages, and source article links open in an in-app browser.

That is the whole remit. The app holds no monitoring logic, no classifier, and no Twilio. Its
only persistence is the local inbox; it has no server-side state and never calls back to the
server. It is a thin client for the push channel plus a local message store.

## How it relates to the push channel in the runtime

The push channel in the monitoring runtime is implemented by `sentinel/alerts/push_client.py`
(`ExpoPushClient`), which POSTs to `https://exp.host/--/api/v2/push/send`, reusing the generic
`AlertRecord` with `alert_type = "push"` — no DB schema change. **Where a push fires is driven
by the per-tier `channel` setting plus the call path:**

- **Urgency 5–8 (the SMS tiers)** — `AlertStateMachine._determine_action` returns the matched
  tier's `channel`. A `push` tier sends a push instead of the Twilio SMS; a `both` tier
  sends SMS and push; an `sms` tier sends SMS only. In production both tiers are `push`, so
  no SMS is sent for urgency 5–8.
- **Urgency 9–10** — the path keeps its Twilio call + confirmation/stop SMS and additionally
  fires an Expo push (additive — it does not replace the call). The push is sent before the
  call is attempted (`state_machine.py`). The `channel` field is ignored on this tier. A
  normal push does not bypass silent mode / Do Not Disturb until Apple Critical Alerts (a
  separate entitlement, pending) is active, so by design the Twilio call is the primary
  wake-up.
- **Acknowledged-event updates** — the update SMS is sent **and** an additive push fires, so
  the phone shows each escalation of an active critical event.

The push carries a **fat payload**: the alert's structured fields (event type, urgency,
countries, aggressor, summary, sources, detection time) plus the original SMS body travel
inside the notification's `data`, so the Detail screen can render the full alert offline with
no callback to the server (see **AD-1** below).

The builder is `_build_push_data` in `sentinel/alerts/state_machine.py`. Besides the fields
above, `data` carries `message_id` (a fresh id per send), `event_id`, `kind` (`event` or
`update`) and `event_type_pl`. The serialized `data` is capped at `PUSH_DATA_MAX_BYTES` (3500
UTF-8 bytes). When it is too large, the builder trims in a fixed order: trailing sources
first, then `sms_body`, then `summary_pl`. So for a very large event the Detail screen can
show fewer sources than the SMS would. The visible push `body` carries only a short summary
snippet (`PUSH_BODY_SUMMARY_MAX_CHARS`). `push_client.py` sends with `priority: high`,
`sound: default` and `_contentAvailable: true`, the best-effort background wake behind AD-3.

### Configuration in production

Keep three sources apart:

- **Code default** (`sentinel/config.py`) and **template** (`config/config.example.yaml`):
  push is disabled, `tokens: []`, and tiers 5–8 use `channel: both`.
- **Live production** (`config/config.yaml`, copied to `/etc/sentinel/config.yaml` by
  `/deploy`): `alerts.push.enabled: true`, and `tokens` holds only the placeholder
  `"${EXPO_PUSH_TOKEN}"`. `sentinel/config.py` (`_substitute_env_vars`) replaces it at load
  with the value from `/etc/sentinel/sentinel.env`. The `high` and `medium` tiers use
  `channel: push`, so tiers 5–8 are push-only by owner decision; SMS for them is switched
  off on purpose. `tests/test_config.py` asserts this shape and the placeholder.
- **Urgency 9–10** keeps its phone call plus the additive push.

If push is disabled or the token is missing, a `push` tier delivers nothing at all, and a
missing `EXPO_PUSH_TOKEN` variable stops config loading with a `ConfigError`. See
[`config-reference.md`](../reference/config-reference.md) for the keys and
[`../how-to/api-setup.md`](../how-to/api-setup.md) for credentials.

**Expo access token.** `push_client.py` sends `EXPO_ACCESS_TOKEN` as an
`Authorization: Bearer` header when that variable is set. Production keeps it in
`/etc/sentinel/sentinel.env`. According to the owner's record from 2026-06-04, "Enhanced
Security for Push Notifications" is turned on for the EAS project, so Expo rejects a send
without this token (log: `Expo push failed` or `no tickets accepted`). If the access token
leaks, rotate it in the Expo dashboard and update `sentinel.env`. Keep the device token out
of tracked files as well. The comment in the config push block that calls Expo's push API
"unauthenticated" is outdated; `TODO.md` tracks it under misleading config comments.

The end-to-end relationship is:

```
mobile/ app  ──(mints + displays Expo push token)──►  you copy the token
                                                          │
                                                          ▼
/etc/sentinel/sentinel.env  EXPO_PUSH_TOKEN=…   (owner-only server write)
                                                          │  substituted at load
                                                          ▼
config/config.yaml  alerts.push.tokens: ["${EXPO_PUSH_TOKEN}"]
                                                          │
                                                          ▼
sentinel/alerts/push_client.py  ──(POST exp.host, fat payload)──►  mobile/ device
                                                          │            receives + stores
                                                          ▼            the alert
                                        in-app inbox (List + Detail), app-icon badge
```

So the app sits at *both ends* of the push channel but is part of *neither* the collection
nor the alerting pipeline: it produces the token going in, and it is the recipient (and now
the archive) coming out. It is intentionally decoupled from the server — nothing in the
monitoring runtime imports or depends on it.

## Current known state: Twilio unfunded

The owner deliberately leaves the Twilio account unfunded. Since 2026-09-21 every Twilio
call and SMS fails with HTTP 401 (`account … with status 4 is not active`), including the
6-digit confirmation SMS. This is a known state chosen by the owner, not an outage. Calls
stay configured and return when the owner recharges the account. Until then the Expo push,
which is sent before the call is attempted, is the only alert that reaches the phone, also
for urgency 9–10. It does not bypass silent mode or Do Not Disturb without Critical Alerts.
See the [server runbook troubleshooting](../how-to/server-runbook.md#troubleshooting).

## Stack & key components

- **Expo SDK 54** (`expo ~54.0.33`), React Native `0.81.5`, React `19.1.0`, TypeScript
  (strict), New Architecture enabled (`newArchEnabled: true`). Push plumbing uses
  `expo-notifications`, `expo-device`, `expo-constants`, and `expo-clipboard`. The inbox adds
  `@react-navigation/native` + `@react-navigation/native-stack` (with `react-native-screens`
  and `react-native-safe-area-context`) for the List/Detail navigation shell,
  `expo-web-browser` for in-app source links, `@react-native-async-storage/async-storage` for
  the persistent store, and `expo-task-manager` for the best-effort background capture task.
  `expo-dev-client` is installed, so `npm start` targets a development build rather than
  Expo Go.
- **The navigation + screen native modules need a native build that includes them** (an EAS
  `preview` or `development` build). Expo Go cannot load them, which is why the on-device
  inbox checklist is a separate, non-gating runbook (see below).
- `mobile/.npmrc` sets `legacy-peer-deps=true`, so `npm install` resolves the SDK-54-pinned
  tree (React Native Testing Library 13 on React 19.1) without a peer-dependency conflict.
- **`AGENTS.md` pins the Expo version** and instructs agents to read the *exact* versioned
  Expo docs at `https://docs.expo.dev/versions/v54.0.0/` before touching any code — the
  `expo-notifications` API shape changes across SDK lines. `mobile/CLAUDE.md` is a one-line
  `@AGENTS.md` import, so both files carry the same instruction. Read
  [`../../mobile/AGENTS.md`](../../mobile/AGENTS.md) and
  [`../../mobile/CLAUDE.md`](../../mobile/CLAUDE.md) before editing the app.

### Screens & components

| File | Role |
|---|---|
| `mobile/App.tsx` | Root component and **navigation shell**: `SafeAreaProvider` → `NavigationContainer` → a native-stack with `List` (initial) and `Detail`. At the root it wires the reliable capture + routing paths (foreground capture, tray-sweep on foreground, tap routing, badge resync). The design showcase is no longer the entry point. |
| `mobile/src/screens/MessageListScreen.tsx` | The inbox **List**: a `FlatList` of SMS-style tiles (newest first), an empty state, and a header with mark-all-read, clear-all (with a confirm), and a Settings entry that opens the push/token panel in a modal. Re-reads the store on focus and resyncs the badge. |
| `mobile/src/screens/MessageDetailScreen.tsx` | The **Detail** view: the alert's structured fields (header, urgency, countries, aggressor when present, summary, sources, detection time) in a fixed order, marks the message read on mount, supports delete-with-confirm, and falls back to the stored SMS body when structured fields are absent. Source rows open their article URL in the in-app browser. |
| `mobile/src/components/MessageTile.tsx` | The memoized SMS-style list tile: kind emoji + event type, urgency, a single-line summary snippet, a relative timestamp, and an unread dot. |
| `mobile/src/messages/` | The persistent data layer (Phase 2): `store.ts` (AsyncStorage source of truth), `parsePayload.ts` (foreground + headless payload adapters), `types.ts`, and the `useMessages()` hook the screens consume. |
| `mobile/src/notifications/` | The capture + routing layer: `bootstrap.ts` (the single `setNotificationHandler` + the headless background task, registered at module load via `index.ts`), `capture.ts` (foreground-received capture + tray-sweep, plus `dismissFromTray`), `routing.ts` (pure tap-routing decision), and `useNotificationRouting.ts` (warm + cold tap → ingest → navigate). |
| `mobile/src/navigation/navigationRef.ts` | The navigation ref plus a guarded `navigate()` that queues a single latest-wins pending route when the container is not yet ready, replayed once on `onReady` — so a cold-start tap routes correctly. |
| `mobile/src/badge.ts` | `syncBadge(unreadCount)` — sets the app-icon badge from the store's unread count, tolerating an ungranted `allowBadge` as a silent no-op. |
| `mobile/src/utils/datetime.ts` | `relative()` / `absolute()` rendering (store UTC, render device-local), consistent with the project's timezone convention. |
| `mobile/push/registerForPush.ts` | The push-registration logic: creates the Android `alerts` channel at MAX importance, requests permission (now including iOS alert/badge/sound), and calls `getExpoPushTokenAsync({ projectId })`. Short-circuits with a clear status on simulators (`must-use-physical-device`) and on denied permission. It **no longer** registers the foreground notification handler — that is owned by `bootstrap.ts`. |
| `mobile/push/PushPanel.tsx` | The Settings/token panel (title "POWIADOMIENIA PUSH"), opened as a modal from the ⚙ button in the List header. Shows the registration status, the Expo push token in a selectable mono box, and a "KOPIUJ TOKEN" (copy token) button. Its Polish hint says to paste the token into the server configuration; in practice that means `EXPO_PUSH_TOKEN` in `sentinel.env`. Its "OSTATNI PUSH" section is inert: no caller passes `lastPush`, so it always shows "brak (jeszcze nic nie odebrano)" (tracked in `TODO.md`). |
| `mobile/push/usePushReceiver.ts` | Legacy observability hook from the push-only phase. The live capture path is now `src/notifications/` + `src/messages/`; `usePushReceiver` is no longer mounted at the App root (only its `LastPush` type is still referenced by `PushPanel`). |
| `mobile/designs/` | The cosmetic theme mock screens (`Original`, `Moro`, `MoroActive`, `MoroArctic`, `Tactical`). Presentational only; no longer wired into the app entry. |

The UI copy is **in Polish**, consistent with the rest of Sentinel's user-facing alerting.

### Architecture decisions

**AD-1 — Fat push payload, no server callback** — the Detail screen renders entirely from
the stored notification payload; the app never fetches.
- Context: the inbox must show full alert content (summary, sources, countries, aggressor,
  detection time) with tappable article links **offline**, with no HTTP/token API back to the
  server (single owner, no server ingress opened — same posture as the manual token copy
  flow).
- Consequences: every screen renders purely from the stored payload, and the structured
  Detail render can be longer than the SMS by design. The original SMS body is stored as a
  fidelity fallback, rendered only when the structured fields are absent.

**AD-2 — React Navigation (native-stack), added additively for two screens** — `List`
(initial) and `Detail`.
- Context: tap-to-Detail and back need real navigation, without migrating to expo-router or a
  web build and without disturbing the existing push/token panel.
- Consequences: `App.tsx` becomes the nav shell and the design showcase is no longer the
  entry. Taps route by the alert's stored `message_id` through a navigation ref, not URL
  schemes. The added native modules (`react-native-screens`, `react-native-safe-area-context`)
  require a native rebuild, so the automated gates stay JS-only and on-device behaviour is
  verified by a separate manual checklist.

**AD-3 — Visible push is primary; reliable capture is foreground-listener + tap handler +
tray-sweep-on-open; the background headless task is non-gating.**
- Context: for a **visible** (title + body) push, iOS will usually **not** run the headless
  background task, and Apple throttles/skips silent wakes and will not wake a force-quit app —
  so guaranteed background capture is impossible.
- Consequences: `App.tsx` sweeps the notification tray on every foreground transition (and
  once on mount), which is the de-facto capture path; the headless task is a best-effort
  bonus. By design the urgency 9–10 Twilio call is the wake-up (see
  [Current known state](#current-known-state-twilio-unfunded)); the inbox is visibility +
  history only.
- Tray dismissal (since 2026-06-04, commit 1c7697b): after a successful ingest, every capture
  path (foreground listener, tray sweep, tap routing) calls `dismissFromTray()`. The alert
  then disappears from the iOS Notification Center once it is in the inbox. The store keeps
  no deletion record, so a tray copy left behind would bring a deleted message back on the
  next sweep.

**AD-4 — `data.message_id` is the cross-delivery dedup key; one tap's cold + warm double-fire
is collapsed in-session only.**
- Context: one physical tap can surface twice (the cold `useLastNotificationResponse` plus the
  warm response listener), and the OS notification identifier is a fresh UUID per delivery,
  unusable for dedup.
- Consequences: a pure routing decision plus an in-memory last-handled `message_id` suppress
  the second navigation, and the store dedups interleaved foreground/tray-sweep deliveries of
  the same alert into a single tile. An **event update** is a distinct `message_id`, so it
  correctly gets its own tile.

**AD-5 — AsyncStorage is the single source of truth** — one JSON blob, newest-first, capped at
a fixed maximum; no hidden in-memory cache.
- Context: the inbox must survive restarts, and the headless and foreground capture paths can
  interleave writes.
- Consequences: screens read only via `useMessages()`; the badge is resynced from the store's
  live unread count after each awaited write; dedup self-heals interleaved duplicates on the
  next sweep. The List re-reads on focus after returning from Detail.

**Single notification-handler registration centralized in `bootstrap.ts`** — `registerForPush.ts`
no longer sets the handler, and the iOS badge permission was added.
- Context: a headless launch needs the handler at module load (before the React tree mounts),
  two registrations would conflict, and the app-icon badge silently no-ops unless `allowBadge`
  is granted.
- Consequences: `bootstrap.ts` owns `setNotificationHandler` (with `shouldSetBadge: false` —
  the app is the sole badge authority via `syncBadge`), and `registerForPush.ts` requests
  iOS alert/badge/sound while keeping its token-minting intact.

### Conventions

- **AsyncStorage is the single source of truth**; the UI consumes it only through
  `useMessages()`, which is the mock seam in the screen tests.
- **Capture and badge side effects are fault-isolated**: every payload parse, store write,
  presented-notifications read, badge set, and in-app-browser open is wrapped so a failure can
  never crash a foreground transition or a screen.
- **Store UTC, render device-local** (the project-wide timezone convention) extends to the app
  via `datetime.ts`; `relative()` accepts an injected "now" for deterministic tests.
- **Native-module versions follow the SDK-54 `npx expo install` resolution** rather than literal
  version pins, so the inbox's navigation modules stay ABI-compatible with the Expo SDK.

### Configuration notes

- `app.json` carries the linked EAS project id (`extra.eas.projectId`) and the Expo owner
  account `beepbeepjeep`, both set on 2026-06-02 (commit 7181f16). `registerForPush.ts`
  reads the id from there and never hardcodes it. Token minting works against this project.
- iOS declares the `remote-notification` background mode; bundle id
  `com.kossakowski.sentinel`. Android sets the same package and an adaptive icon.

## Running it

This is a standard Expo app. From `mobile/`:

```bash
cd mobile
npm install          # first time only
npm start            # expo start — opens Metro + a QR code for a dev build
# or target a platform directly:
npm run ios          # expo start --ios
npm run android      # expo start --android
```

This development path needs a development build on a physical device. Expo push tokens are
not issued on simulators or emulators (`registerForPush.ts` short-circuits with
`must-use-physical-device` there), and the navigation/web-browser native modules cannot load
under Expo Go. Open the app, tap ⚙ in the inbox header, grant the notification permission
(alert + badge + sound), then copy the token shown in the panel. The token goes into
`EXPO_PUSH_TOKEN`, as described in [mobile-push-setup.md](../how-to/mobile-push-setup.md).

**Builds (EAS).** `eas.json` defines `development` (dev client, needs Metro), `preview`
(standalone, internal distribution) and `production` (auto-increments the version) profiles.
App versions are managed remotely (`appVersionSource: remote`). Building requires the EAS
CLI (`eas-cli`) `>= 16.0.0` and the linked EAS project.

- **Shipped path.** The phone runs a standalone `preview` build. A JS fix reaches the phone
  only after a new build and a reinstall, so batch fixes as the mobile section of `TODO.md`
  describes:

  ```bash
  npx eas build --profile preview --platform ios
  ```

- **Development path.** `npx eas build --profile development --platform ios` produces a dev
  client that loads JS from Metro (`npm start`).

**Tests.** The app's logic is covered by a Jest suite (`npm test` from `mobile/`) that runs
JS-only — the capture, routing, navigation-ref, badge, datetime, store, and screen behaviours.
`npm run typecheck` (`tsc --noEmit`) is the second automated gate.
The on-device behaviours that need native modules (tap-to-Detail, tray-sweep, badge, in-app
browser, delete/clear persistence) are verified by hand against the
[mobile-inbox-verification.md](../how-to/mobile-inbox-verification.md) checklist (MA-1…MA-7).

## What this app is NOT

- **Not part of the monitoring runtime.** It does not run on the production VPS, is not
  managed by the `sentinel.service` systemd unit, and is not in the scheduler. The
  monitoring pipeline runs entirely server-side without it.
- **Not a dashboard.** The read-only Article Dashboard is a separate local subsystem under
  `dashboard/` (see [`../../SPEC.md`](../../SPEC.md)); the mobile app is unrelated to it.
- **Not a control surface.** It cannot acknowledge alerts, change config, or trigger
  anything on the server. The inbox is read/manage-only over locally stored alerts.
  (Phone-call acknowledgment is still the 6-digit confirmation-SMS reply flow — see
  [`architecture.md`](architecture.md). That SMS also goes through Twilio, so it is not
  delivered while the account is unfunded.)

## Known limitations

- **Background capture is best-effort only (AD-3).** With a visible push, iOS usually will not
  run the headless task, so in practice capture is the tray-sweep on app open; the headless
  payload shape is assumed-from-docs and unverified on-device. By design the urgency 9–10
  Twilio call is the wake-up; see [Current known state](#current-known-state-twilio-unfunded).
- **On-device checks are manual.** The inbox went live on 2026-06-03 after the owner ran the
  on-device checks (per the owner's project notes). The JS-only automated gates cannot
  confirm native behaviour, so re-run MA-1…MA-7 from
  [mobile-inbox-verification.md](../how-to/mobile-inbox-verification.md) after every new
  build.
- **The inbox starts empty with no historical backfill**, and is **single owner / single
  iPhone** only — the push payload budget assumes one device and would need revisiting for
  multiple tokens.

## See also

- [`../how-to/mobile-push-setup.md`](../how-to/mobile-push-setup.md) — the manual runbook for
  building the app, putting a device token in place, and verifying a push end-to-end on the
  device.
- [`../how-to/mobile-inbox-verification.md`](../how-to/mobile-inbox-verification.md) — the
  non-gating on-device checklist (MA-1…MA-7) for the in-app inbox.
- [`../how-to/api-setup.md`](../how-to/api-setup.md) — enabling and configuring the push
  channel (`alerts.push`) server-side.
- [`architecture.md`](architecture.md) — the push channel inside the alerting pipeline and
  how it relates to the phone-call and SMS channels.
- [`../../mobile/AGENTS.md`](../../mobile/AGENTS.md) / [`../../mobile/CLAUDE.md`](../../mobile/CLAUDE.md)
  — the in-repo agent instructions for the app (Expo version pin).
