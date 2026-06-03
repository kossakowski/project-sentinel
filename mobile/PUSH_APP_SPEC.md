# Project Sentinel — Per-Tier Push Channel — Implementation Specification

## Overview

When complete, Project Sentinel's alert router will let the operator choose, **per urgency
tier**, whether a 5–8 alert is delivered by Twilio **SMS**, Expo **push**, or **both** — a single
`channel:` setting on each `urgency_levels` entry. The urgency 9–10 voice-call path keeps its call + confirmation/stop SMS and **additionally fires an Expo push** (additive — the call stays the primary wake-up); the urgency 1–4 `log_only` path is left **exactly as it is today**.
The Expo mobile app — which already mints and displays a push token — gains a small in-app
"last-received push" surface for on-device verification, and a manual runbook walks the owner
through provisioning a real EAS `projectId`, building to their iPhone, and proving a push lands
end-to-end. All documentation that currently calls push "additive / never replaces the Twilio
channels" is rewritten to describe the new toggle.

For the 5–8 tiers this replaces the **only-additive** push design (push always fired alongside the Twilio channels) with the per-tier `channel:` toggle. The 9–10 tier keeps an **additive** push (call + confirmation/stop SMS + push). The driver is the May Twilio bill (~$150): switching a 5–8 tier to `push` removes its Twilio SMS cost entirely.

## Goals

- Give the operator a per-tier `sms` / `push` / `both` channel switch for urgency tiers 5–6
  (`medium`) and 7–8 (`high`).
- Make event-update and new-event alerts for 5–8 follow that per-tier switch.
- Keep the urgency 1–4 `log_only` path byte-for-byte unchanged; for urgency 9–10 keep the call + confirmation/stop SMS exactly as today and **add an additive Expo push** (on new corroborated critical events and on acknowledged-event updates), with the Twilio call remaining the primary wake-up.
- Default to `both` so that, with push still disabled, behavior is identical to today (SMS only)
  — and flipping a tier to `push` is what actually cuts the Twilio bill.
- Let the owner prove a real push reaches the iPhone (token → backend → Expo → phone) via a
  documented, repeatable manual procedure.
- Bring every doc in line with the new model.

## Non-Goals

- **Replacing the urgency 9–10 voice call with push.** The 9–10 push is **additive** — it does not replace the call. A normal push is not a Do-Not-Disturb-bypassing wake-up; that needs Apple **Critical Alerts** (a separate entitlement, pending), so the Twilio call remains the primary 9–10 wake-up. _(The additive 9–10 push IS in scope — see AD-2; replacing the call is not.)_
- **An automatic HTTP token-registration route + `push_tokens` DB table.** Token entry stays manual
  copy-paste into `config.yaml`. The route is specified at a high level in **Appendix A (Future
  Phase)** but is **not built** in this spec. _(Owner decision: avoid opening a public web ingress
  on the hardened VPS for a single device.)_
- **Multi-device / multi-user token management.** Single owner, single iPhone.
- **Auto-provisioning the EAS `projectId` or building the app.** Both require interactive
  `eas`/Apple login tied to the owner's accounts and **cannot be automated** by the implementation
  loop. They are manual owner steps documented in the runbook (Phase 3).
- **Changing the corroborator's alertability gate** (`Corroborator._determine_alert_status`). The
  two-decision split (corroborator decides *alertable*; state machine decides *channel*) is
  preserved. _(See `.claude/rules/corroboration.md`.)_

## Technical Context

Project Sentinel is a Python 3 (APScheduler) monitoring daemon; SQLite storage; alerts via Twilio
voice/SMS with an existing Expo push client. This spec extends it; it does not restructure it.

**Facts established by reading the code (Step 1 research):**

- **`sentinel/config.py`** — Pydantic v2 models. `UrgencyLevel` has fields `min_score: int`,
  `action: str`, `corroboration_required: int = 1`, `retry_attempts`, `retry_interval_minutes`,
  `fallback`. `AlertsConfig.urgency_levels: dict[str, UrgencyLevel]`. `PushConfig` has
  `enabled: bool = False`, `tokens: list[str] = []`. `ClassificationConfig` shows the project's
  `field_validator` style (allow-list → `ValueError`).
- **`sentinel/alerts/state_machine.py`** — `AlertStateMachine.process_event()` is the dispatcher.
  `_determine_action()` (lines 261–292) sorts `urgency_levels` by `min_score` desc and returns
  `phone_call` / `sms` / `log_only` (phone_call falls back to `sms` when
  `source_count < corroboration_required`). Today an **additive push** fires for every non-
  `log_only` event (lines 239–242) and on every acknowledged-event update (line 214). `_execute_sms`,
  `_execute_phone_call`, `_send_update_sms`, `_maybe_send_push`, `_format_push`, and the
  `_user_already_notified` suppression (alert types `sms`/`whatsapp`/`phone_call`) all already exist.
- **`sentinel/alerts/push_client.py`** — `ExpoPushClient.send_push()` POSTs to
  `https://exp.host/--/api/v2/push/send`; it **no-ops when `push.enabled` is false or `tokens` is
  empty**. Its *logic* is unchanged by this spec, but its class docstring (line 16) currently reads
  "Additive alert channel — fires alongside Twilio, never replaces it" — now factually wrong under
  the channel model — and is corrected by Req 1.8.
- **`_maybe_send_push()`** already no-ops on disabled/empty-tokens and **self-dedups** on a prior
  `push` alert record (so repeat corroborations don't re-push). Its `is_update` parameter and
  dedup-bypass branch are exercised directly by `tests/test_state_machine.py::test_push_update_bypasses_dedup`
  and MUST be retained (AD-3 now uses this `is_update` call site on updates; the parameter and its
  dedup-bypass branch are kept).
- **`config/config.yaml`** omits the `push:` block entirely (relies on `PushConfig`'s
  `enabled=False` default — matching production). **`config/config.example.yaml`** ships the block
  disabled (`enabled: false`, `tokens: []`, lines 572–574). Both are git-tracked, but the
  **production server reads `/etc/sentinel/config.yaml`** (a separate file — see
  `docs/how-to/server-runbook.md`), so editing the repo copies is local-only.
- **`mobile/`** — Expo SDK 54 (`expo ~54.0.33`, RN `0.81.5`, React `19.1.0`), `expo-notifications
  ~0.32.17`, TS `strict: true`. `push/registerForPush.ts` mints the token; `push/PushPanel.tsx`
  displays + copies it; `app.json` carries the **placeholder** `extra.eas.projectId`
  `00000000-0000-0000-0000-000000000000`. `mobile/CLAUDE.md` mandates reading the **v54.0.0**
  versioned Expo docs before writing app code.
- **Tooling:** `ruff` (line-length 120) for lint; `pytest` (testpaths `["tests"]`, `integration`
  marker) for tests; **no mypy**, no CI workflow, no Makefile. Tests live in
  `tests/test_state_machine.py`, `tests/test_config.py`, `tests/test_push_client.py`. **This
  worktree has no `.venv`** — the Phase 1/2 gate setup creates one.

## Architecture Decisions

- **AD-1 — A `channel` field on `UrgencyLevel`, consulted only for SMS-tier levels.**
  `channel ∈ {sms, push, both}`, default `both`. `_determine_action` returns the matched level's
  `channel` when that level's `action == "sms"` (the 5–8 tiers); it ignores `channel` for
  `phone_call` and `log_only` levels. _(Rationale: the config model already splits `high`/`medium`
  into separate entries, so per-tier control costs nothing; keeping `channel` off the call/log
  paths means the 9–10 additive push (AD-2) is unconditional rather than channel-controlled.)_
- **AD-2 — The 9–10 path keeps call + confirmation/stop SMS and adds an additive push.**
  `_determine_action` for the `critical` level still returns `phone_call` (or its `sms` fallback when
  under-corroborated); it never returns `push`/`both`. At dispatch, the `phone_call` action
  **additionally fires `_maybe_send_push`** — the push is additive, not channel-driven. The
  under-corroborated fallback (`action == "sms"`) stays SMS-only, so the push rides only with the
  corroborated call. _(Rationale: owner decision 2026-06-01 — add a push on 9–10 for maximum
  visibility; the call remains the primary wake-up, and a normal push is supplementary and does not
  bypass silent mode until Apple Critical Alerts is active. Reverses the earlier "no push on 9–10".)_
- **AD-3 — Acknowledged-event updates send SMS + an additive push.** The update branch sends
  `_send_update_sms(event)` **and** `_maybe_send_push(event, existing_alerts, is_update=True)`. The
  `is_update` dedup-bypass is intended: each 9–10 escalation update pushes, so the phone shows the
  latest escalation. _(Rationale: owner decision 2026-06-01 — extend the additive 9–10 push to
  escalation updates for repeated visibility on an active critical event. Reverses the earlier
  "updates stay SMS-only".)_
- **AD-4 — Default `channel: both` is behavior-preserving while push is off.** Because
  `_maybe_send_push`/`send_push` no-op when `push.enabled` is false or `tokens` is empty, a tier set
  to `both` (or `push`) sends **SMS only** until a token is configured. So the committed configs ship
  `channel: both` + `push.enabled: false` and the deployed behavior is identical to today.
- **AD-5 — Manual token entry; no server ingress.** The app shows the token; the owner pastes it
  into `alerts.push.tokens`. No new endpoint, no DB table, nothing exposed to the internet.

## Assumptions

- **[AD-2]** 9–10 receives an **additive** Expo push alongside the call + confirmation/stop SMS. The
  push does not replace the call and (as a normal push) does not bypass silent mode/DND until Apple
  Critical Alerts is active.
- **[AD-3]** Acknowledged 9–10 escalation updates also push (SMS + additive push, via the `is_update`
  dedup-bypass so each update pushes).
- The owner has an Expo account and (as of 2026-06-01) an **active** Apple Developer account, and
  will run the interactive `eas`/build steps in the Phase 3 runbook themselves.
- A real push reaching the physical iPhone is verified **manually** (Phase 3, non-gating). The
  automated gates cover routing, config validation, and TypeScript correctness with Expo/Twilio
  **mocked** — they never perform a live send.
- The repo's `config/config.yaml` is a local/dev config; the server's `/etc/sentinel/config.yaml`
  is edited by the owner per the runbook, not by this spec, and not via `/deploy` of repo config.

---

## Phase 1 — Backend per-tier channel routing

The substantive, fully-testable change: introduce `channel`, route 5–8 by it, add an additive push
on the 9–10 path (new corroborated critical events + acknowledged updates), and keep 1–4 untouched.

### Deliverables
- `sentinel/config.py` — add `channel: str = "both"` to `UrgencyLevel` plus a `field_validator`
  restricting it to `{"sms", "push", "both"}` (modify existing).
- `sentinel/alerts/state_machine.py` — (a) `_determine_action` returns the matched SMS-tier level's
  `channel`; (b) `process_event` dispatch routes push/SMS by the resolved channel for the 5–8 tiers,
  preserving the `_user_already_notified` SMS suppression, **and additionally fires an Expo push on the
  `phone_call` (9–10) action** (additive, AD-2); (c) the acknowledged-update branch sends the update
  SMS **and** an additive push (AD-3) (modify existing).
- `sentinel/alerts/push_client.py` — correct the stale "additive … never replaces" wording in the
  `ExpoPushClient` class / `send_push` docstrings to the channel model; **no logic change** (modify
  existing).
- `config/config.yaml` — add `channel: both` to `urgency_levels.high` and `urgency_levels.medium`
  with an explanatory comment. **Do not add a `push:` block** — its absence (PushConfig default
  `enabled=False`) is the production-matching disabled state (modify existing).
- `config/config.example.yaml` — add `channel: both` to `high`/`medium`; keep the existing
  `alerts.push` block disabled (`enabled: false`) (modify existing).
- `tests/test_config.py` — add `channel` default + validation tests (modify existing).
- `tests/test_state_machine.py` — add channel-routing/dispatch tests **and revise the existing
  push-wiring and SMS-tier tests** for the new semantics (modify existing).

### Requirements

**1.1** — `UrgencyLevel` MUST gain a field `channel: str = "both"`.
**1.1a** — A `field_validator` on `channel` MUST raise `ValueError` for any value not in
  `{"sms", "push", "both"}` (same pattern as `ClassificationConfig._validate_summary_metric`).
**1.1b** — Existing `urgency_levels` configs that omit `channel` MUST still load (the default
  applies); loading MUST NOT require `channel` on the `critical` or `low` levels.

**1.2** — `AlertStateMachine._determine_action` MUST, for the matched level whose `action == "sms"`
  (the 5–8 tiers), return that level's `channel` value — one of `"sms"`, `"push"`, `"both"`.
**1.2a** — For the `critical` level (`action == "phone_call"`), `_determine_action` MUST return
  `"phone_call"` when `source_count >= corroboration_required`, else `"sms"` (the existing
  fallback). It MUST NOT return `"push"` or `"both"` for the critical level under any input.
  _(Rationale: AD-2 — `_determine_action` is unchanged; the additive 9–10 push is added at the
  dispatch layer, not by returning `"push"`/`"both"`.)_
**1.2b** — For scores below the lowest SMS tier, `_determine_action` MUST return `"log_only"`.
**1.2c** — The matching MUST remain order-independent (sort by `min_score` descending), as today.

**1.3** — In `process_event`, when the resolved action is `"push"` or `"both"`, the system MUST
  send a push via `_maybe_send_push(event, existing_alerts)` (which no-ops if push is disabled).
**1.3a** — When the resolved action is `"sms"` or `"both"`, the system MUST send a Twilio SMS via
  `_execute_sms(event)`, **except** when `_user_already_notified(existing_alerts)` is true, in which
  case the SMS MUST be suppressed (preserving today's re-alert suppression). The push half is NOT
  gated by this SMS suppression; it is bounded only by `_maybe_send_push`'s own dedup (1.3c).
**1.3b** — When the resolved action is `"phone_call"`, the system MUST place the call via
  `_execute_phone_call` **and MUST send an additive push via `_maybe_send_push(event, existing_alerts)`**
  (which no-ops when push is disabled/empty tokens). The call's confirmation/stop-SMS flow is
  unchanged. _(Rationale: AD-2 — 9–10 gets an additive push.)_
**1.3c** — A second `process_event` cycle for the same event (new corroboration) MUST NOT send a
  second push: `_maybe_send_push`'s existing dedup on a prior `push` alert record MUST be preserved.
  _(Note: the dedup keys on a prior **`push`** record only. If a tier's `channel` is flipped from
  `sms` to `push`/`both` mid-event, or push is enabled after a prior SMS-only cycle, the first push
  fires even though an SMS already went out — that is one push, not a duplicate, and is acceptable.)_
**1.3d** — `log_only` MUST send neither SMS nor push (unchanged).

**1.4** — The acknowledged-event update branch MUST send the update via `_send_update_sms(event)`
  **and MUST send an additive push via `_maybe_send_push(event, existing_alerts, is_update=True)`**
  (AD-3). The `is_update` dedup-bypass is intended so each escalation update pushes; the `is_update`
  parameter and its branch in `_maybe_send_push` MUST be retained (the existing
  `test_push_update_bypasses_dedup` calls it directly). _(Rationale: AD-3, 9–10 updates now push.)_

**1.5** — With `alerts.push.enabled: false` (or empty `tokens`), a tier whose `channel` is `"both"`
  or `"push"` MUST behave as it does today: no push is sent, and a `"both"` tier still sends its
  Twilio SMS. _(Rationale: AD-4 — committed default is behavior-preserving.)_

**1.6** — `config/config.yaml` and `config/config.example.yaml` MUST set `channel: both` on the
  `high` and `medium` urgency levels with a brief explanatory comment. `config.example.yaml` MUST
  keep its `alerts.push` block disabled (`enabled: false`); `config.yaml` MUST remain without a
  `push:` block (the `enabled=False` default is the production-matching disabled state).

**1.7** — The revised `process_event`/`_determine_action` MUST NOT alter the **call placement,
  confirmation/stop SMS, retry loop, cooldown, or acknowledgment** behavior of the `critical`/`phone_call`
  flow; the only behavioral addition to that flow is the additive push (Req 1.3b). _(Verified by keeping
  the existing `critical` call-lifecycle tests green — see Gate.)_

**1.8** — The stale "additive / never replaces" wording in code MUST be corrected to the channel
  model: the `ExpoPushClient` class / `send_push` docstrings in `sentinel/alerts/push_client.py`,
  the `_maybe_send_push` docstring, and the inline dispatch comment in `process_event`. After
  Phase 1, the string "never replaces" MUST NOT appear anywhere under `sentinel/`.

#### Normative example — revised `_determine_action` return contract

```python
# returns one of: "phone_call", "sms", "push", "both", "log_only"
for _level_name, level in sorted_levels:           # sorted by min_score desc
    if score >= level.min_score:
        if level.action == "phone_call":
            return "phone_call" if source_count >= level.corroboration_required else "sms"
        if level.action == "sms":
            return level.channel                   # "sms" | "push" | "both"
        return level.action                        # e.g. "log_only"
return "log_only"
```

#### Normative example — revised `process_event` dispatch (replaces today's lines ~232–248)

```python
send_push = action in ("push", "both", "phone_call")  # 9-10 (phone_call) pushes additively
send_sms = action in ("sms", "both")

# Existing re-alert suppression, now applied only to the SMS half.
if send_sms and self._user_already_notified(existing_alerts):
    self.logger.debug("Event %s already has prior alert; suppressing re-SMS", event.id)
    send_sms = False

# Push reaches the phone immediately and self-dedups on a prior push record.
# Fires for push/both tiers AND additively on the 9-10 call (AD-2).
if send_push:
    await self._maybe_send_push(event, existing_alerts)

if action == "phone_call":
    await self._execute_phone_call(event, existing_alerts)
elif send_sms:
    await self._execute_sms(event)
# push-only / suppressed / log_only -> no Twilio SMS
```

#### Normative example — revised update branch (replaces today's lines ~211–215)

```python
if self._is_acknowledged(existing_alerts):
    if event.last_updated_at > self._last_alert_time(existing_alerts):
        await self._send_update_sms(event)                                   # update SMS
        await self._maybe_send_push(event, existing_alerts, is_update=True)  # + additive push (AD-3)
    return
```

> **Test-fixture note (executor MUST honor):** the shared `config` fixture in `tests/conftest.py`
> defines only the `critical` and `high` urgency levels and **no `push` block**. Tests that exercise
> `medium` (score 5) or `low` (score 3) MUST inject those levels inline — follow the existing pattern
> (`config.alerts.urgency_levels["medium"] = UrgencyLevel(min_score=5, action="sms", ...)`, as in the
> current `test_medium_urgency_triggers_sms` / `test_low_urgency_logs_only`). Tests that need push
> enabled MUST use the existing `_enable_push(config)` helper (sets `enabled=True` + a token).

### Acceptance Tests

1. `test_channel_field_defaults_to_both` — (unit) [1.1]
   `UrgencyLevel(min_score=7, action="sms").channel == "both"`.
2. `test_channel_accepts_each_valid_value` — (unit) [1.1]
   Constructing with `channel` in `{"sms","push","both"}` succeeds and round-trips the value.
3. `test_channel_rejects_invalid_value` — (unit) [1.1a]
   `UrgencyLevel(min_score=7, action="sms", channel="email")` raises `ValueError` (pydantic
   `ValidationError`).
4. `test_config_loads_without_channel_keys` — (unit) [1.1b]
   A config dict whose `urgency_levels` omit `channel` (incl. `critical`/`low`) loads; `high`/`medium`
   resolve to `channel == "both"`. _(Extend an existing `test_config.py` load fixture.)_
5. `test_determine_action_high_returns_channel` — (unit) [1.2]
   With `high` set to `channel="push"` and score 7 → `_determine_action` returns `"push"`; with
   `channel="both"` → `"both"`; with `channel="sms"` → `"sms"`.
6. `test_determine_action_medium_returns_channel` — (unit) [1.2]
   Same as above for `medium` at score 5.
7. `test_determine_action_critical_call_when_corroborated` — (unit) [1.2a]
   Score 10, `source_count=2`, `corroboration_required=1` → `"phone_call"`.
8. `test_determine_action_critical_single_source_fallback_sms` — (unit) [1.2a]
   Score 10, `source_count=1`, `corroboration_required=2` → `"sms"` (never `push`/`both`).
9. `test_determine_action_low_logs_only` — (unit) [1.2b]
   Score 3 → `"log_only"`.
10. `test_channel_push_sends_push_not_sms` — (integration) [1.3, 1.3a]
    Push enabled + token; `high.channel="push"`; new score-7 event → `push.send_push` called once,
    `mock_twilio.send_sms` **not** called, one `push` alert record persisted, no `sms` record.
11. `test_channel_both_sends_push_and_sms` — (integration) [1.3, 1.3a]
    Push enabled + token; `high.channel="both"`; new score-7 event → `push.send_push` called once
    **and** `mock_twilio.send_sms` called once; one `push` + one `sms` record.
12. `test_channel_sms_sends_sms_not_push` — (integration) [1.3a]
    Push enabled + token; `high.channel="sms"`; new score-7 event → `mock_twilio.send_sms` called,
    `push.send_push` **not** called.
13. `test_critical_event_sends_additive_push` — (integration) [1.3b, 1.7]
    Push enabled + token; new score-10, `source_count=2` event → the phone-call flow runs **and**
    `push.send_push` IS called once; one `push` alert record exists. _(This revises the former
    `test_critical_event_sends_no_additive_push`, which asserted the opposite under the pre-flip design.)_
14. `test_push_self_dedup_on_second_cycle` — (integration) [1.3c]
    Push enabled + token; `high.channel="push"`; calling `process_event` twice for the same event →
    `push.send_push` called exactly once. _(Mirrors the existing
    `test_push_enabled_sends_once_per_event` intent under the new routing.)_
15. `test_acknowledged_update_sends_sms_and_push` — (integration) [1.4]
    Push enabled + token; an acknowledged event with `last_updated_at` advanced → `_send_update_sms`
    fires (`mock_twilio.send_sms` called) **and** `push.send_push` IS called (the `is_update`
    dedup-bypass). _(Revises the former `test_acknowledged_update_is_sms_only_no_push`.)_
16. `test_default_both_with_push_disabled_sends_sms_only` — (integration) [1.5, AD-4]
    Push **disabled** (default config), `high.channel="both"`, score-7 event → `mock_twilio.send_sms`
    called once, `push.send_push` not called, no `push` record. _(Confirms the shipped default
    reproduces today's behavior.)_
17. `test_critical_flow_unchanged_regression` — (integration) [1.7]
    The existing critical-call lifecycle test(s) (`test_new_critical_event_triggers_call`,
    `test_single_source_critical_triggers_sms`) still pass under the new code (revise only if their
    assertions referenced the removed additive push).

> **Regression note (executor MUST honor):** the existing tests `test_high_urgency_triggers_sms`,
> `test_medium_urgency_triggers_sms`, `test_acknowledged_event_gets_sms_update`,
> `test_push_disabled_sends_no_push`, `test_push_enabled_sends_once_per_event`, and
> `test_push_dedup_on_existing_push_record` all encode the *old* additive-push / always-SMS
> semantics. They MUST be re-pointed to the new model (default `channel="both"` + push-disabled =
> SMS only; push fires for `push`/`both` tiers and additively on 9–10 per AD-2). Do not delete coverage — convert
> it. **`test_push_update_bypasses_dedup` (calls `_maybe_send_push(..., is_update=True)` directly)
> MUST keep passing unchanged** — do not remove the `is_update` parameter (Req 1.4). All of these
> are collected by the Phase 1 gate, so an unconverted one is a hard RED. **AD-2/AD-3 are now flipped: 9–10 sends an additive push and acknowledged updates send SMS + push. So `test_critical_event_sends_additive_push` and `test_acknowledged_update_sends_sms_and_push` assert push IS sent, and any existing critical-event or acknowledged-update test that asserted "no push" (including `test_acknowledged_event_gets_sms_update`) MUST be re-pointed to expect the additive push.**

### Gate Criteria
- `python -m venv .venv && .venv/bin/pip install -q -r requirements.txt ruff` — create/populate the
  worktree venv (idempotent setup; this worktree ships without one). **`ruff` is installed
  explicitly — it is NOT in `requirements.txt`.**
- `.venv/bin/python -c "from sentinel.config import UrgencyLevel; assert UrgencyLevel(min_score=7, action='sms').channel == 'both'"` — new field + default present.
- `.venv/bin/pytest tests/test_config.py tests/test_state_machine.py tests/test_push_client.py -v` — all acceptance + revised regression tests pass (invalid-`channel` rejection is covered by `test_channel_rejects_invalid_value`).
- `.venv/bin/ruff check sentinel/config.py sentinel/alerts/state_machine.py sentinel/alerts/push_client.py tests/test_config.py tests/test_state_machine.py` — no lint errors.
- `! grep -rIn "never replaces" sentinel/` — the stale in-code "never replaces" wording is gone (Req 1.8; passes when absent).

### Phase Dependencies
- Depends on: none.
- Parallelizable with: Phase 3 (disjoint files: `sentinel/*`,`config/*`,`tests/*` vs `mobile/*` +
  a new `docs/how-to/` file).

---

## Phase 2 — Documentation rewrite

Bring every doc in line with the per-tier channel model (the owner explicitly asked to "rewrite the
docs").

### Deliverables
- `docs/reference/config-reference.md` — document the `channel` field (values, default `both`,
  per-level scope) and rewrite the `alerts.push` block + urgency-tier table; remove the "additive /
  never replaces" framing (modify existing).
- `docs/explanation/mobile-app.md` — rewrite the "push maps to alert tiers" section to the toggle
  model; state 9–10 sends call + confirmation/stop SMS **plus an additive push**, and acknowledged
  updates send SMS **plus an additive push** (modify existing).
- `docs/explanation/pipeline.md` — rewrite Stage 7 push paragraph (modify existing).
- `docs/explanation/architecture.md` — rewrite §5 alert-routing/additive-push description (modify
  existing).
- `docs/how-to/api-setup.md` — update the Expo-push section's "additive" wording (modify existing).
- `docs/how-to/server-runbook.md` — update the push-channel note (modify existing).
- `docs/reference/cli.md` — update the `--test-alert push` description if it implies additive-only
  (modify existing).
- `docs/tutorials/getting-started.md` — update any "additive, off by default" push mention (modify
  existing).
- `CLAUDE.md` — update the top-line "optional additive Expo push" phrasing (modify existing).
- `.claude/rules/corroboration.md` — note the new `channel` in the two-decision section (modify
  existing).

### Requirements

**2.1** — `docs/reference/config-reference.md` MUST document the `urgency_levels.*.channel` field:
  its three values (`sms`, `push`, `both`), the default (`both`), that it applies to the `high`
  (7–8) and `medium` (5–6) tiers, and that it is ignored for `critical`/`log_only`.
**2.2** — No doc under `docs/` and not `CLAUDE.md` MAY retain the claim that push **"never replaces
  the Twilio channels."** Every such claim MUST be rewritten to the channel model. _(MUST NOT.)_
**2.3** — `docs/explanation/mobile-app.md`, `docs/explanation/pipeline.md`, and
  `docs/explanation/architecture.md` MUST describe routing 5–8 by `channel` and MUST state that
  9–10 sends call + confirmation/stop SMS **plus an additive push** (AD-2) and acknowledged-event
  updates send SMS **plus an additive push** (AD-3).
**2.4** — The docs SHOULD state that the shipped default (`channel: both`, push disabled) is SMS-only
  and behavior-preserving, and that switching a tier to `push` is what removes its Twilio SMS cost.
**2.5** — `CLAUDE.md`'s system description MUST no longer call push merely "additive"; it MUST
  reflect the per-tier `sms`/`push`/`both` channel.
**2.6** — `.claude/rules/corroboration.md` SHOULD note that `AlertStateMachine._determine_action`
  now resolves the channel from each SMS-tier level's `channel` setting.

### Acceptance Tests

> Documentation requirements are verified by deterministic `grep` gates (no pytest). Each maps to a
> Gate Criterion below.

1. `doc_channel_field_documented` — (e2e) [2.1, 2.4] — `config-reference.md` contains the backticked
   field reference `` `channel` `` **and** the backticked value `` `both` ``. _(Neither token is
   backticked anywhere in the doc today — plain "channel" appears 7× as prose like "push channel",
   and the only "both" is "even if both match" — so these gates cannot pass without the rewrite, i.e.
   they are not false-greens.)_
2. `doc_no_never_replaces` — (e2e) [2.2] — the phrase "never replaces" is absent from `docs/`,
   `sentinel/`, and `CLAUDE.md`. _(Today it appears in `config-reference.md:198`, `pipeline.md:159`,
   and `push_client.py:16`, so removal is meaningful.)_
3. `doc_explanations_reference_channel` — (e2e) [2.3, 2.6] — each of `mobile-app.md`, `pipeline.md`,
   `architecture.md` contains the backticked `` `channel` `` field reference (no doc has a backticked
   `channel` today). The full semantics of 2.3 (9–10 additive push, updates SMS + push) are verified
   by the blind content review.
4. `doc_claudemd_updated` — (e2e) [2.5] — `CLAUDE.md` no longer contains the phrase "additive Expo"
   (today line 4 reads "optional additive Expo **push**").

### Gate Criteria
- `grep -nF '`channel`' docs/reference/config-reference.md` — the `channel` field is documented as a code span (absent today).
- `grep -nF '`both`' docs/reference/config-reference.md` — the `both` channel value is documented as a code span (absent today).
- `! grep -rIn "never replaces" docs/ sentinel/ CLAUDE.md` — the contradictory claim is gone everywhere (passes when absent; catches `push_client.py` too).
- `grep -nF '`channel`' docs/explanation/mobile-app.md` — mobile-app explainer references the field.
- `grep -nF '`channel`' docs/explanation/pipeline.md` — pipeline explainer references the field.
- `grep -nF '`channel`' docs/explanation/architecture.md` — architecture explainer references the field.
- `! grep -nI "additive Expo" CLAUDE.md` — the CLAUDE.md top-line wording is updated (passes when absent).

### Phase Dependencies
- Depends on: Phase 1 (docs describe Phase 1's runtime behavior; write after the contract is fixed).
- Parallelizable with: none (follows Phase 1).

---

## Phase 3 — Mobile push-receipt observability + on-device verification runbook

The mobile app already mints/displays the token; this phase adds a thin "what just arrived" surface
for verification and the **manual** runbook that proves a push lands on the iPhone. The app code
follows `mobile/CLAUDE.md`: **read https://docs.expo.dev/versions/v54.0.0/ before writing app code.**

### Deliverables
- `mobile/push/usePushReceiver.ts` — a hook/module registering an `expo-notifications` received
  listener and response listener, logging the payload and exposing the last-received
  `{title, body, data}` (create).
- `mobile/push/PushPanel.tsx` — surface the most recent received push (title + body) beneath the
  token, for on-device verification (modify existing).
- `mobile/App.tsx` — wire `usePushReceiver` so a received push updates the panel (modify existing).
- `mobile/package.json` — add a `"typecheck": "tsc --noEmit"` script (modify existing).
- `docs/how-to/mobile-push-setup.md` — the manual provisioning + end-to-end verification runbook
  (create).

### Requirements

**3.1** — `mobile/package.json` MUST define a `typecheck` script that runs `tsc --noEmit`.
**3.2** — All mobile TypeScript MUST type-check cleanly under the existing `strict: true` config
  (`tsc --noEmit` exits 0).
**3.3** — `usePushReceiver` SHOULD register both `Notifications.addNotificationReceivedListener` and
  `addNotificationResponseReceivedListener` (per the **v54.0.0** API), log the received payload, and
  remove the listeners on cleanup/unmount (no leaked subscriptions).
**3.4** — `PushPanel` SHOULD display the most recently received push's title and body (or a "none
  yet" placeholder) so the owner can confirm receipt on-device without the Metro console.
**3.5** — `docs/how-to/mobile-push-setup.md` MUST document the full manual end-to-end procedure, in
  order: (1) `eas login` + provision a real `projectId` (`eas init`/`eas build:configure`) replacing
  the `app.json` placeholder; (2) build a development build to the iPhone and grant notification
  permission; (3) copy the token from the PushPanel; (4) paste it into `alerts.push.tokens` and set
  `alerts.push.enabled: true`; (5) set the desired `urgency_levels.{high,medium}.channel`; (6) run
  `./run.sh --test-alert push`; (7) confirm the push arrives on the phone and shows in the panel.
**3.6** — The runbook MUST state that steps (1)–(2) are **manual, interactive** owner steps
  (`eas`/Apple login) that the automated implementation loop does not and cannot perform, and that
  `app.json`'s `projectId` placeholder is replaced by `eas`, not hardcoded by this spec.
**3.7** — The mobile changes MUST NOT alter the existing token-minting logic in
  `registerForPush.ts` or the token copy flow (additive only).

### Acceptance Tests

1. `gate_typecheck_script` — (e2e) [3.1] — `mobile/package.json` contains a `"typecheck"` script
   (see Gate). _(Absent today.)_
2. `gate_typecheck_passes` — (e2e) [3.2] — `tsc --noEmit` exits 0 under strict mode (see Gate).
3. `gate_runbook_exists` — (e2e) [3.5] — `docs/how-to/mobile-push-setup.md` exists (see Gate).
4. `gate_runbook_covers_provisioning` — (e2e) [3.5, 3.6] — the runbook mentions `eas`, `projectId`,
   and `test-alert push` (see Gate).

> **Verification limits (executor + reviewer MUST honor):** there is no JS test runner in scope, so
> SHOULD reqs **3.3** (listener registration/cleanup) and **3.4** (panel display), and MUST req
> **3.7** (`registerForPush.ts` unchanged), have **no automated behavioral oracle**. `tsc --noEmit`
> only proves type-correctness — a stub hook that type-checks would still pass it. 3.3/3.4 are
> confirmed by the blind code review against the v54.0.0 `expo-notifications` API plus the manual
> on-device check (MA-1); 3.7 is confirmed by review/diff (no edits to `registerForPush.ts`).

### Manual Acceptance (non-gating — owner-run, excluded from Gate Criteria)
- `MA-1` [3.3, 3.4, 3.5] — Following the runbook on the physical iPhone, `./run.sh --test-alert push`
  produces a visible push notification on the device, which then appears in the PushPanel. _(Requires
  a real `projectId`, a dev build, and a live Expo send — non-deterministic and credential-bound, so
  it is not a CI gate. It also exercises Phase 1 backend code — see Phase Dependencies.)_

### Gate Criteria
- `npm --prefix mobile install` — install mobile deps (setup; terminating).
- `npm --prefix mobile run typecheck` — `tsc --noEmit` passes under strict mode.
- `test -f docs/how-to/mobile-push-setup.md` — the runbook exists.
- `grep -niE "eas|projectId|test-alert push" docs/how-to/mobile-push-setup.md` — runbook covers
  provisioning + the test command (exits 0 = found).

### Phase Dependencies
- Depends on: **none for the code/docs deliverables** (mobile code is independent of the backend
  change; the runbook references config keys by name and can be written from this spec).
- **`MA-1` (manual, non-gating) requires Phase 1** — its `./run.sh --test-alert push` step exercises
  the Phase 1 backend. Run MA-1 only after Phase 1 is implemented and push is enabled per the runbook.
- Parallelizable with: Phase 1 (disjoint files).

---

## Appendix A — Future Phase (Non-Goal for v1): automatic HTTP token-registration route

Specified for later; **not implemented by this spec.** If the owner ever decides to expose a web
endpoint, a follow-up spec would add:

- A `push_tokens` SQLite table in `sentinel/database.py` (`id`, `token UNIQUE`, `device_identifier`,
  `registered_at`, `last_sent_at`, `status`).
- A `POST /api/push-token` route (in the existing Flask dashboard app or a new minimal service)
  validating the `ExponentPushToken[...]` shape, requiring a shared secret, and upserting the token.
- Token sourcing in the alert path from the table instead of `config.yaml`.
- A public, authenticated ingress on the VPS (TLS + the existing fail2ban posture), and the app
  POSTing its token on registration.

This is deferred because the system is single-user/single-device and the manual copy-paste path
(AD-5) needs no server ingress.
