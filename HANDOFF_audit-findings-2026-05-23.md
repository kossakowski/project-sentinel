# Handoff — Audit Findings 2026-05-23

**Status:** Open. None of the items below are addressed in code yet.
**Source:** `/sentinel-audit` run on 2026-05-23 covering window 2026-05-16 → 2026-05-23 (7 days). Full audit report at [`data/audit-reports/audit-2026-05-23.md`](data/audit-reports/audit-2026-05-23.md).
**Scope:** These findings are **independent of `SPEC_ALERT_GROUPING.md` Phase 3** (which is complete and merged on `alert-grouping-spec`). They surfaced as a side-effect of running the audit and are unrelated to the event-grouping work.
**Triage order:** Issue #1 (nuclear keyword gap) is **highest priority** — it represents a class of missed real-world threats. Issues #2 and #3 are quality/policy concerns, not active threat misses.

---

## Issue #1 — Keyword filter gap: nuclear vocabulary + Kaliningrad

### Severity
**HIGH.** The system protects against military threats to PL/LT/LV/EE; Russia transferring nuclear warheads to Belarus (a Polish/Lithuanian/Latvian neighbor) is exactly the archetypal escalation indicator the system exists to catch. The audit found ~30+ such articles in the 7-day window with zero coverage.

### Symptom

During 2026-05-21 → 2026-05-22, Russia conducted joint Russia-Belarus nuclear drills, transferring nuclear warheads/munitions to Belarus, with Putin issuing "last resort" nuclear weapon statements. Concurrent NATO warning of "devastating response". The English-language news cluster produced ~30+ articles across MSN, The Independent, Al Jazeera, Foreign Policy Journal, The Times of India, EurAsian Times, Mirror, Bankingnews, AAP, AOL, Polish-language Polskie Radio 24, Onet Wiadomości, TASS, etc.

**The keyword filter caught zero of them.** None were classified. None contributed to any event. None triggered any alert.

### Root cause

`config/config.yaml` (production: `/etc/sentinel/config.yaml`) has:

```yaml
monitoring:
  keywords:
    en:
      critical:
      - nuclear strike
      - nuclear drill
      - nuclear drills
      high:
      - nuclear forces
      - Iskander
      - Kinzhal
      - Kalibr
      # ... no "nuclear munitions", "nuclear warheads", "nuclear weapons", "war games", "nuclear arsenal"
    pl:
      critical:
      - uderzenie rakietowe
      - bombardowanie
      # ... no nuclear-specific bigrams
      high:
      - siły nuklearne
      # ... no "głowice jądrowe", "amunicja jądrowa", "ćwiczenia jądrowe", "Kaliningrad"
  exclude_keywords:
    en:
    - exercise
    - drill
    pl:
    - ćwiczenia
    - manewry
```

Three mechanisms combine to produce the miss:

1. **EN: CRITICAL `nuclear drill`/`nuclear drills` is too narrow.** It only matches that exact word-boundary bigram. Headlines like "Russia delivers nuclear munitions to Belarus during drills" or "Russia launches nuclear war games on Europe's doorstep" contain `drills` and `nuclear` but not the bigram `nuclear drill[s]` together — so the CRITICAL keyword doesn't fire. Then no HIGH keyword fires either (because `nuclear munitions`, `nuclear warheads`, `nuclear weapons`, `war games` aren't listed). Result: the article doesn't match any positive keyword → filtered out for absence of any trigger, not because of the exclude.

2. **PL: `ćwiczenia jądrowe` is excluded by `ćwiczenia`.** Polish uses substring matching, so `ćwiczenia` in the EXCLUDE list matches `ćwiczenia jądrowe` and filters it out. The fix in Polish is to add the bigram `ćwiczenia jądrowe` to CRITICAL — CRITICAL keywords unconditionally override EXCLUDE per the skill's documented logic.

3. **Kaliningrad — completely missing.** `Kaliningrad` (EN), `Kaliningrad`/`Obwód Kaliningradzki` (PL), `Калининград` (RU), `Калінінград` (UK) appear in zero keyword list. The audit found two articles missed because of this: LRT Lithuania publishing the Lithuanian FM publicly stating "NATO has means to neutralise Kaliningrad air defences" (2026-05-22), followed by the PM publicly disciplining the FM for it (2026-05-21). Both went unclassified.

### Fix

Edit **two locations**: `config/config.yaml` (local, if used) AND the production config at `/etc/sentinel/config.yaml` on the VPS (see [docs/server-runbook.md](docs/server-runbook.md) for SSH access — production server policy requires user permission before modifying server files, so confirm with the user before deploying the config change).

Add the following keys:

```yaml
monitoring:
  keywords:
    en:
      critical:
        # ...existing keys...
        - nuclear munitions
        - nuclear warheads
        - nuclear weapons to Belarus
        - nuclear arsenal
        - nuclear war games
      high:
        # ...existing keys...
        - nuclear missiles
        - nuclear weapon
        - Kaliningrad
    pl:
      critical:
        # ...existing keys...
        - głowice jądrowe
        - amunicja jądrowa
        - broń jądrowa do Białorusi
        - ćwiczenia jądrowe       # CRITICAL placement is intentional — overrides the `ćwiczenia` EXCLUDE
        - manewry jądrowe         # ditto for `manewry`
        - nuklearny scenariusz
      high:
        # ...existing keys...
        - Kaliningrad
        - Obwód Kaliningradzki
    ru:
      critical:
        # ...existing keys...
        - ядерные боеголовки
        - ядерные учения          # CRITICAL placement overrides any drill-equivalent in RU exclude (none currently)
      high:
        # ...existing keys...
        - Калининград
    uk:
      high:
        # ...existing keys...
        - Калінінград
```

**False-positive risk:** Low. These are highly specific bigrams. The only term with meaningful noise potential is bare `Kaliningrad` (some tourism/sports articles mention it) but the volume is bounded and the downstream classifier filters non-military uses.

### Acceptance test

After applying:

```bash
# Verify keyword config loads cleanly
.venv/bin/python -c "from sentinel.config import load_config; cfg = load_config('config/config.yaml'); print(len(cfg.monitoring.keywords.en.critical), 'en critical keywords')"

# Run the full test suite to confirm no regressions
.venv/bin/pytest tests/ -v

# Spot-check: simulate the missed articles against the live keyword filter
.venv/bin/python -c "
from sentinel.config import load_config
from sentinel.classification.keyword_filter import KeywordFilter
from sentinel.models import Article
cfg = load_config('config/config.yaml')
kf = KeywordFilter(cfg)
test_titles = [
    'Russia moves nuclear munitions to Belarus amid major drills',
    'Russia launches nuclear war games on Europe\\'s doorstep',
    'Lithuanian FM says NATO has means to neutralise Kaliningrad air defences',
    'Rosja i Białoruś kończą ćwiczenia jądrowe',
]
for t in test_titles:
    article = Article(id='test', source_name='test', source_url='', source_type='rss', title=t, summary='', language='en', published_at='2026-05-22T00:00:00+00:00', fetched_at='2026-05-22T00:00:00+00:00', url_hash='', title_normalized='', raw_metadata='{}')
    matched = kf.matches(article)
    print(f'{matched}: {t}')
"
# Expected: every line prints 'True: ...'
```

### Manual validation (optional, for the deployer)

After deploying the config change to production and waiting one full slow-lane cycle (~15 min), re-run `/sentinel-audit` over a fresh 24h window covering at least one Russia-Belarus / Kaliningrad news cluster and confirm the new keyword adds produce classifications. (Note: the historic May 21-22 cluster will NOT backfill — keyword changes only apply to articles fetched AFTER the config change.)

### Evidence files

- Audit report: [`data/audit-reports/audit-2026-05-23.md`](data/audit-reports/audit-2026-05-23.md) sections "Missed Articles" and "Recommendations" (#1, #2, #3) for the full sampled list and YAML keys.
- Live keyword config: `ssh -p 2222 deploy@178.104.76.254 'sudo cat /etc/sentinel/config.yaml'` (read-only command, safe to run).
- Reproduce the missed-article query directly:
  ```bash
  SINCE="2026-05-16T00:00:00+00:00"
  ssh -p 2222 deploy@178.104.76.254 "sudo sqlite3 /var/lib/sentinel/sentinel.db \"
  SELECT title FROM articles a LEFT JOIN classifications c ON a.id = c.article_id
  WHERE a.fetched_at > '$SINCE' AND c.id IS NULL
    AND (a.title LIKE '%nuclear%' OR a.title LIKE '%ядерн%' OR a.title LIKE '%Kaliningrad%')
  ORDER BY a.fetched_at DESC LIMIT 30;\""
  ```

---

## Issue #2 — Single-source urgency-9 events (corroboration policy concern)

### Severity
**MEDIUM.** Not an active threat miss, but a misfire risk. The current policy allows a single English-language source to drive an urgency-9 SMS alert. If the source is speculative, sensational, or hallucinated, the alert fires anyway.

### Symptom

Three urgency-9 events on 2026-05-20 → 2026-05-22 in the LT cluster, each based on **exactly one** source:

| Event ID | Source | Title |
|---|---|---|
| `66243e6b` | GoogleNews:invasion Baltic states / Meyka | "Lithuania May 23: Drone Airspace Breach Triggers NATO Alert" |
| `d9585cf9` | GoogleNews:Russia attack NATO / The Times of India | "NATO Nation In Lockdown After Drone Strike; MPs, Ministers, Residents In Bomb Shelters" |
| `7c7ab772` | GoogleNews:Russia attack NATO / The Telegraph | "President bundled into bunker as drone shuts down Lithuania's capital" |

The live config has `classification.corroboration_required = 1` (per `CLAUDE.md`), meaning even single-source urgency-9 events qualify for SMS. The corroborator's policy boundary between SMS and phone-call is `corroboration_required = 2` for phone calls — but SMS still fires on `1`.

Two of three above have `alert_status = retry_pending`, meaning Twilio dispatch was attempted and is being retried — these were live alerts to the user.

The Times of India and The Telegraph are reputable, but English-language secondary coverage of a Lithuania incident with no Lithuanian-language primary source is suspicious. The "Meyka" source (66243e6b) is even less established. None of these stories was corroborated by Lithuanian primary sources (LRT, Delfi, LSM-equivalent for LT).

### Root cause analysis (one possible explanation, needs verification)

The corroborator's compatibility-table grouping requires (in pseudocode) `(same event_type) AND (same affected_country) AND (summary_similarity > threshold) AND (within window) AND (independent sources)`. For single-source events, no corroboration count > 1 is achievable until a second source publishes. The classifier may have set `urgency_score = 9` based on the dramatic language in the source ("MPs in bomb shelters", "president in bunker") rather than on confirmed facts.

A speculative or hallucinated single-source urgency-9 article will currently trigger an SMS without any corroboration — exactly the false-positive vector this system needs to guard against.

### Suggested fix (proposal — confirm scope with user)

Add a **per-urgency corroboration threshold** to `classification` config, so urgency 9-10 requires ≥2 independent sources before any alert dispatches (vs the current global `corroboration_required = 1`):

```yaml
classification:
  corroboration_required: 1                # existing — applies to urgency 5-8
  corroboration_required_urgency_9_10: 2   # new — applies to urgency 9-10 (highest stakes)
```

Code change in `sentinel/classification/state_machine.py` (around the SMS/phone-call dispatch decision): switch on `event.urgency_score >= 9` to apply the stricter threshold.

**Trade-off:** This delays real urgency-9 alerts until a second source corroborates (could be 15-360 min depending on source mix). For an actual ongoing crisis, that delay matters. For a speculative single-source story, the delay is the protection. The user (per memory: this is a personal-escape trigger for fleeing Poland on urgency 9-10) should make the policy call.

### Acceptance test

```bash
# Confirm new config key loads
.venv/bin/python -c "from sentinel.config import load_config; cfg = load_config('config/config.example.yaml'); print('urgency_9_10:', getattr(cfg.classification, 'corroboration_required_urgency_9_10', None))"

# Unit test: synthesize a single-source urgency-9 event; assert no SMS dispatched
.venv/bin/pytest tests/test_state_machine.py -v -k "urgency_9_requires_two_sources"
```

(New test needs writing in `tests/test_state_machine.py`.)

### Evidence files

- Audit report: [`data/audit-reports/audit-2026-05-23.md`](data/audit-reports/audit-2026-05-23.md) section "Tier 1 — Full event blocks (urgency 8-10, 8 events)" and the "Tier-1 classification observations" subsection.

---

## Issue #3 — Standalone urgency-5 cyber_attack never grouped into an event

### Severity
**LOW-MEDIUM.** Real classification + correct urgency, but no event row created. The user therefore did not receive an alert for what the classifier judged a credible Belarusian APT campaign targeting Poland.

### Symptom

One article in the 7-day window was classified at `urgency_score = 5`, `event_type = cyber_attack`, `is_military_event = 1`, `confidence = 0.85`, `affected_countries` implying PL, but it appears in the **Standalone classified articles** section of the 2026-05-23 audit — meaning the corroborator did not create an event row for it:

- **[GoogleNews:atak wojskowy Polska] "Białoruscy hakerzy uderzają w Polskę. Nowe ataki grupy UNC1151"** — published 2026-05-20T13:07Z, CyberDefence24.

UNC1151 is a known Belarusian state-aligned APT (Ghostwriter campaign). The article passed the keyword filter and was classified at urgency 5 (corroborator's `_MIN_EVENT_URGENCY = 5` threshold met) with high confidence, but no event row exists. Per the corroborator's own threshold rule, this should have either:
- Created a standalone event row with `source_count = 1`, OR
- Joined an existing matching event

Neither happened. The article is orphaned.

### Root cause hypotheses (need verification)

Two candidates, requires reading `sentinel/classification/corroborator.py:_find_matching_event`:

1. **Event-type compatibility table excludes singleton `cyber_attack`.** Some event types may have stricter creation rules (e.g., requires ≥2 sources even at urgency 5).
2. **`_MIN_EVENT_URGENCY` check is `> 5` not `>= 5`.** An off-by-one would explain a urgency-5 article being excluded from event creation. Check the literal comparison in `corroborator.py`.

### Suggested fix

1. Read `sentinel/classification/corroborator.py` and identify the exact branch that filtered this classification out of event creation.
2. Either:
   - Fix the off-by-one if present
   - Or document the intentional exclusion in `sentinel/classification/corroborator.py` and `docs/pipeline.md`

### Acceptance test

```bash
# Inspect corroborator threshold
.venv/bin/grep -n "_MIN_EVENT_URGENCY" sentinel/classification/corroborator.py

# Synthesize a single-source urgency-5 cyber_attack classification and assert event creation
.venv/bin/pytest tests/test_corroborator.py -v -k "singleton_cyber_attack_creates_event"
```

(New test needs writing in `tests/test_corroborator.py`.)

### Evidence files

- Audit report: [`data/audit-reports/audit-2026-05-23.md`](data/audit-reports/audit-2026-05-23.md) section "Standalone classified articles" and Recommendation #5.
- DB query to reproduce:
  ```bash
  ssh -p 2222 deploy@178.104.76.254 "sudo sqlite3 -header /var/lib/sentinel/sentinel.db \"
  SELECT c.* FROM classifications c JOIN articles a ON c.article_id = a.id
  WHERE c.urgency_score >= 5 AND c.event_type = 'cyber_attack' AND c.classified_at > '2026-05-16T00:00:00+00:00';\""
  ```

---

## Cross-issue notes for the receiving agent

- **Read CLAUDE.md first** ([`CLAUDE.md`](CLAUDE.md)) — it documents the dual-lane scheduler, the `_MIN_EVENT_URGENCY = 5` corroborator constant (which Phase 1 deliberately left as a local constant per `SPEC_ALERT_GROUPING.md:23`), the "no quiet hours" rule, the "alerts in Polish" rule, and the production server policy (NEVER modify production server files without explicit user permission).
- **Read SPEC_ALERT_GROUPING.md** ([`SPEC_ALERT_GROUPING.md`](SPEC_ALERT_GROUPING.md)) — for context on the corroboration window and threshold tunables Phase 1 already exposed via `config.classification`. Issue #2's per-urgency threshold proposal is an additive extension to the same config block.
- **The `alert-grouping-spec` branch is in flight.** All three issues above are **independent of that branch's scope** — they came from the runtime audit, not from Phase 1/2/3 work. Address them on a separate branch (suggested name: `keyword-gap-nuclear-kaliningrad` for Issue #1; separate branches for #2 and #3 if they're tackled separately).
- **Production deploy gate.** Issue #1 needs a production config change AND a code change is NOT required (it's a YAML edit on the server's `/etc/sentinel/config.yaml`). Issue #2 needs both a code change (state_machine.py + config) and a deploy. Issue #3 needs a code change (corroborator.py). All three should go through the project's standard `/deploy` skill — do NOT modify server files manually.
- **Tests must stay green.** Current state: 305/305 passing as of 2026-05-23. Add new tests for #2 and #3 to extend coverage without breaking existing ones.
- **No backfill.** Keyword changes (#1) only apply to articles fetched AFTER the change goes live. The historic May 21-22 missed cluster will NOT be reprocessed. This is consistent with the spec's existing "non-goal: backfilling fragmented events" position.
