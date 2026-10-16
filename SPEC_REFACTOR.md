# Project Sentinel — Refactor 2026-10 — Implementation Specification

Status: ready for build · Author: main session, 2026-10-16 · Base: master `835ed8e`
Evidence: ten read-only audits in [`docs/ideas/refactor-audit-2026-10-16/`](docs/ideas/refactor-audit-2026-10-16/).
A tag such as `[01:A1]` means audit file `01-*.md`, finding `A1`. Read that finding before you implement the
requirement; it holds the file:line evidence, the reasoning and the test idea.

## Context

Sentinel is a life-safety alert bot. Urgency 9–10 places a phone call, sends a confirmation SMS and an additive Expo
push. Urgency 5–8 sends a push only. The audits confirmed, with probe tests, several ways a 9–10 call can be lost
today: a push error, one failing event, or a Twilio network error. The refactor first pins current behaviour with
tests, then closes those error paths, then restructures the code.

The owner approved three kinds of behaviour change, and no others: error-path safety, classification-failure fixes
and ingestion bug fixes. Every other change in this spec MUST preserve behaviour.

## Global rules (apply to every phase)

**G1** — Routing MUST NOT change. For every (urgency score, source count, acknowledged) input, the channels used and
the number of calls placed MUST equal master's, except where a requirement below says otherwise.
**G2** — The phase MUST NOT change any value in `config/config.yaml` that runtime code reads. It MAY delete keys that
no code reads, and it MAY add new keys whose value equals the code default. It MUST NOT add new `${VAR}`
placeholders to `config/config.yaml`, because the server's env file lacks them and the service would not start.
`config/config.example.yaml` MUST be kept in step.
**G3** — MUST NOT ssh to the production server. MUST NOT make paid API calls: no `./run.sh --eval`,
`--test-headline`, `--test-file`, `--diagnostic` or `--test-alert`, and no live OpenAI, Twilio or Expo traffic.
**G4** — MUST NOT create, edit, move or delete owner label data: `data/eval/**`, `tests/fixtures/eval_set.yaml`, any
`*label*` fixture, and `dashboard/data/annotations.db`.
**G5** — MUST NOT edit `CLAUDE.md` files, `mobile/AGENTS.md` or anything under `.claude/`. The owner reviews changes
to instruction files first.
**G6** — MUST NOT install, upgrade or remove packages in `/home/kossa/code/project-sentinel/.venv`. Gates use that
interpreter by absolute path. `npm ci` inside the worktree's `mobile/` or `dashboard/frontend/` is allowed.
**G7** — Code in `sentinel/eval/**` MAY change only as far as a production refactor requires to keep it working.
All eval tests MUST stay green.
**G8** — MUST NOT commit secrets; the repository is public. MUST NOT change `mobile/app.json` or start an EAS build.
Deploy files are edited as files only; nothing is deployed.
**G9** — When a phase adds a config key or a CLI flag, it MUST update `docs/reference/config-reference.md` or
`docs/reference/cli.md`. Other documentation drift is left for a later `/docs-update`.
**G10** — Golden files under `tests/golden/` (Phase 1) MUST stay byte-identical in every later phase, unless a
requirement names the change.

## Non-goals (owner decisions; recorded in TODO.md, "Findings from the 2026-10-16 refactor audit")

These are not built here: acknowledgement reading after the call round `[01:A4]`, a max age for stuck call records
`[01:A6]`, the uncorroborated 9–10 fallback channel `[01:A10]`, `last_updated_at` semantics `[01:A11]`
`[06:F08]`, a critical-first queue, attempt caps and a circuit breaker `[02:C-02]` `[02:C-04]` `[04:F2]`, the provider
code default `[02:C-06]`, the 19 keywords missing from the live lists `[06:F01]`, source identity for two-source
corroboration `[03:F09]`, call rounds outside the cycle lock `[01:A21]`, Expo receipts `[01:A23]`, the health-alert
channel `[10:D2]`, a dependency lock seeded from the server `[10:D4]`, the deploy-skill drift check `[10:D5]`, and the
eval subsystem `[07:*]`.

---

## Phase 1 — Safety net and lint baseline

### Deliverables
- `pyproject.toml` — add the `slow` and `network` markers and `--strict-markers` (modify)
- `sentinel/config.py`, `sentinel.py` — move `load_dotenv()` out of `load_config()` into `main()` (modify)
- `tests/conftest.py` — an autouse guard that refuses non-loopback sockets; a `prod_config` fixture (modify)
- `tests/test_cli.py` — make `test_custom_config_path` offline (modify)
- `sentinel/alerts/state_machine.py` — add the `code_factory` constructor argument only (modify)
- `tests/test_live_config.py`, `tests/test_safety_net_golden.py`, `tests/test_ack_path.py`,
  `tests/test_known_alert_bugs.py`, `tests/golden/*` (new)
- Every file that `ruff check --fix` and `ruff format` touch under `sentinel/ tests/ dashboard/ sentinel.py`
  (mechanical, its own commit)

### Requirements
**1.1** — `ruff check` and `ruff format --check` over `sentinel tests dashboard sentinel.py` MUST pass. The fix MUST
be a separate commit that contains only the output of `ruff check --fix --unsafe-fixes` and `ruff format`. `[08:T-12]`
**1.2** — `load_config()` MUST NOT read `.env`. `sentinel.py main()` MUST call `load_dotenv()` before it loads the
config, so the production process behaves as before. `[08:T-01]` `[06:F06]`
**1.3** — During tests, any connection to a non-loopback address MUST raise an error. No test may need the network;
`test_custom_config_path` MUST run with every source disabled. `[08:T-01]`
**1.4** — A `prod_config` fixture MUST load the tracked `config/config.yaml` through `load_config()`. It MUST move
`database.path`, `logging.file`, `classification.budget.ledger_path` and `sources.telegram.session_name` under
`tmp_path`. It MUST use shape-valid dummies: a numeric `TELEGRAM_API_ID`, an E.164 `ALERT_PHONE_NUMBER`, and an
`EXPO_PUSH_TOKEN` of the form `ExponentPushToken[…]`. `[08:T-03]` `[06:F04]`
**1.5** — `test_live_config.py` MUST pin the life-safety values of the live config: the tier that holds urgency 9–10
is `phone_call`, `max_call_retries` is 1, a single source triggers the call, 5–8 is `push`, the classification
provider is `openai`, and incident memory is enabled.
**1.6** — `test_safety_net_golden.py` MUST drive the real pipeline (`run_cycle`), from a fake fetcher article through
the classifier with OpenAI faked at `httpx.MockTransport`, incident memory, the corroborator, the dispatcher and the
state machine, using `prod_config`. Only the edges are fakes. `[08:T-02]` and section 5 of `08-tests.md`
- **OpenAI:** patch `openai.AsyncOpenAI` (or `OpenAIProvider.__init__`) so that every provider instance uses the
  `httpx.MockTransport`. That includes the enricher's own `enrichment_quality` provider. The handler answers
  `enrichment_quality` with `{"needs_enrichment": false, …}` and the classifier request with the canned result.
- **Twilio:** patch `sentinel.alerts.twilio_client.Client` with `create_autospec`, so the real `TwilioClient` runs.
  TwiML and SMS bodies are read from `calls.create(twiml=…)` and `messages.create(body=…)`.
- **Expo:** autospec `ExpoPushClient.send_push`. The push golden is the `data` dict passed to it.
- **Clock:** one conftest helper `freeze_time` pins `2026-10-16T12:00:00+00:00` by patching `datetime` in
  `sentinel.classification.classifier`, `sentinel.classification.corroborator`, `sentinel.alerts.state_machine`,
  `sentinel.alerts.twilio_client` and `sentinel.database`. Phase 5 replaces the helper with `Clock` injection and MUST
  keep the same instant.
- **Confirmation code:** `AlertStateMachine` MUST accept `code_factory: Callable[[], str]`, whose default makes a
  6-digit code with `secrets`. The golden test passes a constant. Phase 4's `CallRound` MUST keep that argument.
- **Golden article:** its `summary_pl` MUST be shorter than `SMS_SUMMARY_MAX_CHARS` (600).
**1.6a** — For an urgency-10 Poland article it MUST assert one push, one confirmation SMS and `max_call_retries`
calls, and the final `alert_status`.
**1.6b** — For urgency 7 it MUST assert one push and zero calls and SMS. For urgency 3 it MUST assert no delivery.
**1.6c** — It MUST write the exact push payload, SMS bodies and TwiML of 1.6a to `tests/golden/` and compare against
them on every later run. Before comparing, it MUST replace `message_id`, `event_id` and every `*_at` field with fixed
placeholders. The test MUST NOT rewrite the golden files; a `--update-golden` pytest option MAY do that.
**1.7** — `test_ack_path.py` MUST cover a correct SMS-code reply (the event is acknowledged and the follow-up SMS is
sent), a wrong code (not acknowledged), and a call that fails to start, which is today's HTTP 401 case. `[01:A13]`
`[08:T-04]`
**1.8** — `test_known_alert_bugs.py` MUST hold `xfail(strict=True)` tests proving three bugs on master: a push
exception blocks the call `[01:A1]`; a `requests.ConnectionError` on the confirmation SMS blocks the call `[01:A2]`;
one failing event skips later events in the batch `[01:A3]`.
**1.9** — Subprocess smoke tests in `tests/test_cli.py` MUST carry `@pytest.mark.slow`, except
`test_custom_config_path`, which stays unmarked so the gate exercises 1.3.
**1.10** — `tests/golden/routing_table.csv` MUST be generated once on this phase's base from `_determine_action`,
over urgency 0–10 × sources 1–3 with the live tiers from `prod_config`, and checked in. Phase 4 tests against it.

### Acceptance Tests
1. `test_live_config_loads_and_pins_life_safety_values` — (unit) [1.4, 1.5] the live config loads and the values match
2. `test_critical_article_calls_sms_and_pushes` — (integration) [1.6, 1.6a, 1.6c] the golden 9–10 path
3. `test_mid_urgency_article_pushes_only` — (integration) [1.6b] urgency 7 → push only
4. `test_low_urgency_article_sends_nothing` — (integration) [1.6b] urgency 3 → nothing
5. `test_correct_code_reply_acknowledges` — (integration) [1.7] the event is acknowledged and the follow-up is sent
6. `test_wrong_code_reply_does_not_acknowledge` — (integration) [1.7]
7. `test_call_failed_to_initiate_is_recorded` — (integration) [1.7] the 401 shape
8. `test_network_guard_blocks_outbound` — (unit) [1.3] a socket to 1.1.1.1 raises
9. `test_load_config_does_not_read_dotenv` — (unit) [1.2]
11. `test_routing_table_golden_matches_current_routing` — (unit) [1.10]
10. `test_push_error_does_not_block_call`, `test_sms_network_error_does_not_block_call`,
    `test_one_failing_event_does_not_skip_rest` — (integration) [1.8] each marked `xfail(strict=True)` and failing
    for the documented reason

### Gate Criteria
- `/home/kossa/code/project-sentinel/.venv/bin/python -m ruff check sentinel tests dashboard sentinel.py`
- `/home/kossa/code/project-sentinel/.venv/bin/python -m ruff format --check sentinel tests dashboard sentinel.py`
- `/home/kossa/code/project-sentinel/.venv/bin/python -m pytest tests/test_live_config.py tests/test_safety_net_golden.py tests/test_ack_path.py tests/test_known_alert_bugs.py -q -p no:cacheprovider`
- `/home/kossa/code/project-sentinel/.venv/bin/python -m pytest tests/ -q -p no:cacheprovider -m "not slow"`

---

## Phase 2 — Never lose a 9–10 alert (error-path safety)

Depends on Phase 1. All changes here alter behaviour only when something fails.

### Deliverables
- `sentinel/alerts/state_machine.py`, `sentinel/alerts/dispatcher.py`, `sentinel/alerts/twilio_client.py`,
  `sentinel/alerts/push_client.py` (modify)
- `sentinel/config.py`, `config/config.yaml`, `config/config.example.yaml` (modify)
- `sentinel/classification/incident_memory.py`, `sentinel/processing/enricher.py`, `sentinel/utils/html.py`,
  `sentinel/scheduler.py` (modify)
- `tests/test_known_alert_bugs.py` (modify: remove the xfail marks), `tests/test_alert_error_isolation.py`,
  `tests/test_config_validation.py`, `tests/test_error_paths.py` (new)
- Existing test fixtures that the new validation rejects, such as `tests/conftest.py`, `tests/test_config.py` and
  `tests/test_state_machine.py` (modify)

### Requirements
**2.1** — An exception while the additive push is built or sent MUST NOT prevent the 9–10 call. It is logged with
the traceback. The push still goes before the call. `push_client` MUST tolerate a non-dict response body. `[01:A1]`
**2.2** — The Twilio client MUST use an HTTP timeout from the new key `alerts.twilio.http_timeout_seconds`
(default 30). The client's call and SMS methods MUST catch `TwilioException` and `requests` exceptions and report them
as failures; they MUST NOT raise. A failed confirmation SMS MUST NOT stop the call. `[01:A2]` `[04:F1]`
**2.3** — The dispatcher MUST isolate events. An exception in one event is logged, and every later event in the batch
is still processed. The pending-call check and the cleanup still run. `[01:A3]` `[04:F1]`
**2.4** — `UrgencyLevel.action` MUST be `Literal["phone_call", "sms", "log_only"]`; `channel` keeps its current
`sms | push | both` validation. Loading MUST fail when no tier has `phone_call`, when `max_call_retries < 1`, or when
two tiers share a `min_score`. `[01:A7]` `[06:F02]`
**2.5** — Every alert template MUST be rendered once at load time with the full known field set. An unknown
placeholder MUST fail loading. The field set lives in `sentinel/config.py` as `ALERT_TEMPLATE_FIELDS`, because
`config.py` cannot import the state machine. `[01:A8]`
**2.6** — Config models MUST reject unknown keys (`extra="forbid"`). The dead key `sources.gdelt.update_interval_minutes`
MUST be removed from both YAML files; GDELT keeps its current behaviour. The dead alert keys of TODO 6.1 #6 MAY be
removed, but only from the model, both YAML files and every test fixture in one change; otherwise they stay in all of
them. `[06:F03]`
**2.7** — The confirmation SMS MUST cap `summary_pl` with the existing `SMS_SUMMARY_MAX_CHARS`, so the code line is
always sent. `[01:A9]`
**2.8** — When the event is already acknowledged, `check_pending_calls` MUST NOT overwrite `alert_status`. `[01:A5]`
**2.9** — A malformed event row MUST be skipped with a warning when incident-memory candidates are built. If building
candidates fails, the article MUST be classified without memory and not failed. `[03:F05]`
**2.10** — A failure of the OpenAI enrichment gate MUST NOT fail the article. It is logged and recorded as
`enrichment.method = "gate_error"`, and classification goes on without enrichment. `[05:F04]`
**2.11** — `strip_html` MUST keep the text of a summary that ends in a cut-off entity. `[04:F10]`
**2.12** — `--dry-run` MUST skip the pending-call check (TODO 6.1 #17).
**2.13** — The three xfail tests from 1.8 MUST pass as normal tests, with the marks removed.

### Acceptance Tests
1. `test_push_error_does_not_block_call` — (integration) [2.1, 2.13] the xfail mark is removed and it passes
2. `test_sms_network_error_does_not_block_call` — (integration) [2.2, 2.13] the xfail mark is removed and it passes
3. `test_one_failing_event_does_not_skip_rest` — (integration) [2.3, 2.13] the xfail mark is removed and it passes
4. `test_twilio_client_has_http_timeout` — (unit) [2.2]
5. `test_invalid_action_fails_load`, `test_no_phone_call_tier_fails_load`, `test_zero_call_retries_fails_load` —
   (unit) [2.4]
6. `test_unknown_template_field_fails_load` — (unit) [2.5]
7. `test_unknown_config_key_fails_load` — (unit) [2.6]
8. `test_confirmation_sms_keeps_code_with_long_summary` — (unit) [2.7]
9. `test_ack_label_survives_pending_check` — (integration) [2.8]
10. `test_bad_memory_row_is_skipped` — (unit) [2.9]
11. `test_enrichment_gate_error_still_classifies` — (integration) [2.10]
12. `test_strip_html_truncated_entity` — (unit) [2.11]
13. `test_dry_run_skips_pending_calls` — (unit) [2.12]

### Gate Criteria
- `/home/kossa/code/project-sentinel/.venv/bin/python -m ruff check sentinel tests dashboard sentinel.py`
- `/home/kossa/code/project-sentinel/.venv/bin/python -m pytest tests/test_known_alert_bugs.py tests/test_alert_error_isolation.py tests/test_config_validation.py tests/test_error_paths.py tests/test_live_config.py tests/test_safety_net_golden.py -q -p no:cacheprovider`
- `/home/kossa/code/project-sentinel/.venv/bin/python -m pytest tests/ -q -p no:cacheprovider -m "not slow"`

---

## Phase 3 — Classification and ingestion bug fixes

Depends on Phase 2.

### Deliverables
- `sentinel/classification/openai_provider.py`, `sentinel/classification/classifier.py` (modify)
- `sentinel/processing/keyword_filter.py`, `sentinel/processing/enricher.py`, `sentinel/processing/fulltext.py`,
  `sentinel/fetchers/telegram.py`, `sentinel/config.py` (modify)
- `tests/test_direct_openai.py`, `tests/test_telegram.py` (modify), `tests/test_budget_release.py`,
  `tests/test_keyword_match_modes.py`, `tests/test_keyword_config_lint.py`, `tests/test_ingestion_fixes.py` (new)

### Requirements
**3.1** — A request that the provider certainly did not bill MUST release its budget reservation (settled at 0,
status `released`). That covers HTTP 401, 403 and 429 with a response, and a connection error before any response.
A timeout or a 5xx after the request was sent MUST keep its reservation. `[02:C-01]`
**3.2** — A valid classification with an empty or blank `summary_pl` MUST use `summary_language.fallback_pl` and
record `summary_processing.action = "fallback"`. It MUST NOT raise. `[02:C-03]`
**3.3** — Exclude keywords MUST match whole words in every language. Critical and high keywords keep substring
matching for pl/uk/ru and word-boundary matching otherwise, with one exception. The high keywords `GRU` (en, pl) and
`ГРУ` (uk, ru) MUST match only as a whole word and only in that exact case, evaluated against the original-case text.
The keyword lists MUST NOT change. `[05:F01]`
**3.4** — `test_keyword_config_lint.py` MUST load the tracked keyword lists. For every high keyword K of every
language, `KeywordFilter.matches` on an article whose title is exactly K MUST return a high match. The only permitted
exception is `podejrzane manewry` (pl), listed in the test as `KNOWN_CONFLICTS` and in TODO.md as an owner item.
Critical keywords are not checked, because the filter never excludes a critical match.
**3.5** — The Telegram fetcher MUST map each message to its own channel through the numeric peer id resolved at
`start()`. The fallback to the first channel MUST be removed; an unmatched message is logged and dropped. Name,
language and URL come from the matched channel. `[05:F05]`
**3.6** — The enricher MUST NOT fetch a page for Telegram articles. It records
`enrichment = {"method": "none", "reason": "full_text_source"}`. `[05:F03]`
**3.7** — The Google News URL decoder MUST run off the event loop with a deadline from the new key
`processing.url_decode_timeout_seconds` (default 10), in both the enricher and fulltext. When the deadline passes, the original URL is used. (TODO 7.7, `[05:F10]`)

### Acceptance Tests
1. `test_rate_limit_releases_reservation`, `test_timeout_keeps_reservation` — (unit) [3.1]
2. `test_empty_summary_uses_fallback` — (unit) [3.2]
3. `test_exclude_gra_does_not_drop_granicy_or_kaliningrad`, `test_gru_does_not_match_grupa` — (unit) [3.3]
4. `test_live_keywords_not_cancelled_by_excludes` — (unit) [3.4]
5. `test_message_maps_to_its_own_channel`, `test_unmatched_message_dropped` — (unit) [3.5]
6. `test_telegram_article_not_enriched` — (unit) [3.6]
7. `test_decoder_stall_respects_deadline` — (unit) [3.7] a blocking decoder does not stall another coroutine

### Gate Criteria
- `/home/kossa/code/project-sentinel/.venv/bin/python -m ruff check sentinel tests dashboard sentinel.py`
- `/home/kossa/code/project-sentinel/.venv/bin/python -m pytest tests/test_budget_release.py tests/test_keyword_match_modes.py tests/test_keyword_config_lint.py tests/test_ingestion_fixes.py tests/test_telegram.py tests/test_direct_openai.py tests/test_safety_net_golden.py -q -p no:cacheprovider`
- `/home/kossa/code/project-sentinel/.venv/bin/python -m pytest tests/ -q -p no:cacheprovider -m "not slow"`

---

## Phase 4 — Structure: alerting and classification

Depends on Phase 3. Behaviour-preserving (G1, G10).

### Deliverables
- `sentinel/alerts/formatting.py`, `sentinel/alerts/routing.py`, `sentinel/alerts/ledger.py`,
  `sentinel/alerts/call_round.py` (new; split from `sentinel/alerts/state_machine.py`)
- `sentinel/alerts/state_machine.py`, `sentinel/alerts/dispatcher.py`, `sentinel/alerts/twilio_client.py` (modify)
- `sentinel/models.py` — status and type enums (modify)
- `sentinel/classification/legacy_anthropic.py` (new), `sentinel/classification/classifier.py`,
  `sentinel/classification/incident_memory.py` (modify)
- Tests that import moved private names (modify); `tests/test_alert_routing_table.py` (new)

### Requirements
**4.1** — `state_machine.py` MUST be split as described in `[01:A12]`: pure formatters, routing, the delivery ledger
and a per-event `CallRound` that owns the confirmation code and SMS SID (closing TODO 6.1 #5).
`sentinel/alerts/{state_machine,formatting,routing,ledger,call_round}.py` MUST each be 400 lines or fewer (`wc -l`).
**4.2** — Routing MUST be a public function `resolve_action(levels, score, source_count) -> Action`, used by the
dispatcher and the state machine. Production code MUST NOT call `_determine_action`. `[01:A18]` `[08:T-09]`
**4.3** — `TwilioClient` MUST expose `list_inbound_sms(since)` and `get_sms_status(sid)`. No other module may touch
the Twilio SDK object. `[01:A12]` `[08:T-05]`
**4.4** — Alert status, alert type and call status MUST be `StrEnum`s whose values equal today's strings. Stored
values MUST NOT change. `[01:A17]`
**4.5** — Duplicate SMS senders and per-article lookups MUST be folded into one helper each `[01:A16]`. Stale
docstrings MUST be corrected `[01:A19]`. The confirmation code MUST NOT be logged, and the default `code_factory`
(Phase 1) keeps using `secrets` `[01:A22]`.
**4.6** — The legacy Anthropic path MUST move to `legacy_anthropic.py` behind a backend protocol, and `classifier.py`
MUST NOT import `anthropic`. The legacy path still works when `provider: anthropic`. `[02:C-05]`
**4.7** — `test_alert_routing_table.py` MUST assert that `resolve_action` equals every row of
`tests/golden/routing_table.csv` (1.10). Acknowledged behaviour stays covered by `test_ack_path.py`.

### Acceptance Tests
1. `test_routing_table_matches_master` — (unit) [4.2, 4.7]
2. `test_twilio_sdk_used_only_in_client` — (unit) [4.3] a grep-style test over `sentinel/`
3. `test_enum_values_match_stored_strings` — (unit) [4.4]
4. `test_confirmation_code_not_logged` — (unit) [4.5]
5. `test_classifier_does_not_import_anthropic`, `test_legacy_backend_still_classifies` — (unit) [4.6]
6. `test_critical_article_calls_sms_and_pushes` — (integration) [4.1] the golden files are unchanged
7. `test_alert_modules_under_400_lines` — (unit) [4.1]

### Gate Criteria
- `/home/kossa/code/project-sentinel/.venv/bin/python -m ruff check sentinel tests dashboard sentinel.py`
- `/home/kossa/code/project-sentinel/.venv/bin/python -m pytest tests/test_alert_routing_table.py tests/test_safety_net_golden.py tests/test_ack_path.py tests/test_state_machine.py tests/test_classifier.py -q -p no:cacheprovider`
- `/home/kossa/code/project-sentinel/.venv/bin/python -m pytest tests/ -q -p no:cacheprovider -m "not slow"`

---

## Phase 5 — Structure: pipeline, clock and grouping

Depends on Phase 4. Behaviour-preserving (G1, G10).

### Deliverables
- `sentinel/utils/clock.py` (new); `sentinel/classification/corroborator.py`, `sentinel/database.py`,
  `sentinel/alerts/` modules (modify, to take the clock)
- `sentinel/classification/safety.py`, `sentinel/classification/grouping.py` (new);
  `sentinel/classification/corroborator.py` (modify)
- `sentinel/scheduler.py` (modify); `tests/conftest.py`, `tests/factories.py` (new/modify)
- `sentinel/eval/**` (modify only to use the clock, per G7)
- `tests/test_clock_injection.py`, `tests/test_pipeline_factory.py`, `tests/test_grouping_outcome.py` (new)
- `tests/test_classification_queue.py`, `tests/test_incident_memory.py`, `tests/test_integration.py`,
  `tests/test_scheduler.py`, `tests/test_cli_bridges.py`, and every test file that defines `_make_article`,
  `_make_event` or `_make_classification` (modify)

### Requirements
**5.1** — Production modules on the alert path MUST read time from an injectable `Clock`; the default is UTC
wall-clock time. Eval code MUST use it instead of patching `datetime` inside production modules. `[03:F08]` `[07:E-03]`
**5.2** — The life-safety gates of grouping MUST live in `safety.py`. The memory grouper and the legacy grouper MUST
be separate classes. `[03:F01]`
**5.3** — The corroborator MUST return a `GroupingOutcome` per event (event, decision, whether it is alertable). The
scheduler and the dispatcher MUST use it instead of re-reading the event. `[03:F03]`
**5.4** — The stored incident-memory JSON MUST record what really happened: when a match is rejected and a new event
is created, it MUST NOT say `duplicate` with the rejected `matched_event_id`, and it keeps the model's original
decision. Alert behaviour MUST NOT change. `[03:F04]`
**5.5** — `SentinelPipeline` MUST accept its parts by injection. `run_cycle` MUST be split into named steps of 60 lines
or fewer each. Tests MUST build the pipeline through one `make_pipeline` fixture; `__new__` assembly MUST be gone.
`[04:F6]` `[04:F7]` `[08:T-06]`
**5.6** — Article, event and classification test factories MUST live in `tests/factories.py`. `[08:T-07]`
**5.7** — The missing live-path tests MUST be added: article replay, the memory age gate, a deleted matched event, and
lifecycle statuses kept on update. `[03:F06]`

### Acceptance Tests
1. `test_fixed_clock_drives_age_gates` — (unit) [5.1]
2. `test_no_datetime_patch_in_eval` — (unit) [5.1] a grep over `sentinel/eval` for `patch(` on production modules
3. `test_grouping_outcome_drives_dispatch` — (integration) [5.3]
4. `test_rejected_match_audit_json` — (unit) [5.4]
5. `test_make_pipeline_injects_parts`, `test_run_cycle_steps_under_60_lines` — (unit) [5.5]
6. `test_memory_replay`, `test_memory_age_gate`, `test_matched_event_deleted`, `test_update_keeps_lifecycle_status` —
   (integration) [5.7]
7. `test_critical_article_calls_sms_and_pushes` — (integration) [5.2, 5.3] the golden files are unchanged

### Gate Criteria
- `/home/kossa/code/project-sentinel/.venv/bin/python -m ruff check sentinel tests dashboard sentinel.py`
- `/home/kossa/code/project-sentinel/.venv/bin/python -m pytest tests/test_clock_injection.py tests/test_pipeline_factory.py tests/test_grouping_outcome.py tests/test_corroborator.py tests/test_incident_memory.py tests/test_safety_net_golden.py -q -p no:cacheprovider`
- `/home/kossa/code/project-sentinel/.venv/bin/python -m pytest tests/ -q -p no:cacheprovider -m "not slow"`

---

## Phase 6 — Structure: ingestion, health and persistence

Depends on Phase 5.

### Deliverables
- `sentinel/fetchers/base.py`, `sentinel/fetchers/rss.py`, `sentinel/fetchers/google_news.py`,
  `sentinel/fetchers/gdelt.py`, `sentinel/fetchers/telegram.py` (modify);
  `sentinel/fetchers/http.py`, `sentinel/fetchers/feeds.py` (new)
- `sentinel/processing/article_page.py` (new); `sentinel/processing/enricher.py`, `sentinel/processing/fulltext.py`
  (modify)
- `sentinel/scheduler.py` (health), `sentinel/database.py` (modify)
- `tests/test_fetch_result_health.py`, `tests/test_http_helpers.py`, `tests/test_db_time_windows.py` (new)

### Requirements
**6.1** — Fetchers MUST share one HTTP helper (status, 304, 429, 5xx and WAF rules) and one feed-entry parser. The
User-Agent and timeout MUST come from the new keys `sources.http.user_agent` and `sources.http.timeout_seconds`
(default 30), with defaults equal to today's values. The GDELT User-Agent string, including the contact address now at
`sentinel/fetchers/gdelt.py:124`, MUST move to `sources.gdelt.user_agent`, with that exact literal as both the YAML
value and the code default. `[05:F08]`
**6.2** — `BaseFetcher` MUST be an ABC with `start`, `stop`, `lanes()` and `fetch(lane)`. The scheduler MUST NOT
special-case fetchers by name. The fast-lane RSS priority MUST come from the new key
`scheduler.fast_lane_rss_max_priority` (default 1). `[05:F09]`
**6.3** — Fetchers MUST run concurrently, each under an overall deadline from the new key
`scheduler.fetch_deadline_seconds` (default 120). A slow fetcher MUST NOT delay the Telegram buffer drain. `[05:F07]`
**6.4** — The enricher and fulltext MUST share `article_page.py`; `fulltext` MUST NOT call private enricher methods.
`[05:F10]`
**6.5** — `fetch()` MUST return a `FetchResult` that separates "no articles" from "failed". The per-source failure
counter and `health.json` MUST reflect real failures, including a Telegram client that is not connected. `health.json`
MUST be written atomically. `[05:F02]` `[04:F4]`
**6.6** — Stored timestamp formats MUST NOT change. Every window query (`get_recent_titles`, `get_active_events`,
`cleanup_old_records`) MUST compute its cutoff in Python as `(now - delta).isoformat()` through one
`Database._cutoff_iso` helper. A 60-minute window MUST NOT return an article that is 18 hours old. The format rewrite
in `tests/test_database.py:66-90` MUST be removed. `[06:F05]` `[05:F14]`
**6.7** — The daily summary MUST report the whole day's cycles (TODO 6.1 #12).

### Acceptance Tests
1. `test_get_feed_status_matrix` — (unit) [6.1] 200/304/403/429/503/HTML
2. `test_fast_lane_skips_gdelt_and_limits_rss` — (unit) [6.2]
3. `test_slow_fetcher_does_not_delay_telegram` — (integration) [6.3]
4. `test_fulltext_uses_article_page` — (unit) [6.4]
5. `test_failed_fetch_counts_in_health`, `test_health_json_written_atomically` — (unit) [6.5]
6. `test_recent_titles_window_excludes_old_rows` — (unit) [6.6]
7. `test_daily_summary_counts_all_cycles` — (unit) [6.7]

### Gate Criteria
- `/home/kossa/code/project-sentinel/.venv/bin/python -m ruff check sentinel tests dashboard sentinel.py`
- `/home/kossa/code/project-sentinel/.venv/bin/python -m pytest tests/test_fetch_result_health.py tests/test_http_helpers.py tests/test_db_time_windows.py tests/test_rss.py tests/test_google_news.py tests/test_gdelt.py tests/test_telegram.py tests/test_enricher.py tests/test_fulltext.py tests/test_scheduler.py tests/test_safety_net_golden.py -q -p no:cacheprovider`
- `/home/kossa/code/project-sentinel/.venv/bin/python -m pytest tests/ -q -p no:cacheprovider -m "not slow"`

---

## Phase 7 — Tooling, deploy files and repo hygiene

Depends on Phase 6. Files only; nothing is deployed (G8).

### Deliverables
- `pyproject.toml`, `requirements.txt` (modify)
- `deploy/configs/sentinel.service`, `deploy/configs/sentinel.service.d/20-openai.conf` (new),
  `deploy/02-deploy-app.sh`, `deploy/03-setup-services.sh`, `deploy/scripts/check-health.sh` (modify)
- `.gitignore` (modify); untracking `.code-refiner-state-redesign-*/`, `_temp/`,
  `data/audit-reports/.last-audit-timestamp`
- `sentinel.py`, `config/config.example.yaml`, `config/config.yaml` (comments only), `.env.example` (modify)
- `tests/test_repo_hygiene.py`, `tests/test_deploy_files.py`, `tests/test_cli_small_fixes.py` (new)

### Requirements
**7.1** — `pyproject.toml` MUST hold a `[project]` table with the runtime dependencies (upper bounds below the next
major version, including `apscheduler<4` and `telethon<2`), plus `dev` and `dashboard` extras, and
`[tool.setuptools.packages.find] include = ["sentinel*"]`. `requirements.txt` MUST remain an explicit list of runtime
packages, equal to `[project].dependencies`, with no `-e .`. Production MUST NOT need pytest or flask. No new
dependency MAY be added. `[10:D4]`
**7.2** — The systemd unit MUST set `StartLimitIntervalSec=0` under `[Unit]`, which keeps today's endless restart.
TODO 6.1 #2's own fix MUST NOT be applied. `[10:D1]`
**7.3** — The OpenAI drop-in MUST be versioned and installed by `03-setup-services.sh`. `02-deploy-app.sh` MUST use
`.venv` and the tracked `config/config.yaml`. (TODO 6.1 #15 and #16, `[10:D3]`)
**7.4** — `check-health.sh` MUST `cd` into the app directory and use `.venv`. Its alert channel MUST NOT change.
`[10:D2]`
**7.5** — `git ls-files -ci --exclude-standard` MUST return nothing. These MUST stay tracked at their current paths:
`config/config.yaml` (delete its line from `.gitignore`), `data/audit-reports/*.md` and `data/eval/human-labels.yaml`.
Re-include them with directory-level negation (`data/*`, `!data/eval/`, `data/eval/*`, `!data/eval/human-labels.yaml`,
and the same pattern for `data/audit-reports/`), because git cannot re-include a file whose parent directory is
excluded. Only these are untracked with `git rm --cached`: `data/audit-reports/.last-audit-timestamp`, `_temp/` and
`.code-refiner-state-redesign-*/`. Refiner and surgeon state is ignored by the globs `.code-refiner-state*/` and
`.code-surgeon-state*/`. `[10:H1]` `[10:H2]` `[10:H3]`
**7.6** — Small fixes from TODO 6.1: the `--test-alert push` help text names `EXPO_ACCESS_TOKEN` (#4); the example
config uses `max_call_retries: 1` (#7); misleading comments are corrected (#8); `--test-file` rejects list-shaped
YAML with a clear error (#9); `.env.example` lists `EXPO_PUSH_TOKEN` and `EXPO_ACCESS_TOKEN` (#11).
**7.7** — Dated, superseded `finance/build_*.py` generators SHOULD move to `finance/archive/`, unless a document or
script still runs them. `[10:H4]`

### Acceptance Tests
1. `test_pyproject_runtime_deps_bounded`, `test_no_dev_deps_in_runtime`,
   `test_requirements_matches_pyproject_dependencies` — (unit) [7.1]
2. `test_unit_start_limit_in_unit_section`, `test_dropin_versioned_and_installed`, `test_deploy_script_uses_dotvenv`,
   `test_check_health_cds_into_app` — (unit) [7.2, 7.3, 7.4]
3. `test_no_tracked_ignored_files`, `test_labels_still_tracked` — (unit) [7.5]
4. `test_test_file_rejects_list_yaml`, `test_example_config_single_call_retry`, `test_env_example_lists_expo_keys` —
   (unit) [7.6]

### Gate Criteria
- `/home/kossa/code/project-sentinel/.venv/bin/python -m ruff check sentinel tests dashboard sentinel.py`
- `bash -n deploy/02-deploy-app.sh deploy/03-setup-services.sh deploy/scripts/check-health.sh`
- `/home/kossa/code/project-sentinel/.venv/bin/python -m pip install --dry-run --no-deps -q -r requirements.txt`
- `/home/kossa/code/project-sentinel/.venv/bin/python -m pytest tests/test_repo_hygiene.py tests/test_deploy_files.py tests/test_cli_small_fixes.py -q -p no:cacheprovider`
- `/home/kossa/code/project-sentinel/.venv/bin/python -m pytest tests/ -q -p no:cacheprovider -m "not slow"`

---

## Phase 8 — Dashboard

Depends on Phase 7. The dashboard stays local-only and read-only. Read `dashboard/CLAUDE.md` and `SPEC.md` first.

### Deliverables
- `dashboard/db.py` (split into modules behind the same `DashboardDB` class), `dashboard/api/articles.py`,
  `dashboard/sync.py` (modify)
- `dashboard/frontend/src/components/AnnotationPanel.tsx` and its test (modify)
- `tests/dashboard/__init__.py`, `tests/dashboard/conftest.py` (new, live and legacy schema)
- `git mv tests/test_dashboard_{api,db,annotations}.py tests/dashboard/`, then modify them

### Requirements
**8.1** — The annotation form MUST NOT pre-select a label on an article without one. Save MUST be disabled until the
owner picks a label. `[09:D07]`
**8.2** — `annotations.db` MUST be attached read-only by `DashboardDB`. Only the annotation write path may open it for
writing. `[09:D08]`
**8.3** — Dashboard tests MUST build their database with `sentinel.database.Database` (live schema), plus one legacy
schema variant. Hand-copied schemas MUST be gone. `[09:D04]`
**8.4** — List counts and the `event_created` / `has_alert` filters MUST use one joined query (CTE). On a seeded
database of 20 000 articles and 2 000 events, `EXPLAIN QUERY PLAN` for the list query MUST contain no
`CORRELATED SCALAR SUBQUERY`, and the request MUST issue exactly one SQL statement. The test MAY log the elapsed time
but MUST NOT assert on it. `[09:D01]`
**8.5** — Every join MUST use one "latest classification per article" view, so an article with two classification
rows appears once. `[09:D03]`
**8.6** — Sync MUST copy to a `.part` file, check it with `PRAGMA integrity_check`, remove stale `-wal` and `-shm`
files, then swap the file in. `[09:D06]`
**8.7** — `db.py` SHOULD end with no module over 500 lines, and with one shared paging helper. `[09:D02]`

### Acceptance Tests
1. `AnnotationPanel no default label` — (unit, vitest) [8.1]
2. `test_main_connection_cannot_write_annotations` — (unit) [8.2]
3. `test_fixtures_use_live_schema` — (unit) [8.3]
4. `test_list_query_plan_has_no_correlated_subquery` — (integration) [8.4]
5. `test_duplicate_classification_row_listed_once` — (unit) [8.5]
6. `test_sync_atomic_swap_and_sidecar_cleanup` — (unit) [8.6]

### Gate Criteria
- `/home/kossa/code/project-sentinel/.venv/bin/python -m ruff check sentinel tests dashboard sentinel.py`
- `/home/kossa/code/project-sentinel/.venv/bin/python -m pytest tests/dashboard -q -p no:cacheprovider`
- `cd dashboard/frontend && npm ci --no-audit --no-fund && npx vitest run && npx tsc -b`

---

## Phase 9 — Mobile app

Depends on Phase 8. The change reaches the phone only after the owner makes a new EAS build (G8).

### Deliverables
- `mobile/src/messages/store.ts` and `mobile/src/messages/__tests__/store.test.ts` (modify)
- `mobile/src/messages/__fixtures__/push_payload_contract.json` (new)
- `mobile/src/messages/__tests__/contract.test.ts` (new), `tests/test_push_payload_contract.py` (new)

### Requirements
**9.1** — Every store mutation (`ingest`, `markRead`, `markAllRead`, `remove`, `clear`) MUST run one after another
through a single promise chain, so concurrent callers cannot lose or resurrect messages. The header comment MUST be
corrected. `[10:M1]`
**9.2** — One JSON fixture MUST hold a full event payload, an update payload and a byte-trimmed payload.
`test_push_payload_matches_contract_fixture` MUST build the three payloads in memory (fixed `uuid4`, fixed clock,
`prod_config`) and compare them byte for byte, including the exact key set, with
`mobile/src/messages/__fixtures__/push_payload_contract.json`. It MUST NOT write the file; a `--update-contract` pytest
option MAY rewrite it. A jest test MUST assert that `parsePayload` maps every field without a fallback. `[10:M3]`

### Acceptance Tests
1. `concurrent ingests keep both messages`, `remove racing ingest stays removed` — (unit, jest) [9.1]
2. `test_push_payload_matches_contract_fixture` — (unit) [9.2]
3. `contract fixture parses without fallback` — (unit, jest) [9.2]

### Gate Criteria
- `/home/kossa/code/project-sentinel/.venv/bin/python -m pytest tests/test_push_payload_contract.py tests/test_safety_net_golden.py -q -p no:cacheprovider`
- `cd mobile && npm ci --no-audit --no-fund && npx jest src/messages --ci && npx tsc --noEmit`
