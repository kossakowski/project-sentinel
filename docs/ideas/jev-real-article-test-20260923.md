# Jev real-article observation plan — 2026-09-23

This run compares the frozen scoped Jev hybrid with the configured Luna classifier
on 48 verbatim articles exported read-only from production. It has no correct-answer
labels and cannot report accuracy, false alerts, missed alerts or production readiness.
Provider agreement is not ground truth.

## Frozen selection

- Candidate pool: 132 records fetched from September 21 through September 23,
  06:40 UTC. The read-only SQL and export time are retained with the local snapshot.
- The pool contains up to 15 recent records per source-language tag and prior score
  tier. Prior model scores are used only to sample interesting cases, never as labels.
- The selected content-language counts are 16 Polish, 16 English, 13 Ukrainian and
  3 Russian. Assignment uses Lingua's four-language detector and is not independently
  human-verified. Original source-language tags are preserved in model input.
- Strata contain 5 prior critical candidates, 17 awareness candidates, 14 low-tier
  candidates and 12 records not classified in production. The latter are background
  controls fed directly to this local classifier test, not a replay of keyword filtering.
- A fixed SHA-256 ordering chooses within strata. Exact text overlap with existing
  fixtures is excluded. Semantic paraphrases and repeated incident coverage remain.
- All records form one chronological sampled stream. Each pipeline builds its own
  memory. Missing unselected earlier articles make this an incomplete history.
- Selection is enriched and not statistically representative. Three Russian inputs
  cannot establish Russian-language reliability.

Dataset: `data/eval/jev-real-observations-20260923.json`.
SHA-256: `e8ea38e7543871d327c7163c3003a2122e9a5dea0cc690f523efd232cecf2b52`.
Raw candidate snapshots and article bodies stay in ignored local `data/eval/`.

## Prompt and comparison contract

Before inference, preflight inspection found that earlier Jev urgency instructions
referred to monitored countries without explicitly naming the set. The new
`jev-pipeline-v3-scope` variant adds the policy's monitored countries to state and
references that scope in every independent question. NATO membership alone does
not expand scope; existing cross-border exceptions still apply. Version 2 remains
available unchanged for exact old-request recovery.

No model outputs from this real-article run were used to make that change. The
rest of the questions, severity policy, runtime thresholds and summary prompt are
unchanged. Differences from the earlier synthetic run therefore reflect both a
new dataset and the explicitly scoped prompt; they are not a controlled estimate
of the effect of that prompt correction alone.

Observe urgency, geography, status, military-event status, identity, simulated
notifications, latency and cost. Normalize event IDs to their originating article
before comparing providers. Preserve API failures and invalid optional quotations.
Do not treat fewer calls or higher agreement as proof of better decisions.

## Budget and command

Carry the latest ledger, including the original pilot, pipeline run and six-case
regression: $0.100179688 estimated so far. The cumulative cap remains $0.25.

```bash
.venv/bin/python -m sentinel.eval.jev_pipeline --unlabelled --dataset data/eval/jev-real-observations-20260923.json --settings tests/fixtures/jev_observation.yaml --carry-ledger data/eval/jev-country-regression-20260923/usage.db --live --budget-usd 0.25 --output data/eval/jev-real-live-20260923
```

The final report should identify disagreements worth reviewing with their exact
input text and source links. Human review of earlier synthetic labels remains
pending; this observation mode does not approve or replace those labels.
