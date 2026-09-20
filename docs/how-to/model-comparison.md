# Compare candidate classification models

This is an **evaluation-only** workflow. Production still uses Haiku. It never
constructs Twilio or Expo clients, accesses the live database, or sends alerts.
Read-only production sampling is a separate, explicit preparation command.

## Prepared first round

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

## Paid exploratory run (not run during preparation)

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
