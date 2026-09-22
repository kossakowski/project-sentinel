# Jev hybrid pipeline experiment — 2026-09-23

Keep Luna in production. The revised Jev experiment fixed the six known country failures and performed well in simulated alert routing. This sequential hybrid did not deliver a speed or cost advantage once Luna summary generation was included. Fresh labels remain provisional and require human review.

## What changed

- Jev questions now use full country names, including native names, to separate Lithuania and Latvia.
- Code adds explicitly attacked monitored countries to the affected-country list. Raw answers and the additions remain visible in diagnostics.
- Incident identity is judged separately from duplicate/update/escalation. Existing runtime confidence thresholds were preserved, not assumed calibrated.
- Jev produces all structured runtime fields and selects supporting source spans. Luna separately writes Polish summaries, with the existing language guard.
- The replay exercises actual candidate retrieval, memory validation, grouping and alert routing against independent in-memory databases. Recording transports simulate immediate acknowledgement. Polling, real delivery and call-retry timing were not tested.

## Dataset and interpretation

Forty new assistant-authored synthetic articles were frozen before inference in commit `7c3dee5`: ten each in PL/EN/RU/UK. They are four related scenario families, not forty statistically independent incidents. All labels are still provisional. Review [the exact inputs and expected outcomes](../ideas/jev-fresh-case-review-20260923.md). Neither original pilot labels nor production policies were changed.

The previous 64-case reference-context pilot and this runtime-context test are different experiments. Each pipeline now retrieves its own remembered events and summaries. Scores below describe agreement with provisional test expectations, not measured real-world accuracy.

## Results

| Measure | Jev + Luna summaries | Luna |
|---|---:|---:|
| Notification outcome | 40/40 | 40/40 |
| Urgency action band | 40/40 | 38/40 |
| Affected-country set | 40/40 | 39/40 |
| Attack-country set | 38/40 | 27/40 |
| Protection measure | 40/40 | 40/40 |
| Incident status | 34/40 | 32/40 |
| Raw incident identity | 40/40 | 40/40 |
| Accepted incident identity | 39/40 | 40/40 |
| Raw new/duplicate/update/escalation decision | 40/40 | 40/40 |
| Median pipeline time | 3.427 s | 3.088 s |
| 95th-percentile pipeline time | 4.330 s | 3.833 s |
| API requests | 80 | 40 |
| Estimated experiment cost | $0.02609230 | $0.02228030 |

Both pipelines recorded 8 simulated calls, 20 SMS records and 16 push records. Required critical notifications were not missed, and there were no duplicate or false notifications under these expectations. All 80 summaries passed the local Polish-language check without fallback. Summary factual fidelity was not independently graded.

Timing uses 38 uncached cases per pipeline; cases with any cached response were excluded. Jev classification and Luna writing ran sequentially. The hybrid median was 11.0% slower and its inference estimate 17.1% higher in this run. Parallel writing could change latency; these results do not establish an inherent Jev speed disadvantage.

## Remaining issues

- Jev omitted an attack country in two reports about neutralised missile waves. These reports name cities and refer back to prior events; the strict current-source geography expectations deserve human review.
- Jev had six status disagreements, all in denial or hypothetical-report cases. Luna had eight. The distinction between no incident, resolved danger and historical content remains important; the labels have not been independently approved.
- One correct Jev identity match for a low-urgency Russian resolution report was rejected by the existing confidence gate (0.74). It produced no repeat alert in this run. This is evidence that identity accuracy and accepted runtime identity must be measured separately.
- Luna retained urgency 10 for a fully neutralised Latvian missile wave and urgency 5 for a fully neutralised Polish wave. Existing incident state suppressed additional notifications, so notification success alone concealed these classification disagreements.
- Two optional Jev quotation answers were inconsistent with their returned probability rankings. Invalid quotes were discarded; core answers remained validated. This does not establish the accuracy of the other selected evidence spans.

## Regression and spending

Applying the geography invariant to the first pilot’s saved outputs improved affected-country agreement from 57/63 to 59/63 without new model calls. A separate live regression reran only the six known country failures using the revised questions: **6/6 matched**. This is a known-error check, not fresh validation.

The full pipeline experiment cost an estimated **$0.04837260**. The six-case regression added **$0.00285230**. Including the original pilot, combined estimated spending is **$0.10017969**, below the original $0.25 cap. The final ledger contains 254 settled requests and no unresolved reservations. Estimates are not reconciled invoices.

The first pipeline attempt stopped on an invalid optional quotation. The recovery reused five exact saved API responses and copied the ledger. No completed request was sent again. Model prompts, cases and expectations stayed frozen; only optional-quote handling and recovery changed. The original attempt remains intact.

- Original stage-two evidence: `data/eval/jev-pipeline-live-20260923/`.
- Completed stage-two evidence: `data/eval/jev-pipeline-live-20260923-complete/`.
- Geography regression and latest cumulative ledger: `data/eval/jev-country-regression-20260923/`.
- Cached geography audit: `data/eval/jev-geography-audit-20260923.json`.
- Reproduction instructions: [Jev pipeline test](../how-to/jev-pipeline.md).
- Code verification: **609 local tests passed**, with Ruff and whitespace checks.

| Evidence artifact | SHA-256 |
|---|---|
| jev-pipeline-live-20260923-complete/manifest.json | `58bf115fdd5a06c2ee56c1b1d73e8c0642092a0f8a14e50e0e89382f95ef8627` |
| jev-pipeline-live-20260923-complete/calls.jsonl | `65cd69e718b5fcd9cade4ec552e4245917eee57382c9eac3f6ccfd8b721bc337` |
| jev-pipeline-live-20260923-complete/results.jsonl | `2bbbef898f013af89cd276ff80f88609299fd1250e15c6fe9ee53bae3a85b3c3` |
| jev-pipeline-live-20260923-complete/report.json | `a4759c3cab73808bbec60611b0b8b4c39d2eb504904a19ead1304e7d55b01895` |
| jev-country-regression-20260923/report.json | `541ac42dfb29b167ad11069d79bb0baa69ac53be6b3802b7f6d046ea5b3d710b` |

## Recommendation

Keep the production classifier unchanged. Obtain human review of the provisional labels, then evaluate representative real articles before deciding whether Jev’s factual benefits justify another model dependency. Do not lower confidence gates on the strength of this small synthetic run.
