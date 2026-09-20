# Clarified model comparison: run record

## Scope and operator decisions

This is an evaluation-only comparison. Production prompts, model selection,
notification transports and server files are unchanged. The input is still the
stored article title and summary, not a fetched full article body.

On 2026-09-20 the operator selected:

- A confirmed strike inside Ukraine very close to Poland, with no Polish incursion
  or resident warning, merits awareness at 5–6 without a phone call.
- A Russian military drone found in Poland after neutralisation merits one initial
  notification at 7–8 even when no danger remains. Same-incident follow-ups remain
  silent. Factual resolved status is independent of this notification preference.

Unknown border side and unsupported Russian origin are not filled in from memory.
Both exceptions apply only within the scope of the operator's answers. A separate
assistant reviewed these boundaries and the resolved-versus-historical distinction
before inference; the existing held-out status labels needed no changes.

## Planned controlled comparison

Each model receives identical reference history, including after an earlier model
failure. No current/future expected answers are sent. Development runs precede the
fresh held-out challenge. Prompts/settings are frozen before held-out inference;
held-out outputs are not used for tuning.

| Model | Pinned provider endpoint | Development budget | Held-out budget |
|---|---|---:|---:|
| `anthropic/claude-haiku-4.5` | `amazon-bedrock/global` | $0.60 | $1.00 |
| `deepseek/deepseek-v4.1-flash` | `deepinfra/fp8` | $0.30 | $0.50 |
| `qwen/qwen3.8-flash` | `alibaba` | $0.20 | $0.30 |
| `openai/gpt-5.6-luna` | `openai` | $0.20 | $0.40 |

The budgets sum to $3.50. Before this round, the evaluation key reported a $5.00
lifetime limit, $0.209251172 used and $4.790748828 remaining. The per-run budgets
are conservative stop limits, not spending targets or guaranteed final charges.
No retries or provider fallbacks are enabled. Requests use a 30-second total
deadline, 1,024 output-token limit, structured JSON and reasoning disabled.
Returned reasoning, provider, cost and errors remain in each raw report.

Public provider endpoints were checked before the run. DeepSeek is deliberately
tested on DeepInfra instead of the first round's Morph route, so its latency
change cannot be attributed solely to the model or the revised prompt. Base
`openai` routing does not opt into the non-default Flex/Fast service tiers.

These provider controls follow [OpenRouter's routing documentation](https://openrouter.ai/docs/guides/routing/provider-selection).
The separation of task-specific measures and held-out evaluation follows
[OpenAI's evaluation guidance](https://developers.openai.com/api/docs/guides/evaluation-best-practices).

## Interpretation boundaries

- Facts, urgency, raw incident matching and provider reliability are separate
  measures, with denominators shown. There is no all-fields intelligence score.
- Assistant-reviewed labels are not human-approved ground truth. Disputed labels
  are excluded from semantic scoring, not from request-cost or latency accounting.
- The held-out set consists of synthetic diagnostic challenges, not representative
  news traffic. A high score is not a production accuracy guarantee.
- Reference-history results do not prove real notification suppression. Runtime
  simulation and actual transport delivery are separate checks.
- The user's $20/month production target is distinct from this $5 evaluation
  allowance. Article-body extraction and production model migration remain out of scope.

## Execution status

Policy, provider preflight and independent development annotation review are
complete. Development contains 36 cases (24 reviewed, 12 disputed); the held-out
set contains 64 cases (63 reviewed, 1 disputed). No version-2 model inference had
been made when these labels were frozen. The development set's disputed initial
reports limit later identity scoring and make its notification chronology
conditional; it will not be used to claim notification reliability.

Frozen SHA-256 identifiers:

- Prompt: `aa4d4ca8853bc1cc0852241bec01faeec065cbe163c1448c7828ba56a33f5115`.
- Response schema: `dddcaa3db1c04203c4a400552acb1227478c70f3d89f5a12f1525fa11a72ef9e`.
- Development fixture: `81bbf9f7f2cf68f4a1951a7b66d02aeae6d5c44475f94d07c9a7ee5dd18d6158`.
- Held-out fixture: `47fc04cfebd51da3354f262e7610b407929342dc15326277dc75b273e3dd1b17`.
