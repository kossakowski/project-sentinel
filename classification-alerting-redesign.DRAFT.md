# Project Sentinel — Redesign: Dedup-Only Suppression, Reliable 9/10 Capture, and Resilient Alerting

This is an **understanding-oriented** explanation document (Diátaxis). It is a *new* file — it does not overwrite the living `SPEC.md` or the existing `docs/explanation/architecture.md`. It describes the **target redesign** of Project Sentinel's classification, grouping/deduplication, alert-decision, and reliability layers, grounded in a full read of the current code (`sentinel/classification/corroborator.py`, `classifier.py`, `models.py`, `database.py`, `sentinel/alerts/state_machine.py`, `twilio_client.py`, `push_client.py`, `dispatcher.py`, `sentinel/scheduler.py`, `sentinel/eval/harness.py`, `config/config.yaml`, and the deploy units). It encodes the five governing principles — **fire before asking**, **dedup is the sole suppressor**, **geography weighting (Poland/Baltics/Romania + NATO-attacks-Russia = HIGH; inside-Ukraine = LOW)**, **urgency tier → channel class (transport-agnostic)**, and **quality over cost, bounded ~$100/mo** — and it is honest about what those principles cannot buy.

---

## 0. CRITICAL UNRESOLVED RISKS (read this first)

The redesign **reduces** prime-directive risk versus today (it deletes the corroboration gate, fixes the inverted Romania geography, adds a code-level geo floor, and makes Twilio failure loud). But making **deduplication the sole suppressor** (Principle 2) converts *every false merge into a silently missed 9/10*. The mitigations in this document close most of the attack surface; the following risks are **residual — they survive their mitigations** and the owner must accept them, or fund the extra hardware/contacts that shrink them.

> ### 🔴 RESIDUAL CRITICAL / HIGH RISKS
>
> 1. **Merge-into-silence on a thin/empty-locus first copy.** If a real strike on Poland surfaces only as a terse, place-less flash ("explosion reported near the border", no town named, no body fetched), neither the gazetteer scan nor the LLM-emitted locus engages the geo floor, and `urgency = max()` over identically-thin syndicated copies can pin the event below the CALL tier. **Mitigated** by a deterministic body+title gazetteer scan and a "re-read severity when N copies accumulate in a HIGH-tier geocell" rule — but a *determinedly* vague yet real flash can still under-alert until a richer article arrives, which may exceed the ~15-minute escape window. **Residual: HIGH.**
>
> 2. **Separation-vs-collapse is an irreducible tension.** Every knob that prevents a missed *second* strike (strict `geo_id` splitting, short novelty gap, default-to-NEW) re-introduces fragmentation / duplicate calls for the Galati burst the design promises to collapse. We deliberately tune **toward split-when-unsure** and accept occasional duplicate calls — but the over-merge failure direction is the *quiet* one (fewer alerts looks like a calm news day), so it is the hardest to detect in production. **Residual: HIGH.**
>
> 3. **Delivery acceptance ≠ delivery confirmation, and the CALL tier has no independent voice fallback.** Push/Telegram are NOTIFY-grade, not "ring a sleeping person at 3am." Until a **second, different-vendor voice carrier** (e.g. Vonage/Plivo/Telnyx — *not* a second Twilio subaccount) is provisioned and a positive **delivery receipt** gates every transport, a Twilio account-level failure downgrades a 3am 9/10 to a notification the owner may not hear. **Residual: HIGH** until the second carrier + receipts ship (Phase 4).
>
> 4. **The owner is a single point of failure.** A delivered, receipt-confirmed alert still requires the owner's one phone to have signal and attention. No software design closes "the phone is off at 3am." The only true mitigation is a **second human** in the CRITICAL escalation path — which the owner has not yet agreed to (Open Question Q1/Q9). **Residual: CRITICAL** by construction.
>
> 5. **Correlated, crisis-coincident failure.** The independent channels (Telegram, email, hosted watchdog) can fail *together with* the very war scenario the system exists to detect (regional internet throttling, a Hetzner outage, the owner's connectivity). Stacking watchers reduces but never eliminates this; the regress terminates at a human who must care about silence. **Residual: CRITICAL** and irreducible.
>
> 6. **Slow-judge latency on the critical adjudication path may push a 9/10 past the escape window.** The design deliberately escalates the dedup same-event judge to **Sonnet when urgency ≥ 9 on either side** (§5.1 Step 4; §9 Tier 2) to maximize anti-over-merge precision on exactly the articles that matter most. The hazard is that this places the **most critical articles on the slowest adjudication path**: a Sonnet call (plus 429/back-pressure during a war-news burst) on top of a 15-minute slow-lane cycle can push acknowledged contact past T0+20 min — the opposite of what the ~15-minute escape window demands. **Mitigated** by a strict ordering that makes the slow judge *never block the first call*: (a) any article geo-floored to ≥9 in a HIGH-tier geocell **fires the CALL first** and runs the Sonnet judge **asynchronously, only to suppress the NEXT copy** (§5.1 Step 0a, §6.2); (b) critical-band dedup **fails OPEN to NEW + CALL on the slow-judge path** — timeout, 429, or any judge error → NEW + CALL, not only on embedding failure (§5.1 Step 4); (c) a **hard per-call judge timeout (default 8 s) defaulting to NEW + CALL** (§5.1 Step 4, §5.3); (d) a **breaking-keyword-in-HIGH-tier-geocell article is promoted to the fast lane immediately** so a 9/10 never waits a full 15-minute slow cycle (§3.1, §5.1 Step 0a). With these, the Sonnet judge only ever *delays a duplicate-suppression decision*, never the first contact. **Residual: MEDIUM** — the asynchronous judge still consumes budget under burst and a mis-promotion could let one borderline article ride the slow lane, but no first CALL is gated on Sonnet.

Everything else flagged critical/high by the adversarial review (the escalation-re-call contract, the acknowledged-event guard, the empty-`country_iso` override hole, embedding-provider drift, the Expo-push no-op, the watcher-of-the-watcher gap, DB-write-during-the-incident) **is closed by a specific code-level mitigation below** and is not residual *provided the migration phases ship in order*. Those mitigations are stated as "Risk / Mitigation" notes in the relevant sections. The slow-judge-latency finding is folded in as both the §5.1/§6.2 fire-first ordering and Residual Risk #6 above.

---

## 1. Executive summary + rewrite-vs-refactor

**The core failure today is grouping fragmentation, not missed detection-by-design.** A single Russian drone strike on **Galați, Romania (2026-05-29)** produced 304 articles that fragmented into ~23 event rows and ~11–15 phone calls. The audit traced this to a brittle 6-gate matcher, a non-transitive event-type table, a high-urgency country gate that trips on empty/`unknown` country, fuzzy matching over a single Polish summary string, and — the deepest bug — a **classifier prompt that scores Romania 1–3 by rule** (the inverse of Principle 3) so Galați could never reach the call tier even with a perfect grouper. Layered on top are a **no-op corroboration gate**, a **duplicated alert decision** that can disagree, and **reliability defects** (failed alerts not persisted, an unbounded `retry_pending` loop, one Twilio account carrying calls + SMS + the health-escalation SMS, no independent heartbeat).

**Recommendation: HYBRID — greenfield the two rotten cores, targeted-refactor everything around them.**

| | Verdict | Why |
|---|---|---|
| **Greenfield rewrite** | ❌ Rejected | The upstream pipeline (fetchers, title-dedup at `deduplicator.py:21-59`, the R1–R10 classifier rubric, the sliding-window DB query at `database.py:190-206`, the row-keyed suppression at `state_machine.py:232-237`, systemd/logrotate) is sound; several pieces were *already fixed* (the country gate was relaxed below the phone threshold; the sliding window is correct). A full rewrite would deliberately drop 9/10 coverage during the swap — unacceptable. |
| **Pure refactor** | ❌ Rejected | `Corroborator` conflates four concerns (event-identity dedup, corroboration source-counting, a duplicate alert decision, geography/severity leaking into the merge key). You cannot incrementally untangle that. |
| **Hybrid** | ✅ Chosen | **Greenfield** the grouper → new `EventDeduplicator` and the alert decision → new `AlertPolicy`. **Refactor** the surroundings: extend the classifier schema (add `locus`, `onset`, `geo_tier`), add columns/tables to the existing SQLite DB, refactor `TwilioClient` + `AlertStateMachine` for durable failure records, bounded retry, and a transport-abstraction seam. Blast radius is contained to `sentinel/classification/` and `sentinel/alerts/`; the rest is additive. Critically, the new dedup can **shadow-run** against the old one so 9/10 coverage is never dropped during cutover. |

---

## 2. Audit findings (current state)

Each embedded-evidence item is explicitly **CONFIRMED**, **REFUTED**, or **REFINED** against the code. Where evidence and code conflict, the **code wins** and the discrepancy is flagged.

### 2.1 Classification & geography

- **Romania scored 1–3 by prompt rule (CONFIRMS + sharpens evidence).** The system prompt scopes the analyst to "Poland, Lithuania, Latvia, or Estonia" only (`classifier.py:16`); the user-prompt CRITICAL RULES state urgency 9–10 is "EXCLUSIVELY" for PL/LT/LV/EE (`classifier.py:142`) and "Attacks on Ukraine or other non-monitored countries = urgency 1-3" (`classifier.py:143-144`). Romania, a Principle-3 HIGH state, appears nowhere — not in `monitoring.target_countries` (`config.yaml:2-14`), not in keywords, not in the prompt. The Principle-3 "attack ON Russia by NATO = HIGH" case is also entirely unhandled. This is the inverse of Principle 3 and a classifier-level cause of Galați under-scoring — *even a perfect grouper cannot fix it.*
- **`temperature` IS set to 0.0 (REFUTES evidence).** `_send_request` passes `temperature=self.config.classification.temperature` (`classifier.py:278`); `config.yaml:474` sets `0.0`. The Anthropic Messages API has no `seed` parameter, so its absence is expected, not a defect. **The Galați urgency-2-to-9 spread is therefore NOT a sampling artifact** — it is input variance (304 syndicated copies with differing titles/summaries; the enricher overwriting `summary` per copy at `enricher.py:266`; "Source:" query-string leakage) plus prompt edge-cases (R6/R8, R7, R3-vs-scramble). **Do not "fix" instability by lowering temperature — it is already 0.**
- **Keyword pre-filter can silently drop a 9/10 before the LLM (CONFIRMS, new path).** The scheduler runs the keyword filter (Step 4, `scheduler.py:236`) *before* classification (Step 6, `scheduler.py:247`) *and before* enrichment (`scheduler.py:241`). `KeywordFilter.matches()` lowercases title+summary only (`keyword_filter.py:51`) and, for Slavic languages, does pure **substring** matching (`keyword_filter.py:186-189`); English uses word-boundary regex (`190-194`). A PL/UA/RU breaking flash whose wording is not a substring of a configured keyword is discarded pre-LLM. Mitigation today: `keyword_bypass` sources skip the filter (`104-111`) — Defence24, Defence24 EN, and all four Telegram channels (`config.yaml:318,359,447-461`) are safe — but ordinary RSS/Google-News breaking news is gated.
- **Exclude-keyword veto kills "high"-only matches (CONFIRMS, new path).** `matches()` skips the exclude check only on a CRITICAL match (`keyword_filter.py:64`); a "high"-only article (e.g. only `dron`) that also contains an exclude word like `manewry`/`ćwiczenia` (`config.yaml:275-276`) is dropped (`71-78`) — pre-empting the LLM's exercise-vs-attack judgment with a blunt veto.
- **`is_new_event` is a fully dead signal (CONFIRMS, verified end-to-end).** Emitted (`classifier.py:125,188`), modeled (`models.py:116,134,152`), stored NOT NULL (`database.py:58`), and **never read** by the grouper (`corroborator.py:75-143`). A grep across `sentinel/` finds it only in classifier/models/database. The system spends tokens on the LLM's same-event judgment and discards it.
- **Polish summary is under-specified and doubles as the grouping key.** Requested by one inline phrase (`classifier.py:127`), consumed verbatim (`classifier.py:190`) with no required fields/length cap/validation; it is also the fuzzy grouping key (`corroborator.py:130`, threshold 50 per `config.yaml:485`), so summary phrasing variance directly drives fragmentation.

### 2.2 Grouping / deduplication

- **The grouping code has been materially rewritten since the evidence was gathered.** The "7-condition brittle AND match" is now a **6-gate sequential filter** (`corroborator.py:88-141`); the country-intersection gate the evidence blamed has **already been relaxed below the phone threshold** (`_countries_compatible`, `corroborator.py:188-211`: empty/`unknown` no longer blocks merges *below* urgency 9). **STALE evidence flagged.**
- **Non-transitive event-type table (REFINES evidence).** `EVENT_COMPATIBILITY` (`corroborator.py:15-25`): `drone_attack`'s set omits `missile_strike`, and vice versa (`18`/`21`). `_are_compatible_types` checks both directions (`145-155`) and returns False, so a drone-labeled and a missile-labeled article about the *same* Galați strike cannot merge (`89-91`). The precise defect is the **drone↔missile gap**.
- **High-urgency country gate still trips on empty/`unknown` (PARTIALLY CONFIRMS/REFUTES).** At urgency ≥ phone threshold, `_countries_compatible` returns `bool(result_set & event_set)` with no empty-set relaxation (`corroborator.py:207-208`), where the sets drop `''`/`unknown` (`157-165`). A Galați article scored 9 that emitted `[]`/`['unknown']` yields an empty intersection → its own event + its own call. The evidence's "every article spawns its own event because Romania is unmonitored" is **stale** (RO matches RO fine; sub-9 articles now merge). The surviving trigger is **empty/unknown country at urgency ≥ 9**.
- **Summary similarity is the dominant residual splitter (REFUTES literal evidence).** Gate F compares `metric_fn(result.summary_pl, event.summary_pl)` (`corroborator.py:129-139`) — **both operands are Polish**, so the evidence's "token_set_ratio < 50 across translations" framing is stale; the real risk is **Polish-summary phrasing variance** across 304 copies falling below 50.
- **Candidate ordering silently determines grouping (new).** `get_active_events` returns `ORDER BY last_updated_at DESC` (`database.py:199-205`); `_find_matching_event` binds the **first passing** candidate (`corroborator.py:141`). When several siblings are compatible, an article binds to whichever was touched most recently — order-dependent, with **no merge step** to coalesce siblings.
- **Article-level dedup is sound but lets syndication through.** `_check_duplicate` (`deduplicator.py:21-59`) collapses verbatim titles (cross-source ≥ 95), so the 217/304 single-Google-News-query copies survive whenever titles differ by > ~5% and land on the grouper.

### 2.3 Alert decision & dispatch

- **Dual decision authority (CONFIRMS, refines mechanism).** `Corroborator._determine_alert_status` (`corroborator.py:339-359`) stamps a string `alert_status` on the event using hardcoded 9/7/5 cuts and `classification.corroboration_required`; it is persisted (`corroborator.py:268,317`) **but never read by dispatch**. `AlertStateMachine._determine_action` (`state_machine.py:261-292`) independently recomputes the action from `alerts.urgency_levels` and **is** the value that fires (`state_machine.py:223`). They read **two different `corroboration_required` keys** (`classification.*` vs `alerts.urgency_levels.*`), so they drift the moment those numbers differ — a config-drift bug, not a runtime race.
- **Transport is hard-wired (CONFIRMS Principle-4 violation).** `_determine_action` returns literal `'phone_call'/'sms'/'log_only'` (`state_machine.py:285-292`); `process_event` branches straight into `_execute_phone_call → self.twilio.make_alert_call` (`state_machine.py:377`) and `_execute_sms → self.twilio.send_sms` (`552`). The `urgency_levels.action` config field literally names the transport (`config.yaml:493-508`). Push is fired unconditionally for any non-`log_only` action (`state_machine.py:241-242`, `_maybe_send_push:608-643`) as an additive side-channel — never tier-selected, never a fallback. One `TwilioClient.client` (`twilio_client.py:21-25`) backs calls, SMS, confirmation polling, and inbound-ack polling.
- **Corroboration is a confirmed no-op but still wired in.** `corroboration_required=1` everywhere (`config.yaml:475` and each `alerts.urgency_levels.*`), so `source_count >= 1` is always true. The machinery (`_is_independent_source`, `corroborator.py:65-67,213-263`) still runs every cycle.

### 2.4 Reliability & observability

- **Failed alerts are NOT durably persisted (CONFIRMS, critical).** `alert_records` (`database.py:89-99`) has columns id/event_id/alert_type/twilio_sid/status/duration/attempt/sent_at/message_body — **no `error_code`/`http_status`/failure column**, and `AlertRecord.to_dict` (`models.py:232-243`) emits exactly those. `make_alert_call`/`send_sms` catch `TwilioRestException`, log, and **return None** (`twilio_client.py:54-62,86-95`); callers insert only on non-None (`state_machine.py:377-383,552-555`), so `insert_alert_record` (`database.py:208-219`) is never reached on failure. A failed urgency-9 alert leaves **zero rows + one ERROR log line**. Push is identical (`push_client.py:80-98`).
- **`retry_pending` loops forever (CONFIRMS, critical).** A 401 → `make_alert_call` None → call loop `if record is None: continue` for every attempt (`state_machine.py:377-380`) → `alert_status='retry_pending'` (`420`) → re-fired every ~5 min (`retry_interval_minutes:5`) **indefinitely**: no global cap, no backoff, no dead-letter, no escalation. `urgency_levels.*.retry_attempts` is **dead config** (no reader). The SMS fallback shares the same client and also fails.
- **Twilio is a SPOF for the alert path AND the health escalation (CONFIRMS, worse than stated).** `_send_system_sms` (`scheduler.py:429-435`), called by `_check_pipeline_health` at 3 consecutive failures (`508-512`) and `_check_fetcher_health` at 10 (`406-421`), rides the same Twilio account. A 401 kills calls, SMS, confirmation, polling **and the only mechanism that would warn the owner.**
- **Acknowledgement is in-memory and Twilio-dependent (CONFIRMS).** `self._confirmation_code` (`state_machine.py:442`) is lost on restart; the inbound poll (`461-491`) uses the dead client. The only ack path is SMS (no DTMF, per the no-voicemail-false-positive design).
- **No independent heartbeat (CONFIRMS with nuance).** `health.json` is self-reported at cycle end (`scheduler.py:514-556`); a wedged process never updates it and nothing alarms on staleness. No Twilio auth/balance preflight. `check_pending_calls` can't detect a 401 because `get_pending_call_records` only returns `initiated`/`ringing` (`database.py:229-237`), which a 401 never creates.
- **Classifier outage fails SILENT (CONFIRMS, new SPOF).** `classify_batch` is wrapped so an Anthropic outage sets `classifications=[]` and continues (`scheduler.py:243-255`) — zero events, zero alerts, one log line.
- **Eval cannot catch any of this (CONFIRMS).** `run_eval` classifies ONE synthetic headline per case (`harness.py:170-181,231-273`) over 44 owner-labeled fixtures; it re-derives the action mapping a **third time** in `_action_for_urgency` (`harness.py:32-45`); CI gates only at `overall_pass_rate==1.0` (`sentinel.py:398-399`). It never invokes the corroborator (cannot test grouping/over-merge) and never touches dispatch (cannot test delivery). 9/10 recall appears only indirectly in the confusion matrix — **not a first-class gated metric.** Owner-as-sole-labeler is honored (`harness.py:122-167`; captured `haiku_output` is reference-only). Two fixtures exist (`eval_set.yaml` vs newer-mtime `eval_set_human.yaml`) — **canonical one must be pinned.**

---

## 3. Target architecture

### 3.1 End-to-end flow

```
Article
  └─[1] FETCH (unchanged: dual-lane APScheduler, fast 3m / slow 15m)
  └─[2] ARTICLE-DEDUP (unchanged: deduplicator.py:21-59, collapses verbatim titles)
  └─[3] KEYWORD PRE-FILTER (REFACTOR: HINT for breaking lanes, gate kept only for bulk; moved AFTER enrich)
           └─ FAST-LANE PROMOTION (NEW: breaking-keyword + HIGH-tier place token → jump to fast lane,
              so a 9/10 never waits a full 15-min slow cycle)
  └─[4] ENRICH (unchanged: enricher.py:266 overwrites summary with body)
  └─[5] CLASSIFY (REFACTOR schema: + locus, target_country, geo_tier, onset, is_new_event resurrected)
           └─ GeoWeighter (NEW: code-level geo floor, runs AFTER the LLM)
  └─[6] EVENT-DEDUP (GREENFIELD: EventDeduplicator → EventDecision{event_id, NEW|SAME|ESCALATION})
           └─ Step 0a FIRE-FIRST (NEW: geo-floored ≥9 in HIGH-tier geocell → emit NEW+CALL immediately;
              the same-event judge, incl. any Sonnet escalation, runs ASYNC only to suppress the NEXT copy)
  └─[7] ALERT-POLICY (GREENFIELD: the ONE authority → AlertIntent{channel_class, is_update})
  └─[8] DISPATCH (REFACTOR: state_machine becomes a pure executor of AlertIntent)
           └─ Channel registry + ordered fallback chains (NEW: channels.py)
  └─ Watchdog (NEW: out-of-band heartbeat, Twilio auth/balance preflight, independent escalation)
```

The `Corroborator` class is **decommissioned**: its dedup moves to `EventDeduplicator`, its decision moves to `AlertPolicy`, and its corroboration/source-count machinery (`corroborator.py:65-67,213-263`; both `corroboration_required` gates) is **deleted** per Principles 1 & 2.

**Latency contract (critical path).** The slow lane (15 min) and any Sonnet judge escalation must **never gate the first CALL** for a critical article. Two structural rules enforce this: (1) a breaking-keyword article carrying a HIGH-tier place token is **promoted to the fast lane at Step 3** so a 9/10 never sits in a 15-minute slow cycle; (2) at Step 6 the **fire-first short-circuit (Step 0a)** emits NEW + CALL immediately for any geo-floored-≥9 article in a HIGH-tier geocell, and the same-event judge (Haiku or its Sonnet escalation) runs **asynchronously**, used only to suppress the *next* copy — never to delay the first contact. See §5.1 and §6.2.

### 3.2 The single decision authority

**One module: `sentinel/alerts/policy.py :: AlertPolicy.decide(event_decision, weighted_urgency, geo_tier) → AlertIntent`.** It collapses all three current authorities:

- **DELETE** `corroborator._determine_alert_status` (`corroborator.py:339-359`). The `events.alert_status` column survives only as a *lifecycle* state (active/acknowledged/expired), never as a transport name.
- **DELETE** `state_machine._determine_action` (`state_machine.py:261-292`) and its corroboration downgrade (`286-289`).
- **DELETE** the eval's third copy `harness._action_for_urgency` (`harness.py:32-45`); the eval **imports `AlertPolicy`** so it tests the real authority.

The entire mapping (transport-free):

```python
tier = TIER(weighted_urgency)        # CRITICAL ≥9, HIGH 7-8, MEDIUM 5-6, else NONE
if event_decision.relation == SAME and already_alerted(event):
    return AlertIntent(NONE)         # dedup is the SOLE suppressor
channel_class = CALL if tier == CRITICAL else (NOTIFY if tier in {HIGH, MEDIUM} else NONE)
is_update = (event_decision.relation == ESCALATION)
return AlertIntent(channel_class, is_update)
```

`corroboration_required` is removed from config in both locations; the tier→class table lives in config as `{min_score, channel_class}` only. The dual-authority drift bug is *impossible* because corroboration no longer exists and there is one mapping.

> **Risk / Mitigation — single authority removes the only cross-check.** Consolidating to one authority is correct, but a boundary comparator (`>=` vs `>`) or an off-by-one in the geo floor (8 vs 9) becomes a single point of *silent* failure for the call tier. **Mitigation:** (a) a code-level invariant asserted at startup — *a kinetic event in a HIGH-tier geocell MUST map to CALL*; the process refuses to start if config would route urgency-9 HIGH-tier kinetic to anything but CALL (a config that raises CRITICAL `min_score` above 9 fails the self-check); (b) dedicated boundary eval fixtures at urgency *exactly* 9 and *exactly* 10 per HIGH-tier country, separately gated at 100% (§8). **Residual:** boundary correctness now rests on test-coverage discipline, which can erode under pressure.

---

## 4. Classification + geography design

### 4.1 Reliable 9/10 capture — defense in depth, every layer fails toward FIRING

1. **Keep the strong R1–R10 rubric** — shelter/air-raid/evac in monitored states → MIN 9; named offensive weapons over monitored airspace → MIN 9; strike on/at a monitored border → MIN 9. It is genuinely good for true positives once the article arrives.
2. **Widen the prompt's geography scope** so it no longer hard-caps 9–10 to PL/LT/LV/EE and no longer says "other = 1-3" (`classifier.py:16,142-144`). Replace with Principle-3 tiering (§4.2).
3. **Add a CODE-LEVEL geo re-floor AFTER the LLM** (`GeoWeighter`): if `geo_tier == HIGH` and the event is kinetic/escalatory, floor urgency to ≥ 9 regardless of the model's draw. This is the backstop the audit found missing (`classifier.py:178` only clamps).
4. **Fix the upstream keyword veto** (§4.3) so a PL/UA/RU breaking flash cannot die before Haiku.
5. **Fail LOUD on classifier outage** — replace the silent `classifications=[]` continue (`scheduler.py:243-255`) with a Watchdog alarm via the independent channel, and add a dead-letter queue + persisted error for dropped articles (`classifier.py:202-228,260-271`).

> **Risk / Mitigation — the geo floor depends on the LLM emitting a HIGH-tier locus.** A thin summary that omits the Polish town yields empty/UA-framed `country_iso`, so the ≥9 floor never engages. **Mitigation:** run a **deterministic gazetteer/keyword scan over BOTH title and enriched body** (not just the LLM's `locus` field) for any HIGH-tier place token; if any HIGH-tier place is present AND the family is kinetic, floor ≥9 regardless of the LLM. On every merge into an open HIGH-tier event, re-evaluate the floor against the *merged-locus union*. Force at least one LLM severity re-read when a HIGH-tier-geocell event has accumulated > N copies but is still sub-CRITICAL. Treat enrichment failure on a HIGH-tier-geocell article as a signal to **escalate classification to Sonnet**, not to drop to a thin summary. **Residual:** a determinedly place-less real flash (Residual Risk #1) can still under-alert.

### 4.2 Geography weighting per Principle 3 (code-level, not prompt prose)

A new `geography:` section in `config.yaml` (nothing hardcoded):

```yaml
geography:
  high_tier_countries: [PL, LT, LV, EE, RO]     # NATO border states incl. Romania
  nato_members:        [PL, LT, LV, EE, RO, DE, ...]  # for the attack-ON-Russia case
  aggressors:          [RU, BY]
  # LOW = inside-Ukraine routine strikes
```

The classifier emits structured `locus{place, country_iso, admin_region}`, `target_country`, and `attacker_is_nato`. `GeoWeighter` (after the LLM, before `AlertPolicy`):

```
geo_tier = HIGH  if target_country ∈ high_tier_countries
                 OR (target_country == RU AND attacker_is_nato)   # Principle-3 NATO-attacks-Russia HIGH
           LOW   if target_country == UA AND not spillover-toward-border
           else  default HIGH for ambiguity near a monitored border  # bias to fire
```

- **The Galați case:** RO is HIGH → a Russian strike on Galați is geo-floored to ≥9 → reaches the CALL tier (today it is 1–3 by prompt rule — the deepest classification bug). Combined with the locus dedup key (`geo_id='galati'`), 304 copies collapse to one event, one call.
- **NATO-attacks-Russia** (entirely unhandled today): `attacker_is_nato` + `target_country == RU` → HIGH → ≥9 → CALL. This is the clearest Article-5 / border-closure signal.
- **Spillover** into non-monitored territory near a monitored border defaults HIGH. The locus is still extracted even when `target_country` is empty — fixing the empty-country gate the old grouper tripped on (`corroborator.py:207-208`).

> **Risk / Mitigation — `attacker_is_nato` is an LLM boolean.** A missed boolean demotes the single most decision-relevant escalation to NOTIFY. **Mitigation:** a deterministic backstop — a NATO-member-aggressor token scan over the body in addition to the LLM boolean. **Residual:** if a single thin article genuinely cannot distinguish a retaliatory NATO strike from routine war noise, no code floor manufactures that judgment.

### 4.3 Keyword filter: gate → hint (for breaking lanes)

Any priority-1 RSS / Google-News / Telegram article goes to the classifier **regardless of keyword match** (today only `keyword_bypass` sources skip the filter, `keyword_filter.py:104-111`). For breaking lanes the keyword filter becomes a **priority hint**, not a gate, and runs **after** enrich so it sees the body (`scheduler.py:235-247`). Non-breaking *bulk* sources keep a gate for cost control.

**Fast-lane promotion (latency guard).** When the keyword hint fires a **breaking keyword AND a HIGH-tier place token co-occur** in title+body, the article is **promoted out of the slow (15-min) lane into the fast (3-min) lane immediately**, so a critical border-state flash never waits a full slow cycle to be classified. This is the upstream half of the "a 9/10 never rides the slow path" contract; the downstream half is the fire-first short-circuit at §5.1 Step 0a.

> **Risk / Mitigation — the retained bulk gate re-opens the miss path.** A real 9/10 that surfaces ONLY on a bulk source whose wording is outside the keyword set still dies pre-LLM (`keyword_filter.py:174-195`). **Mitigation:** for bulk sources, replace the hard veto with a **cheap second-stage screen** (a low-cost batch Haiku pass or a local embedding similarity-to-attack-prototype score) — fail toward classification, not silence; never apply the exclude-keyword veto to bulk articles that also contain a HIGH-tier place token; audit which sources are "bulk" and promote any source that has *ever* carried a border-state attack to the breaking lane. **Residual:** sending all keyword-miss bulk articles to Haiku pressures the $100 cap on high-volume war days — the cost-vs-recall tension is not fully eliminable while any bulk gate exists.

### 4.4 Stability fix & Polish summary

- **Instability is removed from the dedup key, not "fixed" at the model.** `event_type` collapses into ~9 closed FAMILIES used only for candidate retrieval (replacing the non-transitive table `corroborator.py:15-25`). **Urgency is removed from the dedup key entirely** — it only sets the channel via `max()` on merge, so the 2-to-9 spread can no longer fragment events. Cross-lingual phrasing variance is absorbed by **embedding similarity** (language-stable), not fuzz over one Polish string.
- **Polish summary becomes a structured, validated field** (what/where/aggressor/urgency-cue, length-capped, with few-shot examples and a TTS-clean format), validated/truncated in code. It **stops being the dedup key** (the embedding "event sentence" + locus carry identity now), so summary phrasing variance no longer fragments events. Quality and grouping are decoupled.

---

## 5. Grouping / deduplication — the centerpiece

**Chosen mechanism: a hybrid — deterministic signature/locus prefilter → multilingual-embedding candidate scoring → an LLM "same-event?" judge on the narrow ambiguous band, with HARD deterministic geo/locus overrides the LLM cannot overrule.**

No single audited approach suffices alone: pure embeddings collapse the burst beautifully cross-lingually but lean on a learned model for the cardinal anti-over-merge guarantee; pure LLM-judge gives genuine same-event judgment but calls the LLM on far more articles and depends on noisy free-text place fields; pure signature-hash is deterministic and dirt-cheap and puts geo in the key, but its exact-hash brittleness re-introduces fragmentation when onset crosses a bucket edge. The hybrid stacks **three independent over-merge barriers**, biasing hard against the cardinal sin (false merge = silently missed alert), and keeps cost at ~$3–5/mo because the deterministic path handles the 304-copy burst with index lookups + cheap embeddings while the LLM only adjudicates true edges.

**The judge never gates the first critical CALL.** The hybrid intentionally escalates the same-event judge to Sonnet on the urgency-≥9 band for maximum anti-over-merge precision — but that escalation is what put the most critical articles on the slowest path. The redesign resolves this with a strict ordering rule (Step 0a below): for any geo-floored-≥9 article in a HIGH-tier geocell the **CALL fires before the judge runs**, and the judge (Haiku or Sonnet) executes **asynchronously, only to suppress the next copy**. The judge therefore only ever delays a *duplicate-suppression* decision, never a first contact — see also the latency contract in §3.1 and Residual Risk #6.

### 5.1 Pipeline (replaces `corroborator._find_matching_event`)

New `sentinel/classification/event_dedup.py :: EventDeduplicator.decide(article, result) → EventDecision`. Runs after classify+geo-weight, before event create/update.

**STEP 0 — deterministic critical short-circuit (evaluated FIRST, before embeddings/LLM).** Any article at CRITICAL tier (weighted urgency ≥ 9) whose candidate event is **acknowledged or in cooldown**, **or carries a different `geo_id`**, returns `relation = NEW` immediately. The LLM judge can *never* output SAME for that case. This is the deterministic life-safety guard, extending today's `corroborator.py:105-112` (which only force-NEWs critical-into-acknowledged) to also cover *un-acknowledged* critical events with a new locus.

**STEP 0a — fire-first short-circuit for critical articles (latency guard, evaluated immediately after Step 0).** For any article geo-floored to ≥ 9 in a **HIGH-tier geocell**, the decision path **emits NEW + CALL synchronously and immediately** *unless* Step 0's same-`geo_id`/not-acknowledged/not-cooldown conditions already prove it is a continuation of an event that has *already been called* this cycle. Concretely: if no already-called event shares this exact `geo_id` within the novelty gap, return NEW + CALL **now**; the embedding score (Step 3) and the same-event judge (Step 4) — **including any Sonnet escalation** — then run **asynchronously**, and their *only* job is to decide whether the **next** copy should be suppressed (SAME), not whether *this* article fires. This is the structural fix for the slow-judge-latency hazard: the most critical articles take the **fastest** path to contact, and Sonnet/429/back-pressure can only ever delay a duplicate-suppression decision on a later copy. The synchronous-fire branch **fails OPEN to NEW + CALL** on any error (timeout, embedding failure, judge error, exception). See §6.2 for how the async judge result feeds suppression of subsequent copies.

**STEP 1 — signature + geo key (deterministic, $0).** `geo_id` = gazetteer-snapped canonical place token, falling back to ASCII-folded transliterated place string (so `Gałacz`/`Galati`/`Галац` → `galati,ro` for ALL copies even when country is unmonitored/unknown — fixes `corroborator.py:207-208`). `signature = (event_family, geo_id, onset_bucket)`. `geocell` = adaptive (finer near monitored borders) for adjacency.

**STEP 2 — candidate retrieval (cheap).** Reuse `get_active_events(within_hours)` (`database.py:190-206`, sliding 6h window on `last_updated_at` + 48h max-age cap — already correct, KEEP). Keep a candidate iff: same family AND (same `geo_id` OR adjacent geocell OR place `token_set_ratio ≥ 80`) AND within window. Rank by recency × place-similarity, cap `MAX_CANDIDATES = 4`. **Exact-signature hit → immediate MERGE, no embedding, no LLM** — this is the 304-copy Galați path (index lookups), *disabled for HIGH-tier acknowledged events* (Step 0 wins).

**STEP 3 — embedding score (only for near-but-not-exact candidates).** Embed a language-stable event sentence `f"{event_family} | {geo_id} | {summary_pl}"` (multilingual model, L2-normalized, stored as float32 BLOB in a new `article_embeddings` table + a running **medoid** on events). `cos = dot(article_vec, candidate.medoid)`. This is what fuzz-over-one-Polish-string (`corroborator.py:129-139`) cannot do across PL/EN/UA/RU. For a Step-0a fire-first article this step runs **asynchronously** (its CALL has already fired); for all other articles it runs inline.

**STEP 4 — decide.**
- `cos ≥ MERGE_THRESHOLD` and geo gate passes → MERGE (SAME, or ESCALATION if urgency rose / a new locus was added).
- `BAND_LOW ≤ cos < MERGE_THRESHOLD` → ONE LLM judge call (Haiku; **Sonnet if urgency ≥ 9 either side**): "Same real-world incident, or a NEW/second strike? `{same|escalation|new, confidence}`". **Cost-asymmetric: require ≥0.9 confidence to output SAME for HIGH-tier; default to NEW below.** `is_new_event` is used **only in the NEW direction** (a `true` is evidence to split), *never* as a merge-toward prior.
- `cos < BAND_LOW` → NEW.
- **Critical-band latency guards (mandatory for any decision where urgency ≥ 9 on either side):** (i) the judge runs under a **hard per-call timeout (default `judge_timeout_seconds: 8`)**; a timeout, a 429, a back-pressure error, or any exception **defaults to NEW + CALL** (fail-OPEN on the *slow-judge path*, not only on embedding failure); (ii) for a Step-0a fire-first article the judge has already been demoted to **asynchronous** and can only suppress the *next* copy, so it never delays the first contact; (iii) the Sonnet escalation applies **only** to the suppress-the-next-copy decision, never to the synchronous fire path. This guarantees that the most critical articles are never the slowest to reach the owner.

**STEP 5 — MERGE = UPDATE-NOT-SUPPRESS.** `urgency = max(existing, incoming)`; recompute medoid (robust to a single outlier copy); merge loci; advance `last_updated_at`. If the merge **raised urgency across the CALL tier or added a new HIGH-tier locus** → ESCALATION → `AlertPolicy` emits an UPDATE, and **places a fresh CALL** (see §6 — "one call per (event, distinct HIGH locus)").

**STEP 6 — sibling coalesce.** A periodic pass folds order-dependent siblings, but **re-runs the full `decide()` predicate** (it is not a cheaper key), respects the novelty gap, **never coalesces an override-split pair**, and runs only on UN-alerted events.

### 5.2 Hard overrides (deterministic; the LLM cannot overrule)

1. **Different concrete locus → ALWAYS NEW.** Fire on `geo_id` divergence, **not** just `country_iso` divergence (`geo_id` is always populated via transliteration fallback; `country_iso` is not). Never merge across a > ~100 km geocell gap regardless of cosine. A cell that straddles a border defaults to split.
2. **`geo_tier` upgrade LOW→HIGH → ALWAYS NEW.**
3. **Critical article into an already-ACKNOWLEDGED event → force NEW** (Step 0; keeps the existing life-safety guard `corroborator.py:105-112`).
4. **Kinetic vs non-kinetic is a hard separator** — a kinetic strike can never merge into a non-kinetic airspace-violation event regardless of similarity (reuse the classifier's kinetic boolean).
5. **Critical fire-first never blocks on the judge (latency override).** A geo-floored-≥9 article in a HIGH-tier geocell that is not a continuation of an already-called event **fires CALL synchronously**; no embedding, no judge, no Sonnet call, and no slow-lane delay may sit on the path to that first contact (Step 0a). The judge may only run afterward, asynchronously, to suppress the next copy.

> **Risk / Mitigation — the empty-`country_iso` hole (adversarial CRITICAL).** Conditioning the separation override on *concrete country* silently disables the strongest barrier exactly when a thin Polish first copy emits `country_iso=''`. **Mitigation:** the override fires on **`geo_id` asymmetry and geocell distance**, which do not depend on the LLM's country field. **Residual:** a Polish strike whose only article says "in the east" with no town has no geocell and can attach to whatever HIGH-tier event is open (Residual Risk #1).

> **Risk / Mitigation — medoid drift swallows a distinct event (adversarial HIGH).** A growing low-urgency debris cluster's medoid can pull a later *deliberate* high-urgency strike in the same region above threshold. **Mitigation:** keep per-urgency-tier sub-considerations so a critical article cannot merge into a centroid built only from sub-critical members; and any merge-time crossing sub-critical→critical **always** places a CALL, bypassing the SMS-suppression the way the phone branch does today (`state_machine.py:232`). **Residual:** per-band separation can re-fragment a single real event whose copies legitimately span urgency scores (the Galați strike itself ranged 2–9) — a knob between two failure directions.

> **Risk / Mitigation — embedding-provider silent drift (adversarial HIGH).** A hosted model version swap shifts the cosine distribution; "fail-open" only triggers on a hard exception, not a successful-but-garbage vector. **Mitigation:** pin the exact model version and alarm on a version-change header; run a **continuous canary** (embed a fixed KNOWN-distinct reference pair every cycle; assert cosine stays below `MERGE_THRESHOLD`; on drift, alarm + fail-open to NEW for all critical-band decisions); reject zero-norm vectors; monitor calls-per-hour and events-per-incident as live canaries; **prefer the local model (Tier 1)** to freeze the model under the owner's control. **Residual:** a canary catches gross drift, not subtle per-language shifts; the *collapse-to-one* direction is detected slowly (fewer alerts looks calm), so the catastrophic direction is the harder one to catch.

> **Risk / Mitigation — slow-judge latency on the critical band (adversarial HIGH).** Escalating the same-event judge to Sonnet on the urgency-≥9 band — combined with a 15-min slow-lane cycle and Sonnet latency/429 during a war-news burst — would put the **most critical articles on the slowest adjudication path** and could push acknowledged contact past T0+20 min, the opposite of what the ~15-minute escape window demands. **Mitigation (all four, mandatory):** (1) **fire-first** — any geo-floored-≥9 article in a HIGH-tier geocell emits NEW + CALL synchronously, and the Sonnet judge runs **asynchronously only to suppress the next copy** (Step 0a, §6.2); (2) critical-band dedup **fails OPEN to NEW + CALL on the slow-judge path** — timeout/429/error → NEW + CALL, not only on embedding failure (Step 4 guard i); (3) a **hard per-call judge timeout (default 8 s) defaulting to NEW + CALL** (Step 4 guard i, `judge_timeout_seconds` in §5.3); (4) a **breaking-keyword-in-HIGH-tier-geocell article is promoted to the fast lane immediately** (§4.3, §3.1) so a 9/10 never waits a full 15-min slow cycle. **Residual: MEDIUM** — the async judge still consumes Sonnet budget under burst and a mis-promotion could leave one borderline article on the slow lane, but no *first* CALL is ever gated on Sonnet (Residual Risk #6).

> **Risk / Mitigation — second strike inside the bucket (adversarial HIGH).** A real second strike on the same town 70 min later is inside the 90-min novelty gap and merges via exact-signature. **Mitigation:** **lower `novelty_reopen_gap` drastically for HIGH-tier loci** (15–20 min, not 90); **disable exact-signature auto-merge for HIGH-tier acknowledged events**; any fresh critical article on an acknowledged HIGH-tier event re-calls. **Residual:** a 15-min gap re-calls on genuine syndication delay (nuisance calls), and repeated re-calls during an active incident risk alarm-fatigue → the owner muting the phone, missing the *next* escalation. No threshold distinguishes "syndicated repost of strike 1" from "real strike 2" on the same town within 20 minutes from text+time alone.

### 5.3 Thresholds (all in `config.yaml` under `dedup.*` / `clustering.*`; calibrated conservatively HIGH — split/fire when unsure)

| Parameter | Default | Notes |
|---|---|---|
| `event_families` | ~9 closed set | `aerial_strike` (drone/missile/airstrike/airspace_violation/artillery), `ground_assault`, `airspace_violation`, `naval_attack`, `infrastructure_strike`, `mobilization_conscription`, `nuclear_cbrn`, `nato_strikes_russia`, `other`. **Retrieval only**, never the final merge gate. |
| `onset_bucket` | 6 h (2 h near HIGH-tier) | Coarse buckets re-fragment single events; fine buckets split syndication. Finer near monitored soil. |
| `geocell` | adaptive (finer at PL/RO/Baltic borders) | A cell must never absorb the country dimension across a border. |
| `place token_set_ratio` (retrieval) | ≥ 80 | ASCII-fold + transliteration tolerant. |
| `MERGE_THRESHOLD` (urgency < 9) | cos ≥ 0.82 | Cross-lingual paraphrases of one incident typically 0.80–0.92. |
| `CRITICAL_MERGE_THRESHOLD` (urgency ≥ 9) | cos ≥ 0.88 AND locus match | Higher bar so a critical article splits-and-fires rather than risk a false merge. |
| `BAND_LOW` | 0.72 | Below → NEW outright; in-band → one LLM judge call. |
| `TAU_MERGE` (judge SAME floor) | 0.75 (≥ 0.90 for HIGH-tier) | Cost-asymmetric: near-certainty required to merge a critical pairing. |
| `judge_timeout_seconds` | 8 | Hard per-call timeout on the same-event judge; timeout/429/error on the critical band → **NEW + CALL** (fail-OPEN on the slow-judge path). |
| `critical_fire_first` | true | For a geo-floored-≥9 article in a HIGH-tier geocell, fire CALL synchronously and run the judge (incl. Sonnet) ASYNC only to suppress the next copy (Step 0a). |
| `novelty_reopen_gap` | 90 min (**15–20 min HIGH-tier**) | Second-strike guard. |
| window / max-age | 360 m / 2880 m | Reuse existing (`corroborator.py` time logic, sound). |

**Tuning rule:** thresholds may only be **loosened** if the over-merge eval stays at 0; never loosen the locus/geo gate or `CRITICAL_MERGE_THRESHOLD` without an eval proving zero new over-merges. `judge_timeout_seconds` and `critical_fire_first` are **latency-safety** parameters, not tuning knobs: lengthening the timeout or disabling fire-first re-opens the slow-judge-latency hazard (§5.2, Residual Risk #6) and must be treated as a regression.

### 5.4 Cost

~$0.0006–0.0008/article all-in. The signature rides the existing Haiku call (~+100 output tokens, ~$0.0005). Embeddings fire only on near-but-not-exact candidates: hosted Cohere multilingual @ $0.10/1M ≈ $0.50/mo, or **local BGE-M3 at $0 marginal**. The LLM judge fires only on the ambiguous band (< 10% of articles) ≈ $2–5/mo; because the critical-band Sonnet judge now runs **asynchronously and only to suppress the next copy** (Step 0a), a war-news burst can spike async Sonnet calls — bounded by the per-call timeout and by the fact that fire-first already resolved the alert, but still a budget-pressure line item on heavy days. **Total incremental dedup spend ~$3–5/mo**, dwarfed by the ~$36/mo Haiku classification and far inside the ~$100 budget. The Galați 304-copy burst costs ~304 index lookups + a handful of embeddings, NOT 304 LLM calls.

### 5.5 Galați walk-through: 304 → 1

1. **Article 1** (PL aggregator, "rosyjski dron uderzył w Gałacz"): classifier emits `event_family=aerial_strike`, `geo_id=galati,ro`; `GeoWeighter` floors urgency ≥ 9 because RO is HIGH-tier. No candidate exists → **Step 0a fires NEW + CALL synchronously and immediately** (the one call), opening event **E** (centroid = its event-sentence embedding, `locus_key=galati,ro`); the same-event judge does not run on this first article because there is nothing to suppress yet. `AlertPolicy`: relation NEW, CRITICAL → **CALL fired (the one call), with no Sonnet/embedding on the critical path.**
2. **Articles 2–304** (PL/EN/UA/RU copies, "Russian drone strike on Galati", "удар по Галацу", drone/missile/airstrike labels intermixed, some `country_iso=[]`):
   - TIME gate passes (within the 6h sliding window, which slides on `last_updated_at` so the burst never ages out).
   - GEO gate passes — all share `geo_id=galati,ro` (place name, not the unmonitored country code that emptied the set at `corroborator.py:207-208`).
   - **Exact-signature hit** (same family + `geo_id` + onset bucket) → immediate MERGE, **no embedding, no LLM** — the 217/304 single-Google-News-query copies collapse as cheap index lookups, suppressed against the already-called event E.
   - Where the gazetteer snaps a copy slightly differently → embedding step; if it lands on the ambiguous band the same-event judge runs (asynchronously for any copy that itself geo-floors to ≥9, since E is already called) and resolves to SAME → suppressed. The multilingual model maps all four languages into one neighborhood, `cos ≥ MERGE_THRESHOLD` → MERGE.
3. **The fragmentation drivers are all neutralized:**
   - drone↔missile↔airstrike are ONE family → the non-transitive table (`corroborator.py:15-25`) is gone.
   - urgency 2-to-9 is NOT in the dedup key → it cannot fragment; `max()` pulls E to its tier.
   - empty/`unknown` country no longer matters → `geo_id` is the key.
   - Polish-summary phrasing variance no longer gates → embedding + locus carry identity.
   - the critical-band Sonnet judge never sits on the first call — it only adjudicates suppression of *later* copies, asynchronously.

**Result: exactly ONE event E (member_count 304), ONE call — fired on the fastest path, never waiting on Sonnet or the slow lane.** A later strike on **Przemyśl, PL** is `geo_id=przemysl,pl` — a different concrete `geo_id`, ~600 km away → **hard override → NEW event → Step 0a fires a fresh CALL synchronously** (not an SMS update, and not gated on the judge), because "one call" is scoped to *(event, distinct HIGH locus)*.

---

## 6. Channel + alert-decision design

### 6.1 Urgency tier → channel class (transport-agnostic)

`AlertPolicy` returns a **channel CLASS** (`CALL | NOTIFY | NONE`) and `is_update`; it never names SMS/push/voice. The class→transport mapping lives in a registry (`sentinel/alerts/channels.py`) as **ordered fallback chains**:

| Urgency tier | Channel CLASS | Transport chain (today) |
|---|---|---|
| **CRITICAL (9–10)** | `CALL` | `TwilioVoice → [Phase 4] SecondCarrierVoice → IndependentEscalation (Pushover/email + DEAD_LETTER)` |
| **HIGH (7–8)** | `NOTIFY` | `[Phase 4] Pushover(receipt) → Email → TwilioSMS → ExpoPush` |
| **MEDIUM (5–6)** | `NOTIFY` | same as HIGH |
| **< 5** | `NONE` | — |

`AlertStateMachine` resolves the class to its chain and walks it until a transport returns a **successful** `AlertAttempt`. Adding/removing a transport (e.g. WhatsApp) is a registry edit — zero changes to the decision layer. Push stops being a hardcoded side-channel fired for any non-`log_only` action (`state_machine.py:241-242`); it becomes a registered, *receipt-gated* NOTIFY-class fallback.

> **Risk / Mitigation — delivery acceptance ≠ delivery confirmation (adversarial CRITICAL).** Today a transport "succeeds" on send-acceptance; Expo returns a ticket immediately and the per-device outcome (`DeviceNotRegistered`) only arrives later via the receipts endpoint, and the unprovisioned EAS `projectId` (`TODO.md:196`, `push_client.py:62-64,80-82`) makes push a silent no-op. **Mitigation:** treat a transport as delivered **only after a positive delivery RECEIPT** (poll Expo receipts; Pushover returns receipts; Twilio call `status=completed` with duration > a few seconds); a non-ok receipt = FAILED → continue the chain; **never register push as a CALL-class fallback** (a push is not a 3am phone ring); preflight/canary every transport on a schedule. **Residual:** a receipt means "the provider relayed it," not "the human saw it"; iOS DND/Focus/force-quit can suppress a delivered push, and Twilio `completed` can mean voicemail — distinguishing human-answered from machine-answered without DTMF is unsolved (Residual Risk #3, #4).

### 6.2 Per-event suppression = the dedup result (Principle 2)

There is **no time-window and no severity suppressor**. The ONLY suppression is `EventDecision.relation == SAME` on an event already alerted (checked via `alert_records` rows for that event — the sound mechanism at `state_machine.py:209,232-237`).

- `relation == NEW` → **always alert** (fire on one source).
- `relation == ESCALATION` → **always emit an UPDATE** (never suppressed, even if mis-judged), and **place a fresh CALL** if it crosses into CRITICAL *or* introduces a new concrete HIGH-tier locus/country. The unit of "one call" is **(event, distinct HIGH-tier locus)**, not (event). A `>1` distinct HIGH-tier country counter on one event row is a hard split-and-recall trigger.
- The "one call then NOTIFY for updates" contract is enforced for **all** events including un-acknowledged ones (fixing `state_machine.py:211-215`, which only updated acknowledged events).

**The suppression decision, not the alert, is what waits on the judge.** For a critical (geo-floored-≥9, HIGH-tier-geocell) article, the first CALL is emitted synchronously by Step 0a *before* the same-event judge runs. The judge's verdict — Haiku, or its Sonnet escalation on the urgency-≥9 band — feeds back **only** into whether the **next** copy is suppressed (SAME) or itself fires (NEW): on judge SAME, subsequent copies sharing that `geo_id` are suppressed against the already-called event; on judge NEW (or any judge timeout/429/error, which fail OPEN), the next copy fires its own CALL. This is the entire mechanism by which "the most critical articles take the fastest path" coexists with "Sonnet still adjudicates over-merge precision": Sonnet sits on the *suppress-the-next-copy* path, never on the *first-contact* path.

> **Risk / Mitigation — escalation routed to a silent SMS (adversarial CRITICAL, two findings).** (a) A brand-new strike on Poland attaching as ESCALATION into an already-called HIGH-tier event would, under a naive "call only on first tier-crossing" rule, get only an SMS because the event is *already* critical. (b) A forced-NEW sibling off an acknowledged event guarantees a new row but not a new CALL. **Mitigation:** the CALL re-fire rule is **severity-delta + new-locus**, not tier-crossing — any ESCALATION that adds a new HIGH-tier locus or raises urgency places a fresh CALL even on an already-critical/acknowledged event; a forced-NEW sibling in the same geocell/time window as a prior CALL **inherits a CRITICAL floor** (escalation off a real attack is presumptively critical); the NOTIFY copy for a forced-new sibling is differentiated ("NEW STRIKE / SEPARATE EVENT", distinct ringtone/loud push) so it is not perceived as a routine update. **Residual:** inheriting CRITICAL raises repeat-call volume (the safe direction); the owner may already have fled and find repeat calls noisy.

> **Risk / Mitigation — confirmation code is in-memory and Twilio-dependent (audit).** **Mitigation:** persist the confirmation code per-event in the DB (fixes loss on restart, `state_machine.py:442`); accept ack via **any** inbound channel (SMS *or* Telegram), so an SMS-only Twilio outage cannot wedge a working call into the retry loop. **Decouple TERMINATION from ACK:** a transport returning a strong positive delivery signal stops retry on its own; `DEAD_LETTER` escalation fires only when *no* transport produced a positive delivery signal, never merely on missing ack. **Residual:** Twilio `completed` can be voicemail (Residual Risk #4) — the no-DTMF design accepts this to avoid voicemail false-positives.

---

## 7. Reliability & observability design

Closes every catastrophic gap §2.4 confirmed.

1. **Durable failure records with error codes.** New `alert_attempts(id, event_id, channel_class, transport, attempt_number, outcome[SUCCESS|FAILED|NO_ANSWER|TIMEOUT], error_code, http_status, provider_sid, started_at, ended_at, message_body)`. **Every** attempt — success and failure — writes a row before and after the provider call. `make_alert_call`/`send_sms` stop returning `None` on exception (`twilio_client.py:54-62,86-95`); they **raise a typed `ChannelError(error_code, http_status)`** the state machine persists. A Twilio 401 now leaves a queryable row, not a log line that rotates away. Add a **slow-rotating dedicated audit log** for attempts, separate from the byte-bounded app log (`logging_setup.py:32-41`), so high-volume incidents stay reconstructable.

> **Risk / Mitigation — the failure record lives in the DB that is part of the incident (adversarial HIGH).** A disk-full / SQLite-locked condition makes the *failure write itself* fail (single shared connection, `database.py:21-23,208-219`). **Mitigation:** on any outcome, emit a structured append-only, fsync'd line to a **separate mount** AND mirror it to the independent provider's own off-box sent-log; wrap every alert-path DB write in try/except that escalates "DB WRITE FAILED during alert" out-of-band rather than aborting dispatch; add a disk-space preflight (alarm at < 500 MB free). **Residual:** if the whole VPS is gone, only the off-box watchdog survives.

2. **Bounded retry + hard fallback.** CALL chain: up to N bounded attempts with backoff (config). On exhaustion OR a hard auth/billing `error_code` (401/402/suspended), **do not loop forever** — walk the registry fallback chain, then enter a terminal `DEAD_LETTER` state that fires the independent escalation "ALERT PATH DOWN — urgency-9 could not be delivered." This kills the infinite `retry_pending` loop (`state_machine.py:413-420`) and activates the dead `retry_attempts` config.

3. **Heartbeat + Twilio auth/balance health check via a NON-Twilio channel.** A `Watchdog` (`sentinel/health/watchdog.py`): (a) startup + periodic **Twilio auth/balance preflight** (an authenticated ping + balance read) — detects a 401/de-authorization/low balance *before* an incident; (b) an **external dead-man's-switch**.

> **Risk / Mitigation — the heartbeat watches process liveness, not alert-path health (adversarial CRITICAL).** A live process with a 401'd Twilio account keeps stamping fresh `health.json` (`scheduler.py:514-556`); a freshness-only monitor stays silent for 14 hours — the original incident, recreated. **Mitigation:** the heartbeat the external monitor consumes is emitted **only when** (Twilio preflight passed within X min) AND (classifier succeeded last cycle) AND (nothing parked in `DEAD_LETTER`); if any is false, **stop heartbeating** (so the external monitor alarms) AND fire the independent escalation directly. Add a periodic **synthetic end-to-end probe**: run a canary urgency-9 event through the real decision+dispatch path against test endpoints and require a receipt; a failed canary kills the heartbeat. **Residual:** a canary proves the path worked at probe time, not at the real-incident microsecond.

> **Risk / Mitigation — the watcher has no watcher (adversarial HIGH).** A free-tier uptime check deactivates; a deploy rewrites crontab; a cron on the *same VPS* dies with the process it watches. **Mitigation:** the dead-man's-switch must be a **hosted, off-VPS, heartbeat-expected service** (healthchecks.io / Cronitor / Better Uptime) — the VPS pings *in*; if pings stop, the hosted side alarms. Send the owner a daily "all green, watching" digest so the *absence* of the digest is itself a signal the watcher died. Pin the cron/monitor config in version control and assert its presence in the deploy skill's post-deploy checks. **Residual:** the hosted monitor is itself a third-party SPOF, and humans habituate to "all good" digests within weeks (Residual Risk #4/#5).

4. **The independent escalation channel must not share fate with the crisis.**

> **Risk / Mitigation — reusing the ingestion Telegram identity / crisis-correlated failure (adversarial HIGH + residual CRITICAL).** Telegram is exactly the service that degrades during the geopolitical crisis the system exists to detect (state throttling, account flagging under an outbound burst), and reusing the source-ingestion session shares fate with a component that makes API calls all day. **Mitigation:** do **not** reuse the ingestion identity; provision a dedicated **Pushover/ntfy** (the latter self-hosted on a *second* host, not the Hetzner VPS) as primary independent channel, with **email via a transactional provider** (not the owner's Gmail) as second, and require **delivery receipts**. Treat "classifier outage" as a CALL-worthy event in its own right (place a Twilio call "SYSTEM BLIND" if Twilio is up). Preflight/canary **every** channel on a schedule; centralize all alert-channel secrets with startup presence-and-validity assertions and deploy post-checks. **Residual:** no channel is immune to a regional internet shutdown (which takes out the VPS itself), and the owner's single phone may be off (Residual Risk #4/#5).

5. **Fail-loud classifier/scheduler.** An Anthropic outage (`scheduler.py:243-255`) and a wedged scheduler job (APScheduler `max_instances=1` + an un-timed Twilio SDK call) both trigger the Watchdog independent alarm. Add **per-call timeouts** on the Twilio SDK so a hang cannot silently skip the next fire. Move the systemd `StartLimitBurst`/`StartLimitIntervalSec` keys from `[Service]` to `[Unit]` (today silently inactive, `sentinel.service:14-15`) and add a crash-loop owner alarm.

> **Risk / Mitigation — `DEAD_LETTER` escalates through the channels it just exhausted (adversarial CRITICAL).** **Mitigation:** `DEAD_LETTER` escalation must run through a path **orthogonal** to everything already tried — the hosted off-VPS monitor, on detecting `DEAD_LETTER` or a stopped heartbeat, fires *its own* notifications to multiple owner contacts and to a **second human** who can physically reach the owner. **Residual:** a second human introduces consent/availability/false-alarm-tolerance problems and can also be unreachable; the regress terminates at a human who must care about silence (Residual Risk #4).

---

## 8. Phased migration plan + eval strategy

**Principle: never drop 9/10 coverage during the swap. The owner is the sole ground-truth labeler — no pre-fill, no bootstrap.**

| Phase | Goal | Key steps | Coverage guarantee |
|---|---|---|---|
| **0 — Reliability hardening FIRST** | Stop the catastrophic silent-miss paths before touching grouping | `alert_attempts` table + `error_code`; raise typed `ChannelError` instead of `None`; bound the retry loop with a `DEAD_LETTER` terminal state; stand up Pushover/email + Watchdog (auth/balance preflight + off-VPS heartbeat); per-call Twilio timeouts; persist the ack code; fix systemd `StartLimit` placement; make classifier outage fail-loud | Pure additions to dispatch/observability; the decision+dispatch path is untouched, so coverage is unchanged — and goes **up** immediately (a 401 now escalates instead of going silent for 14h) |
| **1 — Classifier schema + geography backstop** | Make HIGH-tier 9/10 (incl. Romania, NATO-attacks-Russia) reliably reach the call tier; fix the upstream keyword veto | Extend classifier JSON (`locus`, `target_country`, `geo_tier`, `attacker_is_nato`, structured `summary_pl`, resurrect `is_new_event`); add `geography:` config + RO/gazetteer; add `GeoWeighter` floor + deterministic body/title gazetteer scan; demote keyword filter to a hint for breaking lanes, move it after enrich, and add fast-lane promotion for breaking-keyword + HIGH-tier-place articles; run the eval after each change; owner labels new fixtures | The geo floor and keyword-hint changes can only **raise** urgency / admit more articles and pull critical articles onto the faster lane — monotonic toward firing; eval gates ensure no regression on existing 9/10 cases |
| **2 — SHADOW-RUN the new `EventDeduplicator`** | Prove the new dedup collapses bursts AND never over-merges, with ZERO production risk | The OLD `Corroborator` still drives real alerts; the NEW module writes its `EventDecision` to a shadow table only; compare on live + replayed Galați data (events-per-incident, 9/10 recall, over-merge count); **measure judge latency and the fire-first vs judge-completion timing** on the critical band; tune thresholds against shadow output only | The new dedup **cannot suppress** a real alert during shadow — the old path still fires everything. Cutover criterion: shadow 9/10 recall ≥ old AND over-merge == 0 on the labeled set AND no critical fire-first first-contact gated on the judge |
| **3 — Cutover dedup + collapse the decision authority** | Make `EventDeduplicator` authoritative; replace the dual decision with `AlertPolicy` | Flip dedup to drive alerts; introduce `AlertPolicy`; wire Step 0a fire-first + async critical-band judge + `judge_timeout_seconds` fail-OPEN; delete `_determine_alert_status`, `_determine_action`, the corroboration downgrade, the `corroboration_required` config keys; point the eval at `AlertPolicy`; keep a config **kill-switch** to revert to the old grouper for one release | Cutover only after Phase 2 proves equal-or-better recall; the kill-switch reverts in seconds. `AlertPolicy`'s NONE branch fires only on dedup SAME+already-alerted, so a misgrouping fails toward firing; fire-first guarantees no first CALL waits on the judge |
| **4 — Channel abstraction + fallback chains** | Make transport pluggable, push a real fallback, add a second voice carrier | `NotificationChannel` registry + ordered receipt-gated chains; wire `DEAD_LETTER` → independent escalation; provision Expo push (`TODO.md:196`); **add a second, different-vendor voice carrier** for the CALL class | Additive transports only widen delivery; the CALL-for-9/10 mapping is preserved by `AlertPolicy` |

### 8.1 Eval strategy

Use the existing owner-labeled `tests/fixtures/eval_set.yaml` (44 cases) as the foundation; the harness already honors owner-as-sole-labeler (expected values from owner YAML, `harness.py:122-167`; captured `haiku_output` is reference-only, never read as a label, `harness.py:184-228`). **First, pin the canonical fixture** (`eval_set.yaml` vs the newer-mtime `eval_set_human.yaml`) and retire the other (labels untouched).

Three new measurement axes the current harness cannot provide:

1. **9/10 recall as a first-class, asymmetrically-weighted, separately-gated metric.** Today a missed `phone_call` counts the same as any check toward an all-or-nothing 100% gate (`harness.py:398-399`) that 44 noisy LLM cases rarely reach. Add: *of all owner-labeled urgency-9/10 cases, the fraction routed to CALL*, gated **separately at 100%** (a single miss fails CI). The eval **imports `AlertPolicy`** (deleting `harness._action_for_urgency`) so it tests the real authority including the `GeoWeighter` floor. Add **boundary fixtures at urgency exactly 9 and exactly 10 per HIGH-tier country.**
2. **Over-merge rate — the cardinal-sin metric the eval structurally cannot measure today** (the corroborator is never invoked). Add a GROUPING eval feeding multi-article SCENARIOS through `EventDeduplicator`: (a) replay/synthetic Galați-style bursts that MUST collapse to one event (events-per-incident target 1); (b) **owner-labeled over-merge traps** that MUST stay separate — **Poland-after-Romania, same-city second strike, debris-then-deliberate, airspace-then-kinetic, override-split-survives-coalesce, two distinct Ukrainian strikes.** Over-merge rate gated at **0** (any over-merge fails CI). The owner labels the must-merge / must-separate intent; the harness never infers it.
3. **Shadow-diff metric (Phase 2):** new-vs-old event counts and 9/10 routing on live + replayed traffic; the new design may not ship until shadow 9/10 recall ≥ old AND over-merge == 0.

A fourth, **latency-on-the-critical-path** axis is required before Phase 3 cutover: for every owner-labeled urgency-9/10 scenario, assert that the **first CALL is emitted by the Step-0a synchronous path with no embedding/judge/Sonnet call on the first-contact path**, and measure simulated time-to-first-CALL under an injected judge timeout/429 (the judge stub must return slowly) — the fire-first path must still fire within the fast-lane budget. This axis gates the slow-judge-latency mitigation: if any urgency-9/10 first contact is shown to wait on the judge, cutover is blocked.

Cosine thresholds are corpus-sensitive, so the grouping eval doubles as the threshold-calibration harness; thresholds may only be **loosened** if the over-merge gate stays at 0. A green eval can no longer give false confidence about 9/10, because 9/10 recall, over-merge, and critical-path latency are now explicit, separately-gated metrics exercising the real dedup + decision code.

---

## 9. Open questions for the owner

1. **Independent channel choice (Residual Risk #3/#4).** Confirm **Pushover/ntfy + a transactional email provider** as the two non-Twilio escalation channels, *not* the existing source-ingestion Telegram bot (which shares fate with the crisis). Do you also accept a **second human** in the CRITICAL path — the only real defense against "your single phone is off at 3am"?
2. **Second voice carrier (Residual Risk #3).** The CALL tier has no independent voice fallback today. Do you want to provision a different-vendor voice carrier (Vonage/Plivo/Telnyx — *not* a second Twilio subaccount) in Phase 4? This is the difference between a Twilio outage downgrading a 3am 9/10 to a silent text vs. ringing your phone via a second carrier.
3. **Embedding tier.** Hosted Cohere (~$0.5/mo, one external dependency that must fail-open and is exposed to silent provider drift) **vs** local BGE-M3/e5 on the VPS ($0 marginal, ~2 GB RAM, no new network SPOF, version-frozen). Given the Twilio trauma, do you prefer zero new external dependencies in the dedup path (local)?
4. **Model tier (recommendation below).** Tier 2 (~$44/mo) vs Tier 3 (~$70–85/mo) — how much of the $100 do you want to spend on 9/10 recall? Note that the Tier-2 Sonnet-on-critical judge now runs **asynchronously** (it never gates the first call), so its latency/budget hit lands on duplicate-suppression of later copies, not on time-to-first-contact.
5. **Canonical eval fixture.** `eval_set.yaml` vs `eval_set_human.yaml` — which is the CI gate? (Labels untouched either way.)
6. **Over-merge trap labeling.** Will you author ~10–15 multi-article must-merge / must-separate scenarios? They are the *only* way to gate over-merge at 0.
7. **Second-strike window (Residual Risk #2).** Confirm you accept occasional duplicate calls for same-place rapid double-strikes rather than risk merging a second strike into the first.
8. **Geography edge.** For a strike in non-monitored territory near a monitored border (spillover), I default HIGH (fire). Confirm — and should any specific non-NATO country (e.g. **Moldova**, given Galați proximity) be explicitly HIGH-eligible?
9. **Romania scope.** Add the full Romanian border-județe gazetteer + RO sources/keywords now, or only Galați and the immediate Danube-delta region for the first cut?

### LLM tier options

| Tier | Description | Monthly cost | Recommended |
|---|---|---|---|
| **1 — Lean** | Classification on Haiku 4.5. Dedup retrieval via **local** BGE-M3 / multilingual-e5 on the VPS ($0 marginal, no new external SPOF). Haiku same-event judge only on the ambiguous band (< 10%). | ~$36 classify + ~$2 judge + $0 embeddings = **~$38/mo** (+ ~0.5–1 GB RAM quantized/ONNX, ~50–150 ms CPU/article) | No |
| **2 — Balanced** | Classification on Haiku 4.5. **Local** multilingual embeddings on the VPS (Q3 decision — $0 marginal, no external SPOF). Haiku judge on the band, **Sonnet only when urgency ≥ 9 on either side** or the similarity is gray — and on the critical band the Sonnet judge runs **asynchronously (fire-first), only to suppress the next copy**, so it never gates the first call. Embeddings fail-OPEN (a failed embed → NEW → fire), and the critical-band judge fails-OPEN on timeout/429 → NEW + CALL, so neither the embedding step nor Sonnet latency can suppress or delay an alert. | ~$36 classify + $0 embed (local) + ~$2 Haiku judge + ~$5 Sonnet-on-critical = **~$43/mo** | ✅ **CHOSEN (2026-05-31)** |
| **3 — Max quality** | Haiku first pass, **re-classify any borderline 7–9 with Sonnet** for higher 9/10-boundary recall; local embeddings + Sonnet judge on the full band. | ~$36 Haiku + ~$25–40 Sonnet re-class + $0 embed (local) + ~$8 Sonnet judge = **~$69–84/mo** | No |

---

*Citations throughout reference the codebase as read during the audit. Where the embedded incident evidence conflicted with the code — `temperature` is set to 0.0 (`classifier.py:278`, `config.yaml:474`); the country gate is already relaxed below the phone threshold (`corroborator.py:188-211`); the summary similarity gate compares Polish-to-Polish, not cross-language (`corroborator.py:129-139`) — the **code was trusted and the discrepancy flagged** in §2. The single deepest classification bug (Romania scored 1–3 by prompt rule, `classifier.py:142-144`) and the single most dangerous reliability bug (failures never persisted, `database.py:89-99` + `twilio_client.py:54-62`) are the two things this redesign exists to fix first. The slow-judge-latency hazard on the critical adjudication path — created by escalating the same-event judge to Sonnet on the urgency-≥9 band — is folded in as the Step-0a fire-first ordering (§5.1), the async suppress-the-next-copy mechanism (§6.2), the `judge_timeout_seconds`/`critical_fire_first` fail-OPEN parameters (§5.3), fast-lane promotion (§4.3/§3.1), the critical-path latency eval axis (§8.1), and Residual Risk #6 (§0).*
