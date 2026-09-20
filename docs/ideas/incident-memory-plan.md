# Incident memory repair

Status: implemented on `fix/incident-memory`, opt-in and not deployed; final validation
is recorded below. Production deployment requires operator approval.

## Scope and acceptance

Keep the current classification model and article extraction. Repair the distinction
between an article, a real-world incident, and a notification about that incident.
The future combined model workload must fit the operator's USD 20/month ceiling;
provider selection and full-body verification are deferred until measured usage is
available. This change must not add a second model request for every article.

Repeated coverage belongs to the existing incident, even when its classifier event
type changes. Additional sources silently strengthen corroboration. Only significant
escalation in danger creates a new notification revision. Distinct attacks, locations,
incident dates or renewed attack waves remain separate incidents. Ambiguous identity
must not suppress a potentially new urgent incident.

## Design

1. Supply a bounded shortlist of recent stored incidents to the existing Haiku
   classification request. Include their summaries, times, countries and representative
   article evidence. Process classification and grouping sequentially so the next
   article sees the incident created by the previous article in the same cycle.
   Retain exact-URL deduplication, but let different URLs with similar titles reach
   incident comparison. This preserves corroborating sources and avoids discarding
   a new attack because its headline resembles the previous one. It can increase
   the number of classified articles; include that increase in the budget evaluation.
2. Extend the output with an incident decision: `new`, `duplicate`, `update`,
   `escalation`, or `uncertain`; a supplied incident ID for matches; confidence;
   and a short evidence-based explanation. News text is untrusted data. Neither
   `is_new_event` nor string similarity alone authorizes suppression.
3. Validate IDs, types, confidence and country compatibility before accepting a
   match. Missing/invalid/uncertain decisions fail open to a new incident on the
   memory-enabled path. An incoming critical report cannot silently merge into a
   lower-urgency incident: it must trigger escalation. Confirmed same-incident
   repeats may merge after acknowledgement; a new critical incident still gets
   its own event and the existing call workflow.
4. Persist the decision with each classification. Persist an incident notification
   revision and stamp alert records with the revision they attempted to deliver.
   Repeated coverage does not increment revisions. Significant escalation updates
   the alert summary and increments the revision. Replays and restarts must not
   re-notify a provider-accepted revision; immediate/recorded failures must not count
   as accepted. This service does not yet consume final SMS/push delivery receipts,
   so provider acceptance is not proof the handset received the notification.
5. Acknowledgement prevents a second initial call for the same incident. A new
   significant development after acknowledgement sends an update without being
   blocked by the call cooldown. Existing unacknowledged-call retries remain intact.
   A previously noncritical incident crossing the critical threshold remains
   eligible for its first call, subject to corroboration. The existing retry workflow
   is unchanged: re-dispatch on subsequent article activity and polling of pending
   calls. An idle-cycle retry sweep is a separate, pre-existing gap; adding one must
   address old retry records to avoid replaying the production backlog.
6. Migrate existing SQLite databases additively. Existing events and alerts become
   revision 1, preserving delivery history. Do not rewrite historical event identity
   or replay historical notifications during migration.
7. Reject a proposed merge when explicit incident dates/weekday names in source
   text conflict. Record timestamps are not incident dates. Multilingual weekday
   aliases are configured; this is a conservative extra guard, not complete temporal
   understanding. When source text gives no time, uncertainty remains a model limitation.

## Work allocation

- The persistence worker owns additive schema/model changes and migration tests.
- The alert worker owns revision-aware delivery and its regression tests.
- The lead owns candidate retrieval, classification/grouping integration, configuration,
  end-to-end replay tests and documentation.
- An independent reviewer checks for incorrect suppression and restart/replay bugs.

## Verification and rollout

Regression fixtures include the September 16 aircraft-scramble and Rusinowo pairs,
cross-type paraphrases, the same report after acknowledgement/restart, a new attack
wave, different locations/countries, first critical escalation, repeated article IDs,
invalid model decisions and partial delivery failures. Tests must exercise pipeline
decisions through fake notification transports, never real calls or pushes.

Record model accuracy separately from deterministic plumbing tests. A passing mocked
test does not prove Haiku identifies incidents correctly. Run a small labelled model
evaluation before production activation; report tokens and failures. Configuration
allows rollback to the legacy path. No production writes occur in this work session.

## Validation findings and budget (2026-09-20)

The first seven-case live Haiku check rejected a correct noncritical duplicate at
0.85 confidence against the initial 0.9 threshold. Noncritical and critical confidence
thresholds are now separate. These self-reported scores are not calibrated probabilities.

An expanded multilingual case exposed a confidently wrong Monday/Tuesday merge.
The source-text time-conflict guard now overrides it to a new incident. Another
official confirmation was labelled `update` rather than `duplicate`; both are valid
silent same-incident outcomes. Fixtures explicitly accept that equivalence. The suite
is a smoke test, not a representative production accuracy benchmark.

Final verification in this session: **433 offline tests passed**;
**10/10 live memory smoke cases passed**, including Polish, English, Russian and
Ukrainian inputs. The final live run used 29,692 input and 2,771 output tokens.
All development smoke calls together cost approximately USD 0.16 at published
uncached rates. Changed Python files pass Ruff and the diff passes whitespace checks.
A wider Ruff scan still reports ten pre-existing findings in unchanged fetcher,
normalizer and enricher files; those are outside this repair.

Current Haiku pricing used for projections: USD 1/M input and USD 5/M output tokens
([official pricing](https://platform.claude.com/docs/en/about-claude/pricing)).
Read-only production measurements for September 13–16: 1,433 classifications,
3,212,730 input tokens and 336,947 output tokens. Repeating those four relatively
busy days over 30 days projects to **USD 36.73 for classification alone**, before
the existing vagueness gate. This is not the actual monthly bill.

The ten-case memory smoke run used 29,692 input and 2,717 output tokens with ONE
candidate each. At the observed 358.25 articles/day that projects to **USD 46.51/month**,
excluding vagueness checks, additional candidates, extra articles admitted after
fuzzy-title bypass, retries and future full-body verification. This is an illustrative
workload projection, not a production benchmark or upper bound.

**The retained Haiku setup has not demonstrated the USD 20/month target.** Keep memory
disabled until the operator's bill and a representative replay establish the total
workload. Provider/model selection remains deferred by request. Do not enforce the
ceiling by silently stopping emergency classification or notifications.

Independent review also documented two existing delivery limitations: provider
acceptance is not handset delivery, and retry-pending calls lack an idle-cycle sweep.
Neither receipt processing nor replay of the old retry backlog is introduced here.
