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

## Development results

All four models completed all 36 calls without provider or parsing errors. Twelve
disputed cases are excluded from semantic counts. Identity is scorable on only 14
of the remaining 24 cases because disputed anchor reports are not seeded into
reference history. These smaller denominators are not treated as perfect scores.

| Model | Exact urgency | Alert-action band | Attack country | Protection | Status | Raw incident identity | Critical score undercalls | Median / p95 seconds | Reported cost |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Haiku | 16/24 | 16/24 | 23/24 | 23/24 | 12/24 | 13/14 | 1 | 5.19 / 10.25 | $0.168600 |
| DeepSeek | 17/24 | 18/24 | 23/24 | 23/24 | 15/24 | 13/14 | 0 | 7.32 / 13.47 | $0.008677 |
| Qwen | 17/24 | 17/24 | 18/24 | 23/24 | 14/24 | 14/14 | 0 | 6.61 / 10.58 | $0.009867 |
| Luna | 21/24 | 21/24 | 20/24 | 24/24 | 15/24 | 14/14 | 0 | 2.90 / 4.79 | $0.016942 |

Haiku classified the explicit Polish resident air-raid warning in
`mc-scramble-pl-06` as a precaution at urgency 6. It also proposed merging the
explicit separate wave in `mc-synth-escalation-03` into an earlier episode. The
latter is a raw model decision, not an observed missed real or simulated phone
call: reference mode does not run the notification pipeline.

Total reported development cost was $0.2040870324 for 144 calls. The key endpoint
reported $0.412124733 cumulative usage immediately before held-out inference;
provider charge reporting can lag, so returned call costs and key usage are kept
separate rather than forced to reconcile prematurely.

All shared per-case request hashes agree across the four models. No prompt,
policy, model or hosting settings were changed after inspecting development
results. The next step uses the unchanged bundle on the 64 held-out cases.

Raw local reports: `data/eval/v2-development-20260920-{haiku,deepseek,qwen,luna}-reference.json`.

## Held-out results and recommendation

All four models completed all 64 held-out calls without provider/parsing errors,
unknown charges or observed reasoning output. One pre-identified disputed case is
excluded, leaving 63 scored cases, including 32 critical-labelled reports. A
critical report can be a follow-up, so this is not a count of independent attacks.

| Model | Alert-action band | Attack country | Locally affected countries | Protective measure | Raw incident identity | Critical score undercalls | Median / p95 seconds | Reported cost |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Haiku | 63/63 | 52/63 | 62/63 | 60/63 | 60/63 | 0/32 | 4.84 / 6.38 | $0.293220 |
| DeepSeek | 62/63 | 57/63 | 62/63 | 59/63 | 62/63 | 1/32 | 7.56 / 14.67 | $0.014147 |
| Qwen | 63/63 | 32/63 | 42/63 | 60/63 | 60/63 | 0/32 | 6.82 / 9.12 | $0.016584 |
| Luna | 63/63 | 63/63 | 60/63 | 59/63 | 63/63 | 0/32 | 3.05 / 3.83 | $0.028483 |

**Recommendation: Luna is the strongest candidate for the next integration/shadow
test, not an approved production replacement.** It was strongest on development
alert bands and held-out attack geography/identity, and had the lowest observed
latency. It was not best on every field: Haiku and DeepSeek did slightly better on
locally affected countries, and Haiku/Qwen did slightly better on protective
measures. These selected synthetic cases do not establish global intelligence or
real-world reliability percentages.

Important observed failures:

- DeepSeek scored `v2h-ru-04-c` at **3**, despite the current source explicitly
  describing a missile hitting a Polish air base, injured personnel and an active
  continuing threat. Its memory output called the same event an escalation. This
  is a genuine internal inconsistency, not the numeric 9-versus-10 grading issue.
- Haiku proposed three wrong merges on the held-out set, linking geographically
  distinct precautionary episodes. Runtime confidence/country guards could reject
  those proposals; this reference run does not claim they caused suppressed alerts.
- Qwen frequently left `attack_countries` empty even for explicit hostile impacts.
  For example, `v2h-en-01-b` quotes a missile hit in Lithuania but returns `[]`.
  Two identity errors returned `duplicate` with a null target; another returned
  `uncertain` for a clearly different country/incident. The production gate would
  reject an invalid duplicate target.
- Luna still made affected-country/protection errors and some unsupported resolved
  status assertions. Perfect action-band and identity results on these controls
  are not proof that it will never miss a real alert.

Raw local reports: `data/eval/v2-holdout-20260920-{haiku,deepseek,qwen,luna}-reference.json`.
All 64 shared per-case request fingerprints agree across models. The frozen prompt,
schema and both dataset hashes were unchanged throughout paid inference.

## Post-freeze annotation limitations

Inspection exposed a problem in the *fine-grained grading*, not a reason to rerun
models or rewrite the frozen test to favour a result. A separate assistant audited
the labels against the frozen prompt without seeing model outputs or names:

- **35 of the 63 scored cases have unsupported narrow numeric ranges.** For example,
  16 official-warning cases demand exactly 9 although the prompt permits 9–10, and
  8 impact/escalation cases demand exactly 10 without specifying how to distinguish
  9 from 10. Other discrepancies concern allowed low scores within the silent band.
  Across all 64 cases, 36 are affected, including the already-disputed case.
- **14 scored status labels assert `active` without explicit ongoing state.** These
  are each language's `*-01-a`, `*-01-d`, `*-03-d`, plus `v2h-uk-02-d` and
  `v2h-ru-01-c`. They should not be treated as definitive evidence that a different
  current-status answer is wrong. An unsupported `resolved` assertion can still
  be a model error; the disputed distinction is not automatically a model pass.
- The audit found no systemic contradiction in the protective-measure labels.
  Broad action bands/criticality, geography and identity remain usable. Categorical
  notification labels can be used in a separate runtime test, but no notifications
  were simulated in this reference run.

Consequently **exact numeric accuracy and aggregate status accuracy are not used
to rank models here**. The original raw results remain intact: exact-score counts
were Haiku 57/63, DeepSeek 58/63, Qwen 52/63, Luna 49/63, but those numbers are not
a fair accuracy comparison. All 14 of Luna's exact-score mismatches were allowed
10s against labels demanding 9. No prompt, label or setting was changed based on
these held-out outputs. Before future reuse, correct those annotations in a new
version and reserve fresh held-out cases for any subsequent tuning.

The original JSON summaries also carry a legacy top-level `identity_unscorable`
counter that does not describe reference mode correctly. This report uses the
independent dimension numerators/denominators, not that counter. A reporting-only
fix removes that legacy field from future version-2 summaries; it changes no
model request, frozen label, raw output or dimension score in this run.

## Cost and the $20/month target

The complete version-2 experiment made **400 calls** (100 per model) and reported
**$0.5565209268** in charges. Final key usage was **$0.76577204** including the first
round, leaving **$4.23422796** of its original $5 allowance. This reconciles with
reported charges to normal decimal rounding. No production billing changed.

The following estimates use the previously observed 5,917 classifications/month,
the average tokens in these 100 test calls per model, and the pinned provider's
advertised uncached input/output rates. Cached tokens are deliberately charged at
the full input rate for this estimate; observed cache savings are not assumed.

| Model | Test input / output tokens | Uncached input / output price per million | Classification estimate/month |
|---|---:|---:|---:|
| Haiku | 295,030 / 33,358 | $1.00 / $5.00 | $27.33 |
| DeepSeek | 194,359 / 34,172 | $0.14 / $0.42 | $2.46 |
| Qwen | 201,533 / 35,314 | $0.15 / $0.47 | $2.77 |
| Luna | 214,473 / 26,107 | $0.20 / $1.20 | $4.39 |

Formula: `5917 / 100 × (input_tokens × input_price + output_tokens × output_price) / 1,000,000`.

These are **classification-only, benchmark-sized-input estimates**, not measured
monthly bills or guarantees. They exclude other model calls, article-body analysis,
retries, credit-purchase fees and messaging/phone costs. Real traffic and future
prices can differ. Haiku's $27.33 estimate is not a correction to the previously
observed $22.18 bill: the new prompt/output contract and sample differ. Luna leaves
substantial headroom beneath $20 for further model work, but the actual proposed
full-article pipeline needs its own measured budget and a spending cap before launch.

## Next step

Test Luna through Sentinel's actual candidate retrieval, confidence gates and
notification state machine with real sending disabled. Then assess full-article
verification separately. Do not deploy a model change or claim the memory issue
is solved merely because controlled reference matching passed.

Verification: 515 offline software tests passed after the reporting-only fix;
formatting/lint and diff checks passed. All 400 saved completions were reopened
and checked for completion, errors, identical shared inputs and unchanged frozen
prompt/dataset hashes. No scored case combined an expected and predicted urgency
of at least 5 with `is_military_event: false`. No real notification was sent and
no production file, prompt, model setting or server state was changed.
