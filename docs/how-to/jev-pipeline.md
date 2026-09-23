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

## Observe real articles without labels

Use `--unlabelled` with a JSON dataset whose `mode` is `unlabelled`, case
`label_status` is `unlabelled`, and split is `observation`. Expected-answer fields
are rejected. Article records and provenance are required. The report compares
decisions, identities normalized to their originating article, and simulated
notifications. It does not emit accuracy or false/missed-alert scores.

The September 23 sample and exact command are documented in the
[real-article test plan](../ideas/jev-real-article-test-20260923.md). Use
`tests/fixtures/jev_observation.yaml` for version 3, which explicitly names the
monitored countries in the state seen by every independent question.

Large requests pool identical source-handling rules into shared state only when
needed to fit the conservative input bound. No source text, candidates or criteria
are dropped; exact fitting requests remain unchanged. The request encoding is
recorded with each call. This can affect cost and behaviour and must be disclosed
when comparing runs. Recovery may rebuild an unsent request only when its absence
from the spending ledger proves that no call was submitted.

For an unlabelled diagnostic run, `--continue-rank-errors` records a Jev selected
choice that contradicts its returned probability ranking as an invalid response,
then proceeds to the other articles. It supplies no replacement classification
and does not count the article as safe. Other failures and summary fallback still
stop the run. `attempted_all: true` distinguishes finishing all attempts from a
clean `complete: true` result; strict validation failures keep `complete` false.
Use reviewed labels, not provider agreement or call counts, to judge correctness.
