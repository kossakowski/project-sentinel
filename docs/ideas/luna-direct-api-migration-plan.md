# Direct Luna migration — local implementation plan

Date: 2026-09-20. Target: direct OpenAI `gpt-5.6-luna`. Production deployment
requires separate permission. Account setup is the final step, after coding and
offline verification, as requested by the operator.

## Evidence and scope

The [runtime comparison](model-runtime-comparison-20260920.md) supports Luna as
the selected candidate, but records one inconsistent Lithuanian precautionary
scramble classification. Neither that reused synthetic corpus nor mocked software
tests prove real-world detection reliability. Preserve all frozen evidence.

The current classifier owns an Anthropic client; the enrichment quality gate also
uses Anthropic and borrows the classifier model. CLI/eval constructors need client
cleanup. There is no production response cache: URL deduplication is historical
processing state, not a model cache. Dedup inserts articles before classification,
so failures currently become permanently seen. Fix that with an explicit durable
queue for newly selected articles; do not replay the historic database wholesale.

## Implementation

1. Add an explicit provider setting. Retain the legacy Anthropic prompt/provider
   for deliberate rollback, with no automatic paid fallback. Existing configs
   without the setting retain their old provider. Local/example config selects
   OpenAI, the approved clarified policy, and the tested incident-memory path.
2. Move the exact clarified prompt builder and factual schema into runtime-owned
   code. Evaluation imports that shared contract; retain identical message hashes.
   Store operator policy in application configuration. No new prompt tuning or
   threshold changes are part of this migration.
3. Use AsyncOpenAI Responses with strict JSON schema, explicit reasoning `none`,
   `store=false`, bounded output and total timeout, and SDK retries disabled.
   Validate JSON types/ranges, refusals, incomplete output, token accounting and
   model identity. Raise safe actionable errors; never synthesize a safe score.
4. Persist provider/model/prompt/request provenance, factual output and cached-token
   usage through additive schema changes. Existing incident IDs and notification
   revisions remain intact. Never use old classifications as fresh model output.
5. Persist reservations and settled token costs in a shared SQLite usage ledger.
   Reserve conservatively before each request, keep reservations for ambiguous
   failures, and stop new paid calls at the configured monthly allowance. Include
   the existing enrichment quality gate in the same OpenAI allowance. This is an
   application guard at configured prices, not a provider-wide billing guarantee.
6. Queue relevant articles before enrichment/classification. Retry failures on
   later cycles with backoff, preserving article identity and chronological order.
   Persist grouping and queue completion together. Expose pending/error state in
   health output. Do not erase old events, alerts or unsuccessful work.
7. Migrate the existing enrichment quality gate to the selected provider without
   expanding article scraping. Keep its heuristic and body-fetch behaviour.

## Budget and safety decision

The operator's maximum model objective is $20/month. At the limit or on exhausted
credit the service cannot continue paid classification: keep work pending and
report degraded health prominently. This creates a detection gap; silently
exceeding the budget or reporting safe classifications would be worse. Before
production approval the operator must accept this stop policy or authorise a
different spending policy. Do not introduce an automatic alternative model.
Project dashboard alerts alone are not a verified hard cap. Other programs using
the key/account, fees and Twilio spending are outside this ledger.

## Verification and final API setup

Run offline regression tests covering exact prompt parity, strict parsing,
provider selection, no Anthropic requirement in OpenAI mode, errors/refusals,
budget reservation/restart/concurrency, durable failure retry, additive migration,
event identity, client cleanup and no real transports. Prepare a no-send direct
test command with an explicit dollar cap, repeated known-miss inputs, fresh
multilingual cases and broad notification expectations fixed before API calls.

After coding, use a visible Playwright browser, inspect existing tabs and select
an unambiguous dedicated Sentinel project. Ask only for sign-in/private billing
details, organisation ambiguity, purchase confirmation and explicit test cap.
Never capture generated keys in snapshots/logs/chat; transfer directly to the
ignored `.env` securely or let the operator perform the sensitive local paste.
No purchase or automatic recharge is authorised by this plan.

Live validation must check direct access, reasoning disabled, request/message
hashes, costs and no-send runtime behaviour. Repeated scores quantify variability
only for these inputs. Report the known awareness miss even if later calls pass.

## Deployment and rollback boundary

After local verification, commit/push the scoped code and report remaining live
gates. Follow the [server runbook](../how-to/server-runbook.md) only after explicit
deployment permission. Back up SQLite/config, install the new key securely, use
writable absolute ledger paths, apply only reviewed config fields, and verify
health and cost accounting. Do not copy local secrets or replace live config.
Rollback explicitly selects Anthropic and its legacy model/prompt, retains the
Anthropic credential and database history, and preserves queued articles. Never
restore an old database over newer alert history: that could repeat phone calls.

## Official references checked

- [Luna model, reasoning and rates](https://developers.openai.com/api/docs/models/gpt-5.6-luna).
- [Structured outputs and refusal handling](https://developers.openai.com/api/docs/guides/structured-outputs).
- [OpenAI Python SDK](https://github.com/openai/openai-python): asynchronous Responses,
  explicit timeout/retries and client cleanup, checked through Context7.

## Local verification record

Implemented on 2026-09-20. All **557 offline tests passed** in a fresh full run.
Ruff and whitespace checks passed. The offline direct-test command loaded twenty
cases without API calls. A missing-key startup check produced an actionable error.
The direct SDK tests use HTTP mock transport with the installed OpenAI 2.54.0 SDK;
the no-send runner also exercised that real SDK/classifier plus memory, grouping,
and fake notification transports. The known-miss message hash remains exactly
`0563d8bbcf1c2d6673450cf9ba8d1f283dfea171f17c296dfc7dec70518f6622`.

The retry regression verifies recovery after database reopen without refetching,
unchanged article identity, one event, and no second classification on a later
duplicate URL. Grouping failures roll back classification/event insertion together.
Usage tests cover concurrent callers, restart, refusals, incomplete output, malformed
JSON, exhausted credit, rate limits, timeout, missing usage and both spending caps.

No paid direct OpenAI request has been made yet. Browser billing/key setup and the
explicitly capped live run remain the final gates. No production files, credentials,
services or notification transports were changed or invoked. The historic awareness
miss is still unresolved; moving the prompt unchanged cannot establish its cure.

### Operator budget update

On 2026-09-20 the operator selected a **$10 monthly limit**, superseding the
original $20 ceiling as the active allowance, and reported adding $10 credit.
Local/example YAML and the code default now use $10. Current OpenAI documentation
also describes enforced project spend limits, separately from spend alerts;
account setup must verify the actual hard-limit setting. Added explicit handling
for project/organisation spend limits, exhausted credit and assigned usage limits.
The focused configuration/direct-provider run passed **49 tests** after this change.

### Account setup verification

Completed through the Playwright Chrome extension on 2026-09-20, using the
operator's normal Chrome profile and no desktop app. Created the dedicated
**Project Sentinel** project and its **$10/month enforced hard spend limit**.
The saved project page explicitly states that requests fail at the limit.
OpenAI documents slight possible overshoot while enforcement propagates.

Created `sentinel-luna-local`, restricted to Responses write and model-list read
permissions, with no automatic expiration. Transferred its value directly to the
ignored local `.env` through a one-shot loopback receiver, without returning the
key in chat/tool output. Verified file mode `0600`, Git exclusion, and no generated
key in browser diagnostic files. Direct `GET /v1/models/gpt-5.6-luna` returned HTTP
200 and the requested model ID; this checks authentication/access without inference.

The billing UI confirmed $10 credit. It also showed automatic reload enabled
(balance below $5 reloads to $10, without a monthly reload cap); this account-level
setting was not changed, and the operator was asked whether to disable it.
Paid inference validation remains pending the separately requested $0.25 test
allowance. No live classification, real notification or production deployment has
been performed as part of this setup.

### Subsequent approved live validation

The operator subsequently approved the $0.25 test. See the
[direct validation record](luna-direct-api-validation-20260920.md): all twenty
prepared behavioural checks passed, but manual review found a non-Polish critical
summary and five diagnostic repetitions reproduced it. All 25 requests together
used an estimated $0.00980512. Polish-output reliability remains a rollout issue;
production is unchanged.

### Polish-summary fix verified

The operator requested the fix after the language defect was reproduced. See
[Polish summary guard](polish-summary-guard.md): local language validation, one
bounded same-Luna translation, and an explicit Polish fallback notice that retains
the original danger and incident decision. All 581 offline tests, twenty live
runtime-regression cases and six component language checks passed. Total direct
validation spending across the migration remains approximately $0.01802 of the
approved $0.25 allowance. SSH access was verified read-only; no deployment occurred.
