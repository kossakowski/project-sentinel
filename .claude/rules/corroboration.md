---
paths:
  - "sentinel/classification/**"
  - "sentinel/alerts/state_machine.py"
  - "config/config.yaml"
---

# Corroboration & event grouping

Context to keep in mind when editing the corroborator, the alert state machine, or the
`classification.*` config. **Live values live in `config/config.yaml`; the per-parameter reference
is [`../../docs/reference/config-reference.md`](../../docs/reference/config-reference.md). Do not
hardcode thresholds and do not restate their numeric values in prose that will drift — point here
or to the config.**

How an incoming classification is grouped into an `events` row (`sentinel/classification/corroborator.py`):

- **Sliding time window** — `classification.corroboration_window_minutes` is measured from the
  event's `last_updated_at` (LAST activity), **not** `first_seen_at`. A multi-hour incident that
  keeps getting fresh articles stays ONE event.
- **Absolute age cap** — `classification.corroboration_max_age_minutes` (from `first_seen_at`,
  `0` disables) retires perpetually-updated events so they can't chain-merge distinct incidents.
- **Summary match** — `classification.summary_similarity_metric` (a `rapidfuzz.fuzz` function,
  validated against an allow-list; `token_set_ratio` is length-robust) scored against
  `classification.summary_similarity_threshold`.
- **Source independence** — a source counts as independent only if it is a different domain AND
  title similarity `< classification.syndication_similarity_threshold` (catches wire syndication).
- **Country gate** — at/above the phone-call urgency threshold (9), a match requires a concrete
  affected-country intersection (a Poland-critical article with no extracted country spawns its OWN
  event/call). Below the threshold, empty/"unknown" labels don't block; two concrete-but-different
  country sets stay separate. Countries are normalized (uppercased, blank/"unknown" dropped) on merge.
- **Critical-urgency safety guard** — a phone-call-eligible article is NEVER absorbed into an event
  that already has `acknowledged_at` set (already alerted / in cooldown); it forces a NEW event and
  a NEW call so a fresh escalation can't be silenced by an earlier event's cooldown. **This is a
  life-safety invariant — do not weaken it without explicit sign-off.**

Two independent alert-level decisions exist and can disagree:
1. `Corroborator._determine_alert_status` gates whether an event is "alertable" using hardcoded
   urgency cuts (phone_call ≥ 9 AND `source_count ≥ classification.corroboration_required`; sms ≥ 7;
   sms ≥ 5; else pending; `dry_run` short-circuits).
2. `AlertStateMachine._determine_action` makes the final channel choice from
   `alerts.urgency_levels` + each level's `corroboration_required`. For the SMS-action tiers
   (5–8) it resolves the delivery channel from that level's `channel` setting (`sms` / `push` /
   `both`, default `both`), so the operator can route a tier to SMS, push, or both; `channel` is
   ignored on the `critical` (`phone_call`) and `low` (`log_only`) levels (the 9–10 call fires an
   additive push regardless). See the [config reference](../../docs/reference/config-reference.md).

Note `classification.corroboration_required` Pydantic default is `2`, but live `config/config.yaml`
sets `1`.
