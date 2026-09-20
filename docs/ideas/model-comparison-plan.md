# First-round model comparison

Prepare an offline, opt-in paid benchmark of 50 cases, comparing Haiku 4.5,
DeepSeek V4.1 Flash, Qwen 3.8 Flash and GPT-5.6 Luna via OpenRouter.
No production changes and no notification transports are permitted.

## Contract

- Cases have stable IDs, an incident/sequence ID, a development or holdout split,
  original article fields, provenance, expected urgency/action/country/relationship,
  and a label status. Whole incidents stay in one split.
- Prefer real stored articles. Clearly mark synthetic/translated contrast cases.
  Existing operator judgements can inform labels, but historical model output is
  never ground truth. New annotations are provisional; unresolved cases are excluded
  from release gates. Separate content evidence from policy judgements.
- Replay each sequence chronologically in a fresh in-memory database for each
  candidate. Use actual classifier/memory/corroborator code and fake alert clients.
  An isolated replay clock follows original arrival timestamps. Database time
  windows, incident updates and fake alert timestamps all use that clock; source
  timestamps and explicit incident dates remain intact.
- Feed only the article and prior observed model history to the classifier. Never
  include expected labels, future articles, evaluator notes or split names.
- Use the same system prompt, JSON contract and explicit non-thinking baseline
  across candidates. Provider-specific settings and returned model/provider IDs
  are recorded. Do not silently substitute another model.
- Fetch the public OpenRouter model catalogue before paid calls. Use exact IDs,
  current prices (including worst price overrides), required parameter support,
  provider price ceilings, no provider/model fallbacks, no paid tools and no retries.
- Make the default command offline dataset validation. Paid calls require `--live`,
  `OPENROUTER_API_KEY` and an explicit dollar budget. Reserve a conservative per-call
  bound before each request; count reasoning output, timeouts and failed attempts.
  Stop when a request cannot fit. An OpenRouter key-level limit is the independent
  hard ceiling; the runner must not claim its estimates guarantee provider billing.
- Report model errors, critical misses, false alerts, duplicate notifications,
  missed escalations, wrongly merged incidents, latency and returned API cost.
  Reports carry a dataset/prompt hash and distinguish provisional scores from an
  approved held-out release evaluation. Do not project monthly totals from a
  deliberately difficulty-enriched set as if it were representative traffic.

## First-round schema

YAML root: `version: 1`, `description`, `cases`.
Each case: `id`, `sequence_id`, `split` (`development` or `holdout`),
`label_status` (`provisional`, `approved`, `disputed`), `provenance` (object),
`article` (title, summary, source_name, source_url, source_type, language,
published_at, fetched_at), `expected` (urgency_min, urgency_max,
affected_countries optional, notification: `initial|silent|update`,
relation: `new|same`, critical: bool), `rationale`.
All articles in a sequence use fetched_at order, preserving publication timestamps.
Relations refer to prior articles in that sequence; keep independent incident
sequences separate unless testing an explicitly new wave/location.

## Preparation deliverables

1. The frozen 50-case first-round fixture and annotation/review notes.
2. An OpenRouter-only evaluation client; no runtime provider changes.
3. Validation, chronological replay, cost ledger and JSON result report.
4. Offline tests for isolation, label leakage, chronology, budget and error handling.
5. Operator instructions for the key and the first bounded paid run.

Full article extraction and the larger 200-article/30-story study remain later
phases. This first set tests the title/summary and memory path we already have.

## Prepared status

Prepared on 2026-09-20. The first 50 cases contain 44 production articles and six
explicit synthetic contrasts, in 12 sequences. The split is 34 development / 16
holdout after removing prompt-exposed Rusinowo examples from holdout. Labels are
45 provisional and five disputed; no release evaluation is approved yet.

The default validator passes without a key or network. The public OpenRouter
catalogue confirms all four exact model IDs. The runner/provider tests pass, and
the full offline suite passed 473 tests (including 40 provider/runner tests). No paid
inference was run during preparation.
See [operator instructions](../how-to/model-comparison.md) and
[the label review inventory](model-comparison-labels.md).
