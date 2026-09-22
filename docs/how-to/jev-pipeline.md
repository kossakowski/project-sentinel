# Test the Jev hybrid through alert routing

This second-stage local experiment compares the existing Luna classifier with Jev
decisions plus a separate Luna Polish-summary request. Both pass through incident
retrieval, memory validation, corroboration, grouping, and alert routing. Recording
transports simulate immediate call acknowledgement; no notification reaches a phone.
Polling, delivery failures and retry timing are outside this experiment.

The Jev variant uses full country names, preserves raw country answers, and adds an
explicitly attacked monitored country to the affected-country list. It asks incident
identity separately from duplicate/update/escalation, so uncertainty between two
same-incident labels does not automatically become uncertainty about identity.
Runtime confidence thresholds stay unchanged. This tests those gates; it does not
establish that they are calibrated for Jev.

Optional evidence is selected from verbatim source spans. Invalid quotation answers
are discarded and reported separately, without suppressing valid danger decisions.
Invalid core answers still stop the run. Luna writes summaries from the article
only and cannot change Jev's classification. The existing Polish-language guard
remains active; summary fallback is reported and stops further evaluation requests
after recording the current alert outcome.

## Prepare and inspect

```bash
.venv/bin/python -m sentinel.eval.jev_pipeline --output data/eval/jev-pipeline-preview
```

This makes no model requests. The fresh dataset has 40 invented articles in four
related language families. Its labels are provisional, not independent human ground
truth. Review the [exact articles and expectations](../ideas/jev-fresh-case-review-20260923.md).

## Run within the existing allowance

```bash
.venv/bin/python -m sentinel.eval.jev_pipeline --live --allow-provisional --budget-usd 0.25 --carry-ledger data/eval/jev-luna-pilot-20260922-complete/usage.db --output data/eval/jev-pipeline-live
```

Use a new output directory. Carry the **latest** experiment ledger when doing more
work: copying an older ledger omits spending that happened after it. The September 23
session carries the original pilot's charges forward within the same $0.25 cap.
Costs are estimates at configured rates, not reconciled invoices. Keys remain in
the ignored local `.env`; the command does not change billing or production settings.

## Recover without repeating completed calls

Add `--resume-from OLD_RUN_DIRECTORY` and choose a new output directory. Dataset,
policy, settings, summary prompt and runtime configuration must match. Every cached
API request is checked against the exact new request before reuse. The old ledger
is copied and the spending cap cannot increase. Saved API failures are not retried
automatically. Cached or partly cached cases are excluded from fresh latency statistics.

`calls.jsonl` preserves the exact requests, responses, usage, cost and cache markers.
`results.jsonl` adds real runtime candidate history, raw/accepted decisions, simulated
channels, summary checks and grading. `report.json` separates request failures,
retrieval failures, memory-gate rejections, duplicate alerts, missed alerts, quote
issues, language groups and provider costs. The manifest freezes configuration,
prompt and implementation hashes. All reports remain `release_eligible: false`.
