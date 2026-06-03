# Project Sentinel Mobile — In-App Message Inbox — Implementation Specification

## Overview

When complete, the Sentinel iOS app opens directly to a **message inbox**: a scrollable list of
every alert the device has received, shown as SMS-style tiles (type emoji, headline, urgency
`X/10`, a one-line snippet, a relative timestamp, and an unread dot). Tapping a tile — or tapping
the push notification itself — opens a **full message screen** that re-renders the same alert fields
the SMS contains (headline, urgency, affected countries, aggressor, summary, the list of sources,
and the detection time), with every source's article link **tappable** to open in an in-app browser.
The user can mark messages read, delete a single message, clear the whole list, and see an unread
count on the app icon badge. To make this possible, the **server enriches every push notification**
so the full alert content and the article links travel *inside* the notification payload; the app
persists received messages locally so the inbox survives restarts.

**What "SMS-equivalent" means here (precise).** The push carries two things: (a) **structured fields**
(`summary_pl`, `sources[]`, `urgency_score`, `affected_countries`, `aggressor`, `first_seen_at`) — the
**full, untrimmed** data; and (b) `sms_body` — the **exact, trimmed** string the Twilio SMS formatter
produces. The Detail screen renders the **structured fields** (the full content); `sms_body` is stored
for fidelity and used only as a **fallback** when structured fields are missing. The structured render
is therefore a *re-rendering of the same fields*, **not** a byte-for-byte copy of the SMS — it can be
**longer** than the SMS (the SMS truncates summary to 600 chars and trims sources to a 1500-char budget;
the structured fields do not). This divergence is **intended**, not a defect.

## Goals

- Tapping an alert notification opens the app to the **full message** for that alert.
- The full message re-renders the **same fields as the SMS**, including **tappable article links**.
- A **message list** (inbox) shows all received messages as SMS-like tiles; tap to open, go back to the list.
- Message **management**: unread markers, delete one, clear all, app-icon unread badge.
- Messages are **captured** from every reliable path (app open, notification tap, notification-tray
  sweep on open) plus a **best-effort** background path, and **persisted** on-device.

## Non-Goals

- **Replacing the urgency 9–10 Twilio voice call.** The call remains the primary life-safety wake-up.
  The push/inbox is visibility + history only. _(See AD-3.)_
- **Guaranteed background capture.** With a visible notification (title/body present), iOS will
  **usually not** run the headless background task (Expo docs: a headless notification should be
  data-only); Apple also throttles silent pushes (~2–3/hour) and generally will not wake a force-quit
  app. So in practice the "background" capture comes from the **tray-sweep on app open**, not the
  background task; `_contentAvailable` is a harmless additive flag that *may* occasionally wake the
  task. This path is **non-gating**. _(See AD-3.)_
- **A server HTTP/token-registration API or web ingress.** The full content travels inside the push
  payload; the app never calls back to the server.
- **Importing past alerts.** The inbox starts empty and fills from new alerts onward.
- **Multi-device / multi-user.** Single owner, single iPhone.
- **Migrating navigation to `expo-router`, or a web build.** React Navigation (native-stack) is added
  additively for the two screens (AD-2).
- **Deleting the existing `designs/` showcase variants.** They remain in the repo but are no longer the
  app entry point.
- **Editing production server files or deploying.** Server changes (Phase 1) are implemented and tested
  **locally**; deployment is a separate, owner-initiated step.
- **Re-syncing the Detail screen to future SMS-template edits.** The Detail field order (3.9) is owned
  outright by this spec; it matches the current SMS template today but is not bound to future template edits.

## Technical Context

This spec **extends** an existing repo. The following are facts established by reading the code and
verifying APIs against Expo SDK 54 docs (Context7).

### Server (Python) — verified integration points
- `sentinel/alerts/state_machine.py` builds SMS and push **separately**:
  - SMS body via `_format_sms_message(event, db, config)` (around `:122-156`). It renders through the
    **config template** `config.alerts.templates.sms` (`config/config.yaml` / `config.example.yaml`),
    **truncates** `summary_pl` to `SMS_SUMMARY_MAX_CHARS = 600`, and **trims** the sources list to a
    `SMS_MAX_CHARS = 1500` budget via `_build_sources_list(event, db, max_chars=…)` (around `:43-94`),
    which renders each source as `- {source_name}: {title}` then `  {source_url}` and appends a
    `…i N więcej` trailer when trimmed. The detection line is `Wykryto: {first_seen_at_local}` rendered
    in **Europe/Warsaw** wall-clock via `format_warsaw(event.first_seen_at)` (`sentinel/utils/datetime.py`).
    **`_format_sms_message` is therefore a lossy function of the event and requires the live `db` and
    `config`.** Acknowledged-event **updates** are formatted by a **separate** function
    `_format_update_sms(event, db, config)` (around `:159-174`, template `config.alerts.templates.sms_update`)
    — that is the SMS the operator actually receives for an update send.
  - Push title/body via `_format_push(event, is_update=False)` (around `:177-184`):
    event title `🚨 PROJECT SENTINEL: {event_type_pl}`, update title
    `ℹ️ SENTINEL — aktualizacja: {event_type_pl}`, body
    `{summary_pl}\nPilność {urgency_score}/10 · źródła: {source_count}`.
  - The push **`data`** dict is built inline in `_maybe_send_push` and passed to `push_client.send_push`;
    today it contains **only** `{event_id, urgency_score, event_type}`.
  - Push dedup gate in `_maybe_send_push` is record-presence based:
    `if not is_update and any(a.alert_type == "push" for a in existing_alerts): return` — i.e. it
    suppresses a re-push when a prior **push `AlertRecord`** already exists for the event.
- `sentinel/alerts/push_client.py` (`send_push(self, title, body, event_id, data)`, around `:29-100`)
  assembles the Expo message `{to: push_cfg.tokens, title, body, sound, priority, data}` and POSTs it to
  `EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"`. **It receives `data` as an already-built dict
  and has no `event`/`db`/source order.**
- `sentinel/models.py`: `Article.source_url` holds the link. The `Event` dataclass declares
  **`aggressor: str`** and `Event.from_dict` defaults it to `""` — **`aggressor` is never `None`; absence
  is the empty string.** `event.event_type` maps to Polish via `EVENT_TYPE_PL.get(event.event_type,
  event.event_type)` — an **unknown** event_type yields the raw English token (not Polish, not null).
- `EXISTING tests/test_config.py` is a pre-existing regression guard (Phase 1 does not change config).

### Mobile (Expo SDK 54, verified pins)
- Expo SDK `~54.0.33`, React `19.1.0`, React Native `0.81.5`, TypeScript **strict**, New Architecture
  **enabled**. iOS only (iPhone), portrait.
- Current app: `mobile/App.tsx` (design showcase + `PushPanel` overlay), `mobile/index.ts`
  (`registerRootComponent(App)`), `mobile/push/registerForPush.ts` (token minting + `setNotificationHandler`
  with `shouldShowBanner/shouldShowList`, `shouldSetBadge:false`, and `requestPermissionsAsync()` **with no
  options** at `:47`), `mobile/push/usePushReceiver.ts`, `mobile/push/PushPanel.tsx`. **No navigation
  library, no local storage, no test harness** today. `tsconfig.json` extends `expo/tsconfig.base` with
  `strict:true`.
- `app.json` sets `ios.infoPlist.UIBackgroundModes: ["remote-notification"]`, `plugins:
  ["expo-notifications"]`, EAS `projectId`. Bundle id `com.kossakowski.sentinel`.
- **Verified SDK-54 pins** (install with `npx expo install` so versions stay SDK-aligned):
  `@react-native-async-storage/async-storage@2.2.0` (classic default-export singleton; values are
  strings); `expo-task-manager@~14.0.9` (companion for the background task — **native change → new dev
  build**); `expo-web-browser@~15.0.11` (`WebBrowser.openBrowserAsync(url)` → in-app SFSafariViewController,
  resolves `{type:'cancel'}` on close); `@react-navigation/native@^7.2.5`, `@react-navigation/native-stack@^7.16.0`,
  `react-native-screens@~4.16.0`, `react-native-safe-area-context@~5.6.0` (**native deps → new dev build**;
  these are the SDK-54 `npx expo install` resolutions and are **authoritative over any older literal pin**);
  dev: `jest-expo` (SDK-54 line), `jest`, `@types/jest`, `@testing-library/react-native@^13.3.3`
  (**RNTL 13 + React 19: `render`/`fireEvent`/`renderHook` are async and MUST be awaited**; do **not** add
  `react-test-renderer`).
- **Verified expo-notifications (~0.32.17) facts that constrain this spec:**
  - `getPresentedNotificationsAsync()` returns tray notifications (iOS); `request.content.data` is
    `Record<string, unknown>` (may be `{}`).
  - `setBadgeCountAsync(n)` / `getBadgeCountAsync()` exist; on iOS they **silently return `false`** if
    `allowBadge` was not granted (no throw). `requestPermissionsAsync()` with **no args** requests
    alert+badge+sound by default; passing an explicit `ios:{}` object requires `allowBadge:true` to keep
    the badge.
  - Taps: `addNotificationResponseReceivedListener` (warm) + `useLastNotificationResponse()` (cold).
    A tap is `response.actionIdentifier === Notifications.DEFAULT_ACTION_IDENTIFIER`.
    `clearLastNotificationResponseAsync()` consumes/clears the cold response. The synchronous
    `getLastNotificationResponse()` is **deprecated** — MUST NOT be used.
  - `notification.request.content.title`/`.body` are **`string | null`**. `notification.request.identifier`
    is an **OS-generated UUID per delivery** — **unusable as a cross-delivery dedup key**; the same
    physical tap surfaced via both the cold hook and the warm listener shares one in-session delivery.
  - Background task: `TaskManager.defineTask(NAME, ({data,error,executionInfo})=>{})` +
    `Notifications.registerTaskAsync(NAME)`, **defined/registered in `index.ts` module scope** (not a
    component). For a headless receipt the custom payload arrives (per Expo docs) as a JSON **string** at
    `data.data.dataString` (`JSON.parse` it) with `data.notification === null`; this shape is
    **assumed-from-docs and unverified on-device** (handle defensively — see 2.3b).
  - The Expo message sets top-level **`_contentAvailable: true`** (camelCase) for the best-effort wake;
    `content-available` is the APNs key Expo derives — do NOT put it in the Expo message.

## Architecture Decisions

- **AD-1 — Fat push payload, not a server API.** Carry the full structured content + `sms_body` + links
  inside the push `data` payload; the app never calls the server. _(User decision; avoids web ingress.)_
- **AD-2 — React Navigation (native-stack), added additively.** Two screens (`List`, `Detail`); routes
  notification taps via structured `data` (not URL schemes). _(Research.)_
- **AD-3 — Visible push is primary; background capture is effectively tray-sweep.** The push keeps
  `title`/`body` (visible) and also sets `_contentAvailable:true`. **Reliable** capture = foreground
  listener + tap handler + tray-sweep-on-open. The `index.ts` background task is registered, but because
  the push is visible it will **usually not** fire on iOS; treat it as a bonus, **non-gating**. The 9–10
  Twilio call remains the guaranteed wake-up. _(User chose max capture; research established the limits.)_
- **AD-4 — Backend `message_id` is the dedup key.** The server stamps each push send with a unique
  `message_id` (UUID4). Inbox dedup keys on `data.message_id`. An event **update** is a separate send →
  separate `message_id` → its own tile. The OS `request.identifier` is used **only** in-session to
  collapse the cold+warm double-fire of one tap, and is **never persisted**. _(Research.)_
- **AD-5 — Single-key JSON blob in AsyncStorage, capped at 200, newest-first by insertion.** AsyncStorage
  is the source of truth (no hidden in-memory cache that survives a reload). Read-modify-write on the one
  key is last-writer-wins; the headless task and foreground can interleave, and dedup self-heals any lost
  duplicate on the next sweep. _(Research + assumed cap.)_

## Assumptions

- Single owner, single **iPhone** (iOS). Owner has an active Apple Developer account and will run the
  interactive `eas`/dev-build steps; adding native modules requires a **fresh dev build**.
- Server (Phase 1) is implemented/tested **locally**; the owner deploys when ready.
- The inbox starts empty; no historical backfill. _[assumed]_
- Retention cap is **200** messages. _[assumed]_
- The headless background-task payload shape (`data.data.dataString`) is **assumed-from-docs, unverified
  on-device**; the parser handles it defensively. _[assumed]_
- The owner's device is in Poland, so device-local time equals Europe/Warsaw in practice. _[assumed]_

---

## Phase 1 — Server: Enrich the Push Payload

Enrich every push so the full structured content + a trimmed `sms_body` + a stable `message_id` travel
inside `data`, fit a deterministic byte budget, and request best-effort background wake — without
changing routing or existing push behavior.

### Deliverables
- `sentinel/alerts/state_machine.py` — (modify) add a **pure builder** `_build_push_data(event, db,
  config, is_update) -> dict` (1.6) that assembles the full enriched `data` dict, stamps `message_id`
  and `kind`, calls `_format_sms_message(event, db, config)` for `sms_body`, builds structured sources
  via a new `_build_sources_payload(event, db) -> list[dict]`, and applies the byte-budget trim (1.2);
  `_maybe_send_push` delegates to it. Also (modify) `_format_push` to bound its `body` summary to
  `PUSH_BODY_SUMMARY_MAX_CHARS` (1.3b) while leaving `data.summary_pl` full.
- `sentinel/alerts/push_client.py` — (modify) add top-level `"_contentAvailable": true` to the Expo
  message. (It does **not** trim; trimming is done in the builder where `event`/`db` are available.)
- `tests/test_state_machine.py` — (modify/create cases) builder + content + trim + behavior tests.
- `tests/test_push_client.py` — (modify/create cases) `_contentAvailable` test.

### Requirements
**1.1** — `_build_push_data` MUST return a `data` dict that, in addition to the existing keys, includes
the full structured content needed to render a message offline. _(User decision — goal #1.)_
**1.1a** — `data.message_id` MUST be a newly generated, unique, non-empty string per push send (UUID4
hex). Two sends MUST differ. _(Research — AD-4.)_
**1.1b** — `data.sources` MUST be a JSON array of objects `{"name": str, "title": str, "url": str | null}`
where `url` is the article's `source_url` (or `null` if absent), built by `_build_sources_payload`. The
existing `_build_sources_list` **string** behavior (used by the SMS) MUST remain unchanged. _(User decision; research.)_
**1.1c** — `data.sms_body` MUST equal, byte-for-byte, the SMS string the server actually produces for
**this** send (called with the live `db` and `config`): `_format_sms_message(event, db, config)` when
`is_update=False`, or `_format_update_sms(event, db, config)` when `is_update=True`. This is the **trimmed
SMS mirror** (the exact text the operator received for this send), not the full content; it MAY be shorter
than the structured fields. _(User decision — fidelity fallback; research — distinct update formatter.)_
**1.1d** — `data` MUST also include: `summary_pl: str` (the **full, untrimmed** summary — it MAY be longer
than the SMS's 600-char-capped summary; the **only** exception is the 1.2 byte-budget fallback, which may
truncate it as a last resort); `event_type_pl: str` (the server's Polish mapping, which is the
raw English token for unknown event_types); `affected_countries: str[]`; `aggressor: str` (a string,
**`""` meaning "no aggressor"** — never `null`, matching the data model); and `first_seen_at` as a **UTC**
ISO-8601 string. _(User decision; research — aggressor is `str`.)_
**1.1e** — The pre-existing `data` keys `event_id`, `urgency_score`, `event_type` MUST be preserved. _(Research.)_
**1.1f** — `data.kind` MUST be `"update"` when `is_update=True` else `"event"`. The visible push `title`
MUST be exactly what `_format_push(event, is_update)[0]` already produces (event: `🚨 PROJECT SENTINEL:
…`; update: `ℹ️ SENTINEL — aktualizacja: …`). _(Research — bind to source of truth.)_
**1.2** — `_build_push_data` MUST keep the serialized **`data`** payload within a byte budget so it safely
fits Expo/APNs limits: `len(json.dumps(data, ensure_ascii=False).encode("utf-8")) <= 3500`. _(Rationale:
APNs ~4096-byte total payload; the 3500-byte `data` budget reserves headroom for `title`/`body`/aps
overhead; `to` is per-recipient transport, not part of the budget. ensure_ascii=False measures real UTF-8
wire bytes — Polish/emoji are not 6× ASCII-escaped.)_ When over budget, the builder MUST trim in this
exact order until it fits: (1) drop trailing `data.sources` (same article order `_build_sources_list`
uses); (2) if still over with `sources == []`, truncate `data.sms_body` (keep the head); (3) if still
over, truncate `data.summary_pl` (keep the head). Truncation = a codepoint-safe head-slice of the string
(slice the Python `str`, not the encoded bytes) to fit the remaining budget (a trailing `…` MAY be appended). `message_id`, `event_id`, `urgency_score`, `event_type`,
`kind` MUST never be dropped. _(Research — measurement + ownership + fallback.)_
**1.3** — The Expo message (assembled in `push_client`) MUST set top-level `"_contentAvailable": true`
(camelCase) and MUST NOT add a `"content-available"` key. _(Research — AD-3.)_
**1.3a** — The push MUST remain visible: `title` and `body` MUST still be set as today (accepting that
this makes the headless wake unlikely — AD-3). _(Research.)_
**1.3b** — The visible push `body` (built by `_format_push`) MUST bound the embedded `summary_pl` to a
constant `PUSH_BODY_SUMMARY_MAX_CHARS` via a codepoint-safe head-slice (a trailing `…` MAY be appended
when truncated), so that the **total** Expo/APNs payload — `title` + `body` + the ≤3500-byte `data`
(1.2) + aps overhead, excluding the per-recipient `to` transport — safely fits APNs' ~4096-byte limit
with margin. `data.summary_pl` MUST remain the **full, untrimmed** summary (the inbox Detail renders the
full text from `data`, never from `body`), so bounding the body loses no content. This makes 1.2's
"reserves headroom for title/body/aps overhead" premise actually hold (previously the body embedded the
full untrimmed summary, so a long-summary event could push the total past 4096 and Expo could reject the
whole push — including a push-only SMS-tier alert). _(User decision — total-payload fit; closes a gap the
3500-byte `data` budget alone did not.)_ **Budget scope:** the ≤4096 fit is measured on the **APNs
per-device payload** — the assembled Expo message **excluding** the `to` token array, which Expo strips
and fans out one APNs payload per token. This is exact for the single-owner / single-iPhone deployment
(Non-Goals: one token); the raw Expo HTTP request body still carries `to` and grows ~45 bytes per extra
token, so a future multi-device change MUST revisit the budget. _(Research — APNs-vs-Expo-wire distinction.)_
**1.4** — All pre-existing push behavior MUST be preserved unchanged: push fires only when the resolved
action is `push`/`both`/`phone_call`; it is gated by `push.enabled` and a non-empty token list; the
existing **record-presence dedup** suppresses a re-push when a prior push `AlertRecord` exists for the
event with `is_update=False`; the `phone_call` action still sends its additive push; an `is_update=True`
update still pushes (bypassing the dedup). This phase changes only the payload contents. _(Research.)_
**1.5** — `_build_sources_payload(event, db)` MUST be the single source of the structured `data.sources`,
preserving the same article ordering used by `_build_sources_list`. _(Research.)_
**1.6** — `_build_push_data(event, db, config, is_update) -> dict` MUST be a callable, returnable seam
(not inlined into the send call) so tests can build the dict directly; `_maybe_send_push` MUST delegate
to it. _(Research — addressable oracle.)_

### Acceptance Tests
1. `test_build_push_data_includes_full_content` — (unit) [1.1, 1.1d, 1.1e, 1.6] `_build_push_data` for a
   sample event with 2 sources returns a dict with keys `message_id, event_id, kind, event_type,
   event_type_pl, urgency_score, affected_countries, aggressor, summary_pl, sources, sms_body,
   first_seen_at`; assert types and that `event_id/urgency_score/event_type` equal the event's and
   `first_seen_at` parses as ISO-8601 UTC.
2. `test_push_sources_carry_urls` — (unit) [1.1b, 1.5] `data.sources` length matches the event's; each
   `url` equals the corresponding article `source_url`; an article with no URL yields `url is None`.
3. `test_push_sms_body_equals_sms_message` — (unit) [1.1c] For an event send (`is_update=False`),
   `data.sms_body == _format_sms_message(event, db, config)`; for an update send (`is_update=True`),
   `data.sms_body == _format_update_sms(event, db, config)` (same live `db`/`config`).
4. `test_push_message_id_unique_per_send` — (unit) [1.1a] Two `_build_push_data` calls yield different
   non-empty `message_id`.
5. `test_push_update_kind_and_title` — (unit) [1.1f] `is_update=True` → `data.kind=="update"` and the
   push title equals `_format_push(event, True)[0]`; `is_update=False` → `kind=="event"` and title equals
   `_format_push(event, False)[0]`.
6. `test_push_payload_sets_content_available` — (unit) [1.3, 1.3a] The Expo message assembled in
   `push_client` has `"_contentAvailable": True`, no `"content-available"` key, and non-empty `title`+`body`.
7. `test_push_data_within_byte_budget_and_trims` — (unit) [1.2] For a large event (many long
   Google-News-style URLs and a long summary), `len(json.dumps(data, ensure_ascii=False).encode("utf-8"))
   <= 3500`; `data.sources` is trimmed (shorter than full); `message_id`/`event_id` remain present. A
   second case with one pathologically long summary forces `sources == []` and a truncated `summary_pl`
   while staying ≤ 3500.
8. `test_push_behavior_preserved` — (integration) [1.4] `push.enabled=False` or empty tokens → no push;
   enabled + action `both` → exactly one push and the SMS path unchanged; a prior push `AlertRecord`
   present + `is_update=False` → no re-push; action `phone_call` → an additive push is sent; `is_update=True`
   → a push is sent despite an existing push record.
9. `test_push_aggressor_is_string` — (unit) [1.1d] `data.aggressor` equals the event's `aggressor` string;
   for an event with `aggressor == ""`, `data.aggressor == ""` (not `None`).
10. `test_push_summary_pl_is_full` — (unit) [1.1d] For an event with a ~800-char summary and 2 short-URL
    sources (so the serialized `data` is well under 3500 bytes and 1.2 does not fire), `data.summary_pl`
    equals the event's full `summary_pl` and is longer than the summary embedded in `data.sms_body`.
11. `test_push_body_bounded_total_payload_fits` — (unit) [1.3b] For a large event (pathologically long
    summary forcing `data` near the 3500-byte budget), the `body` from `_format_push(event)[1]` is bounded
    (its summary portion ≤ `PUSH_BODY_SUMMARY_MAX_CHARS`, codepoint-safe), `data.summary_pl` remains the
    full untrimmed summary, and the assembled Expo message (`title` + `body` + `data`, **excluding** `to`)
    serialized to UTF-8 is `≤ 4096` bytes with margin.
12. `test_push_data_trim_order_and_stages` — (unit) [1.2] Strengthens the trim oracle: (a) a sources-only
    over-budget case asserts trailing `sources` are dropped first while `sms_body` and `summary_pl` stay
    **intact** (proves sources-first ordering); (b) a case engineered so that after `sources==[]`,
    `sms_body` alone is over budget with headroom left, asserts `sms_body` is head-truncated to a **non-empty**
    prefix while `summary_pl` stays intact (isolates stage 2); (c) the last-resort case asserts `summary_pl`
    is truncated (stage 3) and `message_id`/`event_id`/scalars survive; (d) a case feeding Polish
    diacritics/emoji into a truncated field asserts the result is valid UTF-8 (no split multibyte char),
    guarding codepoint-safety.

### Gate Criteria
- `python -m venv .venv && .venv/bin/pip install -q -r requirements.txt ruff` — environment ready
  _(ruff is a dev-only lint tool, installed alongside requirements; it is not a runtime dep.)_
- `.venv/bin/pytest tests/test_state_machine.py tests/test_push_client.py -v` — all acceptance tests pass
- `.venv/bin/pytest tests/test_config.py -v` — pre-existing config regression guard still green (Phase 1 must not break it)
- `.venv/bin/ruff check sentinel/alerts/state_machine.py sentinel/alerts/push_client.py tests/test_state_machine.py tests/test_push_client.py` — no lint errors

### Phase Dependencies
- Depends on: none. Provides the Appendix-A payload contract consumed by Phases 2–3. Disjoint files from
  the mobile phases (Python only). Not scheduled in parallel with Phase 2 (Phase 2 consumes this
  contract); see manifest `depends_on`.

---

## Phase 2 — Mobile Data Layer: Capture, Parse, Persist, Dedup

Introduce a test harness, a typed message model, payload parsing across all capture shapes, an
AsyncStorage-backed store with dedup/cap/read-state, the `index.ts` module-scope background task, and a
module-scope notification handler. **No UI, no navigation in this phase.**

### Deliverables
- `mobile/package.json` — (modify, **append-only**) add deps `@react-native-async-storage/async-storage@2.2.0`,
  `expo-task-manager@~14.0.9`; devDeps `jest-expo` (SDK-54 line), `jest`, `@types/jest`,
  `@testing-library/react-native@^13.3.3`; add `"test": "jest"` (non-watch) and `"test:watch": "jest
  --watchAll"`; add a `jest` block (`preset:"jest-expo"`, `setupFiles:["<rootDir>/jest.setup.js"]`,
  `transformIgnorePatterns` covering RN/Expo/react-navigation ESM — written forward-compatibly even though
  react-navigation arrives in Phase 3).
- `mobile/tsconfig.json` — (modify) ensure test files are type-checked and jest/node globals resolve:
  add `"types": ["jest", "node"]` to `compilerOptions` (and `@testing-library/react-native` types resolve
  under strict).
- `mobile/babel.config.js` — (create) `module.exports = (api) => { api.cache(true); return { presets:
  ['babel-preset-expo'] }; }`.
- `mobile/jest.setup.js` — (create) mock AsyncStorage via the **exact** path
  `@react-native-async-storage/async-storage/jest/async-storage-mock`; `jest.mock('expo-notifications')`
  **and `jest.mock('expo-task-manager')`** (so importing `bootstrap.ts` in tests does not crash).
- `mobile/src/messages/types.ts` — (create) `StoredMessage`, `MessageSource`, `PushPayload` (Appendix B).
- `mobile/src/messages/parsePayload.ts` — (create) `parsePayload(data, meta)` + path adapters.
- `mobile/src/messages/store.ts` — (create) AsyncStorage-backed store (Appendix B operations).
- `mobile/src/messages/useMessages.ts` — (create) React hook over the store.
- `mobile/src/notifications/bootstrap.ts` — (create) **module-scope side effects**:
  `Notifications.setNotificationHandler(...)` and `TaskManager.defineTask` + `Notifications.registerTaskAsync`.
  A separately-importable module — the testable seam for 2.5/2.8 (importable without mounting the React tree).
- `mobile/index.ts` — (modify) `import './src/notifications/bootstrap'` (side-effect import) **at the top,
  before** `registerRootComponent(App)`.
- `mobile/src/messages/__tests__/store.test.ts`, `mobile/src/messages/__tests__/parsePayload.test.ts`,
  `mobile/src/messages/__tests__/backgroundTask.test.ts` — (create).

### Requirements
**2.1** — The test harness MUST be added at the pinned versions with a non-watch `"test":"jest"` script
and a `jest` block (`preset:"jest-expo"`, `setupFiles`, `transformIgnorePatterns`); `mobile/babel.config.js`
MUST exist with `babel-preset-expo`. `npm --prefix mobile run typecheck` and `npm --prefix mobile test`
MUST both succeed. _(Research.)_
**2.1a** — `mobile/jest.setup.js` MUST mock AsyncStorage via
`@react-native-async-storage/async-storage/jest/async-storage-mock` (NOT the bare `/jest` path) and MUST
also `jest.mock('expo-notifications')` and `jest.mock('expo-task-manager')`. _(Research — version-correct
mock path; importing `bootstrap.ts` needs both mocks.)_
**2.1b** — `mobile/tsconfig.json` MUST be configured so `tsc --noEmit` type-checks the new `*.test.ts(x)`
files cleanly (jest globals via `"types":["jest","node"]`; RNTL and the AsyncStorage mock resolve under
strict). _(Research — typecheck-gate false-red.)_
**2.2** — `StoredMessage` MUST be defined per Appendix B (with `aggressor: string`, not nullable) and pass
strict type-checking. _(User decision; research.)_
**2.3** — `parsePayload(data, meta)` MUST normalize a push `data` object into a `StoredMessage`,
null-guarding `title`/`body` (each may be `null`). The dedup id MUST be `data.message_id`; if absent, fall
back to `data.event_id`, then `meta.osIdentifier`, then a **synthesized key** defined as
`"synth:" + meta.receivedAtMs + ":" + <short random or counter>`. The function MUST never throw and MUST
always produce a non-empty `message_id`. The synthesized key is **per-delivery, not stable**: a payload
carrying no identity does not dedup (acceptable, documented). _(Research — null-safety, AD-4, defined fallback.)_
**2.3a** — When structured fields are present, `parsePayload` MUST populate them; when absent (a legacy
thin push), it MUST fall back so the message still renders: `sms_body`→push `body` (or `""`), `sources`→`[]`,
`summary_pl`→`body` (or `""`), `event_type_pl`→push `title` (or `"(alert)"`), `aggressor`→`""`. _(Research.)_
**2.3b** — Adapters MUST extract the `data` object from each capture shape: the foreground/response/tray
shape (`notification.request.content.data`, an object — typed non-null but may be `{}`) and the
background-task headless shape (`data.data.dataString`, a JSON **string** to `JSON.parse`). Because the
headless shape is assumed-from-docs/unverified, the headless adapter MUST handle a missing/wrong shape
defensively (no throw) and SHOULD log the raw shape on first invocation. _(Research.)_
**2.4** — The store MUST persist messages as a single JSON array under key `@sentinel/messages`. The array
order is **insertion order, newest first** (new messages prepended); `received_at` (UTC ISO, set at
ingest) is non-decreasing across ingests in a session. _(Research — AD-5.)_
**2.4a** — `ingest(payload)` MUST dedup on `message_id`: an existing id is a **no-op on order and on the
stored `received_at` and other fields**, preserving the existing `read` state (no duplicate, no reorder);
a new id is prepended. _(Research — AD-4/AD-5.)_
**2.4b** — An event **update** (same `event_id`, different `message_id`) MUST appear as a **separate**
message. _(User decision.)_
**2.4c** — After prepend/dedup on each write, the store MUST cap retention at **200**, dropping from the
tail (oldest). _(Assumed — AD-5.)_
**2.4d** — `markRead(id)`, `markAllRead()`, `remove(id)`, `clear()` MUST each persist; `unreadCount()`
returns the unread total. _(User decision.)_
**2.4e** — `load()` MUST return `[]` (and log) on missing/corrupted/un-parseable storage; never throws. _(Research.)_
**2.5** — The background notification task MUST be defined with `TaskManager.defineTask` and registered
with `Notifications.registerTaskAsync` in the **module scope of `mobile/src/notifications/bootstrap.ts`**,
which `index.ts` imports for its side effects **before** `registerRootComponent` — so the registration runs
at app load (incl. headless launches) and is import-testable without mounting the React tree. On invocation
the task MUST extract data via the headless adapter (2.3b), `parsePayload`, and `store.ingest`,
catching/swallowing all errors so a failure never crashes the headless launch. _(Research — AD-3; module-scope; isolation seam.)_
**2.6** — (SHOULD) `useMessages()` SHOULD expose `{messages, unreadCount, markRead, markAllRead, remove,
clear, refresh}` and re-read after each mutating operation.
**2.7** — The store MUST treat AsyncStorage as the **source of truth**: it MUST NOT keep a hidden
module-level cache that survives a simulated reload; a fresh `load()` after a write MUST reflect what is in
AsyncStorage. Tests MUST `AsyncStorage.clear()` in `beforeEach`, and the corrupted-storage case MUST be
seeded via `AsyncStorage.setItem('@sentinel/messages','not-json')`. _(Research — reload/cache determinism.)_
**2.8** — `Notifications.setNotificationHandler(...)` MUST be called in the **module scope of
`bootstrap.ts`** (imported by `index.ts` before `registerRootComponent`), returning
`shouldShowBanner:true, shouldShowList:true, shouldPlaySound:true, shouldSetBadge:false`. This MUST be the
**single** handler registration: the pre-existing `setNotificationHandler` call in `registerForPush.ts`
MUST be removed when Phase 3 edits that file (3.12), leaving `bootstrap.ts` the sole owner. Adding this call
is **not** considered "altering token-minting" (cf. 3.12). _(Research — headless handler ownership.)_

### Acceptance Tests
> Store tests `AsyncStorage.clear()` in `beforeEach` (2.7); the AsyncStorage singleton is the official jest
> mock (2.1a).
1. `test_ingest_adds_and_persists` — (unit) [2.4, 2.7] After `ingest(p)`, `all()` length 1 and a fresh
   `load()` (re-reading AsyncStorage) returns the same single message.
2. `test_ingest_dedupes_by_message_id` — (unit) [2.4a] Same `message_id` twice → `all()` length 1.
3. `test_ingest_preserves_read_position_received_at_on_redup` — (unit) [2.4a] Ingest A then B (B newest),
   `markRead(A.id)`, re-ingest A → length 2, A still `read`, A's index and `received_at` unchanged.
4. `test_update_is_separate_message` — (unit) [2.4b] Same `event_id`, different `message_id` → length 2.
5. `test_cap_at_200_keeps_newest` — (unit) [2.4c] Ingest 205 messages with **strictly increasing**
   `received_at` → `all()` length 200; the newest is index 0, the oldest is gone.
6. `test_sorted_newest_first` — (unit) [2.4] After ingesting with increasing `received_at`, `all()[0]` is
   the newest.
7. `test_mark_read_all_remove_clear` — (unit) [2.4d, 2.6] `markRead`/`markAllRead` set flags + `unreadCount`;
   `remove(id)` drops one; `clear()` empties; all survive a fresh `load()`.
8. `test_load_corrupted_returns_empty` — (unit) [2.4e, 2.7] `AsyncStorage.setItem('@sentinel/messages',
   'not-json')` → `load()` returns `[]`, no throw.
9. `test_parse_rich_payload` — (unit) [2.2, 2.3, 2.3a] A full Appendix-A `data` parses to a `StoredMessage`
   with all fields populated (sources length matches, `read===false`, `received_at` set, `message_id` from
   `data.message_id`, `aggressor` a string).
10. `test_parse_thin_payload_fallback` — (unit) [2.3, 2.3a] `data` with only `event_id` + push `body` →
    `sources===[]`, `sms_body`/`summary_pl`===`body`, `event_type_pl` from title-or-`"(alert)"`,
    `message_id` falls back to `event_id`; no throw.
11. `test_parse_null_title_body_synth_key` — (unit) [2.3] `title:null, body:null, data` absent → a message
    with a non-empty `message_id` matching `/^synth:/`; no throw.
12. `test_parse_headless_datastring_shape` — (unit) [2.3b] The headless adapter given
    `{data:{dataString: JSON.stringify(payload)}}` yields the same parsed message as the foreground adapter
    given `{request:{content:{data: payload}}}`; a malformed headless shape returns a fallback message
    without throwing.
13. `test_bootstrap_registers_task_and_handler` — (unit) [2.5, 2.8] Importing
    `mobile/src/notifications/bootstrap.ts` (with expo-notifications, expo-task-manager mocked) calls
    `TaskManager.defineTask`, `Notifications.registerTaskAsync`, and `Notifications.setNotificationHandler`
    at module load (no React tree mounted).
14. `test_background_task_swallows_ingest_error` — (unit) [2.5] Invoking the registered task callback when
    `store.ingest` throws does not propagate the error.

### Gate Criteria
- `npm --prefix mobile install`
- `npm --prefix mobile run typecheck`
- `npm --prefix mobile test`

### Phase Dependencies
- Depends on: Phase 1 (consumes the Appendix-A payload contract). Provides `store`, `parsePayload`,
  `useMessages`, `StoredMessage` to Phase 3. Touches `mobile/package.json`/`tsconfig.json` (shared with
  Phase 3 — **append-only**; see manifest).

---

## Phase 3 — Mobile UI: Navigation, Inbox, Full-Message View, Capture Wiring

Replace the design-showcase entry with a navigation shell (List + Detail), wire the reliable capture paths
and the unread badge, render SMS-style tiles and a full-message screen with tappable article links, and add
the management actions.

### Deliverables
- `mobile/package.json` — (modify, **append-only — MUST preserve Phase-2 scripts, jest block, deps**) add
  deps `@react-navigation/native@^7.2.5`, `@react-navigation/native-stack@^7.16.0`,
  `react-native-screens@~4.16.0`, `react-native-safe-area-context@~5.6.0`, `expo-web-browser@~15.0.11`
  (install via `npx expo install`, which appends — it MUST NOT overwrite the file).
- `mobile/App.tsx` — (modify) `SafeAreaProvider` → `NavigationContainer(ref=navigationRef, onReady=flush)`
  → native-stack `List`(initial)+`Detail`; wire foreground listener, tray-sweep, tap routing, badge sync.
- `mobile/src/navigation/navigationRef.ts` — (create) `createNavigationContainerRef`, guarded `navigate`,
  pending-route queue + `flushPendingRoute()`.
- `mobile/src/notifications/routing.ts` — (create) pure `decideRoute(messageId, lastHandledMessageId)` →
  `{navigate, messageId?, handledMessageId?}`.
- `mobile/src/notifications/useNotificationRouting.ts` — (create) warm listener + cold
  `useLastNotificationResponse` wiring on top of `decideRoute` + `navigationRef`; consumes the cold response
  with `clearLastNotificationResponseAsync()`.
- `mobile/src/notifications/capture.ts` — (create) `attachForegroundCapture()` and `sweepPresented()`,
  each wrapped to catch/swallow errors.
- `mobile/src/badge.ts` — (create) `syncBadge(unreadCount)` → `setBadgeCountAsync`, checks the boolean
  return, swallows a `false`.
- `mobile/src/screens/MessageListScreen.tsx`, `mobile/src/screens/MessageDetailScreen.tsx`,
  `mobile/src/components/MessageTile.tsx`, `mobile/src/utils/datetime.ts` — (create).
- `mobile/push/PushPanel.tsx` — (modify) reachable as a Settings/token view from the list header.
- `mobile/push/registerForPush.ts` — (modify) add `allowBadge`/`allowAlert`/`allowSound` options to the
  `requestPermissionsAsync` call (3.6a); **remove** the now-redundant `setNotificationHandler` call
  (centralized in `bootstrap.ts`, 2.8); token-minting logic (`getExpoPushTokenAsync`/projectId) unchanged (3.12).
- `docs/how-to/mobile-inbox-verification.md` — (create) manual checklist MA-1…MA-7.
- Tests: `mobile/src/navigation/__tests__/navigationRef.test.ts`,
  `mobile/src/notifications/__tests__/routing.test.ts`, `mobile/src/notifications/__tests__/capture.test.ts`,
  `mobile/src/__tests__/badge.test.ts`, `mobile/src/utils/__tests__/datetime.test.ts`,
  `mobile/src/screens/__tests__/MessageListScreen.test.tsx`,
  `mobile/src/screens/__tests__/MessageDetailScreen.test.tsx`,
  `mobile/src/components/__tests__/MessageTile.test.tsx`,
  `mobile/push/__tests__/registerForPush.test.ts`.

### Requirements
**3.1** — The navigation/browser deps above MUST be added **append-only** to the Phase-2 `package.json`
(the Phase-2 `jest` block, `test`/`test:watch` scripts, and async-storage/task-manager deps MUST
survive). Versions MUST be the **SDK-54 `npx expo install` resolutions** — for the native modules
(`react-native-screens`, `react-native-safe-area-context`) the resolver-aligned version **governs over
any literal pin** listed above, so that native ABI compatibility with `expo@~54.0.33` / RN 0.81.5 is
preserved. _(Research; cross-phase coherence. Reconciled 2026-06-03: the original literal pins
`5.4.0` / `~4.13.1` were stale vs the mandated `npx expo install` resolution; the SDK-aligned
`~5.6.0` / `~4.16.0` are authoritative — see run `wf_adeefcf6-3d2`.)_
**3.2** — `App.tsx` MUST render `SafeAreaProvider` → `NavigationContainer` (`ref={navigationRef}`,
`onReady` flushes the pending route) → a native-stack with `List` (initial) and `Detail`. The
design-showcase MUST no longer be the entry; `designs/` MAY remain unused. _(User decision.)_
**3.3** — `navigationRef.ts` MUST export the ref and a `navigate(name, params)` that, when
`!navigationRef.isReady()`, stores the call in a module-level pending route; `flushPendingRoute()` (called
from `onReady`) MUST replay it. _(Research — cold-start ordering.)_
**3.4** — Tap routing MUST open `Detail` for the tapped message: warm via
`addNotificationResponseReceivedListener`, cold via `useLastNotificationResponse()`. It MUST act only on
`actionIdentifier === Notifications.DEFAULT_ACTION_IDENTIFIER`, MUST `store.ingest` the tapped payload
before navigating, and MUST navigate by `data.message_id`. The cold+warm double-fire of one physical tap
MUST be collapsed to a single navigation by tracking the **last-handled `message_id`** in **in-memory,
in-session** state (module/ref), reset on relaunch, and **never persisted**. The cold response MUST be
consumed via `clearLastNotificationResponseAsync()`. The deprecated synchronous
`getLastNotificationResponse()` MUST NOT be used. _(Research — AD-4; cold/warm de-dup.)_
**3.5** — Reliable capture MUST be wired: `addNotificationReceivedListener` → `parsePayload` → `store.ingest`
(foreground); and on `AppState` → `'active'`, `getPresentedNotificationsAsync()` → for each, null-guard
`request.content.data`, `parsePayload`, `store.ingest` (tray-sweep). Both paths MUST resolve `message_id`
identically (from `data.message_id`) so a foregrounded-then-swept push yields **one** inbox entry. The
capture helpers MUST catch/swallow errors (incl. a rejected `getPresentedNotificationsAsync`). _(User decision; research.)_
**3.6** — (MUST) The app icon badge MUST reflect the unread count: `syncBadge(unread)` calls
`setBadgeCountAsync(unread)` on app foreground and after every store mutation/ingest (and `setBadgeCountAsync(0)`
when none unread). `syncBadge` MUST check the boolean return and swallow a `false` (silent no-op when
`allowBadge` is ungranted) without throwing. The handler's `shouldSetBadge` stays `false` (the app is the
sole badge authority). _(User decision — confirmed feature; research — allowBadge no-op.)_
**3.6a** — The permission request in `registerForPush.ts` MUST request `allowBadge` (e.g.
`requestPermissionsAsync({ ios: { allowAlert:true, allowBadge:true, allowSound:true } })`). Adding these
permission **options** is explicitly **permitted** and is **not** "altering token-minting" (cf. 3.12). _(Research — resolves 3.6/3.12 conflict.)_
**3.7** — `MessageListScreen` MUST render messages newest-first in a `FlatList`; each tile (`MessageTile`,
`testID="message-tile"`) MUST show the type emoji (🚨 event / ℹ️ update) + `event_type_pl`, the urgency
`X/10`, a one-line `summary_pl` snippet, and a relative local timestamp; an unread message MUST show an
unread indicator (`testID="unread-dot"`). Tapping a tile MUST navigate to `Detail` for that `message_id`.
With no messages, an empty state (`testID="empty-state"`) MUST show. The header MUST show the title and
provide access to Settings (token) and a Clear-all action. _(User decision.)_
**3.8** — Deleting a single message (swipe action or delete button) MUST prompt a confirm then call
`store.remove(id)`; Clear-all MUST prompt a confirm then call `store.clear()`. (SHOULD) a "mark all read"
action SHOULD be available. _(User decision.)_
**3.9** — `MessageDetailScreen` MUST render the structured fields in **this exact top-to-bottom order**
(owned by this spec; it matches the current SMS template but is **not** bound to future template edits):
(1) `testID="detail-header"` emoji + `event_type_pl`; (2) `testID="detail-urgency"` `Pilność: {urgency}/10`;
(3) `testID="detail-countries"` `Kraje: {affected_countries joined}`; (4) `testID="detail-aggressor"`
`Agresor: {aggressor}` **(this row is omitted entirely when `aggressor` is empty/whitespace)**; (5)
`testID="detail-summary"` the full `summary_pl`; (6) `testID="detail-sources"` a `Źródła ({count})` section
(where `{count}` is `sources.length`, i.e. the post-trim count actually present);
(7) `testID="detail-time"` `Wykryto: {first_seen_at}` in device-local time (3.11). On mount it MUST mark the message read
(`store.markRead`). It MUST provide a delete action (confirm → `store.remove`). If structured fields are
absent, it MUST fall back to rendering `sms_body` (or `body`). _(Note: the structured render is a re-render
of the same fields, not a byte copy of `sms_body`; the `sms_body` fallback may show a Warsaw-local Wykryto
line and an unconditional Agresor row — an accepted divergence.)_ _(User decision.)_
**3.10** — Each source MUST render as `{name}: {title}`; when `url` is non-null it MUST be tappable and open
via `WebBrowser.openBrowserAsync(url)` (in-app); when `url` is null it MUST render as plain text (not
tappable). A rejected/failed `openBrowserAsync` MUST be caught and MUST NOT crash the screen (no
user-visible error required). _(User decision; research — failure mode.)_
**3.11** — `datetime.ts` MUST convert a UTC ISO-8601 string to **device-local** time:
`relative(iso, nowMs)` returns, with these exact boundaries (floor): `<60s`→`"now"`; `60s..<3600s`→
`` `${floor(s/60)}m` ``; `3600s..<86400s`→`` `${floor(s/3600)}h` ``; `>=86400s`→`` `${floor(s/86400)}d` ``.
`absolute(iso)` returns a device-local date-time string. `relative` MUST accept an injected `nowMs` for
deterministic testing. _(Note: device-local equals Europe/Warsaw for the owner; this differs from the
`sms_body` Warsaw wall-clock only off-Warsaw.)_ _(Project convention: store UTC, render local.)_
**3.12** — (SHOULD) The push-token minting + copy flow SHOULD be preserved and reachable as a Settings view
from the list header. `registerForPush.ts`'s **token-minting** logic (the `getExpoPushTokenAsync`/projectId
call and the copy flow) MUST remain functional; adding `allowBadge` permission options (3.6a) and a
module-scope handler move (2.8) are explicitly **not** considered alterations to token-minting. _(Carryover; reconciled with 3.6a/2.8.)_
**3.13** — `docs/how-to/mobile-inbox-verification.md` MUST exist and document MA-1…MA-7, explicitly noting
that background capture (MA-6) is best-effort and, with a visible push, comes essentially from the
tray-sweep. _(Research.)_
**3.14** — `capture.ts` helpers (`attachForegroundCapture`, `sweepPresented`) and the badge sync MUST be
fault-isolated: a thrown/rejected `getPresentedNotificationsAsync`, `parsePayload`, `store.ingest`, or
`setBadgeCountAsync` MUST be caught and MUST NOT crash the app or the foreground transition. _(Research — failure modes.)_

### Acceptance Tests
> **Mock seam:** screens consume the store via `useMessages()`; Phase-3 screen tests
> `jest.mock('../../messages/useMessages')` to inject fixtures. `expo-web-browser` and `expo-notifications`
> are mocked. RNTL renders MUST be awaited (React 19).
1. `test_decide_route_navigates_on_new_message` — (unit) [3.3, 3.4] `decideRoute("m1", null)` →
   `{navigate:true, messageId:"m1", handledMessageId:"m1"}`.
2. `test_decide_route_dedupes_same_message` — (unit) [3.4] `decideRoute("m1", "m1")` → `{navigate:false}`.
3. `test_navigation_ref_queues_until_ready` — (unit) [3.3] With `isReady()` false, `navigate('Detail',{id})`
   does not call the underlying navigator; after `flushPendingRoute()` (ready) it replays exactly once.
4. `test_foreground_listener_ingests` — (unit) [3.5] The `addNotificationReceivedListener` callback
   parses and calls `store.ingest` once for a received notification.
5. `test_sweep_presented_ingests_null_guarded` — (unit) [3.5, 3.14] `getPresentedNotificationsAsync`
   returning two entries (one with `content.data` undefined) → `store.ingest` called for the valid one,
   no throw; a rejected `getPresentedNotificationsAsync` is swallowed.
6. `test_foreground_then_sweep_single_entry` — (unit) [3.5] The same delivery (same `data.message_id`)
   ingested via the foreground path and then the sweep yields one stored message (dedup).
7. `test_sync_badge_sets_unread_count` — (unit) [3.6] `syncBadge(3)` calls `setBadgeCountAsync(3)`;
   `syncBadge(0)` calls `setBadgeCountAsync(0)`; a `setBadgeCountAsync` resolving `false` is tolerated (no throw).
8. `test_register_for_push_requests_allowBadge_and_mints` — (unit) [3.6a, 3.12] Calling
   `registerForPushNotificationsAsync` (Notifications mocked) calls `requestPermissionsAsync` with
   `ios.allowBadge === true` and `getExpoPushTokenAsync` with the configured `projectId`.
9. `test_datetime_relative` — (unit) [3.11] `relative(now-30_000, now)==="now"`;
   `relative(now-130_000, now)==="2m"`; `relative(now-3_600_000, now)==="1h"`;
   `relative(now-259_200_000, now)==="3d"`.
10. `test_datetime_absolute_local` — (unit) [3.11] With `process.env.TZ='Europe/Warsaw'`,
    `absolute("2026-06-02T14:31:00Z")` equals the expected Warsaw-local string.
11. `test_list_renders_n_tiles` — (unit) [3.2, 3.7] Awaited render with 3 messages →
    `getAllByTestId("message-tile")` length 3.
12. `test_list_unread_dot_count` — (unit) [3.7] 2 unread of 3 → `getAllByTestId("unread-dot")` length 2.
13. `test_list_empty_state` — (unit) [3.7] 0 messages → `getByTestId("empty-state")` present.
14. `test_list_clear_all_confirms_and_clears` — (unit) [3.8] Clear-all + confirm → mocked `clear` called once.
15. `test_detail_renders_all_fields` — (unit) [3.9] Detail for a message with 2 sources + a non-empty
    aggressor shows urgency, joined countries, the aggressor, the summary, and each source `name`/`title`,
    and the field rows (`detail-header`, `detail-urgency`, `detail-countries`, `detail-aggressor`,
    `detail-summary`, `detail-sources`, `detail-time`) appear in that top-to-bottom order in the rendered tree.
16. `test_detail_omits_empty_aggressor` — (unit) [3.9] Detail for a message with `aggressor===""` renders
    no Agresor row.
17. `test_detail_source_opens_in_app_browser` — (unit) [3.10] Pressing a source row with a `url` calls
    `WebBrowser.openBrowserAsync` with that exact url; a `url:null` source is not pressable.
18. `test_detail_source_open_failure_swallowed` — (unit) [3.10, 3.14] A rejected `openBrowserAsync` is
    caught (no throw).
19. `test_detail_marks_read_on_mount` — (unit) [3.9] Rendering Detail calls mocked `markRead` with the id.
20. `test_detail_fallback_to_sms_body` — (unit) [3.9] A message missing structured fields but with
    `sms_body` renders the `sms_body` text.
21. `test_tile_shows_title_urgency_snippet_time` — (unit) [3.7] `MessageTile` renders `event_type_pl`,
    `X/10`, a `summary_pl` snippet, and a relative time label.

### Manual On-Device Verification (MA — non-gating, documented in `mobile-inbox-verification.md`)
- **MA-1** — `./run.sh --test-alert push` → banner → tap → app opens to that message's Detail.
- **MA-2** — With unread alerts in the iOS tray, cold-open the app → they appear in the list (sweep).
- **MA-3** — Receive a push while foregrounded → it appears in the list immediately.
- **MA-4** — Tap a source link in Detail → article opens in the in-app browser; Done returns.
- **MA-5** — Unread count shows on the app-icon badge and clears as messages are read.
- **MA-6** — _(best-effort; mostly via tray-sweep)_ Receive a push while backgrounded, don't tap, reopen →
  it appears in the list.
- **MA-7** — Delete one and Clear-all work, with confirm, and survive a restart.

### Gate Criteria
- `npm --prefix mobile install`
- `npm --prefix mobile run typecheck`
- `npm --prefix mobile test`
- `node -e "const p=require('./mobile/package.json'); if(!(p.jest&&p.jest.preset==='jest-expo'&&p.scripts&&p.scripts.test==='jest'&&p.dependencies&&p.dependencies['@react-native-async-storage/async-storage']&&p.dependencies['expo-task-manager'])) { console.error('Phase-2 package.json keys were clobbered'); process.exit(1); }"` — Phase-2 jest config / test script / deps survived the append
- `test -f docs/how-to/mobile-inbox-verification.md`
- `grep -niE "MA-1|background|best-effort" docs/how-to/mobile-inbox-verification.md`

### Phase Dependencies
- Depends on: Phase 2 (consumes `store`, `parsePayload`, `useMessages`, `StoredMessage`). Not parallelizable
  with Phase 2 (shares the mobile tree + `package.json`). Requires a fresh **dev build** after native deps
  are added (cannot be validated in Expo Go); the automated gates are JS-only (Jest/tsc).

---

## Appendix A — Push Payload Contract (Normative; example values illustrative)

The Expo message the server sends (Phase 1). **Normative:** the field set and `data` shape below, plus the
rules in 1.1–1.6. **Illustrative (not byte-normative):** the literal string values — in particular
`sms_body` is **whatever `_format_sms_message` renders from the live `config.alerts.templates.sms` template**
(the template, via 1.1c, is authoritative; the string shown here is only indicative and intentionally
carries a **Warsaw-local** `Wykryto` line that differs from the UTC `first_seen_at` field).

```json
{
  "to": "ExponentPushToken[…]",
  "title": "🚨 PROJECT SENTINEL: Uderzenie rakietowe",
  "body": "Rosja wystrzeliła rakiety w kierunku Polski.\nPilność 9/10 · źródła: 2",
  "sound": "default",
  "priority": "high",
  "_contentAvailable": true,
  "data": {
    "message_id": "f3a9c1e27b8d4e10",
    "event_id": "evt_123",
    "kind": "event",
    "event_type": "missile_strike",
    "event_type_pl": "Uderzenie rakietowe",
    "urgency_score": 9,
    "affected_countries": ["PL"],
    "aggressor": "Rosja",
    "summary_pl": "Rosja wystrzeliła rakiety w kierunku Polski. (full, untrimmed)",
    "sources": [
      {"name": "PAP", "title": "Atak rakietowy na Polskę", "url": "https://www.pap.pl/article/123"},
      {"name": "Reuters", "title": "Missiles fired toward Poland", "url": "https://reuters.com/world/…"}
    ],
    "sms_body": "<exact _format_sms_message(event, db, config) output — see config template; trimmed; Warsaw-local Wykryto>",
    "first_seen_at": "2026-06-02T14:31:00Z"
  }
}
```

Rules recap: `aggressor` is a string (`""` = none, never null). `data` serialized with `ensure_ascii=False`
to UTF-8 MUST be ≤ 3500 bytes (1.2); trim order sources → sms_body → summary_pl; `message_id`/`event_id`/
scalars never dropped. `kind` is `"update"` for acknowledged-event updates.

## Appendix B — StoredMessage + store operations (Normative, mobile)

```ts
export type MessageSource = { name: string; title: string; url: string | null };

export type StoredMessage = {
  message_id: string;          // dedup key (data.message_id; fallbacks per 2.3)
  event_id: string | null;
  kind: 'event' | 'update';
  event_type: string | null;
  event_type_pl: string;       // display title; falls back to push title or '(alert)'
  urgency_score: number | null;
  affected_countries: string[];
  aggressor: string;           // '' means none (never null — matches server model)
  summary_pl: string;          // full; falls back to push body / '' (2.3a)
  sources: MessageSource[];    // [] when absent
  sms_body: string;            // trimmed SMS mirror; falls back to push body / '' (2.3a)
  first_seen_at: string | null;// UTC ISO from server
  received_at: string;         // UTC ISO, set on-device at ingest
  read: boolean;               // false on first ingest
};

// store.ts surface:
//   load(): Promise<StoredMessage[]>            // AsyncStorage source of truth (2.7); [] on corrupt (2.4e)
//   all(): StoredMessage[]                      // newest-first (2.4)
//   ingest(p: StoredMessage): Promise<void>     // dedup on message_id (2.4a), prepend, cap 200 (2.4c)
//   markRead(id), markAllRead(), remove(id), clear(): Promise<void>   // persist (2.4d)
//   unreadCount(): number
```
