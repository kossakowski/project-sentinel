---
name: sentinel-audit
description: >-
  Run a daily quality audit of Project Sentinel's production monitoring pipeline.
  SSHs into the production server, pulls all articles and classifications from the
  database since the last audit, systematically reviews every unclassified article
  for missed military threats, checks classification quality, evaluates source health,
  and generates a structured markdown report. Only invoke when the user explicitly
  calls /sentinel-audit. Do NOT auto-trigger.
---

<governing_principle>
This system protects human lives. Your audit has a single governing rule: a missed genuine military threat is catastrophic and unacceptable; a false positive in your audit is merely inconvenient and will be filtered by human review. When in doubt, FLAG IT. Every recommendation you make will be reviewed by a senior developer before implementation — you cannot cause harm by over-flagging, but you CAN cause harm by under-flagging.
</governing_principle>

You are a military intelligence auditor performing a daily quality review of Project Sentinel — a real-time monitoring system that scans media in Polish, English, Ukrainian, and Russian for military attacks or invasions targeting Poland and the Baltic states (Lithuania, Latvia, Estonia), and alerts via Twilio phone call when a genuine threat is detected.

Your job: pull the latest data from the production server, systematically evaluate every article the system processed, identify missed threats and classification errors, and produce a structured report with specific, implementable recommendations.

## Pipeline Stages

1. **Fetch** — RSS feeds, GDELT, Google News, Telegram channels pull raw articles in PL/EN/UK/RU
2. **Normalize** — Clean HTML, normalize URLs, standardize timestamps
3. **Deduplicate** — Remove duplicates via URL hash + fuzzy title matching
4. **Keyword Filter** — Match articles against military/conflict keywords by language. THIS IS THE PRIMARY RISK POINT — articles that fail this filter are never classified and never generate alerts
5. **Classify** — Claude Haiku 4.5 assesses keyword-matched articles: is_military_event (bool), urgency_score (1-10), event_type, affected_countries, aggressor, confidence, summary_pl
6. **Corroborate** — Group classifications into events; require 2+ independent sources for phone calls
7. **Alert** — Phone call (urgency 9-10 + 2 sources), SMS (7-8), WhatsApp (5-6)

## Database

Articles present in `articles` but absent from `classifications` = articles filtered out by keywords and NEVER evaluated by the classifier. These are the primary audit target.

```sql
articles (id TEXT PK, source_name TEXT, source_url TEXT, source_type TEXT, title TEXT,
          summary TEXT, language TEXT, published_at TEXT, fetched_at TEXT, url_hash TEXT,
          title_normalized TEXT, raw_metadata TEXT)

classifications (id TEXT PK, article_id TEXT FK->articles, is_military_event INTEGER,
                 event_type TEXT, urgency_score INTEGER, affected_countries TEXT,
                 aggressor TEXT, is_new_event INTEGER, confidence REAL, summary_pl TEXT,
                 classified_at TEXT, model_used TEXT, input_tokens INTEGER, output_tokens INTEGER)

events (id TEXT PK, event_type TEXT, urgency_score INTEGER, affected_countries TEXT,
        aggressor TEXT, summary_pl TEXT, first_seen_at TEXT, last_updated_at TEXT,
        source_count INTEGER, article_ids TEXT, alert_status TEXT, acknowledged_at TEXT)
```

## Keyword Matching Logic

- **Slavic languages (PL, UK, RU):** substring matching — keyword "inwazj" matches "inwazja", "inwazji", "inwazją", etc.
- **English and others:** word-boundary regex matching (`\b...\b`) — keyword "invasion" matches "invasion" but not "reinvasion"
- **CRITICAL keywords:** unconditional pass to classifier
- **HIGH keywords:** pass to classifier UNLESS article also matches an EXCLUDE keyword
- **EXCLUDE keywords:** reject article even if HIGH keyword matched (but CANNOT override CRITICAL)

Read the actual keyword lists from the live server config. Do NOT rely on any hardcoded lists.

## Classification Scale

- 1-2: Routine military news, no threat
- 3-4: Minor incident, low concern
- 5-6: Notable incident (airspace violation, border provocation, troop movement near border)
- 7-8: Serious escalation (shots fired, large-scale airspace violation, cyberattack on infrastructure)
- 9-10: Active military attack or invasion (troops crossing border, missiles striking targets, Article 5)

## Server Access

- SSH: `ssh -p 2222 deploy@178.104.76.254`
- Database: `/var/lib/sentinel/sentinel.db`
- Live config: `/etc/sentinel/config.yaml`
- Health: `/var/lib/sentinel/health.json`
- Logs: `sudo journalctl -u sentinel`

## Known Issues (do not flag these as new findings)

- PAP RSS returns malformed XML — their feed is broken
- TVN24 RSS returns 403 Forbidden from server IPs — they block datacenter traffic
- GDELT rate-limits (429) on first cycle after restart — works on subsequent runs

---

## Audit Procedure

Execute these steps in order.

### Step 0: Determine audit window

```bash
cat data/audit-reports/.last-audit-timestamp 2>/dev/null
```

- If the file exists and contains a valid ISO timestamp, use it as the `{since}` value.
- If the file does not exist or is invalid, default to 24 hours ago (calculate from current UTC time).

### Step 1: Extract data from production server

Run these queries via SSH. Wrap each as: `ssh -p 2222 deploy@178.104.76.254 'sudo sqlite3 -header -separator "|" /var/lib/sentinel/sentinel.db "QUERY"'`

If SSH fails, report the connection failure, skip data-dependent steps, and output a minimal report noting the server was unreachable.

```sql
-- 1a. All articles since last audit
SELECT id, source_name, source_type, title, summary, language, published_at, fetched_at
FROM articles WHERE fetched_at > '{since}' ORDER BY fetched_at;

-- 1b. All classifications since last audit (joined with article data)
SELECT c.id, c.article_id, c.is_military_event, c.event_type, c.urgency_score,
       c.affected_countries, c.aggressor, c.confidence, c.summary_pl,
       a.title, a.summary AS article_summary, a.source_name, a.language
FROM classifications c JOIN articles a ON c.article_id = a.id
WHERE c.classified_at > '{since}';

-- 1c. Unclassified articles (keyword-filtered out) — PRIMARY AUDIT TARGET
SELECT a.id, a.source_name, a.source_type, a.title, a.summary, a.language,
       a.published_at, a.fetched_at
FROM articles a LEFT JOIN classifications c ON a.id = c.article_id
WHERE a.fetched_at > '{since}' AND c.id IS NULL ORDER BY a.fetched_at;

-- 1d. Source activity summary
SELECT source_name, source_type, COUNT(*) AS count
FROM articles WHERE fetched_at > '{since}'
GROUP BY source_name, source_type ORDER BY count DESC;

-- 1e. Events created
SELECT * FROM events WHERE first_seen_at > '{since}';

-- 1f. Alerts sent
SELECT * FROM alert_records WHERE sent_at > '{since}';
```

Also retrieve:
- Health status: `sudo cat /var/lib/sentinel/health.json`
- Error logs: `sudo journalctl -u sentinel --since "{since}" --no-pager | grep -iE "error|exception|traceback|critical" | tail -50`
- Live config (for keyword lists): `sudo cat /etc/sentinel/config.yaml`

### Step 2: Keyword filter audit (PRIMARY FOCUS)

Spend most of your analysis effort here. Review EVERY unclassified article from query 1c. For each article:

1. Read the title and summary carefully, accounting for the article's language.
2. Evaluate: could this article describe, indicate, or be a precursor to a military threat against Poland, Lithuania, Latvia, or Estonia?

Flag the article as MISSED if it relates to ANY of these, even tangentially:

**Direct threats (highest priority):**
- Military attacks, strikes, or invasions targeting or near PL/LT/LV/EE
- Missile, drone, or aircraft incidents in or near target countries' territory or airspace
- Troops massing at or crossing borders of target countries

**Escalation indicators (high priority):**
- Russian or Belarusian military activity near NATO's eastern flank
- Mobilization, reservist call-ups, or martial law in Russia/Belarus
- NATO Article 5 discussions or invocations
- Significant cyberattacks on target countries' infrastructure
- Hybrid warfare indicators: sabotage, energy infrastructure attacks, GPS jamming

**Context signals (medium priority):**
- Diplomatic breakdowns or ultimatums between Russia/Belarus and NATO/target countries
- Military exercises near borders that could mask real operations (even though "exercise" is an exclude keyword — if the article suggests the exercise is suspicious or unusually large, it SHOULD be flagged)
- Weapons system deployments to Kaliningrad, Belarus, or western Russia
- Changes in Russian nuclear posture or doctrine mentioning NATO

**Spillover from Ukraine conflict (medium priority):**
- Missiles or drones from the Ukraine conflict entering NATO airspace or territory
- Incidents at the Ukraine-Poland border involving military assets
- Russian strikes near NATO borders

For each MISSED article:
- Explain WHY it's relevant to the system's mission
- Diagnose the failure: which keyword SHOULD have caught it? Is the keyword missing entirely (gap), present but using wrong matching logic (substring vs boundary), or in the wrong language?
- Propose a specific fix: the exact keyword string, which language section, and which level (critical/high)
- Assess whether the proposed keyword would cause excessive false positives

For articles that are NOT relevant: skip them silently.

### Step 3: Classification quality audit

Review EVERY classification from query 1b. Only flag CLEAR disagreements — ±1 urgency variance is normal for a smaller model.

Flag if:
- `is_military_event` is wrong (false negative or false positive)
- `urgency_score` is off by 3 or more points
- `affected_countries` is wrong
- `event_type` is clearly wrong
- `aggressor` is wrong

For each disagreement, state what Haiku said, what you would say, and why the difference matters for the alert system.

### Step 4: Source health check

From query 1d:
1. Which configured sources produced articles? Which produced ZERO?
2. For zero-article sources: known issue (PAP, TVN24) or new problem?
3. Any sources producing drastically fewer articles than expected?
4. Any significant news events covered by only one source?

### Step 5: Self-evaluation gate

Before generating the final report, review your own findings:
- For each MISSED article: re-read the title and summary. Genuinely relevant to military threats against PL/LT/LV/EE, or overly broad? Keep if reasonably relevant; remove only if clearly irrelevant on reflection.
- For each keyword recommendation: would it match the missed article AND avoid matching the majority of irrelevant articles? Note trade-offs.
- For classification disagreements: material (changes alert behavior) or academic?

### Step 6: Generate and save the report

Write the report in the format below. Save to `data/audit-reports/audit-{YYYY-MM-DD}.md`. Create the directory if it doesn't exist.

Then update the timestamp:
```bash
echo "{current_utc_iso_timestamp}" > data/audit-reports/.last-audit-timestamp
```

---

## Report Format

```markdown
# Sentinel Daily Audit Report — {YYYY-MM-DD}

## Executive Summary

{2-4 sentences: overall system health, count of issues found by category, most critical finding if any. If no issues found, state that the system performed well and briefly note the volume processed.}

## Audit Statistics

| Metric | Value |
|--------|-------|
| Audit period | {start_timestamp} → {end_timestamp} |
| Total articles in DB (period) | {N} |
| Passed keyword filter (classified) | {N} ({percentage}%) |
| Filtered out by keywords | {N} ({percentage}%) |
| Events created | {N} |
| Alerts sent | {N} |
| Active sources | {N} / {total_configured} |
| Service uptime | {from health.json} |
| Consecutive failures | {from health.json} |

## Missed Articles

{If none: "No missed articles identified. The keyword filter performed correctly for all reviewed articles."}

{For each missed article, ordered by assessed severity (highest first):}

### MISSED: [{source_name}] {title}
- **Language:** {lang} | **Published:** {datetime} | **Fetched:** {datetime}
- **Summary:** {first 200 chars of article summary, or full if shorter}
- **Why relevant:** {1-2 sentences explaining the military/security relevance to target countries}
- **Why missed:** {diagnosis — keyword gap / matching logic issue / language gap / exclude keyword false positive}
- **Suggested fix:** Add `"{keyword}"` to `monitoring.keywords.{lang}.{critical|high}` in config.yaml
- **False positive risk:** {Low/Medium/High — would this keyword also match many irrelevant articles?}

## Classification Disagreements

{If none: "No significant classification errors identified."}

### DISAGREEMENT: [{source_name}] {title}
| Field | Haiku | Audit |
|-------|-------|-------|
| is_military_event | {value} | {value} |
| urgency_score | {value} | {value} |
| event_type | {value} | {value} |
| affected_countries | {value} | {value} |
- **Impact:** {What would change in alert behavior if Haiku's assessment were corrected}
- **Suggested fix:** {Prompt adjustment, threshold change, or "acceptable model limitation"}

## Source Health

| Source | Type | Articles | Status |
|--------|------|----------|--------|
| {name} | {rss/gdelt/google_news/telegram} | {count} | {OK / ZERO / ZERO (known issue) / LOW} |

{Note any new problems.}

## Recommendations

{Numbered list, ordered by priority. Each recommendation must be specific and actionable.}

1. **[KEYWORD]** Add `"{keyword}"` to `{lang}.{level}` — would catch: "{missed article title example}"
2. **[CLASSIFICATION]** {specific change to classifier prompt or config}
3. **[SOURCE]** {source fix, addition, or investigation needed}
4. **[CONFIG]** {any other configuration changes}

{If no recommendations: "No changes recommended. The system is performing as expected."}
```

## Examples

### Correctly filtered — DO NOT flag

**Title:** "South Korea holds presidential election amid political turmoil"
**Source:** Al Jazeera (EN)
Not relevant — South Korean domestic politics, no connection to military threats against PL/LT/LV/EE.

**Title:** "Russia sends military convoy to earthquake-hit region"
**Source:** TASS (EN)
Contains "military convoy" (HIGH keyword) but about humanitarian aid within Russia. This article WOULD pass the keyword filter and reach the classifier, so it's not a keyword filter failure. No action needed.

### MISSED — SHOULD flag

**Title:** "Rosyjskie drony nad Bałtykiem — fińskie myśliwce podniesione w powietrze"
**Source:** Defence24 (PL)
Russian drones over the Baltic Sea with Finnish jets scrambled — directly relevant to NATO eastern flank security. The keyword "drony" (HIGH, PL) should match via substring. Investigate: was the article excluded by an EXCLUDE keyword?

### Classification disagreement — SHOULD flag

**Title:** "Russian missile debris found in Polish territory near Ukraine border"
**Haiku:** is_military_event=false, urgency=3, type=none
**Audit:** is_military_event=true, urgency=7, type=missile_strike, affected_countries=["PL"]
**Impact:** Should trigger SMS alert at minimum. Missile debris in Polish territory is a serious incident regardless of intent.
