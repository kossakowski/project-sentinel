# Project Sentinel — TODO

## 1. Differentiate Ukraine-targeted vs Poland-targeted attacks in alert messages

**Problem:** Russia attacks Ukraine constantly. The classifier correctly picks these up but the alert messages look identical to alerts about direct attacks on Poland/Baltics, causing alarm fatigue and confusion (e.g., "Poland scrambles jets in response to Russian strike on Ukraine" gets classified as urgency 9 missile_strike on PL).

**Constraint:** Do NOT suppress or deprioritize Ukraine-related alerts. It's better to have many false positives than to miss a real positive. The risk of filtering too aggressively is that we miss a genuine escalation.

**Ideas to explore:**
- Prefix the alert message to clearly distinguish: e.g., `⚠️ ATAK NA UKRAINĘ` vs `🚨 ATAK NA POLSKĘ` — so the recipient immediately knows the context before reading the details.
- Possibly adjust the classification prompt to better distinguish between "Poland is under direct attack" vs "Poland is activating defenses in response to a nearby attack on Ukraine." The urgency score for the latter should be lower (e.g., 4-5 instead of 9).
- Consider a separate `target_country` field in classification to distinguish who is actually being attacked vs who is responding defensively.
- The goal: when you glance at the WhatsApp message, you instantly know whether Poland itself is hit or whether it's a defensive response to an attack on a neighbor.

## ~~2. Include clickable source links in SMS/WhatsApp messages~~ ✅ DONE

Implemented 2026-03-24. `_build_sources_list()` now appends the article `source_url` below each source line. Google News URLs included as-is. Deployed to production.

## 3. Smarter multi-tier classification to reduce false positives

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
