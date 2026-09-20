# Polish summary guard

The direct-Luna test found a critical Latvian warning summarized in Ukrainian
in two of six identical requests. This change adds `polish-summary-v1` after
strict classification parsing. The frozen classification prompt and schema stay
unchanged, preserving the earlier comparisons and model-message hashes.

A local Lingua detector checks Polish against the configured language set. An
explicit Cyrillic-script check also catches untranslated or mixed-script output.
These are statistical/script checks, not proof of meaning, grammar or accuracy.
The existing 25-result evidence set was checked before implementation: both
Ukrainian failures were rejected; all 23 Polish summaries were accepted.

A rejected summary gets at most one same-provider translation request, containing
only the original summary. The response schema accepts only `summary_pl`, so
repair cannot change danger, geography, confidence, facts or incident identity.
The translation prompt is versioned and hashed. Normal Polish output costs no
additional API request. Repair uses the same monthly ledger and remaining test
allowance, explicit reasoning `none`, bounded output and a shorter total deadline.

If repair fails, is refused, hits the budget, or remains non-Polish, use the
configured Polish notice that the summary is unavailable. Preserve the original
accepted classification and pass it to normal corroboration/notification rules.
This avoids delaying a critical warning solely because its summary is in the
wrong language. The trade-off is fewer narrative details in that fallback alert;
linked source articles remain available. No new danger or attack facts are invented.

Persist original text, action (`unchanged`, `translated`, `fallback`), repair
prompt/request hashes and response ID in the additive `summary_processing` column.
Old records and event IDs are preserved. Returned token/cost totals include both
successful provider replies; refused/incomplete/unknown-charge repair attempts
remain accounted in the authoritative usage ledger even if no reply is returned.
The primary request hash/response ID still identifies the classifier request.

The guard is in the direct OpenAI path. Explicit legacy Anthropic rollback keeps
its original behaviour. Local/example options live under
`classification.summary_language`; no detection/corroboration threshold changes
are part of this fix. Production deployment still needs separate permission.

Validation must cover unchanged Polish, the saved failures, English and mixed
script, one bounded repair, metadata persistence and token accounting, plus
refusal/timeout/quota/budget/non-Polish repair failures followed by the expected
simulated critical call. The direct evaluation runner now grades Polish output
and treats a generic fallback as a degraded result, separately from notification
correctness. Fresh translation-only cases are fixed in
`tests/fixtures/polish_summary_guard_fresh.yaml` before paid calls.

## Verification completed on 2026-09-20

- All **581 offline tests passed** in a fresh full run. Ruff and whitespace checks
  passed. Tests include timeout, refusal, quota exhaustion, budget refusal,
  malformed translation, repeated foreign-language output and preserved critical
  notification delivery through fake transports.
- All **20 reused runtime-regression cases passed**, including the new Polish
  output check. Nineteen summaries were already Polish. The Latvian case again
  initially arrived in Ukrainian; the guard translated it to Polish while keeping
  its critical urgency 10 and expected notification outcome. No fallback was needed.
- Both saved Ukrainian failures were translated successfully. Three fresh
  translation-only inputs (English, Ukrainian, Russian) also passed. Their Polish
  results were read manually against the source for geography, negation, uncertainty
  and timing. The fresh Polish input stayed byte-for-byte unchanged with no API call.
  These are six language checks, five paid requests. The synthetic fixture is now seen.
- The runtime-regression run used 21 API requests including one repair, estimated
  $0.00752276. The five component translations used $0.00068860. The fix's live
  verification therefore used 26 requests, estimated **$0.00821136**.
- Including the earlier validation and diagnosis, the persistent ledger has 51
  settled requests and estimated total **$0.01801648**, within the originally
  approved $0.25 test allowance. Remaining allowance: **$0.23198352**. No unresolved
  reservations, real alerts, or production changes occurred.

Raw evidence was reopened and retained locally without overwriting earlier results:

| Artifact under `data/eval/` | SHA-256 |
|---|---|
| `luna-direct-polish-guard-20260920.jsonl` | `2478a35ca647a3f0e690467932e18dc2a8680861296fda442556d25b4c0755d2` |
| `polish-summary-repair-live-20260920.jsonl` | `1d8c3525ce063f475561dc7a4205e9c5355639a634fbc488b045f1957355febb` |
| `polish-summary-guard-manifest-20260920.json` | `1db1af14775e0dfb06a969a4e1ed218872e5cb3539af2f0ba1fde06356b51381` |

The manifest recorded repair-code and fresh-fixture hashes before paid calls.
Detection was checked with Lingua 2.2.0. These results establish the tested repair
behaviour, not guaranteed language detection or perfect future model accuracy.

## Deployment preparation only

At the operator's request, the local `.claude/skills/deploy/SKILL.md` and complete
server runbook were read. A single read-only SSH check succeeded as `deploy` on
port 2222 using the existing local SSH key; the service was active and the server
checkout was `2cad033`. No keys, configuration, code or services were changed there.

The old deploy workflow needs migration-specific planning: it explicitly excludes
changes to `/etc/sentinel/sentinel.env`, while Luna requires an OpenAI credential
on the server. It also copies repository config wholesale; the live database,
logging, Telegram-session and new usage-ledger paths must be preserved/reviewed.
The user's conditional deployment note is not treated as permission to deploy.
