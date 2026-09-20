# Direct Luna validation — qualified result

Date: 2026-09-20. Operator-approved total test allowance: **$0.25**.
Provider: direct OpenAI API, `gpt-5.6-luna`, explicit reasoning `none`, standard
service tier, strict structured output, no immediate retry or provider fallback.

**All 20 prepared cases passed the automated danger-band, affected-country and
notification-decision checks. The complete output contract did not pass: one
critical alert summary was Ukrainian instead of Polish.** Five diagnostic
repetitions reproduced that language failure. Do not describe this as a clean
production-readiness pass.

## Prepared run

Ten requests repeated the exact earlier Lithuanian precautionary-flight input,
each with empty memory. All ten scored urgency 5 and generated the expected
simulated awareness notification. Every model-message hash matches the frozen
original:
`0563d8bbcf1c2d6673450cf9ba8d1f283dfea171f17c296dfc7dec70518f6622`.
This did not reproduce the historical urgency-3 miss; it does not disprove that
failure or establish deterministic output.

Ten fresh synthetic cases covered PL/EN/UA/RU input, precautionary activity,
duplicate reporting, escalation within an incident, a separate attack wave,
resident shelter orders, a Ukrainian strike near Poland, unknown geography,
a neutralised Russian drone in Poland and conventional exercises. Expected
labels were committed before inference. They are engineering expectations,
not human-approved ground truth, and this set is now seen.

All ten matched their three automated behavioural checks. The recording
transports logged the expected three critical calls, with six accompanying SMS
records and seventeen pushes across the entire twenty-case run. Every transport
was a fake; no phone, SMS or push was actually sent. Event databases were in memory.
The test does not cover live polling, fetched article bodies, actual delivery,
or sustained provider availability.

## Reproduced Polish-language defect

The initial `fresh-lv-warning` result assigned the correct critical urgency and
Latvian geography, but copied the Ukrainian source language into `summary_pl`.
The automated runner's `passed` field checks danger band, countries and initial/
update/silent outcome; it does **not** validate summary language. Manual review
found this separate contract violation despite the report's zero automated failures.

Five further requests used exactly the same Latvian-warning model messages,
empty context and unchanged prompt/schema. Their message hashes match the initial
case. Four returned Polish summaries; one returned Ukrainian. Across these six
requests, all critical scores were 10, but **two of six summaries were Ukrainian**.
All summaries were read manually; the Cyrillic flag in the follow-up file was a
diagnostic aid, not a complete Polish-language detector. This tiny targeted sample
does not estimate a real-world error rate.

No prompt, policy, model, threshold, expected label or alert guard was changed in
response to these findings. The remaining rollout issue is Polish-output reliability.
A follow-up safeguard should preserve the accepted urgency and incident identity;
discarding a critical classification solely for a language error can delay an
important warning. A bounded Polish translation would add a request and latency;
its failure behaviour needs to be designed explicitly before rollout.

## Spending and retained evidence

| Run | Requests | Conservative ledger estimate |
|---|---:|---:|
| Prepared validation | 20 | $0.00802777 |
| Identical Latvian-input repetitions | 5 | $0.00177735 |
| Total | **25** | **$0.00980512** |

The follow-up used the remainder of the original $0.25 allowance, not a fresh
allowance. Remaining allowance: **$0.24019488**. All 25 ledger entries are settled;
there are no unresolved-charge reservations. Estimates include the configured
conservative cache-write premium and are not a reconciled provider invoice.

The prepared run recorded 38,993 input tokens, including 34,376 cached tokens,
and 5,155 output tokens. This test-specific cache benefit must not be extrapolated
directly to normal news traffic.

Local raw evidence, retained without overwriting:

- `data/eval/luna-direct-validation-20260920.jsonl`, SHA-256
  `3a35db64e4b0950caee44eab0eca7d10519fb0cff6694b1d7a7054c8b3eba7bd`.
- `data/eval/luna-direct-language-repeat-20260920.jsonl`, SHA-256
  `2ebfbaf2764050ad8ae1916b46356a43538deddeba5a2f3e9608a3a3a975e777`.

Verification: both reports were reopened; request counts, message hashes, scores,
notifications, summary languages and the persistent usage ledger were checked.
No production deployment or real alert occurred. The account's automatic-reload
setting was not changed by this test.
