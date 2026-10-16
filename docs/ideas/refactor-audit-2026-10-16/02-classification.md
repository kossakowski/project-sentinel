# 02 — Classification area audit (read-only)

Scope: `sentinel/classification/classifier.py`, `openai_provider.py`, `policy.py`, `schema.py`,
`summary_language.py`, `incident_memory.py` (corroborator.py excluded). Repo state: master 835ed8e.

Verified this session: the six named test files pass (`120 passed in 102.75s`). Request-size and
reservation figures below were computed locally from `config/config.yaml` with no network call.
Not verified: production DB contents (no ssh by instruction), so claims about live model output
shapes are marked "unverified".

Legend: **BP** = behavior-preserving (yes/no). **9-10 risk** = risk to the urgency 9–10 call path.

---

## TODO cross-check (known items, by title)

- "URGENT — monthly model budget will stop classification in October" (TODO 7.1): accurate, line
  ref `openai_provider.py:64` is correct.
- "Ledger overstates OpenAI cost" (TODO 7.2): **mis-described / understated.** It names only the
  1.25× `cache_write_multiplier`. The much larger overstatement is that every failed request keeps
  its full pre-request reservation (5–8× the real per-article cost). See C-01.
- "Live prompt gets no headline-only signal" (TODO 7.4): accurate.
- "OpenAI project hard spend cap vs the 30 USD app allowance" (section 0): accurate
  (`openai_provider.py:187-188`).
- "Ukraine-only shelter orders scored urgency 9 attempt a phone call" (section 0): **line ref is
  off.** It cites `policy.py:84-87` for "policy v2 rule 1"; rule 1 (official resident orders) is
  `policy.py:79-83`; lines 84-87 are rule 2 (active attack). The natural home for the proposed code
  guard is the post-parse step in `Classifier.classify` (see C-07), where `facts.protection` and
  `affected_countries` are both available.
- "Owner rules: call vs text boundary (revised 2026-10-10)": not re-found; C-07 adds a guard that
  must be designed so the planned new 7–8 bands do not trip it.

---

## Findings

### C-01 — Failed requests keep their full reservation; an OpenAI outage can exhaust the monthly cap and pause classification
- **File:** `sentinel/classification/openai_provider.py:166-210` (bound computed at 166-170,
  reserved at 175, every `except` branch at 180-198 and the usage checks at 199-210 raise without
  settling); `UsageLedger.reserve` writes `charged_usd = amount` at 69-72.
- **Category:** latent bug / budget-cap handling. **Severity: high.**
- **What's wrong:** The reservation is an upper bound: request bytes + 4096 priced at
  `input_per_million × cache_write_multiplier`, plus `max_tokens` of output. With the live config it
  is about $0.0048 (no memory candidates) to $0.0078 (≈12 kB of candidates) per request, against a
  measured real cost of ~$0.00095. Every 401/403/429/5xx/connection error/timeout keeps that full
  amount in `charged_usd` forever, and the article is retried every `retry_delay_seconds` (300 s)
  with no attempt cap. Rate-limit and connection errors are normally not billed by OpenAI at all.
  Rough arithmetic: 20–40 pending articles × 12 retries/hour × ~$0.006 ≈ $1.4–2.9 of phantom spend
  per hour of outage. Mid-month headroom of ~$15 is gone after roughly 5–10 hours. From then on
  `reserve()` raises `BudgetExceeded` for the rest of the calendar month and no 9–10 article is
  classified. The tests encode the current behavior (`assert ledger.total() > 0` after 500,
  429 and timeout in `tests/test_direct_openai.py:151-182`).
- **Proposed refactor:** Split the error path into "provider definitely did not bill" (HTTP
  401/403/429 with a response body, `APIConnectionError` before any bytes were read) and "unknown"
  (timeout, 5xx after send, missing usage). Settle the first group at 0 with
  `status='released'`; keep the second at the reservation but cap it (for example, settle stale
  `reserved` rows older than N hours at the median settled cost for that purpose). Add
  `UsageLedger.release(reservation, reason)`.
- **BP:** no (changes what counts against the cap). Owner decision: it trades cost-cap
  conservatism against missed-alert risk.
- **9-10 risk of the fix:** lowers risk (fewer false budget pauses). Risk of leaving it: high.
- **Effort:** M.
- **Test:** fake transport returns 429 `rate_limit_exceeded` 500 times → `ledger.total() == 0` and
  the next good request still succeeds; a timeout keeps a reservation; a stale-reservation sweep
  test with frozen time.

### C-02 — No retry, no backoff and no circuit breaker: one systemic error is repeated for every pending article
- **File:** `openai_provider.py:131-136` (`max_retries=0`), `:180-198`; caller loop
  `sentinel/scheduler.py:250-260` (cross-area); dispatch only after the whole loop,
  `sentinel/scheduler.py:301-306` (cross-area).
- **Category:** error handling / life-safety latency. **Severity: high.**
- **What's wrong:** (a) A transient failure (one invalid JSON answer, one 5xx, one timeout) on a
  9–10 article delays it by at least `retry_delay_seconds` (300 s) plus cycle alignment; there is no
  quick second attempt. (b) A systemic failure (key revoked, quota, project spend limit,
  `BudgetExceeded`, rate limit, hung API) is retried for each of up to `retry_batch_size` (100)
  articles in the same cycle. With a hung API each attempt waits `timeout_seconds` (30 s), so one
  cycle can run ~50 minutes. Because dispatch happens only after the loop, an event already
  classified as 9–10 earlier in the same loop waits for all of that before its call is placed.
  (c) Every failure becomes the same `ClassificationError`, so the queue's `last_error` column
  (`type(e).__name__`) is "ClassificationError" for budget pause, bad key and bad JSON alike.
- **Proposed refactor:** (1, BP) Introduce subclasses with a `retryable`/`systemic` attribute:
  `ProviderConfigError` (401/403/missing key), `ProviderQuotaError` (insufficient_quota, spend
  limits), `BudgetExceeded`, `TransientProviderError` (5xx, connection, timeout, rate limit),
  `InvalidModelOutput` (schema, refusal, incomplete, wrong model, usage bounds). Keep the messages.
  Scheduler stores the subclass name in `last_error`. (2, not BP) In the scheduler loop, stop
  classifying for this cycle after the first systemic error and still run dispatch; allow one
  immediate retry for `InvalidModelOutput`/`TransientProviderError` (configurable count, default 1).
- **BP:** part 1 yes; part 2 no (cost and latency change, not scores).
- **9-10 risk:** part 2 lowers it; part 1 none.
- **Effort:** S (taxonomy) + M (breaker/retry, crosses scheduler).
- **Test:** handler returns 401 → only 1 HTTP call in a cycle with 5 pending articles, all 5 stay
  pending, previously grouped critical event is still dispatched; handler returns invalid JSON then
  valid → article classified in the same cycle with 2 ledger rows.

### C-03 — Empty `summary_pl` suppresses an accepted alert, against the module's own invariant
- **File:** `sentinel/classification/classifier.py:188-189`.
- **Category:** latent bug. **Severity: high** (rare, but fails in the dangerous direction).
- **What's wrong:** If the model returns a valid classification with `urgency_score: 10` but an
  empty or whitespace `summary_pl` (the schema allows `""`), `classify` raises
  `ClassificationError`. The article is never alerted, and it is re-sent (and re-billed) every 5
  minutes. `summary_language.py` exists precisely so that "a translation failure cannot suppress an
  accepted alert" and already has `fallback_pl` for this.
- **Proposed refactor:** Replace the raise with
  `data["summary_pl"] = cfg.summary_language.fallback_pl` and record
  `summary_processing = {"version": GUARD_VERSION, "action": "fallback", "repair_error": "empty
  model summary"}` without a translation call.
- **BP:** no (an alert that is dropped today would go out). Safe direction; still owner sign-off
  because it touches the call path.
- **9-10 risk:** lowers it.
- **Effort:** S.
- **Test:** fake provider returns urgency 10 with `summary_pl: "  "` → result has
  `summary_pl == fallback_pl`, `summary_processing["action"] == "fallback"`, one ledger row.

### C-04 — Poison articles retry forever at a fixed delay, each attempt paid
- **File:** classification queue in `sentinel/database.py:167-180` (cross-area), fed by every
  `ClassificationError` in `openai_provider.py`; `classification.retry_delay_seconds` in config.
- **Category:** error handling / cost. **Severity: med.**
- **What's wrong:** Deterministic failures (input over the 250 kB bound at `openai_provider.py:164`,
  a reproducible refusal, a reproducible schema violation, a `ClassificationResult(**data)`
  TypeError if the schema gains a field) have no attempt cap and no backoff. `attempts` is counted
  but never read. Each retry costs a reservation (C-01). Pending selection is oldest-first
  (`ORDER BY julianday(a.fetched_at)`), so after a long pause a fresh critical article waits behind
  the backlog.
- **Proposed refactor:** Exponential backoff by `attempts` (configurable base and cap), a
  `classification.max_attempts` after which the row moves to a dead-letter state reported in
  `classification_health`, and consider newest-first or keyword-priority ordering for pending work.
- **BP:** no. Owner decision (dead-lettering could drop a real alert if the cap is too low).
- **9-10 risk:** neutral if the cap is generous and dead letters raise a health alarm; ordering
  change lowers latency for fresh critical articles.
- **Effort:** M.
- **Test:** article whose request always exceeds the size bound → after `max_attempts` it is no
  longer selected, no further HTTP or ledger rows, health shows it.

### C-05 — Provider "abstraction" is an if-branch; ~250 lines of legacy Anthropic code live in the live module
- **File:** `classifier.py:10` (top-level `import anthropic`), `:20-153` (legacy SYSTEM_PROMPT and
  USER_PROMPT_TEMPLATE), `:164-165` (`self.client` is either an OpenAI or Anthropic client),
  `:178-256` (two code paths in one method), `:288-293`, `:299-372` (legacy helpers), `:389-408`
  (legacy cost log with hardcoded prices 0.80/4.00); `incident_memory.py:12-52`
  (`MEMORY_INSTRUCTIONS` is used only by the legacy path and `sentinel/eval/compare_models.py`;
  the live prompt has its own "INCIDENT IDENTITY" section in `policy.py:118-133`).
- **Category:** structure / dead weight / unclear boundaries. **Severity: med.**
- **What's wrong:** The live path and the rollback path share one class with `provider is None`
  checks in four places. The live module carries two divergent definitions of the
  new/duplicate/update/escalation semantics. `dashboard/classifier_input.py` and
  `eval/compare_models.py` reach into `Classifier._build_user_prompt(None, …)` (calling an instance
  method with `self=None`). `tests/test_incident_memory.py:385-421` builds a `Classifier` via
  `__new__` and sets five private attributes by hand, and it tests the legacy path, not the live one.
- **Proposed refactor:** Define a `ClassificationBackend` Protocol
  (`async classify(article, candidates|None) -> ClassificationResult`, `async aclose()`). Move the
  current OpenAI branch to `OpenAIBackend` in `classifier.py`. Move SYSTEM_PROMPT,
  USER_PROMPT_TEMPLATE, MEMORY_INSTRUCTIONS, `_build_user_prompt` (as a module function),
  `_call_api`, `_send_request`, `_parse_json` and the Haiku cost log to
  `classification/legacy_anthropic.py` with a lazy `import anthropic`. `Classifier` becomes a
  factory/facade with the same public API. Repoint `compare_models.py` and
  `dashboard/classifier_input.py` imports.
- **BP:** yes (pure move; legacy prompt hash `legacy:<sha>` must stay identical).
- **9-10 risk:** low (no logic change); guard with the existing frozen-hash tests.
- **Effort:** M.
- **Test:** existing `tests/test_classifier.py` repointed and green; new test asserts the legacy
  `prompt_version` string is byte-identical to today's; `python -c "import
  sentinel.classification.classifier"` with `anthropic` blocked in `sys.modules` succeeds in OpenAI
  mode.

### C-06 — The Anthropic "rollback" is not an equivalent rollback, and it is the code default
- **File:** `sentinel/config.py:232` (`provider` default `"anthropic"`), `:263`
  (`model` default `claude-haiku-4-5-20251001`); `classifier.py:213-256`, `:258-286`.
- **Category:** legacy path / latent bug. **Severity: med.**
- **What's wrong:** Rolling back changes much more than the model: (1) no budget cap or ledger at
  all; (2) no schema validation — `_parse_json` uses a greedy `\{.*\}` regex and `aggressor`,
  `event_type` are barely type-checked; (3) a different, older policy (R1–R10; e.g. R1 makes a Baltic
  shelter order 9–10, which no longer matches the owner's 2026-10-10 rules); (4) in batch mode,
  `int(data.get("urgency_score"))` on a non-numeric value raises `ValueError`, which
  `classify_batch` does not catch (it catches only JSONDecodeError, APIError, ClassificationError),
  so one bad answer discards the whole batch and every article in it is marked failed;
  (5) the rollback has no test against the live config. A config that omits `provider` silently
  lands on this path.
- **Proposed refactor:** Owner decides: delete the legacy path, or keep it as a documented, tested
  rollback. Minimum either way: make `classification.provider` required (no default) or default it
  to `openai` with the live model; catch `(ValueError, TypeError, KeyError)` per article in
  `classify_batch`.
- **BP:** no for both parts. The default change affects only configs that omit `provider` (both
  tracked configs set `provider: openai`, so production is unaffected). The wider catch lets a batch
  that is dropped today partly succeed.
- **9-10 risk:** lowers it.
- **Effort:** S (default + catch), L (deletion with eval/dashboard repoint).
- **Test:** `ClassificationConfig()` without provider raises (or resolves to openai);
  `classify_batch` with one `"urgency_score": "high"` reply still returns the other results.

### C-07 — Policy config is an untyped dict, and nothing checks that attack bands reach the call threshold
- **File:** `sentinel/config.py:234` (`policy: dict[str, Any]`), `:244-263` (validator);
  `policy.py:27-43` (keys read by name).
- **Category:** weak typing / missing guard. **Severity: med.**
- **What's wrong:** The validator checks only that ranges are int pairs in 1–10 and that the prompt
  renders. A typo such as `active_attack: [7, 8]` or `official_warning: [7, 8]` passes, and every
  confirmed attack on Poland is then scored as a text, with no error. Unknown keys
  (`scope`, `operator_decisions`, misspelled range names) are silently ignored. `near_border_strike`
  and `neutralised_drone` are free strings that fail only through a `KeyError` with a generic message.
- **Proposed refactor:** A `PolicyV2Config` pydantic model: `version: Literal[2]`,
  `monitored_countries: list[str]`, `near_border_strike: Literal["awareness","log_only","critical"]`,
  `neutralised_drone: Literal["current_danger","original_severity"]`, `ranges` as a model with one
  named `tuple[int,int]` field per band (`extra="forbid"`). Add a `SentinelConfig`-level validator:
  the lower bound of `active_attack` and `official_warning` must be ≥ the phone-call `min_score`.
  `system_prompt()` keeps taking a dict (`policy.model_dump()`), so the prompt text and hash do not
  change. Design the cross-check so the planned new 7–8 Baltic-strike band (owner rules 2026-10-10)
  gets its own band name and is not caught by it.
- **BP:** yes for the live config (renders the same prompt); the new validator is a policy rule, so
  ask the owner to confirm it.
- **9-10 risk:** lowers it (catches a silent downgrade).
- **Effort:** M.
- **Test:** `prompt_hash(live policy)` equals a pinned value before and after; config with
  `active_attack: [7, 8]` fails to load; config with a misspelled band name fails to load.

### C-08 — Critical-path guards with no test: `critical_min_confidence`, the live prompt hash, live-path memory wiring
- **File:** `incident_memory.py:150-156` (critical bar); `tests/` (grep finds no test that mentions
  `critical_min_confidence`); `tests/test_direct_openai.py:245-256` pins the prompt for the fixture
  policy `tests/fixtures/benchmark_policy_v2.yaml`, not for `config/config.yaml`;
  `tests/test_incident_memory.py:385-421` exercises the legacy Anthropic path.
- **Category:** missing tests on critical paths. **Severity: med.**
- **What's wrong:** The rule "a phone-eligible article may join an existing event only at
  `critical_min_confidence`" is the remaining protection against silently absorbing a critical
  report (see section 0 "Owner sign-off: acknowledged-event guard is gone in incident-memory mode").
  A refactor could swap the two thresholds or compare against the wrong urgency and every test
  would stay green. A change to the live policy in `config/config.yaml` changes the production
  prompt without any test noticing, although the owner's rule is that prompt changes are eval-gated.
- **Proposed refactor:** Tests only: (1) urgency 9 result, `duplicate` at confidence between
  `min_confidence` and `critical_min_confidence` → decision becomes `uncertain` (own event, own
  call); same input at urgency 8 → accepted. (2) Pin `prompt_hash(config/config.yaml policy)` and
  make the failure message point to `docs/how-to/model-eval.md`. (3) An OpenAI-path test that
  candidates reach `messages()` and that `validate` runs on the result.
- **BP:** yes.
- **9-10 risk:** none; protects it.
- **Effort:** S.
- **Test:** the tests above are the deliverable.

### C-09 — `IncidentMemory.validate` is a 60-line in-place mutator; its time-conflict guard is optional
- **File:** `incident_memory.py:122-184`.
- **Category:** oversized function / unclear contract. **Severity: med.**
- **What's wrong:** It returns `None` and overwrites `result.incident_memory` from four exits, with
  interleaved `valid`/`matched` flags; the threshold choice, allow-list check, time-conflict
  override and fallback assembly are tangled. `article` defaults to `None`, and then the explicit
  date/weekday conflict guard is skipped silently. All current callers pass it, so the default only
  invites a future caller to drop the guard.
- **Proposed refactor:** Pure function `decide_memory(raw, candidate_ids, urgency, phone_threshold,
  cfg, time_conflict: Callable) -> MemoryDecision` (frozen dataclass with `to_dict()`), split into
  `_shape_ok`, `_match_ok`, `_time_override`. `validate` becomes a two-line wrapper; make `article`
  required. Keep output dicts byte-identical (including `candidate_ids`, `model_decision`,
  `model_confidence`, truncation lengths).
- **BP:** yes.
- **9-10 risk:** low if the existing `test_incident_memory.py` cases plus C-08's new case stay green.
- **Effort:** S–M.
- **Test:** parametrized table test over (decision, confidence, id, urgency, conflict) → expected
  dict, run before and after the refactor.

### C-10 — Two OpenAI providers in production (classifier and enricher), each with its own client and ledger connection
- **File:** `classifier.py:164`; `sentinel/processing/enricher.py:72-89` (cross-area);
  `tests/test_direct_openai.py:288-299` injects a shared provider by hand
  (`enricher._openai_provider = classifier.provider`), which production never does.
- **Category:** unclear boundaries / duplication. **Severity: med.**
- **What's wrong:** Two `AsyncOpenAI` clients and two SQLite connections to the same ledger file in
  one process. It works because of `BEGIN IMMEDIATE`, but the test covers a wiring that does not
  exist in production, and an eval cap (`session_remaining`) set on one provider does not apply to
  the other.
- **Proposed refactor:** Build one `OpenAIProvider` in `SentinelPipeline.__init__` (and in the CLI
  entry points) and inject it into `Classifier(config, provider=…)` and
  `ArticleEnricher(config, provider=…)`; the pipeline owns `aclose()`.
- **BP:** yes.
- **9-10 risk:** low.
- **Effort:** S–M.
- **Test:** pipeline construction test asserts `pipeline.enricher._openai_provider is
  pipeline.classifier.provider`.

### C-11 — Phone-call threshold derivation duplicated, with a silent default of 9
- **File:** `incident_memory.py:58-62`, `corroborator.py:254-257` (other agent's file, cited only
  for the duplication), ordering logic in `sentinel/alerts/state_machine.py:494-502`.
- **Category:** duplication. **Severity: low.**
- **What's wrong:** Two copies of "min `min_score` of levels whose action is `phone_call`, else 9".
  If someone renames the action or removes the level, both silently fall back to 9.
- **Proposed refactor:** `AlertsConfig.phone_call_min_score` property (raise at config load if no
  `phone_call` level exists, or keep 9 explicitly in one place).
- **BP:** yes (if the fallback is kept).
- **9-10 risk:** none.
- **Effort:** S.
- **Test:** config test for the property; existing memory and corroborator tests stay green.

### C-12 — Stale contracts and test hooks on the provider
- **File:** `classifier.py:173-177` (docstring says it raises `json.JSONDecodeError or
  anthropic.APIError`; the live path raises `ClassificationError`); `openai_provider.py:138`,
  `:171-174`, `:212-213` (`session_remaining` is a public mutable attribute that
  `sentinel/eval/direct_luna.py:90` sets from outside); `openai_provider.py:126-127` (error text
  about "Codex subscription").
- **Category:** clarity / typing. **Severity: low.**
- **Proposed refactor:** Constructor argument `session_cap_usd: float | None = None`; fix the
  docstring; type the provider methods (`UsageLedger.total`, `settle` have no annotations).
- **BP:** yes. **9-10 risk:** none. **Effort:** S.
- **Test:** existing `test_explicit_test_cap_before_http` via the constructor argument.

### C-13 — Hardcoded values and duplicate token tracking
- **File:** `openai_provider.py:163-165` (`4096` framing, `250_000` byte cap), `:158`
  (`service_tier="default"`); `classifier.py:399-400` (Haiku prices `0.80`/`4.00`);
  `classifier.py:168-171`, `:374-396` (in-memory daily token counters that duplicate the ledger and
  log only when the first article of the next UTC day arrives); `incident_memory.py:171-174, 182`
  (truncation lengths 400/30/500); `classifier.py:205` (literal `"clarified-v2"` duplicates
  `policy.version`).
- **Category:** hardcoded values (project rule) / dead weight. **Severity: low.**
- **Proposed refactor:** Move the byte cap and framing allowance to `ModelBudgetConfig`; derive the
  version tag from `policy["version"]`; delete the daily counters on the OpenAI path (the ledger is
  the source of truth); move the Haiku price log into the legacy module (C-05).
- **BP:** yes (same defaults). **9-10 risk:** none. **Effort:** S.
- **Test:** `prompt_version` string unchanged for the live config; budget-bound test unchanged.

### C-14 — Live-mode dead config: `classification.temperature` and `incident_memory.extra_output_tokens`
- **File:** `sentinel/config.py:264-265`, `:181`; read only at `classifier.py:343-345` (legacy).
- **Category:** dead config / clarity. **Severity: low.**
- **What's wrong:** Both keys are set in `config/config.yaml` but the OpenAI payload has no
  temperature and uses `max_tokens` alone. An operator who raises `extra_output_tokens` to fix
  truncated memory answers changes nothing.
- **Proposed refactor:** Move both under a `legacy_anthropic:` sub-block, or document them as
  legacy-only in `docs/reference/config-reference.md`.
- **BP:** yes. **9-10 risk:** none. **Effort:** S.
- **Test:** config test that the OpenAI payload is unchanged.

### C-15 — `prompt_version` does not cover the schema or the user-message shape
- **File:** `classifier.py:205`; `sentinel/eval/suite/runner.py:44` computes `SCHEMA_SHA256`
  separately.
- **Category:** traceability. **Severity: low.**
- **What's wrong:** A change to `CLASSIFICATION_SCHEMA` or to the JSON layout in
  `policy.messages()` changes model behavior but not the stored `prompt_version`, so production
  rows cannot be matched to an eval run.
- **Proposed refactor:** Append a short schema hash and a message-format version, or store them in
  a separate column.
- **BP:** no for stored metadata (alerts unchanged; history comparison by `prompt_version` breaks
  once). **9-10 risk:** none. **Effort:** S.
- **Test:** changing a schema description changes `prompt_version`.

### C-16 — Country and type fields are free strings; normalization is left to grouping
- **File:** `schema.py:4-11`; `classifier.py:186-212` (no post-parse normalization on the live path,
  unlike the legacy clamp at 224-229).
- **Category:** weak typing. **Severity: low–med.**
- **What's wrong:** `affected_countries` items, `event_type`, `aggressor` and
  `facts.attack_countries` are unconstrained strings. "Poland" or "pl" vs "PL" would defeat the
  concrete-country gate and add to the known "Urgency-9 event fragmentation" item. Unverified
  whether production ever returns non-codes (no DB access in this audit).
- **Proposed refactor:** First a read-only DB query of distinct values; then either an `enum` in
  the strict schema (changes the frozen schema → eval-gated) or a post-parse normalizer that maps
  names to ISO alpha-2 and keeps unknowns visible.
- **BP:** no. **9-10 risk:** fragmentation down; misuse could drop a country, so eval-gate it.
- **Effort:** S (query) + M.
- **Test:** normalizer table test; eval suite run.

### C-17 — Time-conflict guard misses common date forms
- **File:** `incident_memory.py:96-107`.
- **Category:** latent gap. **Severity: low.**
- **What's wrong:** Dates are found only as `YYYY-MM-DD` and `DD.MM.YYYY` with two-digit day and
  month. "1.10.2026", "01.10.26", "1 października" or "2026/10/01" are not seen, so a confident
  model match across two different dates is not overridden to `new`.
- **Proposed refactor:** Accept 1–2 digit day/month and Polish/Ukrainian/Russian month names
  (month aliases in config, like `weekday_aliases`).
- **BP:** no (more `new` decisions → more events → possibly more calls; interacts with the known
  fragmentation item). Owner decision. **Effort:** S.
- **Test:** parametrize `test_explicit_incident_time_conflicts_override_confident_model_match` with
  the new forms.

### C-18 — Fail-closed checks that would stop all classification on a provider-side change
- **File:** `openai_provider.py:217-222`.
- **Category:** fragility. **Severity: low.**
- **What's wrong:** If OpenAI starts reporting a nonzero `reasoning_tokens` with
  `reasoning=none`, or serves a snapshot name without the `<model>-` prefix, every article fails,
  is billed, and retries forever (C-01, C-04). No distinct signal reaches the operator.
- **Proposed refactor:** Keep the checks, but classify them as systemic (C-02) so the cycle stops
  after the first one and the health file shows a specific reason.
- **BP:** yes for the taxonomy part. **9-10 risk:** lowers time to detect. **Effort:** S.
- **Test:** reasoning-tokens reply → one HTTP call per cycle, health reason set.

### C-19 — Blocking I/O in the async critical loop
- **File:** `openai_provider.py:40, 62-72` (sync `sqlite3` with `timeout=10` and `BEGIN IMMEDIATE`
  on the event loop); `incident_memory.py:66-71` with `sentinel/database.py:316-323`
  (`get_event_evidence` re-fetches each event, so ~200 queries per article with
  `candidate_pool_size: 100`).
- **Category:** performance. **Severity: low.**
- **What's wrong:** A local eval or dashboard holding the ledger lock can stall the event loop up to
  10 s. The N+1 queries are small but run for every article.
- **Proposed refactor:** Pass the already-loaded `Event` into a `get_event_evidence_for(event, …)`
  variant; consider `asyncio.to_thread` for ledger writes.
- **BP:** yes. **9-10 risk:** none. **Effort:** S.
- **Test:** query-count assertion with `sqlite3` trace callback.

### C-20 — Fallback summary discards the original text from the alert
- **File:** `summary_language.py:88-93`.
- **Category:** behavior choice. **Severity: low.**
- **What's wrong:** When translation fails, the alert carries a generic "summary unavailable"
  sentence; the model's original (English/Russian) summary is kept only in `summary_processing`.
  For a life-safety alert the original text is more informative.
- **Proposed refactor:** Optionally append the original summary (Latin-script only, length-capped)
  after the Polish fallback sentence.
- **BP:** no. Owner decision (he chose Polish-only output). **Effort:** S.
- **Test:** `test_repair_failure_preserves_critical_notification` extended.

---

## Proposed phase grouping (classification area)

**Phase 1 — Tests first (behavior-preserving, unblocks everything else).** C-08 (critical
confidence bar, live prompt-hash pin, OpenAI-path memory wiring), C-12 docstring and typing.
Effort S. No owner decision.

**Phase 2 — Structure (behavior-preserving).** C-05 legacy extraction behind a backend protocol,
C-10 single injected provider, C-09 pure memory-decision function, C-02 part 1 error taxonomy,
C-11 threshold helper, C-13 hardcoded values and duplicate counters, C-14 dead-config labelling,
C-19 query and blocking cleanup. Gate: Phase-1 tests and frozen prompt hashes unchanged.

**Phase 3 — Life-safety behavior changes (owner sign-off each, alert-safe direction).** C-03 empty
summary → fallback, C-01 release unbilled reservations and cap stale ones, C-02 part 2 circuit
breaker and one quick retry (crosses scheduler), C-04 backoff, attempt cap with health alarm and
pending ordering (crosses database), C-18 systemic classification, C-06 provider default and
`classify_batch` catch, plus the owner's call on deleting the legacy path. C-07 typed policy with
the call-threshold cross-check also lands here because the validator encodes policy.

**Phase 4 — Eval-gated changes (frozen prompt/schema).** C-16 country/type normalization, C-17
date forms, C-15 prompt_version scope, C-20 fallback content; together with the known section-0
items "Ukraine-only shelter orders scored urgency 9 attempt a phone call" and "Owner rules: call vs
text boundary (revised 2026-10-10)".
