# Compare Jev with Luna locally

This experiment measures article facts, urgency and incident identity with the same
prior-source context for both providers. It is not part of the monitoring runtime.
It makes no Twilio, Telegram or Expo calls and does not open the production database.

## Prepare without spending

From the project root, run:

```bash
.venv/bin/python -m sentinel.eval.jev_comparison --dataset tests/fixtures/model_comparison_v2_holdout.yaml --output data/eval/jev-preview
```

Without `--live`, this validates every request and writes the manifest and exact
requests without constructing API clients. Use a new output directory every time.
The default dataset is the 36-case development set. The command above selects the
64-case diagnostic set, with 16 articles in each of PL/EN/UK/RU. Existing labels are
reviewed or disputed, not fully operator-approved. These sets have been used before;
the filename `holdout` does not make them a fresh independent release test.

## Run a capped comparison

Store `TYPESAFE_API_KEY` and `OPENAI_API_KEY` in the ignored project `.env`. Never put
keys in arguments, reports, or Git. The direct Luna model and its pricing come from
the local configuration. Jev's pinned model, official endpoint, pricing, country
vocabulary and diagnostic confidence threshold are in
[`jev_evaluation.yaml`](../../tests/fixtures/jev_evaluation.yaml).

After choosing a spending allowance, run:

```bash
.venv/bin/python -m sentinel.eval.jev_comparison --dataset tests/fixtures/model_comparison_v2_holdout.yaml --live --allow-provisional --budget-usd 0.25 --output data/eval/jev-live
```

The allowance covers **both providers together**, using a new persistent usage
ledger inside this run's directory. Estimates use configured token prices, not
reconciled account invoices. Jev reserves its full context price before each call;
Luna uses its existing conservative input/output bound. Unknown charges remain
reserved. Neither client retries. The first API, budget or validation failure stops
the run and preserves partial evidence. A new directory starts a new allowance;
allow for prior spending before starting another run. This does not alter account
balances, buy credits, or change the runtime's monthly budget.

`--max-sequences N` limits whole incident sequences for a small integration check.
It never cuts an article away from the preceding context needed to evaluate it.

## Read the results

- `manifest.json` records the dataset, policy and implementation hashes, settings,
  planned calls, annotation status and limitations before inference.
- `requests.jsonl` contains exact Jev requests and Luna messages, without secrets.
- `results.jsonl` preserves each response, latency, usage, probability distributions,
  errors, diagnostics and per-dimension grading. Each completed row is flushed to disk.
- `report.json` separates scores by model and language, critical urgency misses,
  excessive urgency, wrong incident merges, errors, disagreements and costs.
- `usage.db` preserves settled estimates and reservations, including failed calls.

The models see the same source article and prior raw source text. Prior annotations
group that history only after their own request is constructed. Current expected
answers, rationales and labels are never sent to either model. Independent Jev
questions classify country presence, protection and status; one discrete Choice
assesses urgency under the unchanged policy. A separate Choice compares each prior
incident. Multiple plausible matches produce `uncertain`, not an arbitrary merge.

Disputed labels are excluded from accuracy denominators. Missing or invalid outputs
are errors, never low-danger predictions. Jev country uncertainty is retained in
diagnostics; only explicit positive decisions populate the country lists. An attack
outside the fixed vocabulary is recorded as `OTHER`, not silently discarded.

Urgency uses Choice rather than averaging Score levels. All probabilities remain
available for review. The 0.9 confidence threshold only flags confidently wrong
urgency/protection/status answers; it does not suppress articles or authorize alerts.
Country and candidate-comparison probabilities remain in the raw results.

This first stage does not score notification delivery, runtime candidate retrieval,
Polish summaries, quotations, or exact duplicate/update/escalation distinctions: the
existing identity annotations primarily distinguish a new episode from a known one.
Luna still returns its complete production schema, so timing and cost compare these
two implementations, not identical output workloads. It skips the later summary
language-repair call. Results are always marked `release_eligible: false`.

Before any runtime adoption, review disagreements, obtain fresh human labels,
validate confidence by language, and evaluate the complete alert pipeline with
recording transports. Agreement between models is not independent-source corroboration.

The implementation was checked against the official
[TypeSafe skill](https://github.com/typesafe-ai/skills/blob/main/skills/typesafe-ai/SKILL.md),
[API](https://docs.typesafe.ai/api), [Choice](https://docs.typesafe.ai/primitives/choice),
and [model limits/pricing](https://docs.typesafe.ai/models) on 2026-09-22. The skill was
read directly; it was not installed into either agent's global configuration.
