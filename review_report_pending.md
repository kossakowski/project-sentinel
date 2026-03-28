# Phase 3 Review: Per-User Alert Routing

**Reviewer:** Blind code review agent (Opus 4.6)
**Date:** 2026-03-28
**Branch:** `code-surgeon/multi-tenant-evolution`

## Spec Compliance Summary

| Req | Status | Notes |
|-----|--------|-------|
| 3.1 | PASS | `process_event` queries users via `get_users_by_country()` per affected country, deduplicates by `seen_user_ids`, iterates each with `_process_event_for_user`. |
| 3.2 | PASS | `_determine_action` resolves tier, dispatches to `_resolve_channel_from_preset` or `_resolve_channel_from_user_rules` based on `preference_mode`. |
| 3.3 | PASS | `_fallback_channel` walks `CHANNEL_SEVERITY` from the resolved channel downward, returning the first channel in `available_channels` or `log_only`. |
| 3.4 | PASS | `_execute_phone_call`, `_execute_sms`, `_execute_whatsapp` all accept `User`, use `user.phone_number`, set `record.user_id = user.id`. |
| 3.5 | PASS | `_send_confirmation_whatsapp` creates `ConfirmationCode` model, stores via `db.insert_confirmation_code()`. No `self._confirmation_code` anywhere. |
| 3.6 | PASS | `_check_whatsapp_confirmation` calls `db.get_active_confirmation_code(user.id, event.id)` and `db.mark_confirmation_code_used(code.id)` on match. |
| 3.7 | PASS | `_is_in_cooldown` filters `alert_records` by `user_id`, checks most recent acknowledged record's `sent_at` against cooldown window. Does not use `event.acknowledged_at`. |
| 3.8 | PASS | `_is_acknowledged` operates on user-filtered alert list. `_get_user_alert_records` filters by both `event_id` and `user_id`. |
| 3.9 | PASS (core) / ISSUE (periphery) | `AlertsConfig.phone_number` removed, replaced by `system_phone_number`. `state_machine.py` has zero references. **Stale references remain in `test_e2e_live.py:89` and `deploy/scripts/check-health.sh:30`** (see F-04, F-05). |
| 3.10 | PASS | `AlertDispatcher.dispatch()` signature unchanged. Multi-user iteration inside `state_machine.process_event()`. |
| 3.11 | PASS | `_format_call_message`, `_format_sms_message`, `_format_update_sms` accept optional `language` kwarg, default `"pl"`. |
| 3.12 | PASS | `check_pending_calls` resolves user via `db.get_user_by_id(record.user_id)`, passes user to `_handle_call_result`. |
| 3.13 | PASS | Tests cover: multi-user dispatch, per-user cooldown independence, preset routing, customizable routing, channel fallback, DB persistence of confirmation codes, single-user-ack-does-not-block. |

## Findings

### CRITICAL

*None.*

### HIGH

**F-01: Event-level `alert_status` / `acknowledged_at` is a shared global that creates cross-user interference.**
Files: `sentinel/alerts/state_machine.py` lines 538-542, 673, 684, 502, 737-739
Severity: HIGH (Correctness / Multi-tenant semantics)

`_acknowledge_event` calls `db.update_event(event.id, alert_status="acknowledged", acknowledged_at=...)` which sets a single shared field on the `events` table. Similarly, `_execute_sms` sets `alert_status="sms_sent"`, `_execute_whatsapp` sets `alert_status="whatsapp_sent"`, and `_execute_phone_call` sets `alert_status="call_placed"`.

In a multi-user scenario where User A gets SMS and User B gets a phone call for the same event, User A's execution sets `alert_status="sms_sent"`, then User B's execution overwrites it with `alert_status="call_placed"`. If User A acknowledges, the event goes to `"acknowledged"` globally, which could affect User B's flow on the next cycle -- specifically, `check_pending_calls` -> `_handle_call_result` sets `alert_status="retry_pending"` but that was already overwritten.

This is partially mitigated because the per-user logic uses `alert_records` filtered by `user_id` (not the event-level field) for cooldown and acknowledgment checks. But the event-level `alert_status` is still read by `corroborator.py` and potentially by scheduler diagnostics. The spec says the event-level field "MAY be retained for backward compatibility" (3.7), but the current implementation actively writes to it from user-specific paths, creating a last-writer-wins race.

Recommendation: Either (a) stop updating event-level `alert_status` from per-user paths and only use it as a summary/aggregate, or (b) document that event-level `alert_status` reflects the most recent per-user action and is not authoritative for per-user state.

---

**F-02: `corroboration_required` on `UserAlertRule` is stored but never enforced in routing.**
File: `sentinel/alerts/state_machine.py` lines 381-396
Severity: HIGH (Feature gap)

`UserAlertRule` has a `corroboration_required` field (spec 2.4), and the `premium_user` test fixture sets it to 2 for the critical rule. However, `_resolve_channel_from_user_rules` only checks `min_urgency <= score <= max_urgency` and returns the channel immediately -- it never checks whether `event.source_count >= rule.corroboration_required`.

The legacy `_determine_action_from_config` **does** enforce corroboration (line 373: `if source_count >= level.corroboration_required`). This means premium/customizable users bypass the corroboration requirement entirely. An event with urgency 10 but only 1 source would trigger a phone call for a premium user even if their rule says `corroboration_required=2`.

Recommendation: Add corroboration checking to `_resolve_channel_from_user_rules`, e.g. `if event.source_count < rule.corroboration_required: continue` to fall through to the next lower-priority rule, or fall back to a less aggressive channel.

---

### MEDIUM

**F-03: Dead code block behind `if False:` in `_handle_call_result`.**
File: `sentinel/alerts/state_machine.py` lines 696-714
Severity: MEDIUM (Code quality)

The entire "call was answered" branch is gated by `if False:`, making it unreachable dead code. The docstring still says "If the call was answered (duration > threshold), mark as acknowledged" which is misleading. The comment explains the intent (`# Confirmation is now via WhatsApp only, not call duration`), but the dead code should be removed rather than left behind a `False` guard. The `elif` on line 715 always evaluates, so it's logically just an `if`.

Recommendation: Delete the `if False:` block, convert `elif` to `if`, update the docstring.

---

**F-04: `test_e2e_live.py` still references `config.alerts.phone_number` (removed field).**
File: `test_e2e_live.py` line 89
Severity: MEDIUM (Broken code)

This file was touched on this branch (database path -> url migration in Phase 1) but line 89 still reads `config.alerts.phone_number`. Since `AlertsConfig` no longer has a `phone_number` attribute, this will crash with `AttributeError` at runtime. Should be changed to `config.alerts.system_phone_number` or replaced with a user lookup.

---

**F-05: `deploy/scripts/check-health.sh` still references `config.alerts.phone_number`.**
File: `deploy/scripts/check-health.sh` line 30
Severity: MEDIUM (Broken deploy script)

The Python one-liner `client.send_sms(config.alerts.phone_number, ...)` will fail at runtime for the same reason as F-04. Should use `config.alerts.system_phone_number`.

---

**F-06: `_get_user_alert_records` fetches ALL records for an event then filters in Python; called up to 3x per user per event.**
Files: `sentinel/alerts/state_machine.py` lines 398-403, 232, 240, 446
Severity: MEDIUM (Efficiency)

```python
def _get_user_alert_records(self, event_id, user_id):
    all_records = self.db.get_alert_records(event_id)
    return [r for r in all_records if r.user_id == user_id]
```

This fetches every alert record for the event across all users and filters in Python. It is called at line 240 (main flow), line 411 (inside `_is_in_cooldown`), and potentially line 446 (inside `_execute_phone_call` default). That is 3 DB round-trips returning all users' records, only to filter down to one user each time.

Recommendation: (a) Add a `WHERE user_id = %s` filter to the SQL query (new method or optional parameter). (b) Fetch once at the top of `_process_event_for_user` and pass to all sub-methods.

---

### LOW

**F-07: `_fallback_channel` treats `log_only` as always-available regardless of `available_channels`.**
File: `sentinel/alerts/state_machine.py` lines 163-179
Severity: LOW (Design subtlety, works correctly)

If the loop reaches `log_only` in `CHANNEL_SEVERITY`, it returns `"log_only"` immediately without checking `available_channels`. This is sensible (logging should always work) but is an implicit assumption. Consider adding a brief comment.

---

**F-08: No test for customizable tier user with zero rules.**
File: `tests/test_state_machine.py`
Severity: LOW (Test coverage gap)

No test for a Premium (customizable) user with no `user_alert_rules` rows. Code returns `log_only`, which is likely correct, but worth an explicit test.

---

**F-09: No test for invalid/missing tier (`get_tier_by_id` returns None).**
File: `tests/test_state_machine.py`
Severity: LOW (Test coverage gap)

Lines 309-316 of `state_machine.py` handle tier lookup failure with a warning and `"log_only"` return. No test exercises this branch.

---

**F-10: No test for unknown `preference_mode`.**
File: `tests/test_state_machine.py`
Severity: LOW (Test coverage gap)

Lines 333-338 handle an unknown `preference_mode` by returning `"log_only"`. No test covers this defensive branch.

---

**F-11: `_acknowledge_event` side-effects `event.last_updated_at` via `update_event`.**
File: `sentinel/alerts/state_machine.py` line 538, `sentinel/database.py` line 293
Severity: LOW (Subtle side effect)

`update_event` always sets `last_updated_at = NOW()`. When `_acknowledge_event` runs for User A, it changes `last_updated_at` in the DB, which could affect the `event.last_updated_at > self._last_alert_time(existing_alerts)` comparison at line 243 for User B if they share the same in-memory event object. Mitigated because the event is not re-read from DB mid-loop, but fragile.

---

**F-12: Format message functions accept `language` parameter but ignore it.**
File: `sentinel/alerts/state_machine.py` lines 62-118
Severity: LOW (Expected per spec 3.11)

Polish-only for now, `language` parameter reserved for future i18n. Spec-compliant but should be tracked as a known TODO.

---

**F-13: Standard tier in test fixtures uses `available_channels: ["sms", "whatsapp"]` which differs from spec 2.17's `["phone_call", "sms", "whatsapp"]`.**
File: `tests/test_state_machine.py` lines 83-98
Severity: LOW (Intentional test design)

The test fixture deliberately restricts the Standard tier's available channels to test the fallback mechanism. This is correct for test purposes but creates a discrepancy with the spec-defined Standard tier. Not a bug, just worth noting that production seed data (from `scripts/seed_tiers.py`) has different values than these test fixtures.

---

## Statistics

| Metric | Count |
|--------|-------|
| Files reviewed | 9 |
| Total findings | 13 |
| Critical | 0 |
| High | 2 |
| Medium | 4 |
| Low | 7 |
| Spec requirements checked | 13 (3.1-3.13) |
| Spec requirements fully passing | 12/13 |
| Spec requirements passing with peripheral issues | 1/13 (3.9) |
| Tests in test_state_machine.py | 25 |
| Tests in test_dispatcher.py | 4 |
| Multi-user scenarios tested | 5 (tests #1, #5, #6, #19, #20) |
| Per-user cooldown tests | 2 (tests #5, #8) |
| Channel fallback tests | 4 (unit tests + integration test #4) |
| Edge case tests present | 3 (no users for country, pending call blocks, low urgency log_only) |
| Edge case tests missing | 3 (no rules, no tier, unknown preference_mode) |

---

## Resolution

**Resolver:** Opus 4.6 (1M context)
**Date:** 2026-03-28

### F-01: Event-level `alert_status` shared global — cross-user interference

**Decision:** ACCEPT
**Action:** note (document, do not fix in Phase 3)
**Final severity:** HIGH

**Verification:** Confirmed. Lines 502, 531, 540, 673, 684, 737-738 all call `db.update_event(event.id, alert_status=...)` from per-user code paths. In a multi-user scenario, these writes are indeed last-writer-wins on a shared field.

**Analysis:** The reviewer is correct that this is a real semantic problem. However, I checked all consumers of `alert_status`:

1. **Corroborator** (`corroborator.py:246`): Writes `alert_status` during `_update_event` based on urgency and source count. This runs *before* the alert dispatch, so the state machine's per-user overwrites happen *after* the corroborator is done for that cycle. On the *next* cycle, the corroborator calls `_determine_alert_status()` and *overwrites* whatever the state machine set. So there is no behavioral breakage here -- the corroborator always recalculates.
2. **Scheduler** (`scheduler.py:251`): Filters `e.alert_status != "pending"` to find alertable events. The corroborator sets this field before dispatch, so it works correctly.
3. **State machine internal reads:** The state machine does NOT read `event.alert_status` for any per-user routing decision. All per-user state comes from `alert_records` filtered by `user_id`. The `alert_status` field is write-only from the state machine's perspective.

**Conclusion:** The last-writer-wins race on `alert_status` is cosmetically ugly but does not cause incorrect behavior in the current code because: (a) the corroborator overwrites it every cycle, (b) no consumer depends on it being accurate per-user, and (c) per-user logic reads from `alert_records`. The recommendation to document it as "reflects most recent per-user action, not authoritative" is sound. This should be addressed in Phase 4 cleanup or a future refactor, but it does NOT block Phase 3.

**Blocking:** NO (action=note, not fix)

---

### F-02: `corroboration_required` on `UserAlertRule` stored but not enforced

**Decision:** ACCEPT, RECLASSIFY to LOW
**Action:** note
**Final severity:** LOW

**Verification:** Confirmed. `_resolve_channel_from_user_rules` (lines 381-396) does not check `rule.corroboration_required`. The legacy `_determine_action_from_config` (line 373) does enforce it.

**Analysis:** The reviewer's concern is technically valid -- but the spec does not require enforcement here. Checking CHANGE-SPEC.md:

- **Spec 2.4** defines the `user_alert_rules` table schema including `corroboration_required INTEGER NOT NULL DEFAULT 1`. It specifies the column MUST exist. It says nothing about enforcement during channel resolution.
- **Spec 2.14** says the `UserAlertRule` dataclass MUST have the `corroboration_required` field. Again, storage only.
- **Spec 3.2** says: "If `tier.preference_mode == 'customizable'`, it MUST look up the action from the user's `user_alert_rules` (sorted by priority descending, first matching rule wins based on urgency range)." The spec explicitly says resolution is by urgency range only -- no mention of corroboration enforcement.

The `corroboration_required` field is clearly a stored field for future use (consistent with the spec's general pattern of storing `language` for future i18n). The system-level corroboration check already happens in the corroborator *before* the state machine runs -- events that don't meet corroboration thresholds don't reach the alerting pipeline with an alertable status at all.

Additionally, the global corroboration threshold (`config.classification.corroboration_required`) was recently reduced to 1 (commit 5cacd04), meaning any event with at least 1 source passes corroboration. The per-rule field is dormant by design.

**Conclusion:** Not a feature gap. The field exists for future use as a stored preference. Downgraded to LOW.

**Blocking:** NO

---

### F-03: Dead code block behind `if False:` in `_handle_call_result`

**Decision:** ACCEPT
**Action:** fix
**Final severity:** MEDIUM

**Verification:** Confirmed. Lines 696-714 are gated by `if False:` making them unreachable. The `elif` on line 715 always evaluates. The docstring on line 691 is misleading.

**Analysis:** This is straightforward dead code cleanup. The `if False:` block should be removed, the `elif` should become `if`, and the docstring should be updated. Simple, low-risk fix.

**Blocking:** YES

---

### F-04: `test_e2e_live.py` still references `config.alerts.phone_number`

**Decision:** ACCEPT
**Action:** fix
**Final severity:** LOW (reclassified down from MEDIUM)

**Verification:** Confirmed. Line 89 reads `config.alerts.phone_number`. `AlertsConfig` only has `system_phone_number` (config.py line 142). This will crash with `AttributeError`.

**Analysis:** Per the task context: `test_e2e_live.py` is a manual live E2E test, not part of the automated suite. It references `config.alerts.phone_number` but that is expected to break -- it will need updating but is NOT blocking Phase 3. The fix is trivial (change to `config.alerts.system_phone_number`), but the severity should be LOW since this is a manual test file that will need broader updates for multi-tenant anyway (it does not set up users/tiers, does not call the multi-user code path, etc.).

I will fix it since it is trivial, but it does not block.

**Blocking:** NO (reclassified to LOW)

---

### F-05: `deploy/scripts/check-health.sh` still references `config.alerts.phone_number`

**Decision:** ACCEPT
**Action:** fix
**Final severity:** MEDIUM

**Verification:** Confirmed. Line 30 uses `config.alerts.phone_number`. This will fail at runtime on the production server.

**Analysis:** Unlike F-04, this is an operational script that runs on a real cron schedule. When it fires on a health failure, the SMS alert will crash instead of sending the notification. This is a real production issue. The fix is trivial: change `config.alerts.phone_number` to `config.alerts.system_phone_number`.

**Blocking:** YES

---

### F-06: `_get_user_alert_records` fetches all records then filters in Python; called multiple times

**Decision:** ACCEPT
**Action:** note
**Final severity:** LOW (reclassified down from MEDIUM)

**Verification:** Confirmed. The method is called at lines 240, 411, 447, and 545. Lines 240 and 447 are on different code paths (447 is inside `_execute_phone_call` only when `existing_alerts is None`, and line 240 passes the result to `_execute_phone_call`, so in the normal `_process_event_for_user` flow line 447 does not trigger). Lines 411 and 545 are in `_is_in_cooldown` and `_acknowledge_event` respectively, which run on different branches.

In practice, for a typical event with a handful of users and a handful of alert records, this is negligible. The "up to 3x per user per event" claim is overstated -- in the main `_process_event_for_user` path, it is called once at line 240, and potentially once more at line 411 (cooldown check). The `_acknowledge_event` call at 545 only runs during the phone call loop (inside `_execute_phone_call`), where the existing_alerts were already fetched.

This is a valid efficiency improvement to track, but it is not a correctness issue and the performance impact is negligible at the current scale (single-digit users, single-digit events per cycle). Reclassified to LOW -- a nice-to-have optimization for Phase 4 or a future performance pass.

**Blocking:** NO

---

### F-07: `_fallback_channel` treats `log_only` as always-available

**Decision:** ACCEPT
**Action:** note
**Final severity:** LOW

**Verification:** Confirmed. Line 175-176: `if candidate == "log_only": return "log_only"` without checking `available_channels`. This is correct behavior -- logging should always be available as the ultimate fallback. Adding a comment is a good idea but not blocking.

**Blocking:** NO

---

### F-08: No test for customizable tier user with zero rules

**Decision:** ACCEPT
**Action:** note
**Final severity:** LOW

**Verification:** Confirmed. No test exercises a Premium user with `preference_mode="customizable"` and zero `user_alert_rules` rows. The code at lines 389-396 would iterate over an empty list and return `"log_only"`, which is the correct behavior. Worth tracking for test coverage improvement, but the code path is trivially correct.

**Blocking:** NO

---

### F-09: No test for invalid/missing tier

**Decision:** ACCEPT
**Action:** note
**Final severity:** LOW

**Verification:** Confirmed. Lines 309-316 handle tier lookup failure. Not tested but the defensive code is straightforward.

**Blocking:** NO

---

### F-10: No test for unknown `preference_mode`

**Decision:** ACCEPT
**Action:** note
**Final severity:** LOW

**Verification:** Confirmed. Lines 333-338 handle unknown `preference_mode`. Not tested.

**Blocking:** NO

---

### F-11: `_acknowledge_event` side-effects `event.last_updated_at`

**Decision:** ACCEPT
**Action:** note
**Final severity:** LOW

**Verification:** Confirmed. `update_event` always sets `last_updated_at = NOW()` (database.py line 293). The `_acknowledge_event` call at line 538 triggers this. However, as noted, the event is not re-read from DB mid-loop in `process_event` -- each user gets the same in-memory event object. The `last_updated_at` comparison at line 243 uses the original in-memory value, not the DB value. So there is no actual cross-user interference during a single cycle. On the *next* cycle, the corroborator re-reads the event from DB, and the `last_updated_at` update is harmless (it just reflects the most recent DB touch).

**Blocking:** NO

---

### F-12: Format message functions accept `language` parameter but ignore it

**Decision:** ACCEPT
**Action:** note
**Final severity:** LOW

**Verification:** Confirmed. Polish-only per spec 3.11. The `language` parameter is reserved for future i18n.

**Blocking:** NO

---

### F-13: Standard tier test fixture differs from spec 2.17

**Decision:** ACCEPT
**Action:** note
**Final severity:** LOW

**Verification:** Confirmed. Test fixture has `available_channels: ["sms", "whatsapp"]` (line 87) while spec 2.17 says `["phone_call", "sms", "whatsapp"]`. This is intentional test design to exercise the fallback mechanism. The seed script (`scripts/seed_tiers.py`) uses the spec-correct values for production.

**Blocking:** NO

---

### Resolution Summary

| Finding | Decision | Reclassified? | Final Severity | Action | Blocking? |
|---------|----------|---------------|----------------|--------|-----------|
| F-01 | Accept | No | HIGH | note | NO |
| F-02 | Accept | YES: HIGH -> LOW | LOW | note | NO |
| F-03 | Accept | No | MEDIUM | fix | YES |
| F-04 | Accept | YES: MEDIUM -> LOW | LOW | fix | NO |
| F-05 | Accept | No | MEDIUM | fix | YES |
| F-06 | Accept | YES: MEDIUM -> LOW | LOW | note | NO |
| F-07 | Accept | No | LOW | note | NO |
| F-08 | Accept | No | LOW | note | NO |
| F-09 | Accept | No | LOW | note | NO |
| F-10 | Accept | No | LOW | note | NO |
| F-11 | Accept | No | LOW | note | NO |
| F-12 | Accept | No | LOW | note | NO |
| F-13 | Accept | No | LOW | note | NO |

**Blocking findings: 2** (F-03, F-05)
**Non-blocking fixes (will apply anyway): 1** (F-04)
**Notes for future tracking: 10** (F-01, F-02, F-06, F-07, F-08, F-09, F-10, F-11, F-12, F-13)
