---
paths:
  - "sentinel/classification/**"
  - "sentinel/alerts/state_machine.py"
  - "sentinel/alerts/dispatcher.py"
  - "sentinel/scheduler.py"
  - "sentinel/config.py"
  - "config/config.yaml"
  - "config/config.example.yaml"
---

# Corroboration & event grouping

Context to keep in mind when editing the corroborator, incident memory, the alert state machine, or
the `classification.*` config. Live values live in `config/config.yaml`; code defaults in
`sentinel/config.py` differ from them. The per-parameter reference is
[`../../docs/reference/config-reference.md`](../../docs/reference/config-reference.md). Do not
hardcode thresholds and do not restate their numeric values in prose that will drift — point here
or to the config.

## Consequence today: one source can trigger a phone call
The phone call is gated by `alerts.urgency_levels.critical.corroboration_required` (used by
`_determine_action` in `sentinel/alerts/state_machine.py`), and it is set so a single source is
enough. `classification.corroboration_required` (used by `_determine_alert_status`) only sets the
event's provisional `alert_status` label (`sms` instead of `phone_call`) and does not gate the call:
the scheduler dispatches every event whose status is not `pending`. A new event starts with `source_count` 1, so the first urgency-9+ article
triggers a call; source independence only affects later `source_count` growth. Whether to require a
second independent source is an open owner decision in TODO.md. Do not change the config without it.

## Live grouping: incident memory (`classification.incident_memory.enabled`)
Incident memory is on in production. Code: `sentinel/classification/incident_memory.py`,
`Corroborator._find_memory_match` in `sentinel/classification/corroborator.py`, and the per-article
loop in `sentinel/scheduler.py`.

- Articles are classified one at a time. Each article is sent with remembered incidents
  (`IncidentMemory.candidates`) and the result is grouped before the next article, so each event
  becomes context for the next article.
- An article already attached to an event is recorded as a duplicate and is never regrouped.
- Only military results at or above `_MIN_EVENT_URGENCY` (hardcoded) create or join events.
- The model returns a decision: `new`, `duplicate`, `update`, `escalation` or `uncertain`.
  `IncidentMemory.validate` accepts a match only if the matched event is in the candidate list and
  the confidence reaches `min_confidence` (`critical_min_confidence` for phone-call-eligible
  articles). Explicit conflicting dates or weekdays force `new`. An invalid answer becomes
  `uncertain`.
- `_find_memory_match` then also requires the country gate (see below) and an event age within
  `lookback_hours` of the event's last update. Otherwise the decision becomes `uncertain`.
- `new` and `uncertain` always create a new event with its own alert.
- Only `escalation` raises the event's urgency, replaces its summary and increments
  `notification_revision`. `duplicate` and `update` only add the article and maybe a source.
- The window, age cap, summary-similarity and `EVENT_COMPATIBILITY` settings are not used in this
  mode.

## Critical-urgency protection (live mechanism)
- The model's `new` decision gives a critical article its own event and its own phone call.
- A first critical report matched to a noncritical event is forced to `escalation`. If that event is
  not acknowledged, the dispatcher routes it to a phone call.
- An escalation on an acknowledged event sends an update SMS plus a push, not a new call.
- A critical article judged `duplicate` or `update` of an acknowledged event (at
  `critical_min_confidence`) merges into it silently: no new event, no call, no notification
  (`tests/test_incident_memory.py::test_acknowledged_critical_duplicate_stays_on_same_event`).
- The former invariant ("never absorb a critical article into an acknowledged event") now exists
  only in the legacy path. Owner sign-off on this change is an open item in TODO.md.
- **Life-safety: do not weaken the critical confidence bar, the country gate, the escalation
  override or the `new` → own event and call path without explicit owner sign-off.**

## Legacy fuzzy path (only when `incident_memory.enabled` is false)
Rollback path in `Corroborator._find_matching_event`. Articles are classified in a batch.

- Event-type gate — `EVENT_COMPATIBILITY` (hardcoded) must allow the two event types.
- Sliding time window — `classification.corroboration_window_minutes` is measured from the event's
  `last_updated_at` (last activity), not `first_seen_at`.
- Absolute age cap — `classification.corroboration_max_age_minutes` (from `first_seen_at`, `0`
  disables) retires perpetually-updated events so they can't chain-merge distinct incidents.
- Summary match — `classification.summary_similarity_metric` (a `rapidfuzz.fuzz` function,
  validated against an allow-list) scored against `classification.summary_similarity_threshold`.
- Acknowledged guard — a phone-call-eligible article is never absorbed into an event with
  `acknowledged_at` set; it forces a new event and a new call.

## Shared gates (both paths)
- Source independence — a source counts as independent only if it is a different domain AND title
  similarity `< classification.syndication_similarity_threshold` (catches wire syndication).
- Country gate — at/above the phone-call urgency threshold, a match requires a concrete
  affected-country intersection (a Poland-critical article with no extracted country gets its own
  event and call). Below the threshold, empty/"unknown" labels don't block; two concrete but
  different country sets stay separate. Countries are normalized (uppercased, blank/"unknown"
  dropped) on merge.

## Alert-level decisions
Three layers decide what is sent, and the first two can disagree:
1. `Corroborator._determine_alert_status` sets the event's `alert_status` from hardcoded urgency
   cuts (phone_call ≥ 9 AND `source_count ≥ classification.corroboration_required`; sms ≥ 7;
   sms ≥ 5; else pending; `dry_run` short-circuits). In memory mode an update keeps the lifecycle
   status (`acknowledged`, `retry_pending`, `call_placed`, `expired`) instead of recomputing it.
2. `AlertStateMachine._determine_action` makes the final channel choice from
   `alerts.urgency_levels` and each level's `corroboration_required`. For the SMS-action tiers
   (5–8) it returns that level's `channel` (`sms` / `push` / `both`; code default `both`, live
   value in the config). `channel` is ignored on the `critical` (`phone_call`) and `low`
   (`log_only`) levels; the 9–10 call also sends an additive push.
3. Revision-aware delivery in `AlertStateMachine.process_event`: SMS and push are each suppressed
   only after that channel delivered the current `notification_revision` (`_channel_delivered`); a
   failed send stays retryable. For an acknowledged event no call is placed, and an update SMS plus
   push go out only when the revision advanced (`_has_new_delivered_revision`). Source-count and
   timestamp changes never advance the revision.
