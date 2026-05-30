# Project Sentinel — TODO

## 1. Smarter multi-tier classification to reduce false positives

### 1.0 — URGENT: Audit historical false-positive PL phone calls (escape-trigger misfires)

> Surfaced by the 7-agent event-grouping deep dive on 2026-05-30. Conversation: `20fb6962-608c-433b-978a-92e1a5740b26` (session "event-grouping-bugfix"). This is the safety-critical half of the false-positive problem below — quantify how often the escape trigger has *already* fired wrongly, and close the root cause, before/while building the tiered pipeline.

**What we found (production DB evidence):** the Haiku classifier resolves thin headlines like *"Russian drone hit a residential block in a NATO country"* to **Poland, urgency 9** with fabricated summaries (e.g. *"bezpośrednie zagrożenie dla terytorium Polski"*) for incidents physically in **Romania or Ukraine**. Concrete cases found in `alert_records`:
- **2026-05-01 — Tarnopil (Ukraine) drone strike** classified `["PL"]` urgency 9 → **7 completed Twilio phone calls** (events `61c468f6`, `b8c6feda`). Almost certainly FALSE (Ukrainian city, not Poland).
- **2026-04-03** (event `b2dcd82b`, "masowy atak na Polskę") and **2026-04-17** (event `aa6fd456`, "Polska ostrzelana przez Rosję"): PL/9, **completed phone calls — UNVERIFIED**: real PL events, or the same UA/RO→PL bug?
- **2026-05-30 — Galați (Romania)**: PL/9 row (`a8ae1407`) did NOT call ONLY because `corroboration_required=1` + single source held it at `retry_pending`. The corroboration gate is the sole circuit-breaker that happened to trip.
- Instability scale: across 579 classifications of the single Galați incident, urgency ranged **1–9**, 5 event_types, country `["RO"]`×310 / `[]`×265 / monitored-country×4. PL-contamination is rare (~0.7%) — frequent enough to fire eventually, rare enough that each call looks like an anomaly.

**Task:**
1. **Verify every historical PL/Baltic urgency-9/10 phone call** in `alert_records` (JOIN to `events`/`articles`, read the source). Label each REAL vs FALSE; quantify real escape-trigger calls vs misfires to date.
2. **Assess current exposure:** with live `corroboration_required=1`, a single mis-tagged source can dial out — confirm whether any single-source path to a PL/9 call is currently open, and whether raising the phone-tier `corroboration_required` is warranted (without the grouping changes re-suppressing genuine corroboration).
3. **Root-cause prompt fix (Cause C; feeds §1 tiered pipeline and §5.2):** the classifier prompt's `R4 POLAND PRIORITY` + bare "NATO state = 9" language lets a non-PL NATO incident acquire a PL/9 label. Fix sketch — **eval-gated; owner is sole ground-truth labeler, do NOT blind-deploy:** add an `R0 TARGET-COUNTRY GATE` (non-monitored NATO ≠ PL; "a NATO country" must NOT resolve to Poland), demote R4 to a tie-break applied only once PL is already confirmed, replace "NATO = 9" with "monitored country (PL/LT/LV/EE) = 9", and confine spillover language to urgency only (never to `affected_countries`).

**Why urgent:** a false phone call can trigger a needless flight from Poland — the worst non-miss failure mode of the escape trigger. The grouping fix deployed 2026-05-30 (tag `deploy-20260530-163637`) reduced the duplicate-SMS *symptom*; this item addresses the dangerous *root cause*.

---

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

## 2. Source health analysis & expansion

**Problem:** Some article sources are nearly dead (consistently 403, low yield), while others are very active and fruitful. We haven't re-evaluated sources since initial setup.

**What to do:**
- Audit every current source: volume, error rate, unique article yield, geographic coverage. Identify dead/dying sources and decide: replace, disable, or accept.
- Research new sources to add, especially for real-time military intelligence:
  - **Twitter/X:** Likely the fastest source for breaking military news. However, the API is reportedly very expensive. Investigate: current API pricing tiers, rate limits, what we'd actually need (filtered stream vs search). Explore cheaper alternatives — community-maintained scrapers, Nitter-like proxies, RSS bridges, OSINT aggregators that republish Twitter content.
  - **Truth Social:** Evaluate whether it carries any signal for our use case (military threats to Poland/Baltics). Likely low priority but worth a quick assessment.
  - **Other OSINT sources:** Liveuamap, FIRMS (NASA fire data for strike detection), flight trackers (ADS-B), Telegram channels beyond what we already monitor.

---

## 3. Mobile app — replace SMS notifications

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

## 4. Productize Sentinel — strategy & roadmap

The long-term goal is to turn Sentinel from a personal tool into a multi-user product. This requires both technical and business work, and the two influence each other — feature decisions depend on pricing strategy, and pricing depends on what's technically feasible.

### 4.1 Technical requirements for multi-user

1. **Account system.** Currently the entire app is single-user, hardcoded for one person's preferences. Need: user registration/auth, per-user notification preferences, per-user alert history.

2. **Per-user configuration.** Users should be able to control:
   - Notification channels (push, SMS, call) and which urgency levels trigger each
   - Whether they get calls only on 9-10, or also on 5+ (configurable threshold)
   - Event deduplication window (our 6-hour corroboration window vs custom)
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
- Corroboration window (6h default — user-adjustable or fixed?)
- Event deduplication (per-user or global?)
- Source selection (can users pick which sources to monitor?)
- Notification schedule (quiet hours? — currently deliberately none)

Each configurable parameter adds complexity. Default to fixed unless there's a strong user need.

---

## 5. Pipeline analysis & classifier refinement

**Goal:** Develop a continuous, systematic process for evaluating and improving the entire pipeline — from source ingestion to classification to alerting.

### 5.1 End-to-end pipeline review

Do a full audit of the data flow:
- **Source → keyword filter:** What articles does keyword filtering catch? What does it miss? Is simple keyword matching sufficient, or should we add semantic analysis or AI-based pre-filtering? What would AI-based filtering cost at our article volume?
- **Keyword filter → classifier:** Are there articles that pass keyword filtering but never reach classification? Are there articles filtered out too early that should have been classified? We need visibility into the pre-classification funnel.
- **Classifier → dashboard:** Everything classified is visible on the dashboard. But the annotation system exists precisely to evaluate classification quality — we should actively use it.

### 5.2 Annotation-driven classifier improvement

The annotation system (Phase 4 of the dashboard) was built exactly for this: manual labelling of classifier output to create ground truth. The workflow should be:
- Do regular annotation sessions — review recent classifications, label as correct/incorrect/uncertain, set expected urgency scores.
- Aggregate annotation data to identify systematic classifier errors (e.g., consistently over-rating Ukraine-response articles).
- Use annotation data to refine the classification prompt and potentially fine-tune the tiered pipeline (TODO item #1).

**I need to learn how the annotation system works in practice** — open the dashboard, go through the annotation flow, and understand what it offers before designing the improvement loop.

### 5.3 Continuous quality metrics

Build or plan metrics that track classification quality over time:
- Accuracy rate (annotations vs classifier output)
- False positive rate by category (which event types get over-classified?)
- Source yield (articles per source that actually matter)
- Alert-to-event ratio (how many alerts per real-world event?)

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

---

## Commentary: Priority & sequencing (Claude's assessment, 2026-05-24)

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
