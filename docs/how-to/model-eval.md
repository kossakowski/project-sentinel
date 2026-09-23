# Evaluate candidate classification models (eval suite)

Use this to decide whether a model can replace the production classifier. It measures
quality against the operator's own blind labels and prices every candidate as a
substitute at real production volume. All code lives in `sentinel/eval/suite/`; all data
lives in the gitignored `data/eval/suite/`.

## 1. Build the item pool (once, frozen)

```bash
.venv/bin/python -m sentinel.eval.suite.sample --from-production --config <local-config.yaml>
```

- Reads production read-only over SSH as `deploy@` and samples every classified
  urgency 9–10 article, stratified lower tiers, and 12 real incident chains, plus the
  40 invented hard cases in `tests/fixtures/eval_suite_synthetic.yaml`.
- Splits items into a development pool (~40%) and a locked pool by incident-day
  cluster, so no incident appears in both.
- Production never stores enriched article text, so headline-only items are re-fetched
  now and frozen; `data/eval/suite/enrichment-cache.json` keeps rebuilds identical.
- Refuses to overwrite `items.json`. The local config needs writable paths instead of
  `/var/...` (see `docs/how-to/testing.md`).

## 2. Label (operator)

```bash
.venv/bin/python -m sentinel.eval.suite.label_server   # then open http://localhost:8774/
```

The page shows only what the model saw (Ukrainian/Russian with a Polish translation from
`data/eval/suite/translations.json`), never a model score. Every answer is appended to
`data/eval/suite/labels.jsonl`; the last answer per slot wins. 20 hidden repeats measure
the operator's own consistency.

## 3. Run models

```bash
.venv/bin/python -m sentinel.eval.suite.runner --config <local-config.yaml> --pool dev \
  --name <run-name> --repeats 3 --budget-usd <cap> --live \
  --models openai/gpt-5.6-luna@openai openai/gpt-6-luna@openai "z-ai/glm-5.3-flash@Together+reasoning" ...
```

- Sends the exact production prompt and schema (the manifest records the prompt hash;
  compare it with `prompt_version` in production).
- `@provider` pins the host; `+reasoning` runs models whose reasoning cannot be turned off
  at low effort — label such results as "not production conditions".
- Provider overloads (429/5xx) and timeouts are retried; the model's own bad answers are
  not. `--limit N` runs a cheap smoke test on N single items.
- Resumable: rerun the same command; a half-finished chain is redone.
- Needs `OPENROUTER_API_KEY` in `.env`; check the key's own spending limit first.

## 4. Score, price and report (offline)

```bash
.venv/bin/python -m sentinel.eval.suite.score data/eval/suite/runs/<run-name>
.venv/bin/python -m sentinel.eval.suite.report data/eval/suite/runs/<run-name>
```

`report.html` shows the verdict under the pre-registered rule, quality with 95% intervals,
the substitute-cost table (average, busy and peak month against the $10 cap), a
quality-vs-price chart, chain behaviour and per-language/input slices. Refresh production
volume with `sentinel.eval.suite.price.snapshot_production` when it is stale.

## Rules that keep the result honest

- Tune prompts or rules only on the development pool; run the locked pool once, at the end.
- The operator's labels are the only ground truth; never pre-fill or generate them.
- Candidates that cannot use strict structured output (e.g. `qwen/qwen3.7-flash`, no strict
  JSON provider on 2026-09-23) are excluded rather than tested under different conditions.
