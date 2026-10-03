# Project Sentinel — TODO

Last verified: 2026-10-03 (deployed commit 6429124)

This is the project backlog. Each open item has a stable title (a `###` heading or a bold lead-in), so other docs point to an item by its title, not by a number. Add a new item under the matching section and give it a stable title.

## Contents

- [0. Life-safety items and owner decisions](#0-life-safety-items-and-owner-decisions-open-2026-10-03)
- [1. Classification false positives](#1-smarter-multi-tier-classification-to-reduce-false-positives)
- [2. Source health analysis & expansion](#2-source-health-analysis--expansion)
- [3. Mobile app (done) and inbox bugs](#3-mobile-app--replace-sms-notifications-done-2026-06)
- [4. Productize Sentinel](#4-productize-sentinel--strategy--roadmap)
- [5. Pipeline analysis & classifier refinement](#5-pipeline-analysis--classifier-refinement)
- [6. Codebase refactoring, config/code defects, dashboard, production host](#6-codebase-refactoring-plan)
- [7. Findings from the 2026-09-23 model-eval work](#7-findings-from-the-2026-09-23-model-eval-work-not-yet-fixed)
- [Commentary: priority & sequencing (2026-05-24, partly superseded)](#commentary-priority--sequencing-claudes-assessment-2026-05-24)
- [Completed debt](#completed-debt-reference) · [Documentation reorganization](#documentation-reorganization-2026-05-30)

---

## 0. Life-safety items and owner decisions (open, 2026-10-03)

Found by the 2026-10-03 doc-sync audit against the deployed commit 6429124. Each item needs either a code fix or an owner decision. None of them is fixed yet.

Known state, not an item: SMS is off on purpose for urgency 5–8 (push-only since 2026-06-04). The owner has left the Twilio account unfunded, so every Twilio call and SMS fails with HTTP 401 since 2026-09-21. Phone calls stay configured and return when the owner recharges the account. Read "Stale retry_pending calls after a Twilio recharge" below before recharging.

### Owner decision: corroboration for phone calls (1 vs 2 sources)

- **What:** One source triggers a phone call today. The gate is `alerts.urgency_levels.critical.corroboration_required` in `config/config.yaml`. `classification.corroboration_required` only sets the event's provisional `alert_status` label and does not gate the call.
- **Evidence:** `sentinel/alerts/state_machine.py:503-504` (`source_count >= level.corroboration_required` → `phone_call`); `sentinel/classification/corroborator.py:425-443`.
- **Decide:** keep one source, or require two independent sources for the critical tier. Note that UA/RU sources cannot count as independent today (see "Cyrillic titles normalize to empty") and Telegram channels all look like one source (see "Telegram fetcher mislabels every channel"). Fix those first if you choose two.

### Owner sign-off: acknowledged-event guard is gone in incident-memory mode

- **What:** The old life-safety invariant ("a critical article is never absorbed into an acknowledged event; it forces a new event and a new call") holds only on the legacy grouping path. Incident memory is live, and there a duplicate/update decision with confidence ≥ `critical_min_confidence` attaches a critical article to an acknowledged critical event with no new call. A model "new" decision still gets its own event and call; an escalation sends an update push (and SMS), not a call.
- **Evidence:** `sentinel/classification/corroborator.py:97-144` (memory path, no `acknowledged_at` check) vs `:177-183` (legacy guard); `tests/test_incident_memory.py` `test_acknowledged_critical_duplicate_stays_on_same_event`.
- **Decide:** confirm this change to the invariant, or restore the guard in `_find_memory_match`.

### Telegram fetcher mislabels every channel as Ukrainian Air Force

- **What:** The fetcher compares the numeric `message.chat_id` with `@username` channel ids, so the match never succeeds and it falls back to the first configured channel. Every Telegram article gets the wrong `source_name` and language, and a fake URL such as `t.me/kpszsu/<NEXTA message id>`.
- **Evidence:** `sentinel/fetchers/telegram.py:96-109` (match, then "Fallback: use first channel") and `:118-119` (URL from the wrong channel). Audit query on the production DB (2026-09-03 to 2026-10-03): all 4422 Telegram rows are "Ukrainian Air Force", 736 of them in Russian.
- **Why it matters:** URL-hash dedup can drop a real message when ids from different channels collide, and all Telegram channels count as one source for corroboration.

### Ukraine-only shelter orders scored urgency 9 attempt a phone call

- **What:** Shelter and air-raid orders for Ukraine only get urgency 9 with an empty `affected_countries` list, and each one tries a phone call. Policy v2 rule 1 limits 9–10 official warnings to monitored countries, but no code enforces it. Each empty-country article also starts its own event, so each one gets its own call attempt.
- **Evidence:** events `03ec67e2` (2026-10-02) and `f63c6f6d` (2026-10-03); `sentinel/classification/policy.py:84-87`; `sentinel/alerts/state_machine.py:472-510` (`_determine_action` ignores countries); `Corroborator._countries_compatible` in `sentinel/classification/corroborator.py` (around lines 259-282).
- **Decide:** an eval-gated prompt fix and/or a code guard (no call when urgency ≥ 9 but no monitored country is in `affected_countries`). The owner labels the cases.

### Urgency-9 event fragmentation (one incident, several calls)

- **What:** The critical concrete-country gate in `Corroborator._countries_compatible` splits one incident into several events when the country labels differ or are empty. Each event gets its own call. Incident memory applies the same gate, so it does not prevent this.
- **Evidence:** `sentinel/classification/corroborator.py:131-137` and `Corroborator._countries_compatible` (around lines 259-282); comments at the critical tier and `max_call_retries` in `config/config.yaml`; commits 4353653 and 2cad033 (2026-07-30/31 call storm).
- **Why it matters:** `max_call_retries` was capped at 1 as a stopgap. Do not raise it until this is fixed.

### Stale retry_pending calls after a Twilio recharge

- **What:** Events left in `retry_pending` or `call_placed` are not expired. When a later article matches such an event through incident memory (within `incident_memory.lookback_hours` of its last update, and each match extends that), `_execute_phone_call` runs again with no age check. Calls that failed with HTTP 401 left no `phone_call` record, so the retry-interval guard does not hold them back.
- **Evidence:** `sentinel/classification/corroborator.py:114-145`, `:398`; `AlertStateMachine._execute_phone_call` in `sentinel/alerts/state_machine.py` (retry-interval guard around lines 561-572, failed-call branch `if record is None` around 603-605, `retry_pending` write around 645); no code writes `alert_status = 'expired'`.
- **Before recharging Twilio:** review or expire events in `retry_pending`/`call_placed`, or add a max-age rule for call retries. Otherwise a days-old incident can ring the phone.

### Unacknowledged calls are retried only when a new article joins the event

- **What:** No scheduled re-call exists. `run_cycle` dispatches only events returned by this cycle's corroborator, so a `retry_pending` critical event is called again only if a new article attaches to it. The `_execute_phone_call` docstring ("Never stops until acknowledged") is wrong.
- **Evidence:** `sentinel/scheduler.py:287-306`; `sentinel/alerts/state_machine.py:550-557`, `:637-645`.
- **Related:** the unmerged Phase-1 redesign branch has a retry sweep (see "Owner decision: unmerged redesign branches").

### Owner decision: unmerged redesign branches

- **What:** Branches `redesign-phase0-geography`, `redesign-phase1-alerting` and `redesign-phase2-policy` (2026-07-12) are unmerged. Master has since diverged (Luna classifier, incident memory, push-only 5–8). Their owner follow-ups ("6.0 Alerting reliability & resilience" and "Phase 1 redesign owner follow-ups") exist only in the branch copies of TODO.md.
- **Evidence:** `git show redesign-phase2-policy:TODO.md`; DECISIONS.md (Phase 1 notes: "Owner follow-ups … logged to TODO.md").
- **Decided (owner, 2026-10-03):** the three branches are closed. They are not rebased or merged, and they stay on GitHub as a record. Two parts remain backlog candidates: the Phase-1 bounded retry sweep with durable failure records (see "Unacknowledged calls are retried only when a new article joins the event") and the Phase-0 Romania coverage.
- **Rubric gap from Phase 0:** decided on 2026-10-03, see "Owner rules confirmed 2026-10-03 (call vs text boundary)".

### Owner rules confirmed 2026-10-03 (call vs text boundary)

- **What:** The owner's earlier grades disagreed on where a phone call starts. His May 2026 labels put a Baltic shelter order at 9 (call), his July 2026 labels put a Baltic strike with shelter orders at 8 (text), and the live policy v2 (2026-09-20) puts both at 9–10 (call).
- **Decided (owner, 2026-10-03):**
  - A confirmed Russian strike on a Baltic state (LT, LV, EE), or an official shelter order there, is a phone call (9–10). This is the live rule, so production needs no change. The July grades of 8 for these cases are superseded.
  - A Russian strike on a NATO state outside Poland and the Baltics (for example Romania or Germany) is a text (7–8).
- **To do:** the live policy has no band for the second rule. Add it to `classification.policy` and the prompt in `sentinel/classification/policy.py`. This changes the frozen prompt, so tune it on the development pool of the eval suite and gate it on the owner's labels (`docs/how-to/model-eval.md`). Do not deploy it without that test.

### OpenAI project hard spend cap vs the 30 USD app allowance

- **What:** The app allowance (`classification.budget.monthly_usd` in `config/config.yaml`) was raised to 30 USD on 2026-09-24. The OpenAI project's own hard spend limit was verified at 10 USD on 2026-09-20, and nothing on master shows it was raised. Measured use is about 11–17 USD a month.
- **Evidence:** commit 31acd3a; `docs/reference/luna-deployment-20260920.md` (the sentence "separately verified $10 enforced monthly cap"); `sentinel/classification/openai_provider.py:187-188` (`project_spend_limit_exceeded` → classification paused).
- **Do:** check in the OpenAI dashboard that the Project Sentinel hard limit is at least the app allowance. If it is still 10 USD, classification pauses mid-to-late month and articles wait unclassified, which can delay an urgency 9–10 alert.

### No working out-of-band watchdog (check-health.sh)

- **What:** `check-health.sh` runs from cron every 30 minutes and notices a stale or missing `health.json`, but it cannot alert anyone. It points at the removed legacy venv (`/home/deploy/sentinel/venv/bin/python`), so it never sends its SMS and only logs to syslog (`journalctl -t sentinel-health`). Even with the path fixed, its only channel is Twilio SMS, which is off and unfunded.
- **Evidence:** `deploy/scripts/check-health.sh:9` (same in the deployed copy); audit 2026-10-03: `/home/deploy/sentinel/venv` does not exist on the server.
- **Decide:** a working out-of-band channel (for example push) and the venv path fix. Today a stalled service goes unnoticed.

### Cyrillic titles normalize to empty (UA/RU never count as independent)

- **What:** `_normalize_title` keeps only ASCII letters and digits, so a Cyrillic title becomes an empty string. Two Cyrillic titles from different domains then score 100 on similarity, so they look syndicated (corroborator) or duplicate (legacy dedup).
- **Evidence:** `sentinel/models.py:11-15`; `sentinel/classification/corroborator.py:322-332`; `sentinel/processing/deduplicator.py:42-45`.
- **Why it matters:** it only affects the call today through `source_count`, but it would block UA/RU corroboration if two sources become required.

### Stray server .env and world-readable Telegram session files

- **What:** The audit on 2026-10-03 found `/home/deploy/sentinel/.env` (mode 0644, Twilio, Anthropic and Telegram key names) and world-readable Telegram session files in `/home/deploy/sentinel` and `/home/deploy/sentinel.bak-20260324`. The backup directory is a full stale March checkout with its own old `CLAUDE.md`, `setup.md` and prompts; nothing reads it, and it is a cleanup candidate. The live secrets are in `/etc/sentinel/sentinel.env` and `/etc/sentinel/openai.env`.
- **Decide:** remove the files or tighten their permissions, and whether to rotate the exposed credentials. This is a server change, so the owner does it.

---

## 1. Smarter multi-tier classification to reduce false positives

> Status 2026-10-03: the live classifier is OpenAI `gpt-5.6-luna` with the policy v2 prompt (see `classification.provider` and `classification.model` in `config/config.yaml`). Claude Haiku is the legacy rollback path only. §1.0 Task 1 is still open. The tiered Haiku → Sonnet → Opus plan in §1.1 is superseded.

### 1.0 — URGENT: Audit historical false-positive PL phone calls (escape-trigger misfires)

> Surfaced by the 7-agent event-grouping deep dive on 2026-05-30. Conversation: `20fb6962-608c-433b-978a-92e1a5740b26` (session "event-grouping-bugfix"). This is the safety-critical half of the false-positive problem below — quantify how often the escape trigger has *already* fired wrongly, and close the root cause, before/while building the tiered pipeline.

**What we found (production DB evidence, 2026-05-30; the Haiku classifier was live then):** the Haiku classifier resolves thin headlines like *"Russian drone hit a residential block in a NATO country"* to **Poland, urgency 9** with fabricated summaries (e.g. *"bezpośrednie zagrożenie dla terytorium Polski"*) for incidents physically in **Romania or Ukraine**. Concrete cases found in `alert_records`:
- **2026-05-01 — Tarnopil (Ukraine) drone strike** classified `["PL"]` urgency 9 → **7 completed Twilio phone calls** (events `61c468f6`, `b8c6feda`). Almost certainly FALSE (Ukrainian city, not Poland).
- **2026-04-03** (event `b2dcd82b`, "masowy atak na Polskę") and **2026-04-17** (event `aa6fd456`, "Polska ostrzelana przez Rosję"): PL/9, **completed phone calls — UNVERIFIED**: real PL events, or the same UA/RO→PL bug?
- **2026-05-30 — Galați (Romania)**: PL/9 row (`a8ae1407`) did NOT call ONLY because `corroboration_required=1` + single source held it at `retry_pending`. The corroboration gate is the sole circuit-breaker that happened to trip.
- Instability scale: across 579 classifications of the single Galați incident, urgency ranged **1–9**, 5 event_types, country `["RO"]`×310 / `[]`×265 / monitored-country×4. PL-contamination is rare (~0.7%) — frequent enough to fire eventually, rare enough that each call looks like an anomaly.

**Task:**
1. **Verify every historical PL/Baltic urgency-9/10 phone call** in `alert_records` (JOIN to `events`/`articles`, read the source). Label each REAL vs FALSE; quantify real escape-trigger calls vs misfires to date.
2. **Assess current exposure — answered 2026-10-03.** The single-source path is open: one source triggers a call today. What remains is an owner decision, tracked as "Owner decision: corroboration for phone calls (1 vs 2 sources)" in §0.
3. **Root-cause prompt fix — retargeted 2026-10-03.** Policy v2 (prompt version `clarified-v2`, live since the Luna rollout on 2026-09-20) replaced the R1–R10 prompt. It no longer has `R4 POLAND PRIORITY` or "NATO state = 9", limits the 9–10 bands to monitored countries and says an unknown border side must not be assigned to Poland (`sentinel/classification/policy.py:27-127`). R4 survives only in the legacy rollback `SYSTEM_PROMPT` (`sentinel/classification/classifier.py:63-65`). The remaining live misfire class is "Ukraine-only shelter orders scored urgency 9" in §0. Any fix stays eval-gated; the owner is the sole ground-truth labeler.

**Why urgent:** a false phone call can trigger a needless flight from Poland — the worst non-miss failure mode of the escape trigger. The grouping fix deployed 2026-05-30 (tag `deploy-20260530-163637`) reduced the duplicate-SMS *symptom*; this item addresses the dangerous *root cause*.

### 1.1 Superseded plan: tiered Haiku → Sonnet → Opus pipeline (2026-03, kept for history)

> Superseded by the 2026-09 Luna migration. Do not build this as written: it assumes Haiku as the live first pass and Anthropic API keys. If model escalation is still wanted, restate it against the live provider (`gpt-5.6-luna` first pass, escalation model to be decided) and take costs from the model-usage ledger. The audit part is mostly met: `classifications` rows already store `provider_used`, `prompt_version`, request hash, response id, tokens and cost. Only a tier/pass column is missing.

**Problem:** Haiku misclassifies headlines like "Poland scrambles jets in response to Russian strike on Ukraine" as a direct attack on Poland (urgency 9). Using Opus for all classifications would fix accuracy but is prohibitively expensive at 688+ articles per cycle.

**Approach: Tiered classification pipeline (Haiku → Sonnet → Opus)**

1. **Haiku (first pass, all articles):** Keep Haiku as the fast/cheap initial classifier. Improve the classification prompt to explicitly distinguish "country X is under direct attack" from "country X is responding defensively to an attack on a neighbor." This alone should eliminate most false positives — it's a prompt problem, not a model capability problem.

2. **Sonnet (second pass, ambiguous cases):** When Haiku returns urgency ≥ 5, re-classify with Sonnet 4.6 for a second opinion. Sonnet is ~5x cheaper than Opus and significantly more capable than Haiku. Use the Sonnet score as the authoritative one.

3. **Opus (final verification, before phone calls only):** Before triggering a phone call (urgency 9+; one source triggers a call today, see the corroboration decision in §0), run a single Opus 4.6 verification call. This is the highest-stakes action (waking someone up), so it warrants the best model. Expected volume: 0-2 Opus calls per day — negligible cost.

**Why not use Claude CLI / Max plan instead of API:**
- Max plan is for interactive personal use — automating it in a production pipeline violates TOS and risks account suspension
- No SLA, fragile auth (OAuth tokens expire), rate limits tuned for human-speed interaction
- A critical alert system cannot depend on a consumer subscription

**Cost analysis (based on real production data, 2026-03-24; Haiku-era figures):**

First ~14 hours of operation: 51 classifications, avg 699 input / 146 output tokens each.
Projected ~1,800 classifications/month at steady state (~60/day).
Urgency distribution: 88% score 1-4, 4% score 5-6, 4% score 7-8, 4% score 9+.

| Setup | Monthly cost |
|---|---|
| Then-current (Haiku only) | ~$2.57 |
| Tiered (Haiku + Sonnet + Opus) | ~$3.70 |
| Delta | +$1.13 (+44%) |

Sonnet tier adds ~$0.92/mo (~216 re-classifications). Opus tier adds ~$0.21/mo (~10 verifications). Cost is negligible — the tiered approach is about accuracy, not savings.

**Auditability requirement:**
Every classification step must be saved to the database — not just the final result. When Sonnet re-classifies an article, store the Sonnet prompt, response, model used, tokens, and result alongside the original Haiku classification. Same for Opus verification. The `classifications` table needs a `tier` or `pass_number` column (or a separate `classification_passes` table) so we can trace the full decision chain for any article: what Haiku said → what Sonnet said → what Opus said → final decision.

**Implementation notes (Haiku era):**
- All three tiers use the API (`ANTHROPIC_API_KEY`), just different model IDs
- The classification prompt improvement (tier 1) should be done first — it's free and addresses the root cause
- Tiers 2-3 add cost but only for the small fraction of articles that score high

---

## 2. Source health analysis & expansion

**Problem:** Some article sources are nearly dead (consistently 403, low yield), while others are very active and fruitful. We haven't re-evaluated sources since initial setup.

**What to do:**
- Audit every current source: volume, error rate, unique article yield, geographic coverage. Identify dead/dying sources and decide: replace, disable, or accept.
- **Dead enabled feed: Rzeczpospolita RSS.** It is enabled in `config/config.yaml` but returned HTTP 403 from the server on every slow-lane cycle in the 7 days before 2026-10-03 (710 of 710, no successful fetch; also recorded on 2026-09-20). Decide: disable, replace, or accept. LSM Latvia was healthy in the same census. PAP and TVN24 are already disabled in config.
- **Nuclear keyword gaps from the 2026-05-23 audit.** Issue #1 of `docs/archive/HANDOFF_audit-findings-2026-05-23.md` found ~30 English and Polish articles about the Russia–Belarus nuclear drills that no keyword matched. Checked against `config/config.yaml` on 2026-10-03, these proposed terms are still missing: EN critical `nuclear munitions`, `nuclear warheads`, `nuclear weapons to Belarus`, `nuclear arsenal`, `nuclear war games`; EN high `nuclear missiles`, `nuclear weapon`; PL critical `głowice jądrowe`, `amunicja jądrowa`, `broń jądrowa do Białorusi`, `ćwiczenia jądrowe`, `manewry jądrowe`, `nuklearny scenariusz`; RU critical `ядерные боеголовки`, `ядерные учения`; RU high `Калининград`; UA high `Калінінград`. Already present: EN `nuclear strike`, `nuclear drill(s)`, `nuclear forces` and `Kaliningrad` (EN and PL; PL substring matching also covers `Obwód Kaliningradzki`). Note that the PL exclude list contains `ćwiczenia` and `manewry`, so `ćwiczenia jądrowe` only passes if it is a critical keyword. Decide: add the terms (in the tracked `config/config.yaml`, ideally with eval cases) or accept the gap.
- Research new sources to add, especially for real-time military intelligence:
  - **Twitter/X:** Likely the fastest source for breaking military news. However, the API is reportedly very expensive. Investigate: current API pricing tiers, rate limits, what we'd actually need (filtered stream vs search). Explore cheaper alternatives — community-maintained scrapers, Nitter-like proxies, RSS bridges, OSINT aggregators that republish Twitter content.
  - **Truth Social:** Evaluate whether it carries any signal for our use case (military threats to Poland/Baltics). Likely low priority but worth a quick assessment.
  - **Other OSINT sources:** Liveuamap, FIRMS (NASA fire data for strike detection), flight trackers (ADS-B), Telegram channels beyond what we already monitor.

---

## 3. Mobile app — replace SMS notifications (DONE 2026-06)

> Status: done. A native React Native/Expo app with Expo push and an in-app inbox is live (inbox live 2026-06-03; see `mobile/INBOX_APP_SPEC.md`). Urgency 5–8 has been push-only by owner decision since 2026-06-04 (commit 7c024a5), so the "SMS stays as a fallback" idea and the PWA/FCM questions below no longer apply. SMS remains only on the 9–10 phone-call path. Still open: the second-iteration dashboard view, if still wanted, and the inbox bugs in §3.1.

#### Original plan (2026-05, kept for history)

**Problem:** SMS notifications are inadequate for several reasons:
1. **No differentiation** — an alert SMS looks identical to a work text from France; no custom sound/chime to signal urgency.
2. **No link formatting** — Google News URLs are extremely long and ugly; can't substitute with a short "Click here" link or deep-link into the app.
3. **Cost** — SMS costs ~$50/month via Twilio, which is a lot for a personal project.

**Phone calls should stay.** The call-based alert for urgency 9-10 events is the core value proposition and does not require an app. It must remain regardless.

**Approach: Build a mobile app with push notifications.**
- Push notifications replace SMS: free to deliver, support custom sounds/chimes, support rich content (formatted text, tappable links, images).
- **MVP scope (first release):** Tap the Sentinel logo → app opens, shows only a notification feed. No dashboard, no settings — just push notifications with event details and links.
- **Second iteration:** Add a lightweight dashboard view. We already have a full web dashboard (React/Vite), so this could be a WebView wrapper or a progressive web app (PWA) rather than a native build.
- **SMS stays as a fallback** — keep it plumbed for users without the app, and potentially as a paid tier for future users. *(Superseded 2026-06-04: 5–8 is push-only.)*

**Open questions (resolved: native Expo app with Expo Push):**
- Native app (React Native / Flutter) vs PWA? PWA is cheaper to build and maintain but push notification support varies by platform.
- Notification infrastructure: Firebase Cloud Messaging (FCM) for Android, APNs for iOS? Or a unified service like OneSignal / Expo Push?

### 3.1 — Shipped inbox app: bugs queued for the next dev-build rebuild

> The in-app SMS-equivalent message inbox shipped and went **live in production 2026-06-03** (server push enabled; standalone `preview` build on the iPhone). See `mobile/INBOX_APP_SPEC.md`. The items below are post-launch bugs found on-device. **Batch them:** each fix is JS-only, but *seeing* it on the phone needs a fresh `eas build --profile preview --platform ios` (~15 min) + reinstall — so collect a batch before rebuilding, rather than rebuilding per fix.

1. **Deleting an unread message leaves a stale app-icon badge.** _(minor — cosmetic; fix committed, on-device check pending)_
   - **Symptom (as reported 2026-06-03):** after deleting a message, the red unread count on the iOS home-screen icon did not go down.
   - **Status 2026-10-03:** the list screen has no per-message delete; single-message delete lives in `MessageDetailScreen`, which marks the message read on open and resyncs the badge after `remove` (commit 5d2d979). The probable root cause was that undismissed OS tray copies were re-ingested on cold launch, so deleted messages came back as unread. Commit 1c7697b (2026-06-04, JS-only) fixed that.
   - **Remaining work:** confirm on the iPhone after the next preview build, then close this item.
   - **Never affects SMS or the 9–10 call** — visibility-only.
2. **PushPanel "OSTATNI PUSH" is never fed.** _(minor — misleading UI)_ No caller passes `lastPush` to `PushPanel`, and `usePushReceiver` is unused since the inbox rewrite, so the section always shows "brak (jeszcze nic nie odebrano)" even after pushes arrive. Evidence: `mobile/push/PushPanel.tsx:25-28,64`; `mobile/push/usePushReceiver.ts:39` (no call sites). Feed it from the store's newest message or remove the section.

---

## 4. Productize Sentinel — strategy & roadmap

The long-term goal is to turn Sentinel from a personal tool into a multi-user product. This requires both technical and business work, and the two influence each other — feature decisions depend on pricing strategy, and pricing depends on what's technically feasible.

### 4.1 Technical requirements for multi-user

1. **Account system.** Currently the entire app is single-user, hardcoded for one person's preferences. Need: user registration/auth, per-user notification preferences, per-user alert history.

2. **Per-user configuration.** Users should be able to control:
   - Notification channels (push, SMS, call) and which urgency levels trigger each
   - Whether they get calls only on 9-10, or also on 5+ (configurable threshold)
   - Event grouping window (live grouping uses incident memory with a model decision over `classification.incident_memory.lookback_hours`; the fuzzy `corroboration_window_minutes` window applies only when incident memory is off) vs custom
   - Whether to be notified of every event or only above a threshold
   - Time zone and language preferences

3. **Cost-aware feature design.** Calls and SMS cost real money per user. Push notifications are free. Configurable call thresholds must be paired with cost analysis — if a user sets calls on urgency 5+, that could mean dozens of calls/month. This needs to be reflected in pricing tiers or hard limits.

### 4.2 Business decisions (open)

1. **Go-to-market timing.** Two strategies, undecided:
   - **Polish first:** Make the product excellent for personal use → add accounts → add billing → launch. Risk: takes a long time before any market feedback.
   - **Launch early:** Get to a viable multi-user MVP → launch → iterate based on real user feedback. Risk: rough edges, reputation damage.
   - **Hybrid:** Something in between — e.g., invite-only beta with a small group while continuing to build.

2. **Pricing & tiers.** What do we charge for? Possible axes:
   - Notification channel (push = free, SMS = paid, calls = premium)
   - Number of monitored regions/countries
   - Alert frequency / real-time vs daily digest
   - Access to dashboard / analytics
   - Need to design tiers, pricing, and figure out billing infrastructure (Stripe, etc.)

3. **Marketing & positioning.** This is an unusual product — a military threat early-warning system for civilians. Positioning matters: is it a security tool? An OSINT platform? A peace-of-mind service for expats in Eastern Europe? Need to figure out messaging, website, promotion channels. This is a whole workstream on its own.

4. **Overall roadmap.** We need a real plan with goals and timelines instead of working on whatever feels interesting. What order do we build things in? What are the milestones? What's the MVP for launch? All of this needs to be decided and written down.

### 4.3 What's configurable vs fixed

Before building multi-user, decide what users can change and what we control:
- Call threshold (urgency level that triggers a call)
- Event grouping window (live: incident-memory lookback; the 6h fuzzy window applies only with incident memory off — user-adjustable or fixed?)
- Event deduplication (per-user or global?)
- Source selection (can users pick which sources to monitor?)
- Notification schedule (quiet hours? — currently deliberately none)

Each configurable parameter adds complexity. Default to fixed unless there's a strong user need.

---

## 5. Pipeline analysis & classifier refinement

**Goal:** Develop a continuous, systematic process for evaluating and improving the entire pipeline — from source ingestion to classification to alerting.

> Status 2026-10-03: measurement already exists. A scored eval harness runs with `./run.sh --eval` (`sentinel/eval/harness.py`; see `docs/how-to/testing.md`). Human-labeled ground truth exists in `tests/fixtures/eval_set_human.yaml` (50 articles labeled by the owner on 2026-05-22), the frozen policy v2 benchmark `tests/fixtures/benchmark_policy_v2.yaml` (2026-09-20), and the holdout set `tests/fixtures/model_comparison_v2_holdout.yaml`. The open work below is to extend these sets (for example shelter-order and fragmentation cases), not to build measurement from scratch.

### 5.1 End-to-end pipeline review

Do a full audit of the data flow:
- **Source → keyword filter:** What articles does keyword filtering catch? What does it miss? Is simple keyword matching sufficient, or should we add semantic analysis or AI-based pre-filtering? What would AI-based filtering cost at our article volume?
- **Keyword filter → classifier:** Are there articles that pass keyword filtering but never reach classification? Are there articles filtered out too early that should have been classified? We need visibility into the pre-classification funnel.
- **Classifier → dashboard:** Everything classified is visible on the dashboard. But the annotation system exists precisely to evaluate classification quality — we should actively use it.

### 5.2 Annotation-driven classifier improvement

The annotation system (Phase 4 of the dashboard) was built exactly for this: manual labelling of classifier output to create ground truth. The workflow should be:
- Do regular annotation sessions — review recent classifications, label as correct/incorrect/uncertain, set expected urgency scores.
- Aggregate annotation data to identify systematic classifier errors (e.g., consistently over-rating Ukraine-response articles).
- Feed new labels into the existing eval sets above and use them to refine the policy prompt. The owner stays the sole labeler.

**I need to learn how the annotation system works in practice** — open the dashboard, go through the annotation flow, and understand what it offers before designing the improvement loop.

### 5.3 Continuous quality metrics

Extend the existing eval harness into metrics that track classification quality over time:
- Accuracy rate (annotations vs classifier output)
- False positive rate by category (which event types get over-classified?)
- Source yield (articles per source that actually matter)
- Alert-to-event ratio (how many alerts per real-world event?)

### 5.4 Holdout fixture v2 (annotation corrections)

- **What:** `docs/ideas/model-comparison-v2-run-record.md` lists 35 urgency ranges that are too narrow and 14 unsupported `active` status labels in the frozen holdout. `docs/ideas/model-comparison-v2-holdout-review.md` asks for case `v2h-en-01-c` to be rewritten and re-reviewed. The fixture is unchanged and has been reused since (for example `sentinel/eval/direct_luna.py:31` and the 2026-09-23 GPT-6 holdout runs).
- **Do:** create a new `model_comparison_v2_holdout` v2 file (keep the frozen one), apply those corrections, and have the owner re-review them. Until then, do not rank models on exact urgency or status with this fixture.

---

## 6. Codebase refactoring plan

**Problem:** The codebase has grown organically. Before introducing major changes (accounts, mobile app, multi-user), we should address structural debt — but the timing is a strategic decision.

**Tension:**
- Refactor too early → we refactor code that will change anyway when we add accounts/multi-user.
- Refactor too late → we build new features on top of messy foundations, compounding the debt.

**Possible strategies:**
1. **Refactor-then-build:** Do a major cleanup pass, then build new features on a clean base. Risk: delays feature work.
2. **Build-then-overhaul:** Keep implementing features, then do a big refactor before launch. Risk: tech debt compounds, bugs multiply.
3. **Phase-gate refactors:** Before each major phase (mobile app, accounts, billing), do a targeted refactor of the areas that phase will touch. Probably the best balance.

**Decision needed:** Pick a strategy. This ties into the overall product roadmap (TODO #4) — refactoring milestones should be part of the timeline.

### 6.1 Config & deployment bugs (surfaced 2026-05-30 docs overhaul; extended 2026-10-03)

Issues surfaced while auditing docs against source. All low-impact today but worth fixing:

1. **`config/config.yaml` — stale GDELT field.** `sources.gdelt.update_interval_minutes: 15` targets a non-existent field and is a silent no-op. The real GDELT key is `lookback_minutes` (default `60`). Low impact because GDELT is currently disabled (`sources.gdelt.enabled: false`), but fix this before re-enabling — otherwise GDELT silently falls back to the 60-minute default regardless of the intended value.
2. **`deploy/configs/sentinel.service` — misplaced systemd directives.** `StartLimitBurst` and `StartLimitIntervalSec` are under `[Service]`, but systemd expects them under `[Unit]`, so they are silently ignored and the restart rate-limit is not actually applied. Move both keys to the `[Unit]` section.
3. ~~**`mobile/app.json` — placeholder EAS `projectId`.**~~ **Done:** resolved by commit 7181f16 ("Link EAS project and add expo-dev-client"). `mobile/app.json` carries the real EAS project id and push is live in production.
4. **`--test-alert push` help text names the wrong env var.** The CLI help/failure message references `EXPO_PUSH_TOKEN`, but the credential `push_client.py` actually reads is `EXPO_ACCESS_TOKEN` (`EXPO_PUSH_TOKEN` is only a `${VAR}` placeholder substituted into `alerts.push.tokens`). One-line clarification in the help string.
5. **`state_machine.py` — confirmation code stored on bare instance attributes.** `self._confirmation_code` / `self._confirmation_sms_sid` are not per-event scoped and never reset between events. Safe today because dispatch is serialized by the cycle lock, but if event dispatch is ever parallelized, a reply to one event's code could spuriously acknowledge another. Scope them per-event before any concurrency change.
6. **Dead alert config keys.** `alerts.urgency_levels.*.retry_attempts`, `.retry_interval_minutes`, `.fallback`, `alerts.acknowledgment.cooldown_hours`, `alerts.acknowledgment.call_duration_threshold_seconds` and `alerts.language` are parsed but no runtime code reads them (`grep` finds only `sentinel/config.py`). The cooldown helpers once named in the docs (`_is_in_cooldown` and others) do not exist. Remove the keys or wire them up.
7. **`config/config.example.yaml` still ships `max_call_retries: 5`.** That is the value behind the 2026-07-30 call storm; the live `config/config.yaml` uses 1. Align the template.
8. **Misleading config comments.** `config/config.yaml` (push block, around line 654) says "Expo's push API is unauthenticated", but production uses Expo Enhanced Security with `EXPO_ACCESS_TOKEN`. `config/config.example.yaml` says a push/both tier "still sends SMS only until a token is added", but a `push` tier sends nothing in that case. `config/config.yaml:539` says "Local Luna uses the evaluated memory path. Production rollout is separate", but incident memory has been live in production since 2026-09-20.
9. **`--test-file` crashes on list-shaped YAML.** A top-level list (the shape of every eval fixture) raises an uncaught `AttributeError` at `data.get(...)` instead of a clean error (`sentinel.py:340`). Reject non-mapping YAML with a clear message.
10. **Local runs with the default `--config` fail.** `config/config.yaml` is the production-synced file and the default of `--config`: it needs `${EXPO_PUSH_TOKEN}` and writes to `/var/log/sentinel` and `/var/lib/sentinel`, so it cannot run on a workstation. The docs now work around this with a git-ignored copy of the template passed explicitly (`--config data/config.local.yaml`; see `docs/tutorials/getting-started.md` and `docs/how-to/testing.md`). Still open: decide whether the code should pick up a local config by default (for example when `data/config.local.yaml` exists), so a bare `./run.sh` works locally.
11. **`.env.example` lacks `EXPO_PUSH_TOKEN`.** A fresh checkout that follows `.env.example` cannot load `config/config.yaml`. Add `EXPO_PUSH_TOKEN` and a commented `EXPO_ACCESS_TOKEN`.
12. **Daily summary reports only one cycle.** The "=== Daily summary: cycles=1 … ===" log line reads the stats after they were reset for the new UTC day, so it shows only the first cycle (`sentinel/scheduler.py:101-113` and `:605-618`).
13. **Committed tool state and audit reports.** `.code-refiner-state-redesign-phase0/` and `-phase2/` are tracked in the public repo and missing from `.gitignore`. Under the git-ignored `data/`, six audit reports and `.last-audit-timestamp` are tracked while newer ones are not. Untrack the tool state and decide whether `data/audit-reports/` is versioned or local.
14. **`/deploy` step 6a config check.** The masking regex matches substrings of the dotted key path, so keyword lists and `*_tokens` values show as `***` and the agent cannot see what to copy. The script also runs without `set -e`: a failed `sudo cat` reports every key as UNEXPECTED, and a failed `git show` passes silently. Narrow the regex to whole key names and add explicit `|| exit 4` guards (`.claude/skills/deploy/SKILL.md` step 6a).
15. **OpenAI systemd drop-in is not versioned.** `/etc/systemd/system/sentinel.service.d/20-openai.conf` (it adds `EnvironmentFile=/etc/sentinel/openai.env`) exists only on the server. A rebuild from `deploy/` would start without `OPENAI_API_KEY`, so nothing would be classified. Add it to `deploy/configs/` and the setup script.
16. **`deploy/02-deploy-app.sh` does not match the unit.** It creates and uses `$APP_DIR/venv` (`:61-67`, smoke test at `:121`), but `deploy/configs/sentinel.service` runs `/home/deploy/sentinel/.venv/bin/python`, so a fresh install from `deploy/` cannot start. It also copies `config/config.example.yaml` to `/etc/sentinel/config.yaml` instead of the tracked production `config/config.yaml`. Switch the script to `.venv` and the repo config (together with item 15).
17. **`--dry-run` does not skip the pending-call check.** `sentinel/scheduler.py` (`run_cycle`) gates `state_machine.check_pending_calls()` only on `not diagnostic`, and `dry_run` is read only in `sentinel/alerts/dispatcher.py`. A dry run against a database that holds a phone-call record in status `initiated` or `ringing` polls Twilio and can retry the call or send the fallback SMS. Add a `dry_run` guard.

### 6.2 Dashboard lags the live schema (low priority)

The dashboard has had no commits since 2026-05-30. Fix together:
- It ignores `classification_queue`, so queued or failed articles show as "Unclassified (filtered out before classification stage)".
- Its classifier-input view (`dashboard/classifier_input.py`) rebuilds the legacy Haiku prompt, not the live OpenAI `policy.messages()` payload. Render that payload for `provider_used = 'openai'` rows, or label the current block legacy.
- `push` alert records have no icon or label and are missing from the `AlertRecord.alert_type` union (`dashboard/frontend/src/types.ts`); they render with the generic "•".
- The language filter lacks `ru` (`dashboard/frontend/src/components/FilterBar.tsx`).
- `--sync` copies only `sentinel.db` from a WAL-mode database (`dashboard/sync.py`), so recent writes may be missing. Use `sqlite3 … ".backup"` on the server or copy the `-wal` file too.
- Optional: show `provider_used`, `prompt_version` and `estimated_cost_usd`.

### 6.3 Production host drift (owner decisions, found 2026-10-03)

Read-only server audit findings. Each is a server change, so the owner decides and does it.
1. **Root console session left open.** A root login on the Hetzner web console (tty1) has been active since boot. Anyone who reaches the console gets a root shell. Log out (`exit`) and never leave the console logged in.
2. **Hetzner Cloud Firewall does not restrict SSH.** Port 2222 was reachable from 122 source IPs in 24 hours, so `sentinel-fw` is either not applied or not limited to the admin IP. Check it in the Hetzner console. Today fail2ban and key-only login are the real protection.
3. **Kernel and libc updates not active since 2026-03.** Automatic reboot is not enabled and `/var/run/reboot-required` exists. Schedule a reboot and decide on auto-reboot. A reboot pauses monitoring for a few minutes.
4. **fail2ban `[sshd]` override is shadowed.** `jail.d/whitelist.conf` asks for 5 tries / 1 h, but `jail.local` wins (3 tries / 24 h). Decide which policy you want and put it in a file that wins (`jail.local` or `jail.d/*.local`).
5. **AIDE baseline is stale.** `/var/lib/aide/aide.db` dates from 2026-03-23, so each daily report (`dailyaidecheck.timer`) is full of legitimate changes. Refresh the baseline.
6. **`log_martians` configured but not active.** `/etc/sysctl.d/99-sentinel-hardening.conf` sets it to 1, but the running kernel shows 0. Investigate.
7. **Postfix listens on port 25 on all interfaces.** UFW blocks it from outside. Consider `inet_interfaces = loopback-only`.
8. **SSH login notification script not installed.** `/etc/profile.d/ssh-login-notify.sh` from the hardening guide is absent. Install it only if wanted.

## 7. Findings from the 2026-09-23 model-eval work (not yet fixed)

Surfaced while building the eval suite (`docs/how-to/model-eval.md`). Code was not changed for these.

1. **URGENT — monthly model budget will stop classification in October.** Classification volume rose to ~450/day (2026-09-21..23). At that rate `gpt-5.6-luna` costs ~$10.8/month at list prices and ~$12.3 by the ledger's own estimate, above `classification.budget.monthly_usd: 10` and the OpenAI project's $10 hard cap. Once reached, `UsageLedger.reserve` (`sentinel/classification/openai_provider.py:64`) raises `BudgetExceeded` and articles stay pending — a missed-alert risk. Raise both caps before 2026-10-20. **App cap raised to $30 on 2026-09-24 (commit 31acd3a) and live on the server (verified 2026-10-03: `/etc/sentinel/config.yaml` has `monthly_usd: 30`). Still open: the OpenAI project's own hard cap; see "OpenAI project hard spend cap vs the 30 USD app allowance" in section 0.** Measured 2026-09-24: 420–580 classifications/day, ~$0.00095/article by the ledger (~$0.00084 at list prices). Measured 2026-10-03: the ledger showed `month_usd=1.2627` at 12:20 UTC on day 3, about $0.50/day.
2. **Ledger overstates OpenAI cost.** `cache_write_multiplier: 1.25` charges uncached input 1.25×; OpenAI does not bill cache writes, so the ledger shows ~$0.0009/article where the bill is ~$0.0008. Harmless for safety, but it brings the cap breach earlier.
3. **Enrichment is never persisted.** `enricher.py` replaces `article.summary` and writes `raw_metadata["enrichment"]` in memory only; the DB keeps the pre-enrichment text. Nobody can audit or replay what the model actually saw.
4. **Live prompt gets no headline-only signal.** The "body could not be fetched" caution exists only in the dead legacy prompt (`classifier.py` `_build_user_prompt`); `policy.messages()` passes title/summary with no hint that the text is just a headline.
5. **Enriched body truncated to 500 characters** (`_fetch_body`), which can cut the clause that states geography.
6. **Reproducible `gpt-5.6-luna` rule violations on the synthetic hold-out:** reads past-tense narration of an unresolved precaution as `resolved`; treats an explicitly ended alarm as an active `official_warning`; ignores the worked example that a civilian object found in a monitored country populates `affected_countries`.
7. **Google News decoder can stall the whole cycle.** `ArticleEnricher._fetch_body` calls `_resolve_url` → `googlenewsdecoder.new_decoderv1` synchronously on the event loop; that library calls `requests.get`/`requests.post` with no timeout (0.1.7, lines 49, 71, 126). A hung Google request would freeze the cycle, including phone calls. Fix: run it on a small dedicated thread pool under a deadline (see `specs/fulltext-second-read/PRODUCTION_NOTES.md`, pitfall 1). Found 2026-09-24 during spec verification.
8. **The pre-registered decision rule still names the $10 cap.** The rule in `docs/how-to/model-eval.md` gates a candidate on "projected busy-month cost within the $10 monthly cap", and the report prices against $10. The app allowance has been 30 USD since 2026-09-24. The owner sets the gate value before the locked-pool run; changing it after seeing locked-pool results would break the pre-registration. Found 2026-10-03.

---

## Commentary: Priority & sequencing (Claude's assessment, 2026-05-24)

> [2026-10-03] Superseded in part: #3 shipped as a native Expo app, not a PWA; the #1 Haiku-tier cost figures predate the Luna migration; human-labeled eval sets now exist. The life-safety items in §0 come first. Re-rank the rest before acting on this order.

**The biggest risk is scope explosion.** Items 1–6 above represent 3-4 full-time engineering quarters for a solo side project. Tackling them all in parallel will result in bouncing between fronts and finishing none. Sequencing matters more than any individual item.

**Recommended priority order: 5 → 1 → 2 → 3 → 4 → 6**

1. **Start with #5 (pipeline/classifier).** Highest-ROI — directly improves the thing that matters: not missing a real event and not crying wolf. The annotation system is already built and sitting unused. Using it to systematically measure and improve classification quality is the single best investment of time right now.

2. **#1 (tiered classification) follows naturally from #5.** Once annotation data reveals where Haiku makes systematic errors, the tiered pipeline addresses them with Sonnet/Opus verification. Cost is negligible (+$1.13/mo).

3. **#2 (sources) is worth a focused analysis sprint.** Twitter/X is the obvious gap — it's where military OSINT breaks first. The official API runs ~$100/mo for basic access, but services like SocialData or Apify offer cheaper scraping. Truth Social is noise for this use case — skip it.

4. **#3 (mobile app) — try PWA first, not a native app.** A progressive web app with web push notifications gets you custom sounds, rich links, and zero delivery cost in 2-3 days of work instead of weeks. The one catch is iOS — Safari push works now but is flakier than native. If PWA proves insufficient, then consider React Native. Building a full native app at this stage is overkill.

5. **#4 (productization) is premature.** The classifier hasn't been systematically validated even for personal use — the annotation system exists but hasn't been used to measure accuracy. Selling a military alert product with unvalidated classification quality is a liability, not a business. The sequencing should be: make the pipeline excellent for yourself → prove it with annotation data → then decide if it's worth productizing. If you do eventually productize, invite-only beta beats big-bang launch for a niche product like this — you won't learn what matters from theory, you need 5 real users telling you what's wrong.

6. **#6 (refactoring) — phase-gated is the obvious answer.** Big rewrites kill side projects. Refactor the parts you're about to touch before each major phase, leave the rest alone. Don't do a speculative "clean everything up" pass.

---

## Completed Debt (reference)

All 7 code debt items and 8 ops debt items were resolved 2026-05-25 through 2026-05-27. See git history for details.

---

## Documentation reorganization (2026-05-30)

The documentation was overhauled and reorganized into a Diátaxis `docs/` tree (tutorials / how-to / reference / explanation / archive) on 2026-05-30. Doc paths changed — see [docs/README.md](docs/README.md) for the new index.
