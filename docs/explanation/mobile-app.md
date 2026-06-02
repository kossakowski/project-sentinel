# The Mobile Companion App (`mobile/`)

> **Diátaxis: explanation.** This page explains *what* the `mobile/` app is and *why* it
> exists. It is not the monitoring runtime — it never collects sources, classifies, or
> decides to alert. It is a small companion app whose only operational job is to hand the
> server a device's Expo push token and then receive the push alerts the server sends.

## Purpose

Project Sentinel's monitoring runtime gained an Expo **push** alert channel (push
notifications) alongside the existing phone call and SMS channels. Each SMS urgency tier
(5–8) carries a per-tier `channel` setting (`sms` / `push` / `both`, default `both`) that
selects how that tier is delivered, and the urgency 9–10 call path additionally fires a push
— see the push section in [`architecture.md`](architecture.md). To deliver a push, the server
needs the target device's **Expo push token**, and that token can only be minted *on the
device*.

The `mobile/` app exists to solve exactly that bootstrap problem. It:

1. Registers the physical device for Expo push notifications and **surfaces the resulting
   Expo push token** so you can copy it and paste it into the server's `alerts.push.tokens`
   config list.
2. **Receives push alerts** once the token is registered server-side. On Android it uses a
   MAX-importance notification channel so a critical military-threat alert breaks through with
   sound and a heads-up banner. On **iOS** a normal Expo push does **not** bypass silent mode
   or Do Not Disturb — it lands as an ordinary notification respecting the phone's ringer/DND
   state. Breaking through silent mode on iOS requires Apple **Critical Alerts** (a separate
   entitlement, pending), so on the owner's iPhone the push is supplementary and the Twilio
   phone call remains the primary 9–10 wake-up.
3. **Surfaces the most recently received push** in an **OSTATNI PUSH** ("last push") panel for
   on-device verification — so the operator can confirm a real push actually landed (title +
   body), not just that a token was minted. This is observability-only: it never mints or
   registers tokens. The step-by-step verification path is in
   [`../how-to/mobile-push-setup.md`](../how-to/mobile-push-setup.md).

That is the whole remit. The app holds no monitoring logic, no database, no classifier, no
Twilio. It is a thin client for the push channel.

## How it relates to the push channel in the runtime

The push channel in the monitoring runtime is implemented by `sentinel/alerts/push_client.py`
(`ExpoPushClient`), which POSTs to `https://exp.host/--/api/v2/push/send`, reusing the generic
`AlertRecord` with `alert_type = "push"` — no DB schema change. **Where a push fires is driven
by the per-tier `channel` setting plus the call path:**

- **Urgency 5–8 (the SMS tiers)** — `AlertStateMachine._determine_action` returns the matched
  tier's `channel`. A `push` tier sends a push **instead of** the Twilio SMS; a `both` tier
  sends SMS **and** push; an `sms` tier sends SMS only.
- **Urgency 9–10** — the path keeps its Twilio call + confirmation/stop SMS and **additionally
  fires an Expo push** (additive — it does **not** replace the call). The `channel` field is
  ignored on this tier. The additive push is for visibility only: a normal push does **not**
  bypass silent mode / Do Not Disturb until Apple **Critical Alerts** (a separate entitlement,
  pending) is active, so the Twilio call remains the primary wake-up.
- **Acknowledged-event updates** — the update SMS is sent **and** an additive push fires, so
  the phone shows each escalation of an active critical event.

The channel is **off by default**: the config block `alerts.push` has `enabled: false` and an
empty `tokens: []` list, and the live `config/config.yaml` omits the block entirely — so until
push is enabled, a `both`/`push` tier still sends SMS only and the deployed behavior is
unchanged. Switching a tier to `channel: push` (with push enabled) is what removes that tier's
Twilio SMS cost. See [`../how-to/api-setup.md`](../how-to/api-setup.md) for enabling it.

The end-to-end relationship is:

```
mobile/ app  ──(mints + displays Expo push token)──►  you copy/paste the token
                                                          │
                                                          ▼
config/config.yaml  alerts.push.tokens: ["ExponentPushToken[…]"]
                                                          │
                                                          ▼
sentinel/alerts/push_client.py  ──(POST exp.host)──►  mobile/ device receives the alert
```

So the app sits at *both ends* of the push channel but is part of *neither* the collection
nor the alerting pipeline: it produces the token going in, and it is the recipient coming
out. It is intentionally decoupled from the server — nothing in the monitoring runtime
imports or depends on it.

## Stack & key components

- **Expo SDK 54** (`expo ~54.0.33`), React Native `0.81.5`, React `19.1.0`, TypeScript
  (strict), New Architecture enabled (`newArchEnabled: true`). Push plumbing uses
  `expo-notifications`, `expo-device`, `expo-constants`, and `expo-clipboard`.
- **`AGENTS.md` pins the Expo version** and instructs agents to read the *exact* versioned
  Expo docs at `https://docs.expo.dev/versions/v54.0.0/` before touching any code — the
  `expo-notifications` API shape changes across SDK lines. `mobile/CLAUDE.md` is a one-line
  `@AGENTS.md` import, so both files carry the same instruction. Read
  [`../../mobile/AGENTS.md`](../../mobile/AGENTS.md) and
  [`../../mobile/CLAUDE.md`](../../mobile/CLAUDE.md) before editing the app.

### Screens & components

| File | Role |
|---|---|
| `mobile/App.tsx` | Root component. Hosts a **design/theme picker** (a bottom pill bar) plus a `PUSH` toggle pill that overlays the push panel. Mounts `usePushReceiver()` at the root and feeds the latest push down into `PushPanel`. |
| `mobile/push/PushPanel.tsx` | **The operational screen.** Shows the registration status, the Expo push token in a selectable mono box, a **"KOPIUJ TOKEN"** (copy token) button, and a Polish hint telling you to paste the token into the server config. Also shows an **OSTATNI PUSH** ("last push") box with the most recently received push's title + body (Polish placeholders when a field is missing or nothing has arrived). Logs the token to the Metro console for dev builds. |
| `mobile/push/usePushReceiver.ts` | Observability-only React hook. Registers both `expo-notifications` listeners — `addNotificationReceivedListener` (foreground arrivals) and `addNotificationResponseReceivedListener` (notification taps) — logs each payload to the Metro console, and returns the last push as `{ title, body, data }`. Removes both subscriptions on unmount. Mints/registers no tokens; does not touch `registerForPush.ts`. |
| `mobile/push/registerForPush.ts` | The push-registration logic: sets the foreground notification handler (SDK-54 `shouldShowBanner`/`shouldShowList` shape), creates the Android `alerts` channel at MAX importance, requests permission, and calls `getExpoPushTokenAsync({ projectId })`. Short-circuits with a clear status on simulators (`must-use-physical-device`) and on denied permission. |
| `mobile/designs/` | The cosmetic theme variants selectable from the picker: `Original`, `Moro`, `MoroActive` ("Moro+"), `MoroArctic` ("Arctic"), and `Tactical` (the default). These are presentational mock screens only — they carry no push logic. |

The UI copy is **in Polish**, consistent with the rest of Sentinel's user-facing alerting.

### Why the push receiver is shaped this way

**Mount the receiver at the App root, not inside `PushPanel`** — `usePushReceiver()` lives in
`App.tsx`, above the overlay it feeds.
- Context: `PushPanel` is an overlay that is closed most of the time. Listeners scoped to it
  would miss any push that arrived while it was closed, defeating the verification surface.
- Consequences: the listeners stay alive for the app's whole lifetime, so the latest push is
  always available when the panel opens — at the cost of one always-mounted hook at the root.

**Register both notification listeners** — the hook subscribes to both
`addNotificationReceivedListener` and `addNotificationResponseReceivedListener`.
- Context: the *received* listener only fires while the app is foregrounded; a push delivered
  while the app is backgrounded or closed is not observed by it.
- Consequences: a foregrounded push shows in **OSTATNI PUSH** immediately, but a
  backgrounded/closed push surfaces only after the notification is **tapped** (the *response*
  listener). This is the broadest practical on-device confirmation without a JS test runner;
  it is not a reliable cold-start replay path. The runbook's Step 7 documents this caveat so an
  empty panel is not mistaken for a delivery failure.

### Configuration notes

- The EAS `projectId` is read from `app.json` (`extra.eas.projectId`) and is **never
  hardcoded** in `registerForPush.ts`. Without a real project id the Expo push service
  cannot mint a token. The committed `app.json` ships a placeholder
  (`00000000-0000-0000-0000-000000000000`); a real EAS project id is required before token
  minting works against a build. *(See the bug note at the end of this page.)*
- iOS declares the `remote-notification` background mode; bundle id
  `com.kossakowski.sentinel`. Android sets the same package and an adaptive icon.

## Running it

This is a standard Expo app. From `mobile/`:

```bash
cd mobile
npm install          # first time only
npm start            # expo start — opens Metro + a QR code for Expo Go / a dev build
# or target a platform directly:
npm run ios          # expo start --ios
npm run android      # expo start --android
```

**You must run on a physical device** — Expo push tokens are not issued on simulators or
emulators (`registerForPush.ts` short-circuits with `must-use-physical-device` there). Open
the app, tap the **PUSH** pill, grant the notification permission, then copy the token shown
in the panel.

**Builds (EAS).** `eas.json` defines `development`, `preview`, and `production` profiles.
A development/preview build is distributed internally; production auto-increments the
version. Building requires Expo CLI `>= 16.0.0` and a configured EAS project. Typical flow:

```bash
npx eas build --profile development --platform ios   # or android
```

## What this app is NOT

- **Not part of the monitoring runtime.** It does not run on the production VPS, is not
  managed by the `sentinel.service` systemd unit, and is not in the scheduler. The
  monitoring pipeline runs entirely server-side without it.
- **Not a dashboard.** The read-only Article Dashboard is a separate local subsystem under
  `dashboard/` (see [`../../SPEC.md`](../../SPEC.md)); the mobile app is unrelated to it.
- **Not a control surface.** It cannot acknowledge alerts, change config, or trigger
  anything on the server. (Phone-call acknowledgment is still the 6-digit confirmation-SMS
  reply flow — see [`architecture.md`](architecture.md).)

## See also

- [`../how-to/mobile-push-setup.md`](../how-to/mobile-push-setup.md) — the manual runbook for
  provisioning the EAS `projectId`, building the app, and verifying a push end-to-end on the
  device.
- [`../how-to/api-setup.md`](../how-to/api-setup.md) — enabling and configuring the push
  channel (`alerts.push`) server-side.
- [`architecture.md`](architecture.md) — the push channel inside the alerting pipeline and
  how it relates to the phone-call and SMS channels.
- [`../../mobile/AGENTS.md`](../../mobile/AGENTS.md) / [`../../mobile/CLAUDE.md`](../../mobile/CLAUDE.md)
  — the in-repo agent instructions for the app (Expo version pin).

---

**Bug noticed while documenting (not fixed):** `mobile/app.json` ships a placeholder EAS
`projectId` of all zeros (`00000000-0000-0000-0000-000000000000`). Expo's push service
cannot mint a real token against a placeholder project id, so `getExpoPushTokenAsync` will
fail until a real EAS project id is wired in. Handed to the TODO owner.
