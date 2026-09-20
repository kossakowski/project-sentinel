# Clarified benchmark, version 2

Scope: evaluation only. Preserve the first-round fixture, prompts and results.
Do not modify the production classifier, runtime configuration or alert routing.

## Policy decisions

The operator resolved both choices on 2026-09-20:

- A confirmed strike inside Ukraine very close to Poland, without Polish incursion
  or resident shelter warning: awareness 5–6, without a phone call.
- A Russian military drone found in Poland, already neutralised with no remaining
  danger: retain incident severity 7–8 so the operator learns of the incident once.
  Follow-up reports of that same incident remain suppressed. This exception does
  not invent current danger or establish a hostile impact from recovery alone.

The choices are recorded in `tests/fixtures/benchmark_policy_v2.yaml`. Source
ambiguities remain distinct from policy choices: an unspecified side of a border
is still unknown, and Russian origin must be supported by the current source.

Retain the existing rule that explicit official resident air-raid/shelter/evacuation
orders in a monitored country are critical even without confirmed local impact.
The word "alarm" alone is not proof of such an order.

Separate factual geography from alert relevance:

- `facts.attack_countries` lists countries where hostile physical impacts/incursions
  are explicitly located in the current article, including non-monitored countries.
  Unknown border side or a destination/nationality does not establish this fact.
- `affected_countries` lists monitored countries with a concrete local incident or
  protective response explicitly reported. This does not mean they were attacked.
- `facts.protection` is `official_warning`, `precaution`, `none`, or `unclear`.
- `facts.status` is `active`, `resolved`, `historical`, or `unclear`.
- Short verbatim evidence from the supplied article grounds each factual field.
  Stored incident summaries support matching only, not invented current-article facts.

## Implementation

1. Add a versioned, evaluation-only policy/prompt bundle and schema. Require explicit
   policy selection; never silently mix it with the legacy classification prompt.
2. Add separate metrics for facts, policy scoring, raw incident matching, accepted
   runtime grouping, retrieval coverage and delivered simulated notifications.
   Report denominators and unknowns; no single all-fields accuracy ranking.
   First run controlled `reference` context, where all models see identical prior
   source evidence despite earlier response failures. Then use `model` context
   separately for runtime behaviour, where each model builds its own history.
3. Preserve raw model matching decisions before runtime confidence checks. Count a
   withheld duplicate and a missed new critical notification differently. Group
   incident-level statistics to avoid treating follow-up reports as independent attacks.
4. Review a COPY of development annotations against source evidence and the chosen
   policy, without copying candidate outputs. Preserve uncertainty and provenance.
   Independent assistant review is recorded as `reviewed`, not human approval.
5. Add 64 fresh held-out challenge cases in 16 independent four-report sequences,
   balanced across PL/EN/UA/RU. They are explicitly synthetic diagnostic controls,
   not observed news or a representative traffic sample. They supplement the original
   real-world cases; no claim of real-world accuracy follows from synthetic success.
6. Freeze prompts/settings before any holdout inference. Independently check labels
   without model predictions. Run development first, then held-out checks once on the
   unchanged bundle. Keep all runs within the existing $5 key allowance.
7. Add explicit provider selection and hard total-request deadlines to distinguish
   hosting reliability from model understanding. Record actual provider, cache usage,
   reasoning behaviour and charges. Keep retries/fallback disabled for comparability.

Deployment, runtime prompt replacement, article-body extraction and model migration
remain separate decisions after this benchmark. Price projections use representative
usage estimates, not the deliberately difficult challenge-set error distribution.

## Preparation status

The evaluation code, revised development copy and independently reviewed synthetic
holdout are prepared. Both datasets support offline structural validation. The
operator choices and dependent development labels are resolved and independently
reviewed: 24 reviewed development cases and 12 disputed cases, plus the unchanged
63 reviewed / 1 disputed held-out cases. No production change is implied by software tests or
benchmark results.

The design follows the task-specific criteria and reviewed-data principles in
[OpenAI's evaluation guidance](https://developers.openai.com/api/docs/guides/evaluation-best-practices).
This is a local OpenRouter-based evaluator, not an integration with OpenAI's Evals service.
