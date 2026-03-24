# Project Sentinel — TODO

## 1. Differentiate Ukraine-targeted vs Poland-targeted attacks in alert messages

**Problem:** Russia attacks Ukraine constantly. The classifier correctly picks these up but the alert messages look identical to alerts about direct attacks on Poland/Baltics, causing alarm fatigue and confusion (e.g., "Poland scrambles jets in response to Russian strike on Ukraine" gets classified as urgency 9 missile_strike on PL).

**Constraint:** Do NOT suppress or deprioritize Ukraine-related alerts. It's better to have many false positives than to miss a real positive. The risk of filtering too aggressively is that we miss a genuine escalation.

**Ideas to explore:**
- Prefix the alert message to clearly distinguish: e.g., `⚠️ ATAK NA UKRAINĘ` vs `🚨 ATAK NA POLSKĘ` — so the recipient immediately knows the context before reading the details.
- Possibly adjust the classification prompt to better distinguish between "Poland is under direct attack" vs "Poland is activating defenses in response to a nearby attack on Ukraine." The urgency score for the latter should be lower (e.g., 4-5 instead of 9).
- Consider a separate `target_country` field in classification to distinguish who is actually being attacked vs who is responding defensively.
- The goal: when you glance at the WhatsApp message, you instantly know whether Poland itself is hit or whether it's a defensive response to an attack on a neighbor.

## 2. Include clickable source links in SMS/WhatsApp messages

**Problem:** Current alert messages reference sources by name (e.g., `GoogleNews:military attack Poland: Poland Mobilizes Fighter Jets...`) but don't include a clickable URL. When you receive the alert, you can't instantly verify the article content.

**Requirements:**
- Every SMS/WhatsApp alert must include the source article URL as a clickable link.
- If the source is a Google News redirect URL, include the Google News URL as-is — do NOT try to resolve it to the underlying article. Google News links work fine in browsers and will redirect the user to the actual article.
- The link should be placed prominently so it's immediately tappable on a phone.
