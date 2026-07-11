# Spec Delta — classification-alerting-redesign.SPEC.md — 2026-07-11

**Reason:** Reconcile the spec with the owner-labeled ground truth finalized 2026-07-11 (rubric v2 +
`tests/fixtures/dedup_traps.yaml`, 30 piles / 60 events), per the 11-item spec-drift register in
`data/dedup_analysis_2026-07-11.md` (§ Independent Fable recheck). Owner verdicts in
`data/dedup_consistency_2026-07-11.md` are final ground truth.

## ADDED Requirements

**0.14** — The classifier prompt MUST encode the rubric-v2 geography ladder as urgency guidance:
Poland direct Russian attack = 9–10; live airspace intrusion over Poland = ≥9; inert debris in
Poland = 8; Baltics minor incident 6–7 / real strike 8 / deliberate Russian attack with
casualties or shelter orders 9; Romania minor 6 / strike with injuries 7–8 / massive deliberate 9;
Moldova ≈6; roundup and politician-reaction stories scored on their own weight (foreign reaction
≈4, Polish-government reaction ≈6). _(Owner rubric v2, 2026-07-11.)_
→ test `test_prompt_geography_ladder` (unit); Phase 0 gate (test_classifier_geography.py).

**2.11** — `GeoWeighter` MUST floor a **kinetic** event with `target_country == PL` to ≥ call tier
(≥9). It MUST NOT floor kinetic events for other HIGH-tier countries — their call tier is
scenario-conditional (rubric v2) and carried by the prompt (0.14) + eval gates. Floor membership
config-driven: `geography.floor_countries` (default `[PL]`). `[assumed]` key name. _(Prime
directive + owner labels: every kinetic strike on PL soil in ground truth = 9–10/call; Galați
strike with injuries = 8/sms.)_
→ tests `test_geo_weighter_floors_poland_kinetic`, `test_geo_weighter_no_floor_other_nato`.

**2.12** — For every labeled event in `tests/fixtures/dedup_traps.yaml`, `AlertPolicy`'s band
mapping MUST reproduce the owner's action from the owner's urgency (`call`→CALL, `sms`→NOTIFY,
`none`→NONE) — the ground truth is wired into the policy gate. _(Owner labels 2026-07-11.)_
→ test `test_policy_bands_match_ground_truth` (unit, parametrized over all 60 events).

**3.12** — A roundup/summary story covering multiple incidents, and a politician-reaction story,
MUST form its own event: it MUST NOT be merged into an incident event, and MUST NOT cause two
incident events to merge (no bridging). Detection mechanism `[assumed]` (e.g. a story referencing
≥2 distinct `geo_id`s of otherwise-unrelated open events forms its own event). Ground-truth
examples: pile-03 E2, pile-17 E3, pile-21 E3, pile-06 E2/E4, pile-26. _(Owner rubric v2 —
explicitly flipped from the v1 "recap is not its own event" rule.)_
→ test `test_roundup_not_bridge` (unit).

**3.13** — The behavioral trap gate MUST replay **frozen per-article classifier outputs** from a
separate fixture `tests/fixtures/dedup_traps_frozen.yaml` (never live LLM calls in gates;
`dedup_traps.yaml` itself is never modified). The freeze is generated once by an owner-run CLI
(`./run.sh --freeze-traps`, `[assumed]` flag name) that classifies each fixture story with the
real classifier and writes outputs keyed by pile/story id. Until frozen coverage exists for a
pile, `test_dedup_traps_behavioral` skips that pile (and reports the count); the schema test
always gates. _(Resolves the open frozen-vs-live eval question toward FROZEN — `[assumed]`,
owner may override to live.)_
→ tests: `test_dedup_traps_behavioral` (modified), freeze tooling in `sentinel.py`.

## MODIFIED Requirements

**0.9** — inside-Ukraine stays LOW but bands updated to rubric v2 (UA interior ≈2 — regular
warfare, however severe; the Polish reaction is its own event) + ADDED: Ukrainian attacks inside
Russia ≈1, except the NATO-attacks-Russia HIGH case (0.6).
_(Previously: "…is urgency 1–3 (routine inside-UA = LOW)…")_
Impact: `test_prompt_inside_ukraine_low` gains the RU-interior assertion.

**2.3** — dedup is the only suppressor **of alert-eligible events (urgency ≥ notify threshold)**;
NONE-band events (≤4) produce no alert by band mapping (2.4) — that is banding, not suppression.
_(Previously: unconditional "no-alert ONLY when relation == SAME on an already-alerted event",
which contradicted the none band.)_

**2.4** — three bands per rubric v2: ≥9 → CALL; 5–8 → NOTIFY (SMS/push); **≤4 → NONE (stored and
logged, no alert)**. All boundaries config-driven.
_(Previously: "urgency ≥ call-tier (9–10) → CALL; lower → NOTIFY" — omitted the none band; as
written it would have SMS'd every UA-interior 2, RU-interior 1, and foreign-reaction 4.)_
Impact: new test `test_none_band_silent`; `test_policy_bands_match_ground_truth` (2.12).

**2.5** — GeoWeighter still computes `geo_tier` (unchanged) and CALL still requires urgency ≥
call-tier AND geo HIGH; the **universal kinetic HIGH-tier floor is removed**.
_(Previously: "…MUST floor a kinetic HIGH-tier event's urgency to ≥9…" — contradicted owner
labels: Galați strike with injuries = 8/sms ×3 piles, Constanța missiles with injuries = 7/sms,
Vilnius strike with shelter orders = 8/sms. A universal floor would route ~a dozen owner-labeled
sms events to CALL. Replaced by the Poland-only floor, 2.11.)_
Impact: `test_geo_weighter_floors_high_tier_kinetic` replaced by the two 2.11 tests.

**3.3** — unchanged core (split on concrete signals, never wording) + carve-out: roundup/meta
stories are NOT wording variants of an incident — they form their own event per 3.12.
_(Previously: no roundup carve-out; as written it pushed toward folding roundups into incident
events, which fails the fixture.)_

**3.10** — the fixture **EXISTS** (owner-labeled ground truth, reconciled 2026-07-11: 30 piles /
60 events, `meta.rubric_version: 2`). Implementation MUST treat it as read-only input: MUST NOT
create, modify, regenerate, or extend it; labels, stories, and meta are owner-only. Piles 33–62
are a **sealed reserve** held outside the fixture — MUST NOT be added or requested.
_(Previously: "MUST create … as a blank-label fixture … all label fields present but empty …
MUST NOT fill any label" — inverted by reality; labeling completed 2026-07-11.)_
Impact: `test_dedup_traps_schema` now asserts 30 labeled piles / rubric v2 meta (not blankness);
`test_dedup_traps_behavioral` becomes a live gate over frozen-covered piles (3.13); the named
seed "RO-open→PL-strike" is NOT in the fixture (it was sample pile-02, superseded) — that
scenario stays covered by 3.6's synthetic unit test.

## REMOVED Requirements
None (the floor semantics moved via MODIFIED 2.5 + ADDED 2.11 — no tombstones).

## Non-requirement edits
- Preamble: decisions source of truth now includes rubric v2 + owner verdicts + fixture; DRAFT
  §8.1 eval strategy noted stale (superseded by the fixture reality).
- Overview/End State: dedup ground truth named as the over-merge gate.
- Non-Goals: "labeling any traps" bullet updated — labeling DONE 2026-07-11; prod-DB mining still
  an owner follow-up.
- Technical Context: new "Ground truth (2026-07-11)" fact block (fixture, bands, ladder, sealed
  reserve, file pointers).
- Phase 3 deliverables: fixture reclassified read-only input; `dedup_traps_frozen.yaml` +
  `sentinel.py --freeze-traps` added.
- Gate notes: behavioral-test skip rationale updated (skips = missing frozen coverage, not
  missing labels).
- Owner follow-ups: #1 replaced (label→done; new: run `--freeze-traps` once implemented; grade
  10–15 sealed piles as a blind check when the deduplicator passes the 30).

---

# Round 2 (same day) — fixes from the adversarial verification (13 findings, 4 blocking)

## ADDED
- **0.15** — classifier `event_type` enum gains `debris_found` + `official_statement` (+ prompt
  rules) — the carve-out signals for 2.5b/2.11/3.12. → test `test_prompt_debris_and_statement_types`.
- **3.14** — fixture-backed **9/10 recall gate**: frozen replay → GeoWeighter → AlertPolicy must
  route every owner-labeled call event to CALL (zero misses among covered piles).
  → test `test_dedup_traps_call_recall`.

## MODIFIED (round 2)
- **4.5** — fire-first rescoped from "geo-floored articles" to ANY call-tier + geo-HIGH article,
  floored or natively scored (blocking finding: natively-scored 9s incl. PL airspace calls fell
  outside the guarantee once the floor became Poland-only). Test 4 updated to cover both paths.
- **2.5** — added: urgency ≥ call-tier with geo LOW demotes to NOTIFY, never NONE (closed the
  silent-suppression hole). Test 5 assertion tightened.
- **2.5b / 2.11** — kinetic set must exclude `debris_found`/`official_statement`; 2.11 rationale
  narrowed to "strike"; new tests `test_debris_not_floored`, `test_floor_countries_config_driven`.
- **3.12** — reaction detection pinned to `event_type == official_statement` (was unadjudicable);
  new test `test_reaction_story_own_event`.
- **3.13** — loop MUST NOT author/fabricate/commit `dedup_traps_frozen.yaml` content; manifest
  ownership of the frozen file dropped (owner-generated).

## Stale-prose reconciliations (blocking findings 1–2)
- Phase 3 intro: "Creates the blank trap fixture" → "Consumes the owner-labeled trap fixture
  (read-only) and ships the freeze tooling".
- Phase 2 geo_weighter deliverable: universal floor wording → `floor_countries`-scoped (2.11).

## Minor
- `test_prompt_geography_ladder` now enumerates every ladder element (incl. PL debris 8 and the
  roundup/reaction rule); Phase 2 deliverables note the pre-existing fixture as read-only input;
  shared-files section gains `sentinel.py` (Phases 0+3); 3.10's scenario-coverage claim corrected
  (simultaneous strikes different towns = pile-28; pile-13 is different-country separation);
  gate-notes skip carve-out extended to `test_dedup_traps_call_recall`.

Totals after round 2: 61 requirements (P0 15 · P1 7 · P2 14 · P3 15 · P4 10), 61 tests.

---

# Round 3 (same day) — fixes from re-verification (1 blocking + 5 findings)

- **3.12 (BLOCKING fix)** — roundup signal's "of otherwise-unrelated open events" qualifier
  REMOVED: it provably failed pile-03 E2 (the Mazowsze-fire locus has no open event). New signal:
  ≥2 distinct loci, open events or not (wrong split = warn-only under-merge, safe direction);
  mechanism must reproduce all three cited roundup examples on standalone replay.
- **4.5** — scoped to articles the deterministic core resolves as opening a NEW event, so
  fire-first can never re-fire a duplicate of an already-alerted event (2.6 governs those).
- **3.14** — hit semantics pinned: ≥1 story of the owner call-event must produce a CALL-class
  `AlertIntent` during STATEFUL replay (GeoWeighter-score-only assertions don't count).
- **2.13 [ADDED]** — the hidden fourth pre-decision cut (hardcoded
  `corroborator._MIN_EVENT_URGENCY = 5` + `is_military_event` drop, corroborator.py:28,53 —
  verified in live code) becomes config-driven and must not drop sms-tier statement/roundup
  stories; 2.4's wording reconciled (NONE-band = persisted classification, no event row);
  Technical Context gains the fourth-cut fact bullet. → test `test_min_event_urgency_config_driven`.
- **2.14 [ADDED]** — every `event_type` value gets a Polish rendering in alert templates
  (`EVENT_TYPE_PL` lacks the two new types → raw English would leak into Polish alerts).
  → test `test_event_type_pl_covers_enum`.
- **0.15** — prompt must keep `is_military_event: true` for military-related statement/debris
  stories (else the fourth cut drops them). Test 15 extended.
- **3.8** — made symmetric (debris story never absorbed by an open kinetic event). Test 7 extended;
  `test_reaction_story_own_event` now also covers the open-airspace case;
  `test_geo_weighter_kinetic_from_event_type` asserts the two new types are non-kinetic.
- Deliverables: Phase 0 classifier bullet names the enum extension; Phase 2 corroborator bullet
  names the gate configification; Phase 2 state_machine bullet names the `EVENT_TYPE_PL` extension.

Totals after round 3: **63 requirements** (P0 15 · P1 7 · P2 16 · P3 15 · P4 10), **63 tests**.

---

# Round 4 (same day) — the escalation-to-call hole (1 blocking + 2 hardenings)

- **2.6 (BLOCKING fix)** — first-CALL-per-event semantics: ESCALATION to an event already alerted
  **at CALL class** → NOTIFY (one call per event); but an event's **first CALL-class intent fires a
  call regardless of relation** — an 8/sms-alerted debris event escalating to a 10 strike (pile-16)
  gets its call. Previously the letter allowed an urgency-10 strike on Polish soil to produce only
  an SMS. Test 2 rescoped to the CALL-alerted case; new test 2b `test_escalation_first_call_fires`.
- **4.5** — fire-first extended to call-tier-crossing ESCALATIONs (an event's first CALL-class
  intent); test 4 now covers three cases.
- **2.13** — deterministic exemption: the `is_military_event` drop never applies to
  `debris_found`/`official_statement` articles (prompt compliance alone is not a gate); test 16
  extended.
- Wording: `test_none_band_silent` reconciled with 2.13 (classification persisted, no event row).
- Owner follow-up #6 added: tune the 3.12 two-loci signal if warn-only under-merge reports show it
  over-splitting multi-locus incident stories (safe direction — extra calls, never suppression).

Totals after round 4: **63 requirements** (unchanged), **64 tests**.

## Post-PASS polish (verifier's two optional LOW notes, folded in)
- 2.6: "alerted at CALL class" pinned to intent-DISPATCHED (transport outcome handled by 1.2, never
  re-decided); "regardless of relation" scoped (NEW/ESCALATION; SAME can't carry a tier crossing per
  3.7 — defective input fails toward firing).
- 2.9: pure-function input list extended with the prior alert class (`already_alerted_at`).

**FINAL VERDICT (round 4): PASS** — four adversarial rounds, all blocking findings resolved.
