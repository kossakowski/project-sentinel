# GPT-6 Luna vs GPT-5.6 Luna: evaluation record (2026-09-23)

Evaluation only. Production config, prompts and server files are unchanged; production
still runs `gpt-5.6-luna` with `reasoning: none`.

## Verdict

**Do not switch yet.** GPT-6 Luna costs about 45% of GPT-5.6 Luna for the same work
and grades exact urgency better on the synthetic held-out set, but it breaks the strict
JSON output contract on 11 of 330 production-path requests (3.3%), against 0 of 240 for
GPT-5.6 Luna. Each broken answer leaves the article pending for the 300-second retry,
and one hit the critical Latvian air-raid warning (urgency 10). On the human-labelled
real headlines it is also slightly worse. The saving is about $2.4/month.

## Prices (OpenAI official, confirmed in the OpenRouter catalogue)

| Model | Input $/1M | Cached input $/1M | Output $/1M |
|---|---:|---:|---:|
| `gpt-5.6-luna` | 0.20 | 0.02 | 1.20 |
| `gpt-6-luna` | 0.10 | 0.01 | 0.50 |

`gpt-6-sol` ($2/$10) and `gpt-6-astra` ($10/$50) were not evaluated: they cost 10–50×
more, and `gpt-6-astra` rejects `reasoning.effort=none`.

## A. Held-out comparison (64 synthetic cases, 63 scored, 3 runs per model)

Same bundle as the run that selected Luna: dataset sha `47fc04cf…`, prompt sha
`aa4d4ca8…`, `--context-mode reference`, `--provider-only openai`, via OpenRouter.

| Dimension | GPT-5.6 Luna (r1/r2/r3) | GPT-6 Luna (r1/r2/r3) |
|---|---|---|
| Urgency action band | 63/63/63 | 63/63/63 |
| Urgency exact range | 50/50/48 | **55/56/56** |
| Attack countries | 63/63/63 | 63/63/63 |
| Affected countries | 60/60/62 | 61/61/62 |
| Protection | 58/60/58 | 58/58/58 |
| Status | **52/51/51** | 44/46/45 |
| Raw incident identity | 62/62/63 | 62/63/63 |
| Critical undercalls / wrong merges / errors | 0 / 0 / 0 | 0 / 0 / 0 |
| Cost per run (USD) | 0.0227–0.0284 | 0.0096–0.0120 |
| Median / p95 latency (s) | 2.8–2.9 / 3.8–4.2 | 2.7–2.8 / 3.4–4.1 |

Status errors differ in kind. GPT-6 Luna mostly says `unclear` where the label is
`active` (39 of 55 misses); GPT-5.6 Luna mostly says `resolved` where the label is
`active` (17 of 36). No production code reads `facts.status` directly; it only informs
the model's own urgency reasoning.

## B. Human-labelled real headlines (`eval_set_human.yaml`, 50 cases, 3 runs per model)

Production code path (`./run.sh --eval`) with direct OpenAI calls. Labels are the
operator's own (2026-05-22) and predate policy v2, so absolute scores are low for both
models; only the comparison is meaningful. The `event_type` and `aggressor` checks
target the old schema and are ignored. Totals over 150 case-runs:

| Check | GPT-5.6 Luna | GPT-6 Luna |
|---|---:|---:|
| Action match | **108** | 98 |
| Urgency in range (±1) | **97** | 82 |
| Affected countries | **123** | 115 |
| Military-event flag | 82 | 84 |
| False phone calls | 12 | 10 |
| Invalid structured output | **0** | 8 |
| Cost per run (USD) | 0.0177 | 0.0081 |

## C. Production-path stability (`direct_luna`, 10 fresh cases + 20 repeats of `v2h-ru-01-a`)

| | GPT-5.6 Luna (3 runs, 90 requests) | GPT-6 Luna (6 runs, 180 requests) |
|---|---|---|
| Passed | 90/90 | 177/180 |
| Invalid structured output | 0 | 3 (`fresh-estonian-exercise`, `fresh-lv-warning`, `fresh-unknown-location`) |
| Known repeat case urgency | 5 in all 60 | 5 in all 120 |
| Polish summaries | 90/90 | all valid answers |

Two captured failures show the mechanism: one answer contained the full JSON object
twice in a row, and one began with plain-text reasoning ("We need JSON. Is military
event? …") before the JSON, despite `reasoning.effort=none` and strict JSON schema.

## Cost of this evaluation

About $0.28 in total: A $0.106 (OpenRouter evaluation key), B $0.077 and C $0.095
(direct OpenAI key shared with production).

## What would change the verdict

- A fix for the invalid outputs, e.g. one immediate retry on invalid structured output,
  followed by a rerun showing the effective failure rate near zero.
- A newer `gpt-6-luna` snapshot that passes B and C with zero invalid outputs.

## Reproduce

Raw outputs (gitignored, local only): `data/eval/gpt6-holdout-r{1,2,3}-20260923.json`,
`data/eval/gpt6-direct-<model>-r<n>-20260923.jsonl`, and
`data/eval/eval-20260923-19*.json` for B.

```bash
.venv/bin/python -m sentinel.eval.compare_models --dataset tests/fixtures/model_comparison_v2_holdout.yaml --split holdout --policy-file tests/fixtures/benchmark_policy_v2.yaml --context-mode reference --provider-only openai --allow-provisional --live --budget-usd 0.3 --models openai/gpt-5.6-luna openai/gpt-6-luna --output data/eval/<new>.json
```

B and C need a config copy with `classification.model`, `budget.*` prices and a
separate `budget.ledger_path`, and with the `/var/...` paths moved to a writable
directory; B also needs `EXPO_PUSH_TOKEN` set to any placeholder.
