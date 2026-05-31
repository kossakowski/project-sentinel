# Project Sentinel — Classification & Alerting Redesign: Implementation Specification

> **Consumer:** `/code-refiner` (implement → blind-review → resolve loop). This document is the
> single source of truth for that loop.
>
> **Decisions source of truth:** the 9 resolved owner decisions in `TODO.md` §6.0
> ("Resolved (2026-05-31)") + the design document `classification-alerting-redesign.DRAFT.md`.
> Where this spec and the draft disagree, **this spec + TODO §6.0 win** (the draft has known stale
> framing — e.g. it once called Romania a "gazetteer" addition; corrected here to whole-country).
>
> **Code facts:** grounded in a full read of the live tree on 2026-05-31. Baseline: **361 tests
> pass** (`.venv/bin/pytest tests/`). Line numbers are indicative — the executor must confirm
> against the live files before editing.
>
> **Prime directive (overrides everything):** never miss an urgency 9 or 10 event. A false 3am
> alarm is acceptable; a missed full-scale attack on Poland / a NATO border state is catastrophic.
> Every ambiguity resolves toward *firing*, never toward *suppressing*.

---

## Overview / End State

When complete, Project Sentinel will classify articles with a geography-correct Haiku 4.5 prompt
that scores attacks on monitored NATO border states — Poland, Lithuania, Latvia, Estonia **and now
Romania** — at urgency 9–10, and refuses to launder an unnamed "a NATO country" headline into a
Poland/9 phone call. A single `AlertPolicy` becomes the sole authority that decides what alert
fires, replacing the **three** duplicated decision sites that exist today; the corroboration gate is
deleted, leaving **deduplication as the only thing that can suppress an alert**. A new
`EventDeduplicator` (`sentinel/classification/event_dedup.py`) decides "new event or update to one I
already alerted on?" using a deterministic geo/locus/time core that **splits when unsure** (errs to a
redundant call, never a silenced strike), with a local-on-VPS multilingual embedding layer and a
Sonnet-4.6 same-event judge that engages only in the urgency-≥9 danger band and always runs
fire-first / fail-open. Alert sends are durably recorded with error codes and bounded retry, so a
transport outage can never fail silently. The human-labeled eval set becomes the owner's correctness
gate; the synthetic set stays for regression.

## Goals

- A non-Poland NATO incident can never acquire a Poland/9 label (root-cause fix for the historical
  false-positive PL calls and the Galați near-miss).
- Romania is monitored as a whole HIGH country; "Galați" resolves to Romania exactly as "Warsaw"
  resolves to Poland — no hand-maintained place list.
- One, and only one, code path decides whether/how an alert fires.
- Deduplication is the sole alert suppressor, biased to **split when unsure**.
- No external single point of failure in the alert-decision path (local embeddings; fail-open LLM
  judge; durable failure records; bounded retry).
- All tunables (countries, thresholds, model ids, windows, retry caps) live in `config/config.yaml`.

## Non-Goals

- **Q1 — Second human in the 9/10 escalation path.** Deferred (TODO §6.0). Out of scope.
- **Q2 — Second voice carrier / independent non-Twilio escalation channel + the §7 Watchdog /
  heartbeat / dead-man's-switch.** Deferred. Out of scope (the DRAFT's Watchdog/`channels.py`
  fallback-chain belong to this deferred reliability work, beyond the durable-records + bounded-retry
  slice in Phase 1).
- **Tier 3 LLM strategy** (Sonnet re-reads every borderline 7–9). Deferred (overlaps §1 tiered
  classifier work). Out of scope.
- **§6.1 config/deploy bugs** (stale GDELT `update_interval_minutes`, systemd `StartLimit*`
  placement, `app.json` placeholder `projectId`, `--test-alert push` help-text env var). Tracked
  separately in TODO §6.1.
- **The article-level `Deduplicator`** (`sentinel/processing/deduplicator.py`, URL+fuzzy-title) is
  **sound and stays untouched.** This redesign replaces *event grouping* (in `corroborator.py`), not
  article dedup.
- **The keyword-filter gate→hint refactor and fast-lane promotion** (DRAFT §4.3). Valuable but a
  separate ingestion change; out of scope here to keep the phases focused. (Logged for a follow-up.)
- **Production server deployment.** code-refiner runs and tests **locally only**; it MUST NOT SSH to
  or modify the production VPS. Deployment is a manual owner step after this spec lands.
- **DB-mining real fragmentation trap clusters, and labeling any traps.** Building the *blank*
  fixture (schema + authored catastrophe seeds) is in scope (Phase 3); mining real clusters needs
  read-only prod-DB access the loop lacks, and **the owner is the sole labeler.** Owner follow-ups.
- Mobile app, source expansion, productization (TODO §2/§3/§4).

## Technical Context

Python **3.12.3** monitoring bot. APScheduler dual-lane (fast 3 min / slow 15 min), SQLite
(`sentinel/database.py`), Twilio call+SMS (`sentinel/alerts/`), optional Expo push. Classification on
Claude **Haiku 4.5** (`claude-haiku-4-5-20251001`, read from `config.classification.model`,
`classifier.py:192` / `:276`). Tests: `.venv/bin/pytest` (pyproject `[tool.pytest.ini_options]`, marker
`integration`, `testpaths=["tests"]`). Lint: **ruff is configured** (pyproject `[tool.ruff]`,
line-length 120, target py311, selects E/W/F/I/UP/B/SIM). Config centralized in `config/config.yaml`
+ Pydantic models in `sentinel/config.py`; **nothing is hardcoded.**

Current-state facts the requirements act on (verified 2026-05-31):

- **Geography is country-level only.** `config/config.yaml` has **no top-level `countries:`**; lists
  live under `monitoring.target_countries` (PL/LT/LV/EE) and `monitoring.aggressor_countries`
  (RU/BY), each an object `{code, name, name_native}` (config.yaml:1–21). **No city/town/place list
  or gazetteer exists** anywhere; `sentinel/processing/keyword_filter.py` has zero hardcoded place
  names — only opaque keyword strings from config. The LLM resolves country from article text.
- **The classifier prompt is the root-cause defect** (`sentinel/classification/classifier.py`):
  the system prompt scopes the analyst to "Poland, Lithuania, Latvia, or Estonia" (L16); the user
  prompt states *"Urgency 9-10 is EXCLUSIVELY for attacks directly targeting PL, LT, LV, or EE
  territory"* (L142) and *"Attacks on Ukraine or other non-monitored countries = urgency 1-3"*
  (L143–144); `R4 POLAND PRIORITY` (L57–59) inflates Poland. There is **no literal "NATO = 9"
  string.** Good anti-spillover rules already exist: physical-location attribution (L34–35),
  "don't assume a monitored country if not explicitly stated → urgency 2-3" (L36–37), and
  affected_countries "ONLY list countries EXPLICITLY mentioned … Use [] if none" (L145–146).
  `affected_countries` is parsed raw at `classifier.py:186` (`data.get("affected_countries", [])`).
- **Three decision sites exist** (must collapse to one):
  1. `corroborator._determine_alert_status` (`sentinel/classification/corroborator.py:339-359`) —
     hardcoded 9/7/5 cuts, gates on `classification.corroboration_required`; written to
     `event.alert_status` but **never read by dispatch**.
  2. `state_machine._determine_action` (`sentinel/alerts/state_machine.py:261-292`) — config-driven
     from `alerts.urgency_levels`, gates on each level's `corroboration_required`. **This is the one
     that actually fires.**
  3. `harness._action_for_urgency` (`sentinel/eval/harness.py:32-45`) — a third copy with its own
     `MONITORED_COUNTRIES = {"PL","LT","LV","EE"}` (L25).
- **`corroboration_required` is a no-op** in two config namespaces:
  `classification.corroboration_required` (=1, config.yaml:475) and each
  `alerts.urgency_levels.*.corroboration_required` (=1). `source_count >= 1` is always true.
- **`alert_records` (`database.py:89-99`)** columns: id, event_id, alert_type, twilio_sid, status,
  duration_seconds, attempt_number, sent_at, message_body. **No error/failure column.** On send
  failure the Twilio/push client catches `TwilioRestException`/`httpx.HTTPError`, logs, and returns
  `None`; the caller inserts only on non-None — so **a failed urgency-9 alert leaves zero rows + one
  log line** (`twilio_client.py:60-62,93-95`; `state_machine.py:378-380`). Twilio `error_code` is
  read at `state_machine.py:510` but never persisted.
- **Retry is unbounded across cycles.** A failed phone round sets `alert_status="retry_pending"`
  (`state_machine.py:420`); the next cycle re-enters via `process_event`. Per-round is bounded by
  `acknowledgment.max_call_retries`; **cross-cycle round count has no cap** (docstring: "Never stops
  until acknowledged"). `urgency_levels.critical.retry_attempts: 3` is **dead config** (no reader).
- **`_confirmation_code` / `_confirmation_sms_sid`** are bare instance attributes set dynamically
  (`state_machine.py:442,452`), not per-event scoped; safe only because dispatch is serialized.
- **Eval:** `--eval` resolves `eval_path` at `sentinel.py:245`
  (`args.eval if args.eval != "DEFAULT" else config.testing.eval_set_file`). `TestingConfig`
  (config.py:207) defaults `eval_set_file="tests/fixtures/eval_set.yaml"`; **the live
  `config.yaml` `testing:` block has only `dry_run` — no `eval_set_file` key.** The gate is exit-code
  based at `overall_pass_rate == 1.0` (`sentinel.py:399`), run **manually** (`./run.sh --eval`); there
  is **no `.github/`, no Makefile, no automated CI.** `run_eval` hits the **live** Haiku API.
  - `eval_set.yaml` = 44 cases, each with `haiku_output` populated (frozen past behavior →
    regression), 0 urgency-9, `summary` non-null on 8/44.
  - `eval_set_human.yaml` = 50 owner blind-labeled cases (2026-05-22), `haiku_output: null`,
    `summary` (real DB snippets) on all 50 → the intended owner gate.
  - Per-case fields: `id`, `headline`, `summary` (falls back to headline when null), `source`,
    `language`, `audit_date`, `haiku_output`, `expected{is_military_event, event_type, urgency_min,
    urgency_max, affected_countries, aggressor, expected_action}`, `failure_mode`, `notes`. **There
    is no `body`/`article_text` field.**
- **No embedding stack exists** (no numpy/onnx/sentence-transformers/torch in requirements.txt;
  only `rapidfuzz`). Adding local embeddings is greenfield.

## Architecture Decisions

- **HYBRID rewrite/refactor.** Greenfield the two rotten cores (a new `EventDeduplicator`; a single
  `AlertPolicy`); targeted-refactor everything else. Avoids a risky full rewrite of a production
  life-safety system. _(DRAFT §1.)_
- **Deduplication is the sole alert suppressor; corroboration deleted.** _(Principles 1–2.)_
- **Geography stays country-level**; Romania added as a whole monitored HIGH country, no gazetteer.
  _(Q9.)_
- **Embeddings run locally on the VPS** (quantized/ONNX, ~0.5–1 GB), fail-open. _(Q3.)_
- **Tier 2** model strategy — Haiku classifies all; Sonnet 4.6 judges same-event only in the
  urgency-≥9 band, async/fire-first, fail-open. _(Q4.)_
- **Dedup splits when unsure**, on concrete signals only (geo_id, tier-cross, time gap). _(Q7.)_

## Assumptions

> The owner pre-decided all 9 governing questions (TODO §6.0), so the **decisions** are firm. Several
> **mechanism** details are the author's best judgment and are tagged `[assumed]` on the requirements
> that rely on them.

- **A1** New config key names (`geography.high_tier_countries`, `geography.nato_members`,
  `alerts.retry.*`, `dedup.*`, channel-class mapping, embedding/judge keys) are the author's choice;
  the executor may rename for consistency provided tests and the manifest stay in sync. `[assumed]`
- **A2** New modules: `sentinel/alerts/policy.py`, `sentinel/classification/event_dedup.py`,
  `sentinel/classification/geo_weighter.py`, `sentinel/classification/embeddings.py`,
  `sentinel/classification/dedup_judge.py`. `[assumed]` paths; keep consistent with conventions.
- **A3** Default numeric values (retry caps, dedup windows/thresholds) are starting points the owner
  tunes in config. `[assumed]` exact values.
- **A4** The exact local embedding model is deferred to implementation (Q3 says e5-small / BGE-M3
  int8 via ONNX); the spec requires the *seam*, not a pinned model. `[assumed]` exact model.
- **A5** `Rumunia` is the correct Polish `name_native` for Romania. `[assumed]`

---

## Phase 0 — Geography correctness (Romania + classifier prompt fix)

Root-cause fix for the historical false-positive PL calls and the Galați miss. Config + prompt only;
no new runtime infra. The deterministic post-LLM geo floor (`GeoWeighter`) is **Phase 2**.

### Deliverables
- `config/config.yaml` — add Romania to `monitoring.target_countries`; add a `geography:` block with
  `high_tier_countries` (incl. `RO`); add the `testing.eval_set_file` (human set) and
  `testing.regression_eval_set_file` (synthetic) keys; add Romanian-language source/keywords surface
  (modify).
- `sentinel/config.py` — add `regression_eval_set_file` to `TestingConfig`; add the `geography:`
  Pydantic model if the geography block needs typing (modify).
- `sentinel/classification/classifier.py` — revise the geography/urgency prompt: widen the system
  scope line to include Romania; replace the "EXCLUSIVELY PL/LT/LV/EE" + "non-monitored = 1-3"
  clauses so monitored = `PL/LT/LV/EE/RO` are 9–10-eligible and add the Principle-3 "NATO attack ON
  Russia = HIGH" case; add an explicit target-country gate (unnamed "a NATO country" must not resolve
  to a specific monitored country); demote `R4 POLAND PRIORITY` to a confirmed-PL tie-break; preserve
  the existing explicit-country-only / physical-location / inside-Ukraine-is-low rules (modify).
- `sentinel/eval/harness.py` — add `"RO"` to `MONITORED_COUNTRIES` (L25) so RO/9 maps to `phone_call`
  in the eval action derivation (modify).
- `sentinel.py` — run a second, **non-gating** regression eval reading
  `config.testing.regression_eval_set_file`; keep the gate run on `config.testing.eval_set_file`
  (~L245) (modify).
- `tests/test_classifier_geography.py` — deterministic prompt-construction tests (create).
- `tests/test_config_countries.py` — config-shape + harness-constant tests (create).

### Requirements
**0.1** — Config MUST add Romania to `monitoring.target_countries` as an object
`{code: RO, name: Romania, name_native: Rumunia}` (matching the existing object schema). _(Q9.)_

**0.2** — Config MUST add a `geography:` block whose `high_tier_countries` list contains
`PL, LT, LV, EE, RO`, marking Romania HIGH-eligible (a strike anywhere on Romanian soil, incl.
Bucharest, is HIGH). _(Q9 + principle 3.)_ `[assumed]` key name.

**0.3** — The implementation MUST NOT introduce any hardcoded city/town/place list or gazetteer for
Romania or any country; country resolution stays LLM-driven and country-level. _(Q9 — verified no
gazetteer exists.)_

**0.4** — Config SHOULD add Romanian-language source(s) and/or keyword entries so events on Romanian
soil are ingested (scan covers PL/EN/UA/RU/**RO**). _(Q9.)_ `[assumed]` exact sources.

**0.5** — The classifier prompt MUST include an explicit target-country gate: an unnamed "a NATO
country" / "a NATO member" reference MUST NOT be resolved to Poland or any specific monitored country
unless that country is explicitly named (strengthening the existing L36–37 rule). _(TODO §1.0.)_

**0.6** — The classifier prompt MUST revise the "Urgency 9-10 is EXCLUSIVELY for … PL, LT, LV, or EE"
clause (L142) and the "other non-monitored countries = 1-3" clause (L143–144) so that: monitored
countries = `PL/LT/LV/EE/RO` are 9–10-eligible; a non-monitored NATO state is NOT auto-9 on
membership alone; and a NATO/NATO-member attack ON Russia is HIGH-eligible. The system-prompt scope
line (~L16) MUST include Romania. _(TODO §1.0 + Q9.)_

**0.7** — `R4 POLAND PRIORITY` (L57–59) MUST be demoted to a tie-break applied **only after** Poland
is already confirmed as the physically-attacked country; it MUST NOT promote a non-PL incident to a
PL label. _(TODO §1.0.)_

**0.8** — The prompt MUST preserve (not weaken) the existing rules that spillover/defensive-response
affects urgency only and that `affected_countries` lists only countries explicitly named / physically
attacked (L34–37, L145–146). _(TODO §1.0.)_

**0.9** — The prompt MUST retain that a strike physically inside Ukraine with no monitored-country
soil involved is urgency 1–3 (routine inside-UA = LOW) and is not labeled an attack on a monitored
country (R9, L92–95). _(Principle 3 + Q8.)_

**0.10** — Config MUST set `testing.eval_set_file: tests/fixtures/eval_set_human.yaml` (the owner
correctness gate). _(Q5.)_

**0.11** — Config + `TestingConfig` SHOULD add `regression_eval_set_file:
tests/fixtures/eval_set.yaml`, wired in `sentinel.py` as a second **non-gating** (report-only)
regression run. _(Q5.)_ `[assumed]` key name.

**0.12** — The implementation MUST NOT modify, pre-fill, bootstrap, or auto-generate any labels in
`eval_set_human.yaml` or `eval_set.yaml`. The owner is the sole ground-truth labeler. _(CLAUDE.md /
project memory.)_

**0.13** — `harness.MONITORED_COUNTRIES` MUST include `"RO"` so the eval action derivation maps an
RO/urgency-9 case to `phone_call` (else the eval contradicts 0.1/0.2). _(Q9 + harness fact.)_

### Acceptance Tests
1. `test_prompt_scope_includes_romania` — (unit) [0.6] Build the prompt; assert the system scope line
   names Romania and the urgency-9–10 clause includes `RO`; assert the literal "EXCLUSIVELY for
   attacks directly targeting PL, LT, LV, or EE" string is gone/revised.
2. `test_prompt_nato_attack_on_russia_high` — (unit) [0.6] Assert the prompt contains a rule making a
   NATO/NATO-member attack ON Russia HIGH-eligible.
3. `test_prompt_target_country_gate` — (unit) [0.5] Assert the prompt forbids resolving an unnamed
   "a NATO country" to Poland/a specific monitored country unless explicitly named.
4. `test_prompt_r4_scoped_to_confirmed_pl` — (unit) [0.7] Assert R4 wording is scoped to "Poland
   already confirmed" and contains no language elevating a non-PL incident to PL.
5. `test_prompt_affected_countries_explicit_only` — (unit) [0.8] Assert the explicit-country-only +
   physical-location rules (L34–37, L145–146 equivalents) are still present.
6. `test_prompt_inside_ukraine_low` — (unit) [0.9] Assert the inside-Ukraine = urgency-1–3 rule is
   still present.
7. `test_config_ro_target_country` — (unit) [0.1] Load config; assert an object with `code == "RO"`
   exists in `monitoring.target_countries`.
8. `test_config_ro_high_tier` — (unit) [0.2] Assert `"RO"` ∈ `geography.high_tier_countries`.
9. `test_config_no_gazetteer` — (unit) [0.3] Structural predicate (deterministic): assert no config
   key named `gazetteer` / `places` / `cities` / `coordinates` / `geocells` exists at any depth, and
   that every `monitoring.target_countries` entry has only the keys `{code, name, name_native}` (i.e.
   countries stay code-level; this does not constrain free-form `monitoring.keywords` strings).
10. `test_config_eval_gate_human` — (unit) [0.10] Assert `config.testing.eval_set_file` ends with
    `eval_set_human.yaml`.
11. `test_config_regression_eval` — (unit) [0.11] Assert `config.testing.regression_eval_set_file`
    ends with `eval_set.yaml` and differs from the gate.
12. `test_harness_monitored_includes_ro` — (unit) [0.13] Import the harness; assert `"RO"` ∈
    `MONITORED_COUNTRIES`.
13. `test_harness_does_not_write_fixtures` — (unit) [0.12] Inspect the harness module source; assert
    no write/open-for-write against any path under `tests/fixtures/`.

**Non-gating acceptance (owner-run, live LLM — excluded from gate criteria, non-deterministic):**
`./run.sh --eval` (now defaulting to the human set) — Romania/Galați-type cases score HIGH and reach
`phone_call`; pass-rate ≥ pre-change baseline. (Note: the existing gate threshold is `==1.0`; on 50
blind human cases via live Haiku that will rarely be 100% — treat the report as diagnostic, not a
hard pass/fail. Revisiting that threshold is an owner decision, out of scope here.)

### Gate Criteria
- `.venv/bin/pytest tests/test_classifier_geography.py tests/test_config_countries.py -v`
- `.venv/bin/ruff check sentinel/classification/classifier.py sentinel/eval/harness.py sentinel/config.py`
- `.venv/bin/python -c "import sentinel.classification.classifier, sentinel.eval.harness"`
- `.venv/bin/python -c "import yaml; yaml.safe_load(open('config/config.yaml'))"`

---

## Phase 1 — Alerting reliability (durable failure records + bounded retry)

Logically independent of Phase 0, but both append to `config/config.yaml`, so run them serially.

### Deliverables
- `sentinel/database.py` — add `error_code TEXT` and `error_detail TEXT` columns to `alert_records`
  + an additive migration for existing DBs (modify).
- `sentinel/models.py` — add `error_code` / `error_detail` fields to `AlertRecord` and its `to_dict`
  (modify).
- `sentinel/database.py` — also add a persistent per-event retry-round counter column to the `events`
  table (e.g. `alert_round_count INTEGER NOT NULL DEFAULT 0`) so the cross-cycle cap (1.2) has
  durable state, plus its additive migration (modify).
- `sentinel/models.py` — add the matching `alert_round_count` field to the `Event` model (modify).
- `sentinel/alerts/state_machine.py` — persist a failure `AlertRecord` on the failed-send path;
  increment the per-event round counter each round and stop at the config cap; scope
  `_confirmation_code` / `_confirmation_sms_sid` per-event (modify).
- `sentinel/alerts/twilio_client.py`, `sentinel/alerts/push_client.py` — return a structured send
  result carrying the caught error code/detail on failure (replacing the bare `None`-return), so the
  caller can persist it (modify).
- `config/config.yaml` + `sentinel/config.py` — add `alerts.retry.max_rounds` (wiring the dead
  `urgency_levels.critical.retry_attempts` intent) (modify).
- `tests/test_alert_reliability.py` — (create).

### Requirements
**1.1** — A failed send MUST persist an `alert_records` row with `status="failed"` and a non-null
`error_code` — not only a log line. (This depends on 1.4: the client must surface the error to the
caller.) _(DRAFT §2.4 / §7.)_

**1.2** — The cross-cycle phone-retry rounds MUST be bounded by a config value
(`alerts.retry.max_rounds`), enforced against a **durable per-event round counter**
(`events.alert_round_count`, incremented once per round): when the counter reaches the cap the event
MUST move to a terminal failed status (e.g. `alert_status="failed_terminal"`) and stop re-entering
the retry loop. The bound MUST NOT rely on in-memory state (it survives restarts). _(DRAFT §2.4 /
§7.)_

**1.3** — A failed primary send MUST NOT silently drop the alert: it is recorded (1.1) and retried up
to the cap (1.2). Fail-loud, never fail-silent. _(Prime directive.)_

**1.4** — The Twilio/push clients MUST return a structured send result carrying the error
code/detail on failure (replacing the bare `None`-return), so the caller can persist the failure
record (1.1) and read the `error_code`. Transport errors are caught and surfaced, never swallowed.
_(DRAFT §2.4.)_ `[assumed]` exact result shape — a small dataclass `{success, error_code, detail}`
or an `AlertRecord` with `status="failed"` is acceptable; the executor MUST update all
`if record is None` call sites accordingly.

**1.5** — `_confirmation_code` / `_confirmation_sms_sid` SHOULD be scoped per-event so a reply to one
event's code cannot acknowledge another. _(TODO §6.1.5.)_

**1.6** — All retry/cap values MUST be read from `config/config.yaml`; none hardcoded. _(CLAUDE.md.)_

**1.7** — The `alert_records` schema change MUST migrate existing rows without data loss (additive
columns, sane defaults). _(Data integrity.)_

### Acceptance Tests
1. `test_failed_call_is_recorded` — (integration) [1.1, 1.3] Mock `make_alert_call` to return None
   (simulated 401); dispatch a critical event; assert an `alert_records` row with `status="failed"`
   and non-null `error_code` exists.
2. `test_retry_rounds_bounded` — (unit) [1.2] With `max_rounds=3` and persistent failure, assert
   `events.alert_round_count` increments to 3, the event then reaches `alert_status="failed_terminal"`,
   and a subsequent cycle does not place another call (counter read from the DB, not memory).
3. `test_failure_record_has_error_code` — (unit) [1.4] Mock a transport failure carrying an error
   code; assert the client returns a structured failure result and that code is captured into the
   persisted `alert_records` failure row.
4. `test_confirmation_code_per_event` — (unit) [1.5] Process two events; assert an ACK for event A
   does not resolve event B.
5. `test_retry_cap_is_config_driven` — (unit) [1.6] Set `max_rounds` to 1 then 5 in a test config;
   assert round count follows config.
6. `test_migration_adds_columns_preserves_rows` — (integration) [1.7] Seed an old-schema DB; run the
   migration; assert prior rows intact and `error_code`/`error_detail` present with defaults.

### Gate Criteria
- `.venv/bin/pytest tests/test_alert_reliability.py -v`
- `.venv/bin/ruff check sentinel/alerts/state_machine.py sentinel/alerts/twilio_client.py sentinel/alerts/push_client.py sentinel/database.py sentinel/models.py`
- `.venv/bin/python -c "import sentinel.alerts.state_machine, sentinel.database, sentinel.models"`

### Phase Dependencies
- Depends on: none (logically). Shares `config/config.yaml` with every phase — run serially.

---

## Phase 2 — Single `AlertPolicy` + `GeoWeighter` (decision consolidation; remove corroboration)

Collapses the **three** decision sites into one authority, deletes corroboration, and adds the
deterministic post-LLM geo floor. Defines the `EventDecision` contract that Phase 3 produces.

### Deliverables
- `sentinel/alerts/policy.py` — new `AlertPolicy`; `AlertIntent`, `EventDecision` (relation
  `NEW|SAME|ESCALATION`), `GeoTier`, `ChannelClass` contracts (create).
- `sentinel/classification/geo_weighter.py` — new `GeoWeighter` computing `geo_tier` from
  `target_country` / `attacker_is_nato` against `geography.*`, and a `kinetic` boolean derived from
  `event_type` against a config-driven kinetic-event-type set; floors kinetic HIGH-tier events to ≥9
  (create).
- `sentinel/classification/classifier.py` — extend the output schema with `target_country` and
  `attacker_is_nato` (and `geo_tier` if emitted by the LLM) consumed by `GeoWeighter` (modify).
- `sentinel/classification/corroborator.py` — delete `_determine_alert_status` and the corroboration
  source-count machinery (`_is_independent_source` and the source-count gate); the class no longer
  makes alert decisions (modify).
- `sentinel/alerts/state_machine.py` — `_determine_action` delegates to `AlertPolicy` (modify).
- `sentinel/eval/harness.py` — delete `_action_for_urgency`; derive the action via `AlertPolicy`.
  **Keep `MONITORED_COUNTRIES`** (still used by `_check_case` at ~L206-208 and by Phase 0's RO
  addition) (modify).
- `config/config.yaml` + `sentinel/config.py` — add the tier→channel-class mapping
  (`{min_score, channel_class}`) and a `geography.kinetic_event_types` list; remove the
  corroboration config surface in **all four places**: the `classification.corroboration_required`
  key (yaml) AND the `ClassificationConfig.corroboration_required` Pydantic field+default (config.py,
  ~L163, default 2), the per-level `alerts.urgency_levels.*.corroboration_required` keys (yaml) AND
  the `UrgencyLevel.corroboration_required` Pydantic field (config.py). Also remove the
  `corroboration_required` key set in `tests/conftest.py` (~L66) so the test config still loads
  (modify).
- `tests/test_alert_policy.py`, `tests/test_geo_weighter.py` — (create).

### Requirements
**2.1** — `AlertPolicy` MUST be the single authority deciding the alert action. After this phase,
`corroborator._determine_alert_status`, `state_machine._determine_action`, and
`harness._action_for_urgency` MUST NOT independently decide — they are deleted or delegate to
`AlertPolicy`. (The `harness.MONITORED_COUNTRIES` constant MUST survive — it is still used by
`harness._check_case`; only `_action_for_urgency` is removed.) _(DRAFT §3.2.)_

**2.2** — Corroboration MUST be removed: no corroboration / independent-source / `source_count` gate
may suppress or delay any alert. The entire corroboration config surface MUST be removed — both YAML
keys (`classification.corroboration_required`, `alerts.urgency_levels.*.corroboration_required`),
both Pydantic fields (`ClassificationConfig.corroboration_required` incl. its default,
`UrgencyLevel.corroboration_required`), and the `corroboration_required` key in `tests/conftest.py`
— so config still loads cleanly with no dead field. _(Principle 1.)_

**2.3** — Deduplication ("already alerted on THIS event") MUST be the only mechanism that suppresses
an alert: `AlertPolicy` returns no-alert ONLY when `relation == SAME` on an already-alerted event.
_(Principle 2.)_

**2.4** — Urgency tier MUST map to channel class: urgency ≥ call-tier (9–10) → `CALL`; lower → the
existing non-call `NOTIFY` class (SMS/push). _(Principle 4.)_

**2.5** — `GeoWeighter` MUST compute `geo_tier`: HIGH if `target_country ∈
geography.high_tier_countries` OR (`target_country == RU` AND `attacker_is_nato`); LOW for routine
inside-Ukraine / interior Moldova; and MUST floor a **kinetic** HIGH-tier event's urgency to ≥9.
`AlertPolicy` MUST require urgency ≥ call-tier **AND** `geo_tier == HIGH` for `CALL`. _(Q8, Q9,
principle 3.)_

**2.5b** — "Kinetic" MUST be derived deterministically from the classifier `event_type` against a
config-driven set `geography.kinetic_event_types` (e.g. invasion/airstrike/missile_strike/
artillery_shelling/drone_attack — owner tunable), NOT a new LLM field and NOT hardcoded. This single
definition is consumed by both `GeoWeighter` (2.5) and the Phase 3 kinetic separator (3.8).
_(DRAFT §5.2; closes the otherwise-undefined kinetic signal.)_ `[assumed]` exact set.

**2.5a** — If `geo_tier` is UNKNOWN/unresolved for an urgency-≥9 event, it MUST be treated as HIGH
(fail toward firing). _(Prime directive; DRAFT §4.2 "default HIGH for ambiguity".)_

**2.6** — A `NEW` event at CALL tier MUST fire a call; an `ESCALATION`/UPDATE to an already-alerted
event MUST use `NOTIFY` (SMS), not a second call — one call per event. _(Principle 4 + CLAUDE.md.)_

**2.7** — The decision MUST be channel-agnostic: `AlertIntent` carries a channel **class**; transport
(Twilio call/SMS, optional Expo push) stays pluggable behind it; current transports preserved.
_(Principle 4.)_

**2.8** — All thresholds (call-tier value, tier→class mapping, `geography.*` membership) MUST live in
`config/config.yaml`; none hardcoded. _(CLAUDE.md.)_

**2.9** — `AlertPolicy.decide(...)` SHOULD be a pure function of its inputs (`EventDecision`,
weighted urgency, `geo_tier`) with no I/O, so it is fully unit-testable. _(Testability.)_

**2.10** — This phase MUST define the `EventDecision` contract (relation `NEW|SAME|ESCALATION` +
`matched_event_id: str|None`) as the interface Phase 3's `EventDeduplicator` produces and
`AlertPolicy` consumes. `policy.py` is a serialization point shared with Phase 3. _(Interface
contract.)_ `[assumed]` exact field set.

### Acceptance Tests
1. `test_new_critical_high_calls` — (unit) [2.4, 2.5, 2.6] relation=NEW, urgency=9, geo=HIGH →
   channel-class CALL.
2. `test_escalation_high_notifies_not_recall` — (unit) [2.6] relation=ESCALATION on an
   already-alerted event, urgency=9, geo=HIGH → NOTIFY, not CALL.
3. `test_same_already_alerted_suppresses` — (unit) [2.3] relation=SAME on already-alerted → no alert.
4. `test_no_corroboration_gate` — (unit) [2.2] relation=NEW, urgency=9, geo=HIGH, single source →
   still CALL (no source-count consulted); assert neither `corroboration_required` key exists in
   config.
5. `test_low_geo_critical_does_not_call` — (unit) [2.5] relation=NEW, urgency=9, geo=LOW (inside-UA)
   → not CALL.
6. `test_unknown_geo_critical_fails_open` — (unit) [2.5a] relation=NEW, urgency=9, geo=UNKNOWN →
   treated HIGH → CALL.
7. `test_lower_urgency_notifies` — (unit) [2.4] relation=NEW, urgency=5, geo=HIGH → NOTIFY, not CALL.
8. `test_geo_weighter_nato_attacks_russia_high` — (unit) [2.5] target=RU, attacker_is_nato=true →
   geo_tier HIGH.
9. `test_geo_weighter_floors_high_tier_kinetic` — (unit) [2.5] HIGH-tier kinetic event with LLM
   urgency 4 → floored ≥9.
10. `test_geo_weighter_kinetic_from_event_type` — (unit) [2.5b] an `event_type` in
    `geography.kinetic_event_types` → kinetic True; `troop_movement` → kinetic False; assert it
    follows config (move a type in/out of the set).
11. `test_thresholds_config_driven` — (unit) [2.8] move the call-tier threshold in a test config;
    assert the CALL boundary shifts.
12. `test_old_decision_sites_removed` — (unit) [2.1] assert `corroborator._determine_alert_status`
    and `harness._action_for_urgency` no longer exist (or are thin delegations),
    `state_machine._determine_action` delegates to `AlertPolicy`, and `harness.MONITORED_COUNTRIES`
    still exists.
13. `test_event_decision_contract` — (unit) [2.9, 2.10] construct an `EventDecision`; assert it
    exposes the relation + matched_event_id consumed by `AlertPolicy`.

### Gate Criteria
- `.venv/bin/pytest tests/test_alert_policy.py tests/test_geo_weighter.py -v`
- `.venv/bin/ruff check sentinel/alerts/policy.py sentinel/classification/geo_weighter.py sentinel/classification/corroborator.py sentinel/alerts/state_machine.py sentinel/eval/harness.py`
- `.venv/bin/python -c "from sentinel.alerts.policy import AlertPolicy, EventDecision; from sentinel.classification.geo_weighter import GeoWeighter"`

### Phase Dependencies
- Depends on: Phase 0 (RO + `geography:` config + `target_country` prompt fields) and Phase 1 (the
  action emits through the durable-record path). Provides the `EventDecision` contract for Phase 3.

---

## Phase 3 — `EventDeduplicator` (deterministic core; split-when-unsure)

New `sentinel/classification/event_dedup.py :: EventDeduplicator.decide(article, result) →
EventDecision`, replacing the event-grouping logic in `corroborator._find_matching_event`. **The
article-level `sentinel/processing/deduplicator.py` is NOT touched.** No network/LLM I/O here
(Phase 4). Creates the blank trap fixture.

### Deliverables
- `sentinel/classification/event_dedup.py` — new `EventDeduplicator` + deterministic `geo_id` /
  signature / event-family logic (create).
- `sentinel/classification/corroborator.py` — remove `_find_matching_event` grouping; the
  `Corroborator` either delegates grouping to `EventDeduplicator` or is reduced to non-grouping
  responsibilities (modify).
- `config/config.yaml` + `sentinel/config.py` — `dedup.*` window/novelty/geo settings (modify).
- `tests/fixtures/dedup_traps.yaml` — BLANK-label multi-article trap fixture (create).
- `tests/test_event_dedup.py` — deterministic dedup tests (create).
- `tests/test_dedup_traps.py` — fixture schema test + label-gated behavioral test (create).

### Requirements
**3.1** — `EventDeduplicator.decide(...)` MUST replace the grouping in
`corroborator._find_matching_event` and emit an `EventDecision` (relation `NEW|SAME|ESCALATION` +
matched event) per the Phase 2 contract. _(DRAFT §5.)_

**3.2** — When same-event vs new-event is genuinely ambiguous, the relation MUST default to `NEW`
(a possibly-redundant call), never `SAME` (a possibly-silenced strike). _(Q7.)_

**3.3** — Splitting MUST be driven by **concrete signals** — different `geo_id`, urgency crossing the
CALL tier, a real time gap / novelty-window expiry — and MUST NOT split on mere wording differences
(to avoid re-introducing Galați-304 fragmentation). _(Q7.)_

**3.4** — `geo_id` normalization MUST collapse cross-language references to the same locus (e.g.
`Gałacz` / `Galați` / `Галац` → one `geo_id`) via transliteration/ASCII-folding, NOT a hardcoded
town list. _(Q9; DRAFT §5.1 Step 1.)_

**3.5** — A new event whose urgency ≥ an existing lower-urgency event at the same place MUST NOT be
silently merged into it (no attach-and-silence): a sub-critical→critical crossing MUST surface as
`ESCALATION`/`NEW`, never a silent `SAME`. _(Q6; DRAFT §5.2.)_

**3.6** — A strike on monitored-country soil while a different event is already open MUST produce a
`NEW` event re-evaluated for CALL (the RO-event-open → PL-strike catastrophe). _(Q6.)_

**3.7** — Deduplication MUST NOT suppress across a different `geo_id` or across the CALL-tier
boundary (hard deterministic overrides the smart layer cannot overrule). _(Q7; DRAFT §5.2.)_

**3.8** — A kinetic strike MUST NOT merge into a non-kinetic (airspace-violation) event regardless of
similarity, using the same `geography.kinetic_event_types` definition introduced in 2.5b. _(DRAFT
§5.2 override 4.)_

**3.8a** — The classifier already emits `is_new_event` (`classifier.py:125,188`). The deduplicator
MAY use it as a NEW-direction signal only (a `true` is evidence to split); it MUST NOT use it as a
merge-toward-prior signal. (Resolves the DRAFT §5.1 reference: this spec neither requires resurrecting
it as a gate nor forbids using it to split.) _(DRAFT §5.1.)_

**3.9** — The deterministic core MUST perform no network/LLM I/O (embeddings/judge are Phase 4) and
MUST be deterministic and fully unit-testable. _(Testability.)_

**3.10** — The implementation MUST create `tests/fixtures/dedup_traps.yaml` as a **blank-label**
multi-article fixture: a defined schema plus authored catastrophe seed scenarios (RO-open→PL-strike;
same place hours apart; kinetic vs non-kinetic same place; simultaneous strikes different towns) with
all merge/separate/urgency label fields **present but empty**. The implementation MUST NOT fill any
label. _(Q6 + CLAUDE.md.)_

**3.11** — All dedup windows/thresholds/normalization settings MUST live in `config/config.yaml`;
none hardcoded. _(CLAUDE.md.)_

### Acceptance Tests
1. `test_geo_id_cross_language_collapse` — (unit) [3.4] `["Gałacz","Galați","Галац"]` normalize to
   one `geo_id`.
2. `test_different_geo_id_splits` — (unit) [3.7, 3.3] two articles, different `geo_id` → two `NEW`.
3. `test_urgency_tier_cross_splits` — (unit) [3.3, 3.5] same place, second crosses CALL tier →
   `ESCALATION`/`NEW`, never silent `SAME`.
4. `test_ambiguous_defaults_to_new` — (unit) [3.2] no concrete same-event signal → `NEW`.
5. `test_no_attach_and_silence` — (unit) [3.5] low-urgency event open, higher-urgency strike same
   place → not a silent `SAME`.
6. `test_ro_open_then_pl_strike_splits` — (unit) [3.6] RO event open, then PL-soil strike → `NEW`
   for CALL re-evaluation.
7. `test_kinetic_not_merged_into_nonkinetic` — (unit) [3.8] kinetic strike vs open airspace-violation
   event → not merged.
8. `test_dedup_no_network_io` — (unit) [3.9] patch network/LLM to raise; assert `decide` still
   returns an `EventDecision`.
9. `test_dedup_traps_schema` — (unit) [3.10] load `dedup_traps.yaml`; assert it parses, has the
   defined per-scenario fields, contains the authored catastrophe seeds, and every label field is
   blank.
10. `test_dedup_traps_behavioral` — (integration) [3.5, 3.6, 3.7] parametrized over **labeled** trap
    cases only (unlabeled cases `pytest.skip`); for each labeled case assert the deduplicator's
    verdict matches the owner label. (Green now via skips; a real gate once the owner labels.)
11. `test_dedup_window_config_driven` — (unit) [3.11] change the dedup window in a test config;
    assert the time-gap split boundary shifts.

### Gate Criteria
- `.venv/bin/pytest tests/test_event_dedup.py tests/test_dedup_traps.py -v`
- `.venv/bin/ruff check sentinel/classification/event_dedup.py sentinel/classification/corroborator.py`
- `.venv/bin/python -c "from sentinel.classification.event_dedup import EventDeduplicator"`
- `.venv/bin/python -c "import yaml; yaml.safe_load(open('tests/fixtures/dedup_traps.yaml'))"`

### Phase Dependencies
- Depends on: Phase 0 (`target_country`/affected_countries feed `geo_id`), Phase 2 (`EventDecision`
  contract). Provides the deterministic deduplicator Phase 4 augments.

---

## Phase 4 — Embeddings + Sonnet critical-band judge (the smart layer)

Layers a local embedding candidate scorer and a Sonnet-4.6 same-event judge onto the deterministic
deduplicator. Highest uncertainty (exact model deferred per Q3); requirements are intentionally a
touch higher-level and refinable after Phase 3 lands.

### Deliverables
- `sentinel/classification/embeddings.py` — local embedding wrapper (quantized/ONNX), fail-open
  (create).
- `sentinel/classification/dedup_judge.py` — Sonnet 4.6 same-event judge, async/fire-first,
  fail-open (create).
- `sentinel/classification/event_dedup.py` — wire embedding candidate scoring + judge into the
  ambiguous band; fire-first short-circuit for geo-floored-≥9 HIGH-tier articles (modify).
- `config/config.yaml` + `sentinel/config.py` — embedding model name/path, candidate-band
  thresholds, judge model id (Sonnet 4.6), judge trigger (urgency ≥ 9 either side),
  `judge_timeout_seconds`, Tier-2 toggle (modify).
- `requirements.txt` — add embedding runtime deps (e.g. `onnxruntime`, `numpy`,
  `sentence-transformers`) (modify).
- `tests/test_embeddings.py`, `tests/test_dedup_judge.py` — hermetic tests (create).

### Requirements
**4.1** — The embedding model MUST run locally on the host; no hosted embedding API in the dedup path.
_(Q3.)_

**4.2** — Embeddings MUST fail-open: a failed/unavailable embed yields relation `NEW` (fire), never a
suppression. _(Q3.)_

**4.3** — Embedding similarity MUST apply only in the ambiguous band between the deterministic
prefilter and the final verdict; the Phase 3 deterministic hard overrides (geo/locus mismatch,
CALL-tier crossing, kinetic/non-kinetic) MUST NOT be overruled by similarity. _(DRAFT §5.1–5.2.)_

**4.4** — The Sonnet 4.6 same-event judge MUST be invoked **only** when urgency ≥ 9 on either side.
_(Q4.)_

**4.5** — For a geo-floored-≥9 HIGH-tier article the CALL MUST fire first (synchronously); the judge
runs **asynchronously** and may only suppress a subsequent duplicate copy — it MUST NOT gate or delay
the first call. _(Q4; DRAFT §5.1 Step 0a.)_

**4.6** — The judge MUST fail-open on timeout/429/error → relation `NEW` + CALL, under a config
`judge_timeout_seconds` hard timeout. _(Q4; DRAFT §5.1 Step 4.)_

**4.7** — Article classification MUST remain on Haiku 4.5; only the dedup judge escalates to Sonnet
4.6 (Tier 2). _(Q4 + CLAUDE.md.)_

**4.8** — Embedding model identity, judge model id, the urgency trigger, candidate-band thresholds,
`judge_timeout_seconds`, and the Tier-2 toggle MUST all live in `config/config.yaml`; none hardcoded.
_(Q4 + CLAUDE.md.)_

**4.9** — The embedding model SHOULD be a lightweight/quantized multilingual model suited to the VPS
(2 cores, 3.8 GB RAM) — e.g. `multilingual-e5-small` or `BGE-M3` int8 via ONNX (~0.5–1 GB); exact
choice tuned against the over-merge eval. _(Q3.)_ `[assumed]` exact model.

**4.10** — Tests for the embedding layer and the judge MUST be hermetic (mock the local model and the
Sonnet API); any test requiring the real model/live API MUST be marked non-gating (`integration`).
_(Determinism.)_

### Acceptance Tests
1. `test_embedding_fail_open` — (unit) [4.2] patch the embedder to raise; assert `decide` returns
   relation `NEW`.
2. `test_embedding_only_in_ambiguous_band` — (unit) [4.3] a hard `geo_id` mismatch → split despite a
   forced high similarity (override not overruled).
3. `test_judge_only_on_high_urgency` — (unit) [4.4] urgency 5 both sides → judge not called; urgency
   9 either side → judge called (mocked).
4. `test_judge_is_fire_first` — (unit) [4.5] a geo-floored-≥9 HIGH-tier article fires CALL without
   awaiting a blocking judge mock.
5. `test_judge_fail_open` — (unit) [4.6] judge mock raises/times out → relation `NEW` + CALL.
6. `test_classification_model_is_haiku` — (unit) [4.7] assert the classifier model id resolves to
   `claude-haiku-4-5-20251001` and the judge id to a Sonnet 4.6 id, from config.
7. `test_dedup_smart_layer_config_driven` — (unit) [4.8] flip the Tier-2 toggle off in a test config;
   assert the judge is never invoked.

### Gate Criteria
- `.venv/bin/pytest tests/test_embeddings.py tests/test_dedup_judge.py -v`
- `.venv/bin/ruff check sentinel/classification/embeddings.py sentinel/classification/dedup_judge.py sentinel/classification/event_dedup.py`
- `.venv/bin/python -c "import sentinel.classification.embeddings, sentinel.classification.dedup_judge"`

### Phase Dependencies
- Depends on: Phase 3 (augments `EventDeduplicator`) and Phase 2 (`EventDecision`). Last/most
  refinable phase.

---

## Shared files / serialization points

`config/config.yaml` + `sentinel/config.py` are touched by every phase (each appends a disjoint
section). `classifier.py` (Phase 0 prompt, Phase 2 schema), `state_machine.py` (Phase 1, Phase 2),
`corroborator.py` (Phase 2, Phase 3), `harness.py` (Phase 0, Phase 2), `policy.py` (Phase 2, Phase 3
contract), `event_dedup.py` (Phase 3, Phase 4) are each touched by two phases. code-refiner walks
phases serially, so these do not conflict; do not parallelize phases that share a file.

## Gate notes

- **Treat "0 tests collected" as failure.** Each phase's named test files are deliverables; pytest
  exits 0 ("no tests ran") when given a path that does not exist yet, so the orchestrator MUST treat
  a 0-collected result as a FAIL (not a vacuous pass) until that phase's executor has created the
  test file. (The exception is `test_dedup_traps_behavioral`, which intentionally skips all cases
  until the owner labels them — its sibling `test_dedup_traps_schema` always runs and guards the
  fixture.)
- All gate commands use `.venv/bin/pytest` and `.venv/bin/ruff` (both verified present:
  ruff 0.15.14). Do not use a bare `pytest`/`ruff` (not on PATH).

## Implementation order & parallelism

- **Phase 0 → Phase 1 → Phase 2 → Phase 3 → Phase 4** (serial; Phase 0 and 1 are logically
  independent but share `config.yaml`).
- Coverage never drops: Phase 0 fixes the detection root cause before the dedup suppressor (Phases
  3–4) exists, so the system is never both able-to-suppress and mis-scoring geography.

## Owner follow-ups (outside the code-refiner loop)

1. Label `tests/fixtures/dedup_traps.yaml` (merge/separate + urgency) — owner is sole labeler; this
   activates `test_dedup_traps_behavioral` as a real gate.
2. Mine the production DB (read-only) for real fragmentation clusters and add them to the trap
   fixture (needs server access the loop lacks).
3. Add 2–4 GB swap on the VPS before enabling local embeddings, then pick/pin the model and deploy.
4. Run `./run.sh --eval` after Phase 0 and judge the human-set report; decide whether to relax the
   `overall_pass_rate == 1.0` exit-code threshold for a live-LLM gate.
5. Consider the deferred ingestion change (keyword gate→hint + fast-lane promotion, DRAFT §4.3) and
   the deferred reliability work (Watchdog/heartbeat, Q1/Q2 channels) as future specs.
