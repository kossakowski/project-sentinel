# Luna versus DeepSeek: no-send runtime replay

## Scope fixed before inference

The operator requested testing both shortlisted models through Sentinel's memory
and alert logic. This replay uses the existing evaluation runner's `model`
context mode, not the earlier identical-reference-history mode.

- Each model processes the same 36 development articles and 64 challenge articles
  in arrival order. It builds its own temporary event history from its own answers.
- Candidate retrieval, incident confidence/date/country checks, event grouping,
  notification revisions and alert-channel decisions use the repository's runtime
  code. All databases are in memory; Twilio and Expo are replaced by recording
  transports. No real phone call, SMS or push can be sent by this runner.
- The memory feature is enabled only in the local evaluation configuration.
  The remaining classification/alert settings come from `config/config.yaml` and
  are captured in each report. No runtime thresholds or source requirements are
  changed to improve the result.
- The version-2 policy, current-source article inputs, expected labels, provider
  routes and model settings remain unchanged. This deliberately reuses the earlier
  challenge set to test integration; it is not a new independent held-out sample.
- Calls are simulated as immediately acknowledged. Live polling, collection,
  scheduler timing, phone/SMS delivery, retry behaviour and sustained provider
  uptime are outside this test.

## Models, settings and budget

| Model | Pinned provider | Development limit | Challenge limit |
|---|---|---:|---:|
| `openai/gpt-5.6-luna` | `openai` | $0.25 | $0.50 |
| `deepseek/deepseek-v4.1-flash` | `deepinfra/fp8` | $0.25 | $0.50 |

The combined new-run limits are $1.50, within the existing evaluation key's
remaining allowance (to be rechecked before calls). These are stop limits, not
spending targets. Reasoning is disabled, output is capped at 1,024 tokens, requests
have a 30-second total deadline, and retries/fallbacks are disabled.

## Evaluation and limitations

Report actual simulated initial/update/silent outcomes and delivery channels,
then inspect repeat notifications, missed required notifications, wrong event
merges and rejected correct model matches separately. A model's correct matching
proposal can still be rejected by a runtime safeguard; a higher raw-model score
does not establish correct end-to-end behaviour.

The prior annotation audit still applies. Do not rank exact numeric urgency or
aggregate status grades. Twelve development cases and one challenge case are
disputed. Development notification chronology is conditional where the first
reports are disputed; use it for diagnostics, not a clean notification accuracy
percentage. Compare the challenge set's notification labels separately from model
scores, and explain intended corroboration/channel gates rather than classifying
all withheld calls as model failures.

This stage follows the component-versus-workflow distinction in
[OpenAI's evaluation guidance](https://developers.openai.com/api/docs/guides/evaluation-best-practices).
No production files, settings, model choice or server state are changed.

## Results

Both models completed all 100 API requests with no provider/parsing failures or
unknown charges. Results below use the corrected phone simulator described later.
No production alert was sent. The challenge set is a reused integration corpus,
not a fresh independent estimate of real-world accuracy.

### Challenge set: 63 scored cases

One pre-identified disputed case is excluded. Forty scored articles require an
initial notification or an update; the others should stay silent.

| Measure | Luna | DeepSeek |
|---|---:|---:|
| Correct initial/update/silent decision | 62/63 | 51/63 |
| Required notifications delivered in simulation | 39/40 | 40/40 |
| Missed critical notification | 0 | 0 |
| Missed awareness notification | 1 | 0 |
| Notifications on articles expected to stay silent | 0 | 4 |
| Updates incorrectly treated as a new initial alert | 0 | 8 |
| Simulated phone calls (16 expected) | 16 | 28 |
| Correct model matches rejected by runtime guards | 1 | 12 |
| Median / p95 API response time | 3.06 / 3.82 seconds | 9.49 / 15.53 seconds |

The Luna guard rejection was a low-urgency political-commentary match; it stayed
silent and did not cause a wrong notification. All twelve DeepSeek guard
rejections above caused unnecessary new phone calls: four repeated critical
reports and eight developments that should have generated update messages, not
another call.

### Development diagnostics: 24 scored cases

Twelve cases are disputed. As specified before the run, these numbers are
diagnostic because some sequence roots have conditional notification labels.

| Measure | Luna | DeepSeek |
|---|---:|---:|
| Exact initial/update/silent outcome | 24/24 | 15/24 |
| Unexpected notifications on expected-silent articles | 0 | 7 |
| Of those, same-incident repeat notifications | 0 | 6 |
| Required critical notification undercalled | 0 | 1 |
| Correct model matches rejected by runtime guards | 0 | 5 |
| Median / p95 API response time | 3.03 / 4.12 seconds | 9.95 / 22.32 seconds |

DeepSeek scored the explicit resident air-raid warning in `mc-scramble-pl-06` at
6 and generated a push rather than the required critical call. Its repeated
notifications in the scramble and Rusinowo sequences are consistent with the
confidence-gate mechanism observed in the cleaner challenge cases.

## What caused the differences

**DeepSeek is not a drop-in fit for the current confidence guards.** Its model
often identified the correct existing incident, but the confidence it supplied was
below the configured matching cutoff. Sentinel then rejected that match, created a
new event, and correctly applied the alert rules to that new event. The result was
unnecessary repeat phone calls even though the model's raw incident identity was
usually correct. The raw/accepted identity figures on the challenge set were
62/63 versus 50/63. Luna's were 62/63 versus 61/63.

Examples of the rejected correct DeepSeek matches:

- `v2h-en-02-b`, `v2h-ru-03-c`, `v2h-uk-02-b` and `v2h-uk-03-c` should have stayed silent,
  but each became a new event and phone call.
- The eight `*-02-c` and `*-04-c` escalation cases should have remained in the
  already-called incident and generated updates; each became a new event/call.

Do not simply lower the safety cutoff to make these results pass. Model confidence
is not a calibrated probability. A weaker guard could suppress a genuinely new
attack by accepting a wrong match. Threshold calibration, evidence-based matching
and false-merge tests are a separate change, not part of this replay.

**Luna has observable answer variability.** For `v2h-ru-01-a`, it returned urgency
5 in the earlier controlled run but 3 in this runtime run. The saved model-message
hash is identical in both: `0563d8bbcf1c2d6673450cf9ba8d1f283dfea171f17c296dfc7dec70518f6622`.
Both requests had empty history. Therefore this error cannot be attributed to the
runtime memory contents. The article describes a Lithuanian precautionary aircraft
launch; the lower score suppressed the required awareness notification. Sampling
was left at the provider defaults; this test does not establish deterministic
answers or quantify a real-world failure rate.

## Simulator correction and zero-cost verification

The initial no-send phone override recorded an acknowledged phone call but omitted
the confirmation and follow-up SMS records that the production flow creates. In
the Luna development run this produced a spurious SMS at `mc-scramble-pl-07`, after
the earlier precautionary episode had escalated to an acknowledged call.

An independent read-only code audit and an in-memory reproduction traced the
effect. The runtime state machine was correctly filling an apparently missing SMS
channel for the current revision; the simulator had supplied incomplete state.

The fix is confined to `RecordingAlerts` in the evaluation runner. It now invokes
the real confirmation-SMS and acknowledgement/follow-up helpers against fake
recording transports. It still bypasses live telephony, inbound SMS polling,
waiting and retries. The regression test checks precaution → critical call →
routine follow-up produces initial → update → silent, including both SMS records
for the acknowledged call.

All 200 saved raw model responses were then replayed offline using
`sentinel.eval.cached_runtime`. The tool restored original event IDs and verified
every model-message hash before using its saved response. All hashes and raw
answers matched. No new model call was needed, no original report was overwritten,
and no expected label or prompt was changed. The spurious Luna development SMS
disappeared; DeepSeek's confidence-related repetitions remained.

Original local reports:
`data/eval/v2-runtime-{development,holdout}-20260920-{luna,deepseek}.json`.

Corrected derived reports:
`data/eval/v2-runtime-{development,holdout}-20260920-{luna,deepseek}-corrected.json`.

Original API costs and response times are preserved as historical evidence in the
derived reports. They are not new replay charges or newly measured latency.

## Cost, checks and recommendation

| Paid run | Cost |
|---|---:|
| Luna development | $0.01584610 |
| Luna challenge | $0.02831015 |
| DeepSeek development | $0.0085104208 |
| DeepSeek challenge | $0.0125268416 |
| Total new API cost | **$0.0651935124** |
| Corrected offline replays | **$0** |

The key reported $0.830965486 cumulative usage and $4.169034514 remaining after
this stage, within its original $5 allowance. Small sub-microdollar differences
from returned charges are rounding. No production model or notification spending
was changed.

Verification: 525 offline software tests passed; focused tests after the exclusive
output-write guard also passed. Formatting, lint and whitespace checks passed.
Both paid runs per model finished successfully. All four corrected reports were
reopened and checked against the raw responses and message hashes. Production
classifier, memory thresholds, alert code/config and server files are unchanged.

**Recommendation:** Luna remains the better candidate for this particular runtime.
It avoided the repeat-alert problem in the scored replay and was faster. It is
not perfect: investigate the inconsistent awareness classification and test fresh
news plus repeated identical inputs before switching production. DeepSeek would
need separate confidence calibration and safety testing before being considered
as either the primary classifier or an automatic fallback.
