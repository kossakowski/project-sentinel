# HANDOFF: Classifier Input Quality Problem

Paste this into a fresh Claude Code session in the project-sentinel directory.

---

## Context

Project Sentinel is a military alert system that classifies news articles for threat urgency (1-10). It uses Claude Haiku 4.5 as the classifier. The system was just calibrated — prompt rules now achieve 98% action-tier accuracy on a 50-article human-labeled test set.

However, during calibration we discovered a separate, unsolved problem: **the classifier sometimes receives garbage input** — vague clickbait headlines with no real summary — and has to make life-safety decisions based on insufficient information.

## What We Learned in the Calibration Session

### The pipeline feeds 4 source types to the classifier:

| Source Type | What classifier receives | Quality |
|---|---|---|
| RSS (Defence24, Ukrainska Pravda, etc.) | Title + real multi-sentence summary | Good |
| Telegram channels | Title + full message body | Good |
| Google News | Title + **title repeated with outlet name** | Bad |
| GDELT | Title + GDELT-extracted snippet | Variable |

### The classifier input template (`sentinel/classification/classifier.py`):
```
Source: {source_name} ({source_type})
Language: {language}
Published: {published_at}
Title: {title}
Summary: {summary}
```

### Concrete examples of bad inputs from this session:

**Example 1 — False positive (urgency 7→ should be 2):**
```
Title: Rosjanie zaatakowali w biały dzień. Drony uderzyły w ważne dla Polski miejsca
Summary: Rosjanie zaatakowali w biały dzień. Drony uderzyły w ważne dla Polski miejsca RMF24
```
Reality: This is about strikes on Lviv, Ukraine (near Polish diplomatic posts). But the classifier can't know that — the headline says "places important for Poland" and the summary is just the title + outlet name.

**Example 2 — Debunking article scores as attack:**
```
Title: "Shahedy" nad wschodnią Polską. Prawda wyszła na jaw
Summary: "Shahedy" nad wschodnią Polską. Prawda wyszła na jaw WP Tech
```
Reality: "Prawda wyszła na jaw" (the truth came out) likely means this is a DEBUNKING or explanation article. But the classifier sees "Shaheds over eastern Poland" and scores 9-10.

**Example 3 — Good input (Defence24 RSS):**
```
Title: Niezidentyfikowany dron znaleziony w pobliżu granicy z Rosją
Summary: W pobliżu polsko-rosyjskiej granicy znaleziono drona, na którego podzespołach były napisy zapisane cyrylicą – informuje RMF24. Teren miał zostać zabezpieczony przez Żandarmerię Wojskową.
```
This has real context: location, details, what happened. The classifier scores it correctly (5).

### Quantified impact from the old eval set:

8 out of 44 test cases are false-positive phone calls caused by vague inputs. All 8 are Google News articles where:
- The headline uses Poland/NATO keywords for clicks
- The actual event is in Ukraine or a non-monitored country
- The summary provides zero additional information

### Current mitigations (insufficient):

The classifier prompt already says:
- "The 'Source:' field is metadata... Do NOT infer that a country is affected because it appears in the source name"
- "If the headline and summary do NOT explicitly state which country was attacked, do NOT assume it was a monitored country. Assign urgency 2-3 and confidence below 0.5."

These rules help (~50% of cases) but fail when the headline EXPLICITLY mentions Poland while the actual event is in Ukraine. The classifier can't distinguish "real attack on Poland" from "clickbait about Ukraine using Poland in the headline" without seeing the article body.

## What Needs to Happen

A fresh agent should:

1. **Analyze the full pipeline** — understand how articles flow from source → fetcher → keyword filter → deduplication → classifier. Key files:
   - `sentinel/fetcher/` — all fetcher implementations (rss.py, google_news.py, telegram.py, gdelt.py)
   - `sentinel/pipeline.py` — orchestration, filtering, dedup
   - `sentinel/classification/classifier.py` — what actually reaches Haiku
   - `config/config.example.yaml` — all sources, keywords, thresholds

2. **Quantify the problem** — query the production DB to answer: what % of classified articles have summary == title (or summary is just title + outlet name)? Which sources consistently produce garbage summaries?

3. **Research and propose solutions** — this is a design problem with multiple possible approaches:
   - Fetch article body before classification (adds latency + cost + rate limits)
   - Score input quality and abstain/downgrade confidence on garbage input
   - Different handling per source type (skip classification for title-only articles?)
   - Something else entirely

4. **Implement the chosen approach** — whatever solution is picked, it needs to work within the constraints:
   - Pipeline runs every 3 minutes (fast lane) — can't add 30s per article
   - ~200 articles per cycle, ~10-30 new per cycle after dedup
   - Cost budget: currently ~$0.06/eval run, should stay cheap
   - Must not break the 98% accuracy we just achieved

## Key Files

| File | Purpose |
|---|---|
| `sentinel/classification/classifier.py` | SYSTEM_PROMPT, USER_PROMPT_TEMPLATE, API call |
| `sentinel/fetcher/rss.py` | RSS fetching (Defence24, BBC, etc.) |
| `sentinel/fetcher/google_news.py` | Google News fetching |
| `sentinel/fetcher/telegram.py` | Telegram channel monitoring |
| `sentinel/fetcher/gdelt.py` | GDELT source |
| `sentinel/pipeline.py` | Full pipeline orchestration |
| `config/config.example.yaml` | All sources and configuration |
| `data/eval/human-labels.yaml` | 50 human-labeled ground truth articles |
| `tests/fixtures/eval_set.yaml` | 44-case eval set (AI-labeled, includes the false positives) |
| `tests/fixtures/eval_set_human.yaml` | Human-labeled eval set for harness |

## Production DB Access (read-only)

```bash
ssh -p 2222 deploy@178.104.76.254
sqlite3 /var/lib/sentinel/sentinel.db
```

Useful queries:
```sql
-- Articles where summary ≈ title (garbage input)
SELECT source_name, source_type, COUNT(*) 
FROM articles 
WHERE summary = title OR summary LIKE title || '%'
GROUP BY source_name, source_type;

-- Source quality breakdown
SELECT source_type, COUNT(*), 
  SUM(CASE WHEN length(summary) > length(title) + 20 THEN 1 ELSE 0 END) as has_real_summary
FROM articles 
GROUP BY source_type;
```

## What NOT to Change

- The 10 calibration rules in the classifier prompt — these are working (98% accuracy)
- The eval harness (`sentinel/eval/harness.py`) — this is the measurement tool
- The human labels (`data/eval/human-labels.yaml`) — ground truth, never modify
