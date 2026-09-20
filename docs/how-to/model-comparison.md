# Compare candidate classification models

This is an **evaluation-only** workflow. Production still uses Haiku. It never
constructs Twilio or Expo clients, accesses the live database, or sends alerts.
Read-only production sampling is a separate, explicit preparation command.

## Prepared first round

The first exploratory development round has been run. Keep its dataset and raw
report unchanged. Its labels and prompt contain policy ambiguities, so its combined
pass rate is not a valid model ranking. Use the version-2 workflow below for the
next comparison.

The dataset is `tests/fixtures/model_comparison_first50.yaml`: 50 cases in 12 story
sequences, comprising 44 real stored articles and 6 marked synthetic contrasts.
The source fields of the real cases were checked against the local production
snapshot. There are 34 development cases and 16 held-out cases. Rusinowo is in
development because it already appears in the memory prompt examples.

The set contains Polish, English, Ukrainian and Russian text. Incorrect language
metadata in the original articles is preserved; `provenance.content_language`
records actual content language separately. Forty-five labels are provisional and
five disputed. **None is approved ground truth.** Read the
[label review inventory](../ideas/model-comparison-labels.md) before interpreting scores.

Full article-body verification and the larger representative study are not yet
included. This first round evaluates the existing title/summary + incident-memory
contract. It is deliberately enriched for hard cases and must not be used directly
to estimate normal monthly traffic or claim a production accuracy percentage.

## Validate without a key or network

Run from the repository root:

```bash
.venv/bin/python -m sentinel.eval.compare_models
```

This validates IDs, provenance, timestamps, labels, same-incident anchors and
development/holdout separation. It prints counts and does not instantiate a provider.

## OpenRouter setup

One OpenRouter key covers all four verified catalogue IDs:

- `anthropic/claude-haiku-4.5` is the baseline.
- `deepseek/deepseek-v4.1-flash` is the first challenger.
- `qwen/qwen3.8-flash` is the low-cost challenger.
- `openai/gpt-5.6-luna` is the third challenger.

Put `OPENROUTER_API_KEY` in the ignored project `.env`, not a committed file or chat.
Use a separate evaluation key with a USD 5 credit limit in OpenRouter. No direct
Anthropic, DeepSeek, Alibaba or OpenAI key is required by this runner.

Verify current catalogue availability without a key or paid inference:

```bash
.venv/bin/python -m sentinel.eval.compare_models --catalog
```

Prices are read from OpenRouter, not copied from the vendors' direct-API lists.
In particular Qwen's observed OpenRouter rate differs from the Frankfurt-direct
rate used in the earlier shortlist. The client considers advertised price overrides
when reserving a request, so the reservation can exceed its eventual charge.

## Legacy paid exploratory command

```bash
.venv/bin/python -m sentinel.eval.compare_models --live --budget-usd 5 --allow-provisional
```

This runs the 34 development cases against all four models, using one shared
USD 5 runner budget. It makes no automatic retries and does not switch models or
fall back to other providers. Reasoning is explicitly disabled for the first
comparison; returned reasoning tokens and provider names are still recorded.
The router may select an initial provider for each request; this is recorded,
not a promise of a single pinned hosting provider for the entire benchmark.

The runner reserves a conservative amount before each request, including input,
schema and maximum output. Timeouts and unknown costs retain their reservations.
Returned API cost replaces the estimate when available. **This is not a guarantee
of the provider's final billing:** the key-level limit is the independent ceiling.
Credit-purchase fees are separate from reported model usage charges.

The JSON report is saved under `data/eval/` after each completed case. It contains
dataset/prompt/request hashes, configuration, actual model/provider, token usage,
cost, latency, accepted incident decision and simulated notification channels.
All secrets and real recipient/device details are excluded.

If a run is interrupted, inspect its partial report and OpenRouter usage before
starting another run. A request interrupted before its response may still have
been charged. There is no automatic resume/retry; an existing output path is never
silently overwritten. A new command has a new runner budget, so keep the separate
key-level ceiling in place across invocations.

## Read the results

Models build their own memory in arrival order. Only prior observed reports appear
in prompts; expected answers, rationale and evaluator metadata are never sent.
Each sequence/model starts with a fresh in-memory database and a historical replay
clock. A simulated critical call is immediately acknowledged, making subsequent
duplicate/escalation behaviour testable without retry timers or telephony.

Scores distinguish wrong incident merges, duplicate notifications, missed critical
cases, false alarms, geography, median/p95 latency, and reported/unknown cost.
Identity is unscorable when the anchor never became a stored incident (for example
a low-urgency story). Such cases still test severity and notification behaviour.
Disputed labels are excluded from scored totals. Refusals, malformed output and
provider errors remain explicit failures; they are never treated as low danger.

`release_eligible` means only that a complete, error-free run used approved holdout
labels. It is not a release approval and does not mean the model passed the safety,
accuracy, latency or budget targets. Provisional/development runs cannot qualify.

After the development instructions and model settings are frozen, run the held-out
split once with `--split holdout`. Do not tune against its results and then claim
it is still an untouched test set. Extend the dataset and obtain annotation review
before making a production decision.

## Version 2: separate understanding from runtime behaviour

The [clarified plan](../ideas/model-comparison-v2-plan.md) defines the evaluation-only
contract. Production still uses its existing prompt, model, memory settings and
alert policy. There is no article-body fetch in either benchmark version.

- `tests/fixtures/model_comparison_v2_development.yaml` contains 34 revised development
  cases plus 2 synthetic positive controls for the confirmed Ukraine-side awareness
  rule. The operator choices are resolved; genuine source ambiguities remain disputed.
- `tests/fixtures/model_comparison_v2_holdout.yaml` contains 64 fresh synthetic cases
  across 16 sequences, equally divided between PL/EN/UA/RU. A separate assistant
  reviewed them without model predictions: 63 are `reviewed`, one is `disputed`.
  These diagnostic challenges do not represent everyday news traffic.
- `tests/fixtures/benchmark_policy_v2.yaml` records the operator's choices: confirmed
  nearby strikes inside Ukraine score 5–6; Russian military drones recovered and
  neutralised in Poland score 7–8 for one notification, with repeats suppressed.
  No revised paid run is allowed if policy choices or affected labels remain pending.
  Assistant `reviewed` status never becomes human `approved` status automatically.

Both datasets can be validated without credentials, a resolved policy, or network
access. For example:

```bash
.venv/bin/python -m sentinel.eval.compare_models --dataset tests/fixtures/model_comparison_v2_development.yaml
```

Replace the filename with `model_comparison_v2_holdout.yaml` to check its structure.
Structural validation is not model inference and does not open the held-out answers
for prompt tuning. Supplying `--policy-file` also checks that the policy is resolved.

After policy resolution, use two distinct run types:

1. **Controlled understanding:** `--context-mode reference` gives every model the
   same prior source articles, grouped using prior annotations. Current/future labels,
   expected urgency, rationale and model-generated summaries never enter the request.
   Prior context is unchanged even when one model fails an earlier request. Disputed
   prior articles are omitted. This measures facts, urgency and raw incident identity,
   not the program's notification behaviour.
2. **Runtime simulation:** `--context-mode model` lets each model build its own
   temporary incident history. It also tests candidate retrieval, confidence gates,
   grouping and simulated alerts. Models can consequently see different histories;
   these scores cannot be presented as a controlled intelligence comparison.

For version 2, both modes require
`--policy-file tests/fixtures/benchmark_policy_v2.yaml` and the matching version-2
dataset. The runner rejects mixing clarified prompts with legacy labels, unresolved
annotations, and unapproved labels without `--allow-provisional`, before network
access. Freeze policy, labels, prompt and model/provider settings after development;
run the fresh held-out cases only once on that unchanged bundle.

The report records independent correct/scored counts for attack geography, local
effects, protective measures, current status, urgency band and incident identity.
Raw model matches are separate from matches accepted by the program. An expected
anchor missing from the shown context has no identity score; retrieval failure is
reported separately. A correctly silent duplicate is not a missed critical alert.
Required-notification misses and critical score undercalls are separate counters.
Notification counters describe the simulation; they are not proof of real phone
delivery or adequate corroboration timing. The `false_alert` counter includes
unexpected duplicate notifications and therefore overlaps `duplicate_notification`.

Evidence presence is recorded but is not proof that a quotation supports a fact.
Evidence correctness is scored only where an explicit reference label exists;
alternative valid quotations can need human review. Missing evidence grades must
not be converted into perfect grounding scores. Disputed labels are excluded from
semantic scores, but their API failures and latency remain in operational totals.

`--provider-only PROVIDER` pins an allowed hosting provider without fallback. Use
separate runs for models requiring different providers, and verify the actual
provider returned in each report. The default `--timeout-seconds 30` is a total
request deadline, not just a network-idle timeout. There are no automatic retries.
Request IDs, provider names, cached tokens, observed reasoning and charges are
recorded. An absent reasoning count is not proof that no hidden reasoning occurred.

The original evaluation key has a **$5 cumulative allowance**, not $5 per command.
Check its actual remaining credit before each paid batch and reserve part for the
held-out comparison. The ongoing production target is separately **$20/month**.
This test neither enforces that production limit nor proves it will be met.

## Reanalyse an existing report without API spending

The metric-only tool requires the exact original dataset hash and a new output
path. It does not rerun models, repair old labels, or overwrite the original report:

```bash
.venv/bin/python -m sentinel.eval.rescore_dimensions --report data/eval/model-comparison-development-20260920.json --dataset tests/fixtures/model_comparison_first50.yaml --output data/eval/model-comparison-development-20260920-reanalysis.json
```

This can reveal whether a raw correct match was rejected by a runtime gate. It
cannot turn the first round's ambiguous labels into a reliable model ranking.
