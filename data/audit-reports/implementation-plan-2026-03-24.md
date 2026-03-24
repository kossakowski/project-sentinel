# Implementation Plan: Audit 2026-03-24 Remediation

**Status:** DRAFT -- awaiting review and approval before execution
**Based on:** `data/audit-reports/audit-2026-03-24.md`
**Codebase exploration date:** 2026-03-24

---

## Audit Corrections (Read First)

Before implementing, note that two of the audit's infrastructure recommendations are **already satisfied by the code** and should be struck from scope:

1. **Recommendation #28 (case-sensitivity bug):** The code at `keyword_filter.py:38` lowercases the entire searchable text (`f"{article.title} {article.summary}".lower()`), and `keyword_filter.py:153` lowercases each keyword before comparison. **Matching is already case-insensitive.** The Rzeczpospolita "Alarm na Litwie" article was missed for a different reason -- most likely deduplicated against another copy from the same fetch cycle, or the article's `summary` field contained an EXCLUDE keyword not visible in the title alone. **Action:** Investigate via production DB query, not a code fix.

2. **Recommendation #29 (title + summary check):** The code at `keyword_filter.py:38` already searches `f"{article.title} {article.summary}"`. **Both fields are checked.** The Defence24 article "Samoloty wrociły do baz" with "naruszenie przestrzeni powietrznej" in the summary should have matched. If it didn't, the summary may have been empty at fetch time. **Action:** Investigate via production DB query, not a code fix.

---

## Workstream Overview

| ID | Workstream | Type | Risk | Files Changed |
|----|-----------|------|------|---------------|
| A | Keyword config updates | Config only | Low | `config/config.example.yaml`, production `/etc/sentinel/config.yaml` |
| B | Classifier prompt amendments | Code | Medium | `sentinel/classification/classifier.py` |
| C | Telegram fetcher hardening | Code | Low | `sentinel/fetchers/telegram.py` |
| D | GDELT diagnostics | Investigation | None | (diagnostic only) |
| E | Missed-article investigation | Investigation | None | (diagnostic only) |

**Dependency chain:** A and B are independent. C and D are independent. E informs future work. All can be parallelized.

**Deployment order:** B (classifier prompt) should deploy BEFORE A (keywords). Reason: adding new keywords will send more articles to the classifier. If the classifier still has the over-scoring bugs, the new keywords will generate MORE false alerts, not fewer. Fix the classifier first, then widen the keyword net.

---

## Workstream A: Keyword Configuration Updates

### Scope
Config-only changes to `monitoring.keywords` and `monitoring.exclude_keywords` in YAML. No Python code changes.

### Files to modify
1. `config/config.example.yaml` -- the repository template (lines ~90-230)
2. Production: `/etc/sentinel/config.yaml` via SSH (same structure)

### Changes: Priority 1 (critical missed articles)

Each change below specifies the YAML path, the action (add/replace), and the exact string value.

#### A1. Replace `"drony"` with `"dron"` in `monitoring.keywords.pl.high`

- **Find:** `- "drony"` in the `pl.high` list
- **Replace with:** `- "dron"`
- **Rationale:** Slavic substring matching means `"dron"` matches: dron, drona, dronem, dronow, dronowy, dronami, drony, dronowych. The current `"drony"` misses all singular and non-nominative-plural forms.
- **False positive risk:** Low. "dron" only appears in drone-related words in Polish. "eskadron" (squadron) contains "dron" but is rare and would be filtered by the classifier.
- **Validates against:** Lithuania drone crash articles (6 missed)

#### A2. Add `"poderwał"` to `monitoring.keywords.pl.high`

- **Location:** Append to the `pl.high` list
- **Value:** `- "poderwał"`
- **Rationale:** Substring matches: poderwał, poderwała, poderwało, poderwane, poderwano, poderwali, poderwany. Covers all conjugations of "scrambled" (jets).
- **False positive risk:** Low. In Polish news context, "poderwał" is almost exclusively military (scrambled jets). Colloquial "picked up (a girl)" usage does not appear in news sources monitored by Sentinel.
- **Validates against:** Poland scrambled jets articles (~15 missed)

#### A3. Add `"alarm lotniczy"` to `monitoring.keywords.pl.critical`

- **Location:** Append to the `pl.critical` list
- **Value:** `- "alarm lotniczy"`
- **Rationale:** "Air alarm over Poland" is an unconditionally critical event. CRITICAL level bypasses EXCLUDE keywords.
- **False positive risk:** Very low. "Alarm lotniczy" is unambiguously military.

#### A4. Add `"atak na Polskę"` to `monitoring.keywords.pl.critical`

- **Location:** Append to the `pl.critical` list
- **Value:** `- "atak na Polskę"`
- **Rationale:** Any article discussing "attack on Poland" must reach the classifier unconditionally.
- **False positive risk:** Very low. Even rhetorical/diplomatic uses of this phrase should be classified.
- **Note:** Substring matching means this also matches "zaatakować Polskę" (since "atak na polskę" would NOT be a substring of "zaatakować polskę" -- the "na" would fail). So also add:
- **Additional value:** `- "zaatakować Polskę"`

#### A5. Add `"Szahed"` to `monitoring.keywords.pl.high`

- **Location:** Append to the `pl.high` list
- **Value:** `- "Szahed"`
- **Rationale:** Polish transliteration of Shahed drone. Current `"Shahed"` (Latin) does not substring-match `"Szahedy"` (Polish). Substring matching catches: Szahed, Szahedy, Szahedów, Szahedem.
- **False positive risk:** Very low.

#### A6. Add `"drone crash"` and `"drone crashed"` to `monitoring.keywords.en.high`

- **Location:** Append to the `en.high` list
- **Values:** `- "drone crash"` and `- "drone crashed"`
- **Rationale:** EN word-boundary matching means "drone incursion" does not match "drone crash." These are distinct phrases.
- **False positive risk:** Low. Civilian drone crashes are uncommon in international news. Classifier filters non-military incidents.

#### A7. Add `"UAV"` to `monitoring.keywords.en.high`

- **Location:** Append to the `en.high` list
- **Value:** `- "UAV"`
- **Rationale:** Common military synonym for "drone" used by TASS and military outlets. Not covered by any existing keyword.
- **False positive risk:** Very low. "UAV" is exclusively military/technical.

#### A8. Add `"scramble"` to `monitoring.keywords.en.high`

- **Location:** Append to the `en.high` list
- **Value:** `- "scramble"`
- **Rationale:** EN word-boundary matching means `\bscramble\b` matches "scramble" but NOT "scrambled" or "scrambles". **Decision point:** Add all three forms (`"scramble"`, `"scrambled"`, `"scrambles"`) OR add just `"scramble"` and accept that past tense won't match.
- **Recommendation:** Add all three: `"scramble"`, `"scrambled"`, `"scrambles"`
- **False positive risk:** Medium. "Scramble" has cooking meanings but word-boundary matching + military-focused sources + classifier make false alerts very unlikely.

#### A9. Replace `"дрони"` with `"дрон"` in `monitoring.keywords.uk.high`

- **Find:** `- "дрони"` in the `uk.high` list
- **Replace with:** `- "дрон"`
- **Rationale:** Same as A1 -- Ukrainian declension fix. `"дрон"` substring-matches: дрон, дрона, дроном, дронів, дрони.
- **False positive risk:** Low.

#### A10. Add `"безпілотник"` to `monitoring.keywords.uk.high`

- **Location:** Append to the `uk.high` list
- **Value:** `- "безпілотник"`
- **Rationale:** Common Ukrainian word for "drone/UAV" not covered by `"дрон"`. Substring matches all declensions.
- **False positive risk:** Low.

### Changes: Priority 2 (hybrid warfare and escalation indicators)

#### A11. Add `"sabotaż"` to `monitoring.keywords.pl.high`

- **Value:** `- "sabotaż"`
- **Rationale:** Covers sabotage. Substring matches sabotaż, sabotażu, sabotażem, sabotażowy. Czech arms factory arson was missed.
- **False positive risk:** Low.

#### A12. Add `"sabotage"` to `monitoring.keywords.en.high`

- **Value:** `- "sabotage"`
- **False positive risk:** Low-medium. Metaphorical usage ("sabotage negotiations") possible but classifier handles.

#### A13. Add `"GPS jamming"` to `monitoring.keywords.en.high`

- **Value:** `- "GPS jamming"`
- **Rationale:** Electronic warfare against Baltic states. 300+ incidents in Lithuania missed.
- **False positive risk:** Very low.

#### A14. Add `"cyberattack"` to `monitoring.keywords.en.high`

- **Value:** `- "cyberattack"`
- **Rationale:** Current keyword `"cyberattack on infrastructure"` requires full phrase. Standalone `"cyberattack"` has word-boundary matching, so it matches the singular form. **Note:** `\bcyberattack\b` will NOT match "cyberattacks" (plural). Also add `"cyberattacks"`.
- **Additional value:** `- "cyberattacks"`
- **False positive risk:** Low.

#### A15. Add `"bezzałogowc"` to `monitoring.keywords.pl.high`

- **Value:** `- "bezzałogowc"`
- **Rationale:** Polish for "unmanned" (vehicle/aircraft). Substring matches: bezzałogowiec, bezzałogowce, bezzałogowców, bezzałogowcem.
- **False positive risk:** Low. Technical military term.

#### A16. Add `"rakiet"` to `monitoring.keywords.pl.high`

- **Value:** `- "rakiet"`
- **Rationale:** Substring matches: rakieta, rakiety, rakietowy, rakietowe, rakietę. "Missiles over the Baltic Sea" article was missed.
- **False positive risk:** Low-medium. "Rakietka" (badminton racquet) contains "rakiet" and could match sports articles. But badminton articles are extremely unlikely to co-occur with military keywords in the same source feeds. Classifier would filter.

#### A17. Add `"крилат"` to `monitoring.keywords.uk.high`

- **Value:** `- "крилат"`
- **Rationale:** Matches cruise missiles (крилатих ракет, крилаті ракети). Ukrainian Air Force alert about cruise missile launches was missed.
- **False positive risk:** Very low. "Крилат" (winged/cruise) in Ukrainian news is almost exclusively military.

#### A18. Add `"drone strike"` to `monitoring.keywords.en.high`

- **Value:** `- "drone strike"`
- **Rationale:** Primorsk port attack articles used "strike" not "incursion."
- **False positive risk:** Low.

#### A19. Add `"Baltic states"` to `monitoring.keywords.en.high`

- **Value:** `- "Baltic states"`
- **Rationale:** Direct references to the monitored region. "Russia expands laws... alarming Baltic states" was missed.
- **False positive risk:** Medium. Could match tourism/economics articles. However, word-boundary matching requires the exact phrase, and the classifier would filter non-military articles. Accept the trade-off.

#### A20. Add `"война гібридна"` and `"wojna hybrydowa"` for hybrid warfare

- **PL value:** `- "wojna hybrydowa"` added to `pl.high`
- **Rationale:** Hybrid warfare is a core monitoring criterion per the audit skill. Estonian "Narva Republic" disinformation was missed.
- **False positive risk:** Low.

#### A21. Add `"пуски ракет"` to `monitoring.keywords.uk.high`

- **Value:** `- "пуски ракет"`
- **Rationale:** "Missile launches" -- covers Ukrainian Air Force alerts about Russian missile launches.
- **False positive risk:** Very low.

### Testing strategy for Workstream A

1. **Before deployment:** Run existing tests: `pytest tests/test_keyword_filter.py -v`
   - All existing tests must pass (they use their own fixture configs, NOT the production config, so config changes cannot break them)
2. **Manual validation:** Use `./run.sh --test-headline` locally with each missed article title from the audit to confirm the new keywords would match:
   - `./run.sh --test-headline "Dron spadł na terytorium Litwy"` -- should now match via "dron"
   - `./run.sh --test-headline "Polska poderwała myśliwce"` -- should now match via "poderwał"
   - `./run.sh --test-headline "Szahedy atakują w ciągu dnia"` -- should now match via "Szahed"
   - `./run.sh --test-headline "GPS jamming incidents continue in Lithuania"` -- should match via "GPS jamming"
   - (test each new keyword against at least one missed article title)
3. **Negative validation:** Test that non-military headlines still get filtered:
   - `./run.sh --test-headline "Turniej badmintona w Warszawie"` -- should NOT match despite "rakiet" in "rakietka" being possible (verify: does "turniej badmintona" contain "rakiet"? No -- "badmintona" does not. Only if the word "rakietka" appeared would it match.)
4. **Regression check:** Run `./run.sh --dry-run --once` locally with the new config to verify the pipeline completes without errors and the keyword filter stats look reasonable.

### Deployment for Workstream A

1. SSH to production: `ssh -p 2222 deploy@178.104.76.254`
2. Edit config: `sudo nano /etc/sentinel/config.yaml`
3. Apply all A1-A21 changes to the production config
4. Restart: `sudo systemctl restart sentinel`
5. Monitor first cycle: `sudo journalctl -u sentinel -f` -- verify no errors, check keyword filter count in logs
6. After 1-2 cycles: query DB to verify new keywords are catching articles: `sudo sqlite3 /var/lib/sentinel/sentinel.db "SELECT COUNT(*) FROM classifications WHERE classified_at > datetime('now', '-10 minutes')"`

---

## Workstream B: Classifier Prompt Amendments

### Scope
Modify the classifier prompt in Python code to fix 6 systematic classification errors. This is a code change requiring deployment.

### File to modify
`sentinel/classification/classifier.py` -- specifically `SYSTEM_PROMPT` (lines 14-33) and `USER_PROMPT_TEMPLATE` (lines 35-65)

### Changes

#### B1. Prevent Google News query contamination

**Where:** Add to `SYSTEM_PROMPT`, after the existing "IMPORTANT DISTINCTIONS" section (after line 30)

**What to add (conceptual -- implement as a new paragraph):**
A new paragraph that instructs the model:
- The "Source:" field in the article data is metadata identifying WHERE the article was found, NOT article content
- For Google News sources, the source_name contains the search query (e.g., "GoogleNews:drone incursion Poland") -- this query is NOT part of the article
- Classify ONLY based on the "Title:" and "Summary:" fields
- Do NOT infer that Poland or any other country is affected just because it appears in the source name

**Why it matters:** This is the single most dangerous classification error. The mezha.net article about a Ukraine attack was classified as urgency 9 attack on Poland because the classifier read "drone incursion Poland" from the source_name.

#### B2. Distinguish defensive activation from direct attack

**Where:** Add to `SYSTEM_PROMPT`, in the "IMPORTANT DISTINCTIONS" section

**What to add (conceptual):**
A new bullet point that instructs the model:
- A country scrambling jets or activating air defense as a PRECAUTIONARY measure in response to attacks on a NEIGHBORING country is urgency 5-6 (notable incident), NOT urgency 7-10
- Urgency 7+ requires evidence that the country itself was directly attacked or that its own territory/airspace was breached
- Example: "Poland scrambles jets after Russian attack on Ukraine" = urgency 5-6 (precautionary). "Russian missile enters Polish airspace" = urgency 8-9 (direct threat)

**Why it matters:** 4 articles about Poland scrambling jets were scored urgency 7-9, generating false SMS alerts.

#### B3. Disambiguate attack location from cultural association

**Where:** Add to `SYSTEM_PROMPT`, in the "IMPORTANT DISTINCTIONS" section

**What to add (conceptual):**
A new bullet point:
- An attack on cultural, historical, or diplomatic assets associated with country X but physically located in country Y is an attack on country Y, NOT country X
- Score `affected_countries` based on the PHYSICAL LOCATION of the attack
- Example: "Russian drones hit Polish heritage sites in Lviv" -- affected_countries = ["UA"] (Lviv is in Ukraine), NOT ["PL"]

**Why it matters:** 7 articles about Lviv drone attacks were classified with affected_countries=["PL"] because the articles mentioned "places important for Poland."

#### B4. Cap urgency for attacks on non-monitored countries

**Where:** Modify the urgency scale in `USER_PROMPT_TEMPLATE` (lines 57-64)

**What to change (conceptual):**
After the existing urgency scale, add a clarifying paragraph:
- Urgency 9-10 is EXCLUSIVELY for attacks directly targeting PL, LT, LV, or EE territory
- Attacks on Ukraine, Moldova, or other non-monitored countries should not exceed urgency 4, regardless of severity, UNLESS they directly threaten monitored country territory (e.g., missile debris entering Poland, airspace violation over Lithuania)
- An attack on Ukraine near the Polish border is urgency 3-4 (important context) not 7-8

**Why it matters:** Multiple Lviv drone attacks were scored urgency 8-9 even when Haiku correctly identified affected_countries as ["UA"].

#### B5. Handle ambiguous/missing geographic attribution

**Where:** Add to `SYSTEM_PROMPT`, after the "IMPORTANT DISTINCTIONS" section

**What to add (conceptual):**
A new paragraph:
- If the article headline and summary do NOT explicitly state which country was attacked, do NOT assume it was a monitored country
- Assign urgency 2-3 and confidence below 0.5 for geographically ambiguous articles
- Example: "Drones hit a train at night -- casualties reported" with no country named = urgency 2, confidence 0.3

**Why it matters:** The wGospodarce clickbait headline "Atak w środku nocy. Drony uderzyły w pociąg" was classified as urgency 9 attack on Poland with no geographic evidence.

#### B6. Restrict affected_countries to explicitly mentioned countries

**Where:** Add to the JSON format instructions in `USER_PROMPT_TEMPLATE` (near line 50)

**What to add (conceptual):**
In the description of `affected_countries`:
- Only include countries EXPLICITLY mentioned in the article title or summary as being affected
- Do NOT infer affected countries from the monitoring scope (PL/LT/LV/EE)
- If no monitored country is explicitly mentioned, use an empty array `[]`

**Why it matters:** The Newsweek article about NATO deploying jets was classified with all four monitored countries as affected when only Poland was relevant.

### Testing strategy for Workstream B

1. **Unit tests:** Run `pytest tests/test_classifier.py -v` -- all existing tests must pass. These tests mock the Anthropic API, so prompt changes don't affect them unless the prompt format itself is broken.

2. **Integration validation with real API calls:** Use `--test-headline` with the problematic headlines from the audit. **These cost real API tokens** (Haiku is cheap, ~$0.001 per call):
   - `./run.sh --test-headline "Russian forces launched a combined drone and cruise missile strike, air raids declared across regions"` -- should NOT produce affected_countries=["PL"], urgency should be 1-2
   - `./run.sh --test-headline "Poland Mobilizes Fighter Jets and Air Defense in Response to Russian Missile Strike"` -- urgency should be 5-6, NOT 9
   - `./run.sh --test-headline "Drony uderzyły w serce Lwowa. Zagrożone bezcenne polskie dokumenty"` -- affected_countries should be ["UA"], NOT ["PL"]
   - `./run.sh --test-headline "Atak w środku nocy. Drony uderzyły w pociąg – są ofiary"` -- urgency should be 2-3 with low confidence
   - `./run.sh --test-headline "NATO Deploys Fighter Jets, Helicopters Over Russian Shahed Drone Attacks"` -- affected_countries should NOT include all four countries

3. **Positive validation (must NOT break real threats):** Test that actual attacks still score high:
   - `./run.sh --test-headline "Rosyjskie rakiety uderzyły w terytorium Polski"` -- should still be urgency 9-10
   - `./run.sh --test-headline "Russian troops cross Polish border in armed invasion"` -- should still be urgency 10
   - `./run.sh --test-headline "Dron naruszył polską przestrzeń powietrzną"` -- should be urgency 6-8

4. **Prompt length check:** After adding all B1-B6 text, verify total prompt stays well under the Haiku context window (200k tokens). Current prompt is ~600 words; additions are ~300 words. No risk.

### Deployment for Workstream B

1. Commit the code change to git locally
2. Deploy code to production via scp:
   ```
   scp -P 2222 sentinel/classification/classifier.py deploy@178.104.76.254:/home/deploy/sentinel/sentinel/classification/classifier.py
   ```
3. Restart: `sudo systemctl restart sentinel`
4. Monitor first classification cycle for errors

### Risk assessment
- **Breaking risk:** Low. The prompt changes are additive (new instructions, no removal of existing ones). The JSON output format is unchanged. The parsing code is unchanged.
- **Behavioral risk:** Medium. New prompt instructions could cause the model to be overly cautious and under-score genuine threats. This is why positive validation (step 3 above) is essential.
- **Rollback:** Revert the single file `classifier.py` to previous version via git.

---

## Workstream C: Telegram Fetcher Hardening

### Scope
Add per-channel error handling, validation, and logging to the Telegram fetcher so that silent channel failures become visible.

### File to modify
`sentinel/fetchers/telegram.py`

### Problem diagnosis
The fetcher uses Telethon's `events.NewMessage(chats=channel_ids)` which resolves channel usernames to IDs at registration time. If a channel fails to resolve (not in entity cache, restricted, username changed), it is silently dropped. No error is logged. The startup log only reports the total count of channels, not which ones succeeded.

### Changes

#### C1. Add per-channel resolution validation at startup

**Where:** In the `start()` method, after client startup but before event handler registration

**What to do:**
- Iterate through each configured channel individually
- For each, attempt `client.get_input_entity(channel_id)` or `client.get_entity(channel_id)` in a try/except
- Log SUCCESS at INFO level: "Telegram: resolved channel {name} ({channel_id})"
- Log FAILURE at ERROR level: "Telegram: FAILED to resolve channel {name} ({channel_id}): {error}"
- Collect only the successfully resolved channel IDs for the event handler
- Log a summary: "Telegram: monitoring {N}/{total} channels ({failed_names} failed)"

**Why:** Makes silent failures visible in logs. Operators can see immediately which channels work.

#### C2. Add periodic channel health reporting

**Where:** In the `fetch()` method or a separate health method

**What to do:**
- Track message count per channel since last report
- Every N fetch cycles (e.g., every 10), log per-channel stats:
  "Telegram channel stats: @kpszsu=5, @GeneralStaffZSU=0, @DeepStateUA=0, @nexta_live=0"
- Zero-article channels after extended period get a WARNING log

**Why:** Even if a channel resolves successfully at startup, it might stop producing messages later. Per-channel tracking catches this.

#### C3. Add initial history fetch for newly resolved channels

**Where:** In the `start()` method, after successful channel resolution

**What to do:**
- For each resolved channel, fetch the last N messages (e.g., 10) via `client.get_messages(channel, limit=10)`
- Convert to Articles and add to the buffer
- This provides immediate articles on startup rather than waiting for new messages

**Why:** The current passive/event-driven approach means a fresh restart gets zero historical articles. This is especially problematic after service restarts.

### Testing strategy for Workstream C

1. Run `pytest tests/test_telegram.py -v` -- all existing tests must pass
2. Test locally with `./run.sh --dry-run --once` to verify Telegram fetcher starts without errors
3. After deployment, check logs: `sudo journalctl -u sentinel | grep -i telegram` -- verify per-channel resolution messages appear

### Deployment
Same as Workstream B -- scp the modified file + restart.

### Risk assessment
- **Breaking risk:** Low. Changes are additive (new logging, new validation). The event handler mechanism is unchanged.
- **C3 (history fetch) risk:** Medium. `get_messages()` could trigger rate limits or return unexpected data. Implement with a try/except that logs and continues if history fetch fails.

---

## Workstream D: GDELT Diagnostics

### Scope
Investigation only -- no code changes until root cause is identified.

### Diagnostic steps (run on production server)

1. **Check recent GDELT log entries:**
   ```
   sudo journalctl -u sentinel | grep -i gdelt | tail -30
   ```

2. **Check if GDELT ever produced articles:**
   ```
   sudo sqlite3 /var/lib/sentinel/sentinel.db "SELECT COUNT(*), MIN(fetched_at), MAX(fetched_at) FROM articles WHERE source_type='gdelt'"
   ```

3. **Check current GDELT config:**
   Verify `sources.gdelt.enabled: true` and `sources.gdelt.themes` is non-empty in `/etc/sentinel/config.yaml`

4. **Test GDELT API directly from server:**
   ```
   curl "https://api.gdeltproject.org/api/v2/doc/doc?query=(theme:ARMEDCONFLICT OR theme:TAX_FNCACT_MILITARY) sourcecountry:(PL OR LH OR LG OR EN)&mode=ArtList&maxrecords=10&format=json&TIMESPAN=60min&sort=DateDesc"
   ```

5. **Check if deduplication is consuming all GDELT articles:**
   If step 2 shows GDELT has historical articles, the articles may be consistently deduplicated against RSS/Google News articles (same stories, same URLs).

### Possible outcomes
- **Config issue:** themes/countries not set correctly → fix config
- **API returns empty:** GDELT query too narrow → adjust themes/CAMEO codes
- **Deduplication consuming all:** Expected behavior if GDELT articles duplicate RSS sources → no action needed, or adjust dedup thresholds
- **Network/rate limit:** Server can't reach GDELT API → firewall or proxy issue

---

## Workstream E: Missed-Article Investigations

### Scope
Investigate the two audit corrections noted at the top of this document.

### E1. Investigate "Alarm na Litwie" article

**Query on production:**
```sql
SELECT id, source_name, title, summary, language, fetched_at
FROM articles WHERE title LIKE '%Alarm na Litwie%';
```

Check if:
- The article exists in DB (was it fetched at all?)
- The summary contains any EXCLUDE keyword
- There's a duplicate from the same cycle that DID get classified

### E2. Investigate "Samoloty wrociły do baz" article

**Query on production:**
```sql
SELECT id, title, summary, language FROM articles
WHERE title LIKE '%Samoloty wr%';
```

Check if the summary field was populated at fetch time. If `summary` was empty, the keyword "naruszenie przestrzeni powietrznej" wouldn't have been in the searchable text.

---

## Testing Matrix (Pre-Deployment Validation)

| Test | Command | Expected | Validates |
|------|---------|----------|-----------|
| Existing keyword tests pass | `pytest tests/test_keyword_filter.py -v` | All pass | A (no regression) |
| Existing classifier tests pass | `pytest tests/test_classifier.py -v` | All pass | B (no regression) |
| Existing telegram tests pass | `pytest tests/test_telegram.py -v` | All pass | C (no regression) |
| Full test suite passes | `pytest tests/ -v` | All pass | All (no regression) |
| Lithuania drone headline matches | `./run.sh --test-headline "Dron spadł na terytorium Litwy"` | keyword match on "dron" | A1 |
| Poland scramble headline matches | `./run.sh --test-headline "Polska poderwała myśliwce"` | keyword match on "poderwał" | A2 |
| Shahed Polish headline matches | `./run.sh --test-headline "Szahedy atakują w ciągu dnia"` | keyword match on "Szahed" | A5 |
| UAV headline matches | `./run.sh --test-headline "Ukraine-launched UAV crashes on Lithuanian territory"` | keyword match on "UAV" | A7 |
| GPS jamming headline matches | `./run.sh --test-headline "GPS jamming incidents reported by pilots in Lithuania"` | keyword match on "GPS jamming" | A13 |
| Ukraine attack NOT scored as Poland | `./run.sh --test-headline "Russian forces launched a combined drone and cruise missile strike on Ukraine"` | urgency 1-3, affected_countries != ["PL"] | B1, B4 |
| Poland scramble scored correctly | `./run.sh --test-headline "Poland Mobilizes Fighter Jets in Response to Russian Missile Strike on Ukraine"` | urgency 5-6 | B2 |
| Lviv heritage scored correctly | `./run.sh --test-headline "Drony uderzyły w serce Lwowa. Zagrożone polskie dokumenty"` | affected_countries = ["UA"] | B3 |
| Ambiguous headline scored low | `./run.sh --test-headline "Atak w środku nocy. Drony uderzyły w pociąg"` | urgency 2-3, confidence < 0.5 | B5 |
| Real invasion still scores 10 | `./run.sh --test-headline "Russian troops cross Polish border in armed invasion"` | urgency 10, affected_countries = ["PL"] | B (no over-correction) |
| Real missile strike on PL still works | `./run.sh --test-headline "Rosyjskie rakiety uderzyły w terytorium Polski"` | urgency 9-10 | B (no over-correction) |

---

## Deployment Sequence

### Phase 1: Code deployment (Workstreams B + C)

1. Make code changes locally (classifier.py, telegram.py)
2. Run full test suite: `pytest tests/ -v`
3. Run `--test-headline` validation matrix (API-calling tests)
4. Commit to git
5. Deploy to production via scp
6. Restart service
7. Monitor for 2-3 cycles via `journalctl -u sentinel -f`
8. Verify classifier output on first batch of articles -- check DB for sanity

### Phase 2: Config deployment (Workstream A)

1. Update `config/config.example.yaml` locally with all A1-A21 changes
2. Run `./run.sh --dry-run --once` locally with updated config
3. Verify keyword filter stats look reasonable (not flooding classifier with false positives)
4. Commit to git
5. SSH to production, edit `/etc/sentinel/config.yaml` with same changes
6. Restart service
7. Monitor first 2-3 cycles:
   - Keyword filter pass rate should increase from ~4.4% to ~6-8%
   - Classifier should handle the additional volume without issues
   - No new false critical/high alerts from the new keywords

### Phase 3: Diagnostics (Workstreams D + E)

1. Run GDELT diagnostic queries on production
2. Run missed-article investigation queries
3. Based on findings, create follow-up tickets if code changes are needed

---

## Rollback Plan

| Scenario | Action |
|----------|--------|
| Classifier prompt causes false negatives (real threats scored too low) | Revert `classifier.py` from git, scp to production, restart |
| New keywords cause excessive false positives | SSH to production, edit `/etc/sentinel/config.yaml` to remove problematic keywords, restart |
| Telegram changes cause crash | Revert `telegram.py` from git, scp to production, restart |
| Everything broken | `git checkout HEAD~1`, scp entire codebase, restart |

**Rollback time:** < 5 minutes for any single change. The service restarts in seconds.

---

## Out of Scope (Deferred)

The following were mentioned in the audit but are deferred:

1. **Adding Russian (`ru`) keywords for "беспілотник"** -- Russian keyword list already has "беспилотник" (Russian spelling). Ukrainian form is different. No change needed for RU.
2. **Adding country names as keywords (e.g., "Białoruś", "NATO")** -- Too broad, would flood the classifier with irrelevant articles. Deferred pending false positive analysis.
3. **Exclude keyword refinements** -- No exclude keyword changes are proposed. The current exclude list is working correctly.
4. **New test fixture file creation** -- The `tests/fixtures/test_headlines.yaml` file is empty. Creating a comprehensive fixture set based on the audit's missed articles would be valuable but is a separate task.
5. **GoogleNews UK query reformulation** -- The query `"військовий напад Польща"` produced zero results. May need reformulation but this is a low-priority investigation.
