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

## Status

The protocol is recorded before any runtime-mode paid calls. Results will be added
after the saved outputs and actual program decisions have been inspected.
