# 07 — Eval / model-comparison subsystem audit (read-only)

Scope: `sentinel/eval/` (21 modules, 5,300 lines), `tests/fixtures/*`, and the eval tests.
Baseline: the 12 eval-related test files pass on master (154 passed in 33 s:
`.venv/bin/pytest tests/test_eval_suite_*.py tests/test_model_comparison.py tests/test_openrouter_eval_client.py tests/test_separate_metrics.py tests/test_cached_runtime.py tests/test_clarified_policy.py tests/test_cli_bridges.py -q`).
I ran no paid commands. Labels and fixtures are out of scope for edits; every proposal below changes code only.

Known items I did not rediscover (TODO.md section 7): "The pre-registered decision rule still names the $10 cap"
(item 8, which is also `suite/report.py:398 --monthly-cap default=10.0`), "Enriched body truncated to 500 characters" (item 5) and
"Google News decoder can stall the whole cycle" (item 7). Findings E-11 and E-12 touch those items but are separate.

## 1. Big picture

- There are **two parallel eval stacks**:
  - **Stack A, "model comparison v1/v2"** (Sept 2026): `compare_models`, `openrouter_client`, `clarified_policy`,
    `reference_history`, `separate_metrics`, `rescore_dimensions`, `cached_runtime`, `direct_luna`, `export_candidates`,
    `incident_memory`. Its datasets are the YAML fixtures. It chose Luna (2026-09-20) and ran the GPT-6 check (2026-09-23).
  - **Stack B, "eval suite"** (`suite/`): the current tool under the pre-registered decision rule in `docs/how-to/model-eval.md`.
    It uses `items.json` and the owner's `labels.jsonl`.
- Stack B is not standalone. `suite/runner.py`, `suite/sample.py` and `suite/fulltext_snapshot.py` import the replay
  primitives (`ReplayClock`, `ReplayDatabase`, `RecordingAlerts`, `make_config`, `make_article`, `parse_prediction`) from
  `compare_models.py`. That 622-line module also holds the legacy-v1 comparator. So the frozen legacy module cannot be
  archived until those primitives move out.
- **Production does not import eval on its runtime path.** The only import is the lazy one at `sentinel.py:393`
  (`from sentinel.eval.harness import ...` inside `_run_eval`, which only `--eval` reaches). The scheduler,
  classification, alerts and database packages import nothing from `sentinel.eval`.
- The **reverse coupling is the fragile part.** Eval reaches into production in these ways:
  - It monkeypatches `datetime` in 3 production modules.
  - It monkeypatches `Event` in the corroborator.
  - It copies one production SQL query.
  - It calls an unbound private method with `self=None`.
  - It calls the private `ArticleEnricher._fetch_body`.
  - It depends on a test-only hook (`OpenAIProvider.session_remaining`) that lives in production code.

## 2. Findings

### E-01 — compare_models v2 sends a schema with a different property order than production (fidelity bug)
- **File:line:** `sentinel/eval/compare_models.py:325` and `:450` build
  `{**RESPONSE_SCHEMA, "properties": {"facts": FACT_SCHEMA, **FIELDS}, "required": ["facts", *FIELDS]}`.
  Production `sentinel/classification/schema.py` `CLASSIFICATION_SCHEMA` uses `{**FIELDS, "facts": FACT_SCHEMA}` and `[*FIELDS, "facts"]`.
- **Category:** latent bug / duplication. **Severity:** high (it undermines the validity of historic results).
- **What's wrong:**
  - I checked this: `json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)` is False. In stack A, `facts` comes first.
    In production, `facts` comes last.
  - Strict JSON-schema decoding emits keys in schema order. So under stack A the model writes its facts before it
    commits to `urgency_score`, and in production it writes them after.
  - The Luna selection (v2 runs) and section A of the GPT-6 record were measured under the facts-first order.
  - `docs/how-to/model-comparison.md` says "the benchmark modules import that runtime contract". That claim does not
    hold for the schema.
  - `suite/runner.py:90` correctly uses `CLASSIFICATION_SCHEMA`, so stack B is unaffected.
- **Refactor:** Delete the local schema construction and import `CLASSIFICATION_SCHEMA` in both `replay` and
  `replay_reference`. Add a note to `docs/reference/gpt-6-luna-eval-20260923.md` and to the v2 run record that those
  runs used facts-first ordering.
- **Behavior-preserving:** no. Future stack-A requests change. Cached replays still work because `cached_runtime`
  hashes only the messages.
- **Effort:** S.
- **Proving test:** `test_eval_schema_is_production_schema`. It asserts that the `json_schema` passed to `client.complete`
  by `replay` and by `replay_reference` `is` (or `==` with key order compared via `list(...)`) `CLASSIFICATION_SCHEMA`.

### E-02 — The runtime-simulation step is copy-pasted 3 times; replay primitives live in the legacy module
- **File:line:**
  - `compare_models.py:328-389`: `replay`, with the inner block at 369-386.
  - `suite/runner.py:194-240`: `replay_chain`, with the inner block at 219-237.
  - `direct_luna.py:114-127`.
  - The shared classes are at `compare_models.py:145-209`.
- **Category:** duplication / unclear boundaries. **Severity:** high (it blocks every archive step and invites drift).
- **What's wrong:** All three copies repeat the same sequence. They set `ReplayClock.current`, `db.insert_article`,
  `memory.candidates`, `memory.validate`, apply the triple `patch(... datetime, ReplayClock)`, call
  `grouper.process_classifications`, diff before/after with `get_alert_records`, and compute the notification
  (`"silent" | "update" | "initial"`) and the channels. Stack B and `direct_luna` import these primitives from the
  legacy comparator. Production tests (`tests/test_summary_language.py:16`, `tests/test_direct_openai.py:246`) also
  import from `compare_models`.
- **Refactor:**
  - Create `sentinel/eval/simulation.py` with `ReplayClock`, `ReplayDatabase`, `RecordingTransport`, `RecordingAlerts`,
    `make_config`, `make_article` and `parse_time`.
  - Add one coroutine to it: `simulate_runtime(db, grouper, alerts, result) -> SimOutcome(event, notification, channels)`.
  - Have all three callers use it.
  - Keep re-exports in `compare_models.py` for one release so the tests and cached reports don't break.
- **Behavior-preserving:** yes.
- **Effort:** M.
- **Proving test:** The existing `test_model_comparison.py`, `test_eval_suite_runner.py`,
  `test_direct_openai.py::test_no_send_runner_uses_real_direct_classifier` and `test_cached_runtime.py` pass unchanged.
  Add `test_simulation_notification_sequence` (initial → silent duplicate → update on escalation) against `simulate_runtime` directly.

### E-03 — Process-global monkeypatching of production modules, used inside `await`
- **File:line:**
  - `compare_models.py:13,369-373`, `suite/runner.py:20,220-224` and `direct_luna.py:9,116-120` call
    `unittest.mock.patch("sentinel.{classification.corroborator,alerts.state_machine,database}.datetime", ReplayClock)`.
  - `cached_runtime.py:245` calls `patch("sentinel.classification.corroborator.Event", new=event_ids.construct)`.
  - `ReplayClock.current` is mutable class state (`compare_models.py:145-150`).
- **Category:** fragile coupling / latent bug. **Severity:** med.
- **What's wrong:**
  - **Failure mode 1:** A production module can switch to `from sentinel.utils.datetime import utcnow` (the util
    surface the timezone rule points at), or to `import datetime`. When that happens the patch silently stops working
    and replays run on wall-clock time. The memory-age gate in `_find_memory_match` then rejects every match, and
    nothing fails loudly.
  - **Failure mode 2:** Other modules on the alert path read the clock without being patched. `alerts/push_client.py:101`
    and `alerts/twilio_client.py:72` do, and so do SQL `datetime('now')` queries such as `database.py:293`
    (`get_active_events`) and `:228`. These are only safe today because `make_config` forces memory mode and uses the
    fake transports.
  - **Failure mode 3:** The patch is process-global while the code awaits. `suite/runner.py:404` runs the singles
    concurrently with a chain. The singles stamp `classified_at=ReplayClock.current` (`compare_models.py:272`) from
    whatever chain is active. If anyone parallelises the chains the way the singles are parallelised, the clocks
    cross-contaminate.
- **Refactor:**
  - Give the corroborator, the state machine and the database an injectable `clock: Callable[[], datetime]`. It defaults
    to `lambda: datetime.now(UTC)`, so production behaviour is unchanged.
  - Make `ReplayClock` an instance that is passed in, or a `contextvars.ContextVar`.
  - Give the corroborator an `event_factory` parameter in place of the `Event` patch.
  - Remove `unittest.mock` from non-test code.
- **Behavior-preserving:** yes. The clock defaults to wall time.
- **Effort:** M. It touches 3 production modules, so it needs owner sign-off under the life-safety rules for the
  corroborator and alerts.
- **Proving test:** `test_replay_uses_injected_clock_not_wall_time`. It replays a 2-article chain dated 2026-01-01 with
  the patches removed and asserts that the second article is a `duplicate` of the first event. Add an AST test that
  `sentinel/eval/**` never imports `unittest.mock`.

### E-04 — `ReplayDatabase.get_memory_events` copies the production SQL
- **File:line:** `compare_models.py:153-163` duplicates `sentinel/database.py:299-313` with `julianday('now')` replaced by a parameter.
- **Category:** duplication / fragile coupling. **Severity:** med.
- **What's wrong:** Any change to the production candidate query, such as a status filter or a new ordering, silently
  leaves the eval on the old query. Then the eval "runtime simulation" no longer simulates the runtime.
- **Refactor:** Give `Database.get_memory_events` an optional `now: datetime | None = None` parameter. Production passes
  nothing and SQL uses `'now'`. The replay passes `ReplayClock.current`. Then delete the override. This falls out
  naturally from the clock injection in E-03.
- **Behavior-preserving:** yes.
- **Effort:** S.
- **Proving test:** `test_memory_events_window_respects_explicit_now` in `tests/test_database*.py`, plus the existing replay tests.

### E-05 — Eval re-implements production output validation, and it is looser than production
- **File:line:**
  - `compare_models.py:212-276` (`parse_prediction`, 20 branches) hardcodes the enums at `:223,:225`, which duplicates
    `FACT_SCHEMA`.
  - `suite/runner.py:127-133` runs jsonschema and then `parse_prediction`.
  - Compare production `sentinel/classification/classifier.py:186-189` and `openai_provider.py:107-118`.
- **Category:** duplication / latent bug. **Severity:** med.
- **What's wrong:**
  - Production rejects an empty `summary_pl`: "Empty classification summary; article remains pending". It also rejects
    NaN and Infinity at parse time (`parse_constant=reject_constant`).
  - `parse_prediction` accepts `summary_pl == ""`, and `OpenRouterEvalClient` uses a plain `json.loads`
    (`openrouter_client.py:684`).
  - Result: an answer that production would treat as invalid, leaving the article pending, counts as valid in
    `invalid_call_rate`. That metric feeds the pre-registered rule "the model's own invalid answers ≤ 0.5%".
  - Stack A (`compare_models.replay`) does not run jsonschema at all.
- **Refactor:** Add a production-owned `sentinel/classification/validation.py` with
  `validate_classification(data) -> dict`, containing schema + empty-summary + finiteness checks. Add
  `build_result(data, article, …) -> ClassificationResult`, used by `Classifier.classify` and by the eval.
  `parse_prediction` becomes a thin wrapper, and the hand-written enum checks go.
- **Behavior-preserving:** yes for production. For the eval it is a deliberate tightening, so invalid rates can rise slightly.
- **Effort:** M.
- **Proving test:** `test_eval_rejects_what_production_rejects`. It is parametrised over empty summary, NaN confidence
  and a bad enum, and asserts that `runner.validate_output` raises if and only if `validate_classification` raises.

### E-06 — Urgency→tier thresholds are hardcoded in 6 places and ignore `alerts.urgency_levels`
- **File:line:**
  - `harness.py:32-45` (`_action_for_urgency`: `>=9` plus the monitored-country gate, `>=5` → "sms").
  - `separate_metrics.py:69-74` (`_action_band`).
  - `suite/score.py:45-56` (`stratum_of`, `action`).
  - `suite/sample.py:49-56` (`stratum`, an exact copy of `score.stratum_of`).
  - `suite/label_server.py:24` (`TIERS`) and its JS twin `suite/label_page.html:57` (`TIERS` with ranges).
  - Monitored countries are hardcoded in `harness.py:25` and `label_server.py:25`, where `policy["monitored_countries"]` exists.
- **Category:** duplication / "nothing hardcoded" rule violation. **Severity:** med.
- **What's wrong:** Production derives the call threshold from config (`Corroborator._phone_call_threshold`,
  `corroborator.py:248`). The eval copies cannot drift-check against it. `harness._action_for_urgency` also encodes
  rules that production no longer has:
  - It requires a monitored country for a call. Production calls on urgency alone, gated by corroboration.
  - It labels 5–8 as "sms". Live 5–8 is push-only.
  - So the `action_match` that `./run.sh --eval` reports is not production's action.
- **Refactor:** Add `sentinel/eval/tiers.py` with `action_for(urgency, config)` and `stratum(urgency)` derived from
  `config.alerts.urgency_levels`. Read the countries from `config.classification.policy["monitored_countries"]`. Have
  `label_server` serve `TIERS` to the page via the existing JSON API instead of the JS constant.
- **Behavior-preserving:** yes for score, separate_metrics, sample and label_server under the current config. For
  harness it is no, because dropping the country gate changes `action_match`, and the owner should decide.
- **Effort:** S–M.
- **Proving test:** `test_eval_tiers_follow_config`. It changes `critical.min_score` in a copied config to 8 and
  asserts that `score.action(8) == "call"`. Add `test_label_page_tiers_from_server` to check that the HTML has no hardcoded range.

### E-07 — Two scorers with contradictory outage taxonomies
- **File:line:** `separate_metrics.py:101-110` (`_is_transport_error`: {transport, transport_error, http_error, timeout})
  vs `suite/score.py:22-34` (`OUTAGE_KINDS`, which adds provider_error, budget_exhausted, invalid_response_json and model_mismatch).
- **Category:** inconsistent error handling. **Severity:** med.
- **What's wrong:** `provider_error` was added to `openrouter_client.py:657` on 2026-09-23. Stack A counts it as a
  model error and stack B counts it as an outage. So the same raw row is "the model's fault" in one report and
  "infrastructure" in the other. `_is_transport_error` also string-matches free-text `error` as a fallback.
- **Refactor:** Put a single `ERROR_KINDS` table (kind → `outage | model_fault | pre_send`) next to `CompletionError` in
  `openrouter_client.py`. Have both scorers import it. Delete the string matching.
- **Behavior-preserving:** no for stack A (provider_error and budget_exhausted move to outage). It is yes for stack B.
- **Effort:** S.
- **Proving test:** `test_error_kind_classification_is_shared`. It checks that every `kind` string emitted by
  `OpenRouterEvalClient.complete` is in `ERROR_KINDS`, and that `_is_transport_error({"error_kind": k})` equals
  `score.is_outage(...)` for every k.

### E-08 — `OpenRouterEvalClient.complete()` is 290 lines, with 13 near-identical `_failure(...)` calls
- **File:line:** `openrouter_client.py:446-732` (C901 24, 61 statements). Each failure call repeats 6–9 kwargs
  (`usage, request_id, returned_model, returned_provider, finish_reason, reasoning, provider_latency_ms`).
- **Category:** oversized function / duplication. **Severity:** med.
- **What's wrong:** Adding a field to `CompletionResult` means editing 13 call sites. One site already omits
  `request_id` (`:577-585`), harmlessly today.
- **Refactor:** Split the method into three steps:
  - `_preflight(model_id)`, which returns an optional failure.
  - `_send(body, reservation)`, which returns a response or a failure.
  - `_interpret(response, ctx)`, where `ctx` is a dict accumulated once from the payload and failures are
    `self._failure(..., **ctx)`.
  - Expected size: about 120 lines.
- **Behavior-preserving:** yes.
- **Effort:** S–M.
- **Proving test:** `tests/test_openrouter_eval_client.py` (539 lines) passes unchanged. Add a parametrised test that
  every failure kind after the HTTP send carries `request_id` when the payload has one.

### E-09 — Policy validation exists 3 times with different rules
- **File:line:** `sentinel/config.py:244-262` (production validator: ints required, monitored_countries required),
  `eval/clarified_policy.py:10-25` (`load_policy`: non-int ranges allowed, `scope: evaluation_only` required) and
  `eval/cached_runtime.py:60-70` (`_validate_policy`: a third subset, no range check).
- **Category:** duplication. **Severity:** low–med.
- **What's wrong:** The "is this policy usable" contract lives in three places. `clarified_policy.py` is otherwise only
  a 25-line re-export shim (`noqa: F401`) of `sentinel.classification.policy`.
- **Refactor:** Add `validate_policy(policy, *, scope=None)` in `sentinel/classification/policy.py` and call it from all
  three places. Fold `load_policy` into `compare_models` or into a `policy_file` helper, and delete `clarified_policy.py`
  (update the imports in 3 modules and 2 tests).
- **Behavior-preserving:** yes, as long as the eval-only checks stay scoped.
- **Effort:** S.
- **Proving test:** `test_policy_validation_single_source`. The same malformed policies are rejected by
  `SentinelConfig(...)`, `load_policy` and `_validate_policy`, each through `validate_policy`.

### E-10 — The test-only budget hook lives in the production provider
- **File:line:** `sentinel/classification/openai_provider.py:138,171-174,212-213` (`session_remaining`). It is set only
  by `eval/direct_luna.py:90,161` and `tests/test_direct_openai.py:279`.
- **Category:** eval leaking into production. **Severity:** low.
- **What's wrong:** It is a mutable public attribute on the live provider. Production never sets it, but it is extra
  surface in the money path.
- **Refactor:** Move the logic into a `SessionCapLedger` wrapper that `direct_luna` installs around
  `provider.ledger`, or make it a constructor argument `session_cap_usd=None`.
- **Behavior-preserving:** yes.
- **Effort:** S.
- **Proving test:** The existing `test_direct_openai.py::test_budget_refuses_before_http` and the `direct_luna` no-send
  test, rewritten against the wrapper.

### E-11 — The sampler calls a private production method that TODO 7.7 will change
- **File:line:** `suite/sample.py:258-283` calls `enricher._fetch_body(article)` and `is_garbage_summary`.
- **Category:** fragile coupling. **Severity:** low–med.
- **What's wrong:** The fix for "Google News decoder can stall the whole cycle" (TODO 7.7) will restructure
  `_fetch_body` and `_resolve_url`, and the sampler breaks silently or changes the frozen text on a rebuild. Also note
  `enrichment-cache.json`: it protects the frozen items only while the cache exists.
- **Refactor:** Expose a public `ArticleEnricher.fetch_body(article)` (or reuse `sentinel.processing.fulltext.fetch_full_text`,
  which `fulltext_snapshot.py` already uses). Have the sampler call that.
- **Behavior-preserving:** yes.
- **Effort:** S.
- **Proving test:** `test_sample_enrich_uses_public_api`, which monkeypatches the public method and asserts that
  `enrich` frozen-caches its output.

### E-12 — `harness.py` (the production `--eval` path) carries legacy-schema checks and hardcoded Haiku prices
- **File:line:**
  - `harness.py:27-29,335-338`: `HAIKU_*_PRICE_PER_M`, used when `provider != openai`.
  - `:62-64,198-204`: the `aggressor` and `event_type` checks, which the GPT-6 record calls "target the old schema and are ignored".
  - `:248`: `except Exception`, which swallows everything, including `BudgetExceeded`, and keeps looping.
- **Category:** dead code / weak error handling. **Severity:** low.
- **Refactor:**
  - Drop the Haiku price constants and read the cost from `config.classification.budget` or the ledger on both paths.
  - Move the legacy checks behind an explicit `legacy_checks` flag on the case, or report them separately from `overall_pass`.
  - Catch `ClassificationError` and stop on `BudgetExceeded`, as `direct_luna` does.
  - Do not touch `eval_set*.yaml`.
- **Behavior-preserving:** partially. `overall_pass` changes only if the legacy checks are excluded, which needs the owner's decision.
- **Effort:** S.
- **Proving test:** `test_harness_stops_on_budget_exceeded` and `test_harness_cost_uses_config_prices`.

### E-13 — Dead constants and minor duplication
- **Dead constants:** `suite/runner.py:46` `TRANSIENT` and `:62-68` `PRE_SEND` are referenced nowhere, not in the
  package and not in the tests. Severity: low. Effort: S. Behavior-preserving: yes. Delete both.
- **Request-hash duplication:** The request hash
  `sha256(json.dumps(messages, ensure_ascii=False, sort_keys=True))` is written out at `compare_models.py:344,477`,
  `runner.py:146`, `cached_runtime.py:50-51`, `direct_luna.py:106` and `tests/test_direct_openai.py:253`. Add
  `messages_sha256()` next to `prompt_hash` in `classification/policy.py`. Effort: S. Behavior-preserving: yes.
  Proving test: the hash pin `0563d8bb…` in `test_shared_prompt_matches_frozen_known_miss` stays green.
- **Percentile duplication:** Four percentile helpers use two definitions: `compare_models.py:411` and
  `separate_metrics.py:283` use the ceil method, while `suite/score.py:251` and `suite/price.py:58` use the round
  method. Unify them in `suite/stats.py`. Effort: S. Behavior-preserving: no, because reported p95 values can shift by
  one rank. Keep both definitions if historic comparability matters.
- **Inline model-spec parsing:** `parse_model_spec` (`runner.py:100`) is re-implemented inline at `score.py:402` and
  `report.py:381`. Import it. Effort: S. Behavior-preserving: yes.
- **SSH target duplication:** The SSH target and DB path are hardcoded twice. `suite/sample.py:21-22` uses no `sudo`,
  while `export_candidates.py:29-31` uses `sudo sqlite3`. The two disagree on whether `sudo` is needed. Use one
  `PROD_SSH` constant in `suite/sample.py` (or in config). Effort: S.
- **Unequal live budget caps:** The caps are hardcoded and unequal: `compare_models.py:536` allows ≤5,
  `runner.py:324` ≤60 and `direct_luna.py:81` ≤0.5. Treat this as documentation only, because they are deliberate safety rails.

### E-14 — `price.py` hardcodes the baseline model and has no way to model provider promotions
- **File:line:** `suite/price.py:32-36` (`BASELINE_SQL ... model_used = 'gpt-5.6-luna' AND classified_at >= '2026-09-20T21:30'`)
  and `:116-160` (`price_table` has no free-token input).
- **Category:** hardcoding / missing capability. **Severity:** med, because it can mislead a decision.
- **What's wrong:**
  - The owner rule of 2026-10-15 says every cost comparison must include provider promotions, which are now dominant:
    2.5M free tokens a day for the Luna group and 250k a day for the GPT-6 group.
  - `report.html` prices only list cost × volume. So the report's "cheaper" and "within cap" checks in
    `report.decide` currently invert the true ranking of 5.6-luna vs 6-luna.
  - The baseline SQL also breaks the day the baseline model changes.
  - This is separate from TODO 7.8, which is about the cap value. This finding is about the free allowance.
- **Refactor:**
  - Give `price_table` a `free_tokens_per_day: dict[model, int]` argument. Read it from a small tracked
    `config/eval_pricing.yaml`, or pass it via a `--promotions` JSON flag.
  - Compute "with" and "without" promotion monthly columns.
  - Parametrise `BASELINE_SQL` by the `--baseline` model.
- **Behavior-preserving:** no. The report gains new columns. Whether `decide()` should use the promo column is owner
  policy, and it must be fixed before the locked-pool run (pre-registration).
- **Effort:** M.
- **Proving test:** `test_price_table_applies_daily_free_tokens`. With 2.5M free tokens a day and 2.77M tokens a day of
  usage, the monthly cost equals the list price × (0.27/2.77).

### E-15 — `bad_input` labels are captured but never used in scoring
- **File:line:** `suite/label_server.py:123` stores `bad_input`, and `suite/score.py:87` copies it into the truth dict.
  Nothing in `score.py` or `report.py` reads it.
- **Category:** latent bug (data captured, semantics undefined). **Severity:** low–med.
- **What's wrong:** Items that the owner flagged as unusable input still count in critical recall, false-call rate and
  tier accuracy for every model.
- **Refactor:** No label change. Add an explicit, pre-registered rule: either exclude `bad_input` items from the paired
  metrics, or report them as a separate slice (`input:bad_input_flagged`). The slice is the safer default because it
  changes no headline number. The owner chooses.
- **Behavior-preserving:** yes, if added as a slice only.
- **Effort:** S.
- **Proving test:** `test_bad_input_items_reported_as_slice`.

### E-16 — The legacy-v1 path in compare_models depends on legacy production internals
- **File:line:** `compare_models.py:137-142`. `request_messages` calls `Classifier._build_user_prompt(None, article, candidates)`,
  an unbound private method with `self=None`. Also `:18` (imports `SYSTEM_PROMPT` and `USER_PROMPT_TEMPLATE`), the
  `score()` at `:279-316`, `summarize()` v1 at `:401-427`, `DEFAULT_DATASET = first50` and `DEFAULT_MODELS` (haiku,
  deepseek, qwen).
- **Category:** dead-ish code / fragile coupling. **Severity:** low.
- **What's wrong:**
  - The first round is closed. The docs say its "combined pass rate is not a valid model ranking".
  - The v1 path still pins the legacy Haiku prompt builder, so that legacy code cannot be simplified without breaking eval.
  - Running the bare command `python -m sentinel.eval.compare_models` validates the obsolete first50 dataset.
- **Refactor:** After E-02, move the v1 branch (`policy is None`) into `sentinel/eval/legacy/compare_v1.py`, or delete
  it and keep `rescore_dimensions` for reanalysing the saved v1 reports. Change the defaults to the v2 holdout plus
  `benchmark_policy_v2.yaml`.
- **Behavior-preserving:** no, because the CLI defaults change.
- **Effort:** S–M.
- **Proving test:** `test_model_comparison.py` is split. The v1 tests move along with the code. A new
  `test_default_cli_validates_v2` asserts the new default.

## 3. Module table

| Module | Lines | Still used? By whom | Verdict |
|---|---:|---|---|
| `harness.py` | 420 | Yes: `sentinel.py:393` (`./run.sh --eval`), `tests/test_cli_bridges.py`. Used for GPT-6 section B. | **Keep**, but clean it up (E-06, E-12). It is the only eval module on a production CLI path. |
| `compare_models.py` | 622 | Yes: the v2 comparator (GPT-6 section A re-run recipe). Also the de facto library for stack B and for `direct_luna`, `cached_runtime`, `rescore_dimensions`, `fulltext_snapshot` and 5 test files. | **Split.** Primitives go to `simulation.py` (E-02). Keep v2. Archive v1 (E-16). |
| `openrouter_client.py` | 807 | Yes: `suite/runner.py`, `suite/report.py` (catalogue), `compare_models`. | **Keep.** Shrink `complete()` (E-08). Own the error-kind table (E-07). |
| `separate_metrics.py` | 391 | Yes, but only from stack A (`compare_models`, `rescore_dimensions`). | **Keep while stack A lives.** Unify the taxonomy (E-07) and the tiers (E-06). |
| `reference_history.py` | 48 | Only from stack A (`replay_reference`, `rescore`). | **Keep** with stack A (it is small and pure). |
| `clarified_policy.py` | 25 | Shim used by stack A plus 2 tests. | **Merge** into `classification/policy.py` and `compare_models` (E-09), then delete. |
| `rescore_dimensions.py` | 57 | One-off reanalysis of the 2026-09-20 v1 report. Tested in `test_clarified_policy.py`. | **Archive** with the v1 path (E-16), or keep frozen. It is cheap either way. |
| `cached_runtime.py` | 314 | One-off for the 2026-09-20 Luna/DeepSeek runtime replay. It needs the config from the original commit. Has 309 test lines. | **Freeze, then archive** when stack A is retired. It is only useful for stack-A model-mode reports. |
| `direct_luna.py` | 185 | Yes: the GPT-6 verdict lists rerunning C as what would change it. `tests/test_direct_openai.py` exercises it. | **Keep but generalise.** Remove the hardcoded `DIRECT_LUNA_MODELS`, the holdout path and `v2h-ru-01-a` (`:29,33-34`). Rename it to `production_path_check.py`. |
| `export_candidates.py` | 56 | No. A one-off 2026-09-13..17 export, superseded by `suite/sample.py --from-production`. No tests. | **Archive** (move to `docs/archive/` or `scripts/archive/`). Drop the line in model-comparison.md. |
| `incident_memory.py` (eval) | 114 | Manual smoke only. No test. Has no spend cap, unlike `direct_luna`. Duplicates `make_config` sanitisation (`:37-39`). | **Merge** into `direct_luna`/production-path checks as a case set, or archive. Stack-B chains now cover memory decisions. |
| `suite/runner.py` | 435 | Yes: the current tool. | **Keep.** Dedupe via E-02. Delete dead constants (E-13). Split `run()` (C901 22) into manifest/resume/execute. |
| `suite/score.py` | 451 | Yes. | **Keep.** Tiers (E-06), taxonomy (E-07), `bad_input` (E-15). |
| `suite/report.py` | 415 | Yes. | **Keep.** `build_html` is 190 lines (C901 15). Splitting it per section is optional. |
| `suite/price.py` | 160 | Yes. | **Keep.** Add promotions and a parametrised baseline (E-14). |
| `suite/sample.py` | 350 | Yes (pool built once; rebuild only if needed). | **Keep.** Public enrich API (E-11), shared stratum (E-06). |
| `suite/label_server.py` + `label_page.html` | 297 | Yes: the owner is labelling now. | **Keep.** Only touch the tier constant (E-06), after the labelling batch. |
| `suite/fulltext_snapshot.py` | 64 | Yes (feeds `full_text` to the labeller, commit 8e055a0). No docs, no test. | **Keep.** Add a no-network test and a docs line. |
| `suite/stats.py` | 87 | Yes. | **Keep.** It becomes the home for the shared percentile (E-13). |

The fixtures stay where they are. `polish_summary_guard_fresh.yaml` is loaded by no code (as `docs/how-to/testing.md:127`
already says). Leave it as is, because it is owner-reviewed data.

## 4. Proposed phases

1. **Phase 1: safe mechanical cleanup.** No behaviour change, about half a day.
   - E-13 (dead constants, `messages_sha256`, `parse_model_spec` reuse, SSH constant).
   - E-08 (`complete()` split).
   - E-09 (single policy validator, delete the `clarified_policy` shim).
   - E-10 (session-cap wrapper).
   - Archive `export_candidates.py`.
   - Gate: all 154 eval tests plus `test_direct_openai.py` green, and the hash pins unchanged.
2. **Phase 2: separate the library from the legacy comparator.** No behaviour change.
   - E-02 (`sentinel/eval/simulation.py` + `simulate_runtime`).
   - E-04 (`get_memory_events(now=...)`).
   - E-11 (public enrich API).
   - Gate: the same tests, plus the new `simulate_runtime` sequence test.
3. **Phase 3: fidelity fixes.** These change eval numbers, so do them before the locked-pool run and record them in the
   pre-registration.
   - E-01 (production schema in stack A).
   - E-05 (shared output validation).
   - E-07 (one error taxonomy).
   - E-06 (config-derived tiers and countries).
   - E-14 (promotions plus parametrised baseline).
   - E-15 (`bad_input` slice).
   - The owner decides on E-06 (harness country gate), E-14 (whether `decide()` uses promo prices) and E-15
     (exclude or slice). These choices must be fixed before the locked-pool run, so the pre-registration stays honest.
4. **Phase 4: clock injection.** This touches production modules on the alert path, so it needs owner sign-off.
   - E-03 (injectable clock and event factory; remove `unittest.mock` from `sentinel/eval`).
5. **Phase 5: retire stack A.** Optional, and only after stack B has produced its locked-pool verdict.
   - E-16 (archive v1).
   - Move `cached_runtime`, `rescore_dimensions` and the v1 tests under `sentinel/eval/legacy/` or into git history.
   - Generalise `direct_luna`.
   - Merge or archive the eval `incident_memory`.
   - E-12 (harness cleanup).
