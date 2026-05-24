# Project Sentinel — TODO

## 1. Differentiate Ukraine-targeted vs Poland-targeted attacks in alert messages

**Problem:** Russia attacks Ukraine constantly. The classifier correctly picks these up but the alert messages look identical to alerts about direct attacks on Poland/Baltics, causing alarm fatigue and confusion (e.g., "Poland scrambles jets in response to Russian strike on Ukraine" gets classified as urgency 9 missile_strike on PL).

**Constraint:** Do NOT suppress or deprioritize Ukraine-related alerts. It's better to have many false positives than to miss a real positive. The risk of filtering too aggressively is that we miss a genuine escalation.

**Ideas to explore:**
- Prefix the alert message to clearly distinguish: e.g., `⚠️ ATAK NA UKRAINĘ` vs `🚨 ATAK NA POLSKĘ` — so the recipient immediately knows the context before reading the details.
- Possibly adjust the classification prompt to better distinguish between "Poland is under direct attack" vs "Poland is activating defenses in response to a nearby attack on Ukraine." The urgency score for the latter should be lower (e.g., 4-5 instead of 9).
- Consider a separate `target_country` field in classification to distinguish who is actually being attacked vs who is responding defensively.
- The goal: when you glance at the WhatsApp message, you instantly know whether Poland itself is hit or whether it's a defensive response to an attack on a neighbor.

## 2. Smarter multi-tier classification to reduce false positives

**Problem:** Haiku misclassifies headlines like "Poland scrambles jets in response to Russian strike on Ukraine" as a direct attack on Poland (urgency 9). Using Opus for all classifications would fix accuracy but is prohibitively expensive at 688+ articles per cycle.

**Approach: Tiered classification pipeline (Haiku → Sonnet → Opus)**

1. **Haiku (first pass, all articles):** Keep Haiku as the fast/cheap initial classifier. Improve the classification prompt to explicitly distinguish "country X is under direct attack" from "country X is responding defensively to an attack on a neighbor." This alone should eliminate most false positives — it's a prompt problem, not a model capability problem.

2. **Sonnet (second pass, ambiguous cases):** When Haiku returns urgency ≥ 5, re-classify with Sonnet 4.6 for a second opinion. Sonnet is ~5x cheaper than Opus and significantly more capable than Haiku. Use the Sonnet score as the authoritative one.

3. **Opus (final verification, before phone calls only):** Before triggering a phone call (urgency 9+, 2+ corroborating sources), run a single Opus 4.6 verification call. This is the highest-stakes action (waking someone up), so it warrants the best model. Expected volume: 0-2 Opus calls per day — negligible cost.

**Why not use Claude CLI / Max plan instead of API:**
- Max plan is for interactive personal use — automating it in a production pipeline violates TOS and risks account suspension
- No SLA, fragile auth (OAuth tokens expire), rate limits tuned for human-speed interaction
- A critical alert system cannot depend on a consumer subscription

**Cost analysis (based on real production data, 2026-03-24):**

First ~14 hours of operation: 51 classifications, avg 699 input / 146 output tokens each.
Projected ~1,800 classifications/month at steady state (~60/day).
Urgency distribution: 88% score 1-4, 4% score 5-6, 4% score 7-8, 4% score 9+.

| Setup | Monthly cost |
|---|---|
| Current (Haiku only) | ~$2.57 |
| Tiered (Haiku + Sonnet + Opus) | ~$3.70 |
| Delta | +$1.13 (+44%) |

Sonnet tier adds ~$0.92/mo (~216 re-classifications). Opus tier adds ~$0.21/mo (~10 verifications). Cost is negligible — the tiered approach is about accuracy, not savings.

**Auditability requirement:**
Every classification step must be saved to the database — not just the final result. When Sonnet re-classifies an article, store the Sonnet prompt, response, model used, tokens, and result alongside the original Haiku classification. Same for Opus verification. The `classifications` table needs a `tier` or `pass_number` column (or a separate `classification_passes` table) so we can trace the full decision chain for any article: what Haiku said → what Sonnet said → what Opus said → final decision.

**Implementation notes:**
- All three tiers use the API (`ANTHROPIC_API_KEY`), just different model IDs
- The classification prompt improvement (tier 1) should be done first — it's free and addresses the root cause
- Tiers 2-3 add cost but only for the small fraction of articles that score high

---

## 3. Audit & resolve existing TODO items

Go through every item in this file (problems, code debt, ops debt) and verify whether each is still relevant. Fix or close them one by one. Some may have been resolved by recent work; others may have rotted further. The goal is to get to a clean, accurate backlog before adding major new features.

---

## 4. Source health analysis & expansion

**Problem:** Some article sources are nearly dead (consistently 403, low yield), while others are very active and fruitful. We haven't re-evaluated sources since initial setup.

**What to do:**
- Audit every current source: volume, error rate, unique article yield, geographic coverage. Identify dead/dying sources and decide: replace, disable, or accept.
- Research new sources to add, especially for real-time military intelligence:
  - **Twitter/X:** Likely the fastest source for breaking military news. However, the API is reportedly very expensive. Investigate: current API pricing tiers, rate limits, what we'd actually need (filtered stream vs search). Explore cheaper alternatives — community-maintained scrapers, Nitter-like proxies, RSS bridges, OSINT aggregators that republish Twitter content.
  - **Truth Social:** Evaluate whether it carries any signal for our use case (military threats to Poland/Baltics). Likely low priority but worth a quick assessment.
  - **Other OSINT sources:** Liveuamap, FIRMS (NASA fire data for strike detection), flight trackers (ADS-B), Telegram channels beyond what we already monitor.

---

## 5. Mobile app — replace SMS notifications

**Problem:** SMS notifications are inadequate for several reasons:
1. **No differentiation** — an alert SMS looks identical to a work text from France; no custom sound/chime to signal urgency.
2. **No link formatting** — Google News URLs are extremely long and ugly; can't substitute with a short "Click here" link or deep-link into the app.
3. **Cost** — SMS costs ~$50/month via Twilio, which is a lot for a personal project.

**Phone calls should stay.** The call-based alert for urgency 9-10 events is the core value proposition and does not require an app. It must remain regardless.

**Approach: Build a mobile app with push notifications.**
- Push notifications replace SMS: free to deliver, support custom sounds/chimes, support rich content (formatted text, tappable links, images).
- **MVP scope (first release):** Tap the Sentinel logo → app opens, shows only a notification feed. No dashboard, no settings — just push notifications with event details and links.
- **Second iteration:** Add a lightweight dashboard view. We already have a full web dashboard (React/Vite), so this could be a WebView wrapper or a progressive web app (PWA) rather than a native build.
- **SMS stays as a fallback** — keep it plumbed for users without the app, and potentially as a paid tier for future users.

**Open questions:**
- Native app (React Native / Flutter) vs PWA? PWA is cheaper to build and maintain but push notification support varies by platform.
- Notification infrastructure: Firebase Cloud Messaging (FCM) for Android, APNs for iOS? Or a unified service like OneSignal / Expo Push?

---

## 6. Productize Sentinel — strategy & roadmap

The long-term goal is to turn Sentinel from a personal tool into a multi-user product. This requires both technical and business work, and the two influence each other — feature decisions depend on pricing strategy, and pricing depends on what's technically feasible.

### 6.1 Technical requirements for multi-user

1. **Account system.** Currently the entire app is single-user, hardcoded for one person's preferences. Need: user registration/auth, per-user notification preferences, per-user alert history.

2. **Per-user configuration.** Users should be able to control:
   - Notification channels (push, SMS, call) and which urgency levels trigger each
   - Whether they get calls only on 9-10, or also on 5+ (configurable threshold)
   - Event deduplication window (our 6-hour corroboration window vs custom)
   - Whether to be notified of every event or only above a threshold
   - Time zone and language preferences

3. **Cost-aware feature design.** Calls and SMS cost real money per user. Push notifications are free. Configurable call thresholds must be paired with cost analysis — if a user sets calls on urgency 5+, that could mean dozens of calls/month. This needs to be reflected in pricing tiers or hard limits.

### 6.2 Business decisions (open)

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

### 6.3 What's configurable vs fixed

Before building multi-user, decide what users can change and what we control:
- Call threshold (urgency level that triggers a call)
- Corroboration window (6h default — user-adjustable or fixed?)
- Event deduplication (per-user or global?)
- Source selection (can users pick which sources to monitor?)
- Notification schedule (quiet hours? — currently deliberately none)

Each configurable parameter adds complexity. Default to fixed unless there's a strong user need.

---

## 7. Pipeline analysis & classifier refinement

**Goal:** Develop a continuous, systematic process for evaluating and improving the entire pipeline — from source ingestion to classification to alerting.

### 7.1 End-to-end pipeline review

Do a full audit of the data flow:
- **Source → keyword filter:** What articles does keyword filtering catch? What does it miss? Is simple keyword matching sufficient, or should we add semantic analysis or AI-based pre-filtering? What would AI-based filtering cost at our article volume?
- **Keyword filter → classifier:** Are there articles that pass keyword filtering but never reach classification? Are there articles filtered out too early that should have been classified? We need visibility into the pre-classification funnel.
- **Classifier → dashboard:** Everything classified is visible on the dashboard. But the annotation system exists precisely to evaluate classification quality — we should actively use it.

### 7.2 Annotation-driven classifier improvement

The annotation system (Phase 4 of the dashboard) was built exactly for this: manual labelling of classifier output to create ground truth. The workflow should be:
- Do regular annotation sessions — review recent classifications, label as correct/incorrect/uncertain, set expected urgency scores.
- Aggregate annotation data to identify systematic classifier errors (e.g., consistently over-rating Ukraine-response articles).
- Use annotation data to refine the classification prompt and potentially fine-tune the tiered pipeline (TODO item #2).

**I need to learn how the annotation system works in practice** — open the dashboard, go through the annotation flow, and understand what it offers before designing the improvement loop.

### 7.3 Continuous quality metrics

Build or plan metrics that track classification quality over time:
- Accuracy rate (annotations vs classifier output)
- False positive rate by category (which event types get over-classified?)
- Source yield (articles per source that actually matter)
- Alert-to-event ratio (how many alerts per real-world event?)

---

## 8. Codebase refactoring plan

**Problem:** The codebase has grown organically. Before introducing major changes (accounts, mobile app, multi-user), we should address structural debt — but the timing is a strategic decision.

**Tension:**
- Refactor too early → we refactor code that will change anyway when we add accounts/multi-user.
- Refactor too late → we build new features on top of messy foundations, compounding the debt.

**Possible strategies:**
1. **Refactor-then-build:** Do a major cleanup pass, then build new features on a clean base. Risk: delays feature work.
2. **Build-then-overhaul:** Keep implementing features, then do a big refactor before launch. Risk: tech debt compounds, bugs multiply.
3. **Phase-gate refactors:** Before each major phase (mobile app, accounts, billing), do a targeted refactor of the areas that phase will touch. Probably the best balance.

**Decision needed:** Pick a strategy. This ties into the overall product roadmap (TODO #6.4) — refactoring milestones should be part of the timeline.

---

## Commentary: Priority & sequencing (Claude's assessment, 2026-05-24)

**The biggest risk is scope explosion.** Items 3–8 above represent 3-4 full-time engineering quarters for a solo side project. Tackling them all in parallel will result in bouncing between fronts and finishing none. Sequencing matters more than any individual item.

**Recommended priority order: 3 → 7 → 4 → 5 → 6 → 8**

1. **Start with #3 (audit existing debt) and #7 (pipeline/classifier).** These are highest-ROI — they directly improve the thing that matters: not missing a real event and not crying wolf. The annotation system is already built and sitting unused. Using it to systematically measure and improve classification quality is the single best investment of time right now.

2. **#4 (sources) is worth a focused analysis sprint.** Twitter/X is the obvious gap — it's where military OSINT breaks first. The official API runs ~$100/mo for basic access, but services like SocialData or Apify offer cheaper scraping. Truth Social is noise for this use case — skip it.

3. **#5 (mobile app) — try PWA first, not a native app.** A progressive web app with web push notifications gets you custom sounds, rich links, and zero delivery cost in 2-3 days of work instead of weeks. The one catch is iOS — Safari push works now but is flakier than native. If PWA proves insufficient, then consider React Native. Building a full native app at this stage is overkill.

4. **#6 (productization) is premature.** The classifier hasn't been systematically validated even for personal use — the annotation system exists but hasn't been used to measure accuracy. Selling a military alert product with unvalidated classification quality is a liability, not a business. The sequencing should be: make the pipeline excellent for yourself → prove it with annotation data → then decide if it's worth productizing. If you do eventually productize, invite-only beta beats big-bang launch for a niche product like this — you won't learn what matters from theory, you need 5 real users telling you what's wrong.

5. **#8 (refactoring) — phase-gated is the obvious answer.** Big rewrites kill side projects. Refactor the parts you're about to touch before each major phase, leave the rest alone. Don't do a speculative "clean everything up" pass.

---

## Tracked Code Debt

1. **WhatsApp action plumbed but routed to SMS.** `state_machine.py:190-191` overrides `whatsapp` action to `_execute_sms`. `_execute_whatsapp` (`state_machine.py:478`) and `TwilioClient.send_whatsapp` are unreachable from the production flow. 17 historical successful WhatsApp alerts in DB suggest the channel worked at some point. Decision needed: enable, remove entirely, or keep as a fallback.

2. **Dead `_check_confirmation_sms_delivered`.** Defined at `state_machine.py:415`, never called. Either delete the method or wire it into the SMS-confirmation flow.

3. **Unread `testing.test_mode` field.** `config.py:182` defines this field; nothing in the codebase reads it. Either delete or implement.

4. **Synchronous Anthropic SDK call inside async pipeline.** `Classifier._call_api` (`classifier.py`) calls the synchronous Anthropic SDK from inside `async run_cycle`. Same issue with blocking `time.sleep()` in `_execute_phone_call` — blocks the asyncio event loop for up to ~500s per call round. Wrap with `asyncio.to_thread()` or switch to an async-native client.

5. **Empty `tests/fixtures/`.** `config.testing.test_headlines_file` defaults to `tests/fixtures/test_headlines.yaml` but the file does not exist. Either create the fixture or fix the default.

6. **Dead config: GDELT `cameo_codes` and `goldstein_threshold`.** Parsed by `GDELTConfig` in `config.py` but `GDELTFetcher.build_query()` only uses `themes` and `target_countries`. These fields do nothing.

7. **Dead code in `state_machine.py:501-518`.** An `if False:` block containing the call-duration-based acknowledgment path. Replaced by SMS-code confirmation. Delete.

---

## Tracked Ops Debt

1. **Delete `/home/deploy/sentinel.bak-20260324/.env` on production server** — contains live Twilio/Anthropic/Telegram credentials in a stale clone.

2. **Delete `/home/deploy/sentinel/project-sentinel/` on production server** — nested untracked clone inside working tree, also contains live credentials. Causes permanent `git status` noise.

3. **Re-attach server repo to `master`.** `/home/deploy/sentinel` is in detached HEAD state; would break `git pull origin master`. Fix: `cd /home/deploy/sentinel && git checkout master`.

4. **Deploy current `config/config.yaml` to `/etc/sentinel/config.yaml`.** Live config is missing ~35 keywords that commit `d96f4a4` added.

5. **Add deploy-snapshot pruning.** `/home/deploy/backups/` is at 792 MB and growing; deploy-snapshot directories are not auto-pruned (only DB backups are).

6. **Decide TVN24 + LSM Latvia source health.** Both consistently 403 Forbidden — 558 + 93 errors in most recent log respectively. Replace, disable, or accept.

7. **Update repo template `deploy/configs/sentinel.service`** to use `.venv/` (matches live) instead of legacy `venv/`.

8. **Remove legacy `/home/deploy/sentinel/venv/` on server** — only `.venv/` is used by systemd.
