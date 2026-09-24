# Full-Text Second Read — Eval Variants A/B/C — Implementation Specification

> **Executor context.** This spec is consumed by a fresh agent with no prior repo knowledge, no
> conversation history, and possibly no MCP/doc tools. Everything needed to implement correctly
> is in this file. Requirements state WHAT and binding constraints; where a requirement mandates
> a specific technology or pattern, the rationale says why — do not "optimize" away from it.
>
> **Loop integrity.** The acceptance tests and gate criteria in this spec are the contract, not a
> suggestion: the implementing agent MUST NOT weaken, special-case, hardcode around, or delete a
> test or gate to make it pass. If a test appears wrong or conflicts with a requirement, that
> conflict MUST be surfaced as a finding/escalation — never resolved by gaming the check.

## Overview

Project Sentinel is a life-safety alert bot: an LLM (`gpt-5.6-luna`) scores news articles 1–10
from their headline and a ≤500-character summary; 9–10 places a phone call, 5–8 sends an
SMS/push, 1–4 is logged only. The operator wants to know whether letting the model read the
**full article text** a second time improves alerts. When this spec is finished, the offline eval
suite can run every frozen article through a first read and a full-text second read in one paid
run, compose variant A (today), variant B's correction statistics and several variant-C
definitions from that single run, score each C variant against the operator's labels with the
existing pre-registered decision rule (against the A variant of the same model), and price B and
every C variant from the real production score mix. Production code is not changed; a production
spec follows only if a variant passes (design notes in `specs/fulltext-second-read/PRODUCTION_NOTES.md`,
which the executor does not need to read).

**Variant glossary (used throughout):**

| Variant | When the model reads the full article | What the eval measures |
|---|---|---|
| **A** | Never (today's behaviour) | Reference |
| **B** | First read scored in the call tier (≥ 9); in production it would run after the call and could only send a neutral correction message | How often the full read would lower a call-tier score, and whether that correction would be right or misleading, plus projected cost |
| **C** | First read below the call tier and matching a trigger (e.g. 5–8) | Quality under the pre-registered rule when the second read replaces the first for triggered articles, plus projected cost |

## Goals

- The operator can see, on their own labels, whether full-text second reads improve alert
  decisions, with the same strict paired decision rule already used for model selection.
- The operator can compare several definitions of a "hard" article (variant C) from one paid run.
- Cost projections for B and C reflect the production score mix, not the stratified eval pool.

## Non-Goals

- **No production change.** No edits to `sentinel/scheduler.py`, `sentinel/classification/classifier.py`,
  `sentinel/processing/fulltext.py`, `config/config.yaml` or any alerting code. The production
  second read is a later, separate spec.
- **No change to the classification system prompt, response schema, or `policy.messages()`.**
  The frozen v2 prompt (hash `aa4d4ca8…`) stays byte-identical so every existing eval run stays
  comparable.
- **No live (paid) eval run and no production snapshot refresh inside the implementation loop.**
  All gates are offline. The operator runs the live commands documented in `docs/how-to/model-eval.md`.
- **No "headline-only" trigger for C.** Data (2026-09-24, frozen eval items): of 35 production
  items whose summary was only the headline because the page fetch failed, full text was
  obtainable for 1. The trigger would almost never produce a second read.
- **No per-variant replay of incident chains.** Chain items get a second read, but memory and
  grouping in the replay use the first read only (see 1.8, 1.19).
- **No edit of `CLAUDE.md`.**
- **No changes to `data/eval/suite/items.json`, `queue.json`, or `labels.jsonl`.** Labels belong
  to the operator only; code MUST NOT generate, pre-fill or modify them.

## Technical Context

- **Stack:** Python 3.12, `.venv/` virtualenv, pytest (+ pytest-asyncio), ruff (lint + format),
  Pydantic v2 config models, OpenRouter for eval runs (`sentinel/eval/openrouter_client.py`,
  unchanged).
- **Baseline observed 2026-09-24 on branch `eval/model-suite`:** `.venv/bin/pytest tests/ -q` →
  642 passed. `ruff check .` on the whole tree reports 78 pre-existing errors (23 of them in the
  tracked `test_e2e_live.py`) in files this spec does not own; every file this spec owns currently passes `ruff check` and `ruff format --check`.
  Gates are therefore scoped to owned files.
- **Alert tiers** come from `config.alerts.urgency_levels`, a `dict[str, UrgencyLevel]` whose values
  have `min_score` and `action`: one with `action: phone_call` (`min_score: 9`), and `action: sms`
  values with `min_score: 7` and `min_score: 5`.
- **Eval suite** (`sentinel/eval/suite/`):
  - `runner.py` writes one JSONL row per (model spec, repeat, item) to
    `data/eval/suite/runs/<name>/calls.jsonl` plus `manifest.json`. A model spec is
    `vendor/model[@provider][+reasoning]`. Rows are written by an inner `write()` that sets a
    `stopped` flag on `budget_stopped` or a `FATAL_HTTP` status. `request_cost(completion)`
    returns the billed cost, or the reservation for a timeout/transport error, else 0.
    `load_done` supersedes rows with outages on resume. `--concurrency` defaults to 6.
  - `score.py` scores a run dir against `labels.jsonl`/`queue.json`/`items.json` and writes
    `score.json`. It distinguishes `expected` (labelled items in the run's pool) from all pool
    items; builds per-model reports from the per-item majority of repeats; and computes
    `paired_vs_baseline = {m: paired(reports[baseline], reports[m], items)}` against a single
    baseline, then removes the per-item `_outcomes` from the reports. `score.json` also contains
    the run `manifest`.
  - `report.py` renders `report.html` and `price.json` from `score.json` and a production volume
    snapshot. `decide(model, baseline, score, prices)` reads `score["paired_vs_baseline"][model]`
    and applies the pre-registered margins; `build_html` decides every non-baseline model against
    the one baseline, labels a model as
    `m.split("/")[-1].partition("@")[0].removesuffix("+reasoning")` plus `REASONING_NOTE` when
    `m.endswith("+reasoning")`, renders sequence cells with `s.get('same_ok', 0)`-style lookups,
    and renders the price table sorted by `total` with `vs_baseline` formatted `:.2f`.
    `model_prices` maps a spec to its catalogue id with `spec.removesuffix("+reasoning").partition("@")[0]`.
  - `price.py`: `snapshot_production(path)` runs SQL over SSH (read-only) and writes
    `{"daily": [...], "baseline_usage": {...}}` to `data/eval/suite/volume.json`;
    `volume_scenarios(daily)` returns `average_day`, `busy_day_p90`, `busiest_day`, `days`;
    `price_table(...)` projects per-article and monthly cost; `DAYS_PER_MONTH = 30.4`.
  - `make_config(path)` (the eval's config loader, which tolerates missing environment secrets but
    needs a full config file) lives in `sentinel.eval.compare_models`.
- **Frozen items** (`data/eval/suite/items.json`): keys `id, origin, article_id, cluster_id,
  chain_id, chain_pos, article, input, prod, pool, full_text, full_text_status`;
  `full_text_status == "ok"` means `full_text` holds the extracted text (≤ 8000 chars). 223 of 277
  production items have full text; the 40 synthetic items have `full_text_status == "synthetic"`.
  The pool is **stratified**: in the dev pool 23% of items were production 9–10 and 59% were 5–8,
  versus 2.0% and 12.1% in production — so rates measured on the pool must never be used as
  production rates.
- Row fields written by the runner for an answered item (normative, existing):
  `model, model_id, reasoning, repeat, item_id, chain_id, request_sha256, usage, cost_usd,
  reserved_usd, latency_seconds, provider, request_id, finish_reason, error_kind, http_status,
  attempts, retry_cost_usd, error, raw_content, budget_stopped, finished_at` plus outcome fields
  `urgency, countries, is_military_event, event_type, summary_pl, summary_polish, memory, facts`;
  chain rows also carry `candidate_ids, event_id, notification, channels, accepted_memory`.
  `usage` (possibly `None` when no response arrived) holds `prompt_tokens, cached_tokens,
  completion_tokens, total_tokens, reasoning_tokens`.
- External dependencies: none new and no new external call shapes (the OpenRouter client and the
  SSH snapshot path are reused unchanged), so this spec has no Verified Usage Reference appendix.

### Projected production cost (informational; the report computes its own)

Measured 2026-09-24 on production (read-only): ~520 classifications/day; ~$0.00095 each by the
ledger; a second read ≈ $0.0012; full text available for ~80% of articles. Extra per month:
B ≤ $0.30 (≤ 2.0% of first reads score ≥ 9); C `band_5_8` ≈ $1.85 (12.1%); C `band_7_8` ≈ $0.05
(0.3%); C `facts_unclear` ≈ $6.00 (39.5%). The app's monthly cap is $30.

## Architecture Decisions

- **Full text replaces the summary; the system prompt is unchanged.** The second read sends
  `messages(replace(article, summary=full_text), candidates, policy)`. _(Binds: 1.1, 1.2)_
  **Rationale:** the system prompt says to use "the CURRENT article title and summary" and
  demands verbatim evidence excerpts from them; putting the full text in the `summary` slot keeps
  that contract and keeps the prompt hash identical.
- **One eval run, variants composed offline.** _(Binds: 1.5, 1.14–1.22)_ **Rationale:** paired
  comparisons are exact (identical first reads), any C definition can be tried without paying
  again, and the Luna cost of a full dev-pool run is ≈ $0.35.
- **Variants are pseudo-models.** A composed row's `model` is `"<spec>#<VARIANT>"`, so the
  existing `score.py`/`report.py` machinery scores variants without a parallel code path; each C
  variant is decided against the `#A` of its own source spec. _(Binds: 1.16, 1.17, 1.23, 1.26,
  1.30, 1.32, 1.37, 1.40)_
- **Variant cost comes from the production score mix, not from the eval pool.** Extra cost =
  `mean second-read cost × production trigger share × full-text availability`, added to A's
  projected cost. The eval-billed second-read cost is used as an approximation. _(Binds: 1.33,
  1.35, 1.36, 1.38)_
- **Trigger definitions live in a production module** (`sentinel/classification/second_read.py`)
  so the future production spec reuses exactly the rule the eval tested. _(Binds: 1.3, 1.17, 1.35)_

## Invariants

- **AD-2 — Variant naming.** **Binds:** 1.16, 1.17, 1.22, 1.23, 1.26, 1.32, 1.37, 1.40 · **Rule:**
  variant rows use `model = "<source spec>#<NAME>"` where `NAME` is `A` or a rule name matching
  `^C-[A-Za-z0-9-]+$`; a source spec containing `#` is rejected (1.22). The source spec of a
  variant model is its `model` with the `#...` suffix removed.

## Assumptions

- [assumed] The eval's call threshold for B statistics is score.py's existing `action()` (9),
  which equals the production config.
- [assumed] Author choices: the variant label format `· NAME` (1.32); B and variant counts are
  per row (every repeat counts), labelled as such in the report (1.24, 1.34); the eval-billed
  second-read cost is used as the cost basis (1.33, 1.35); resume re-pays the first read (1.10);
  the rule-name pattern (1.22); the `#A` tie-break in baseline resolution (1.23).
- [assumed] Cost approximations: full-text availability (`p_full_text_*`) is measured on the eval
  pool, which includes synthetic items that never have full text, so it biases the projected cost
  downward; the production score mix (`urgency_mix`) comes from Luna classifications and is applied
  to every source spec's variants.

## Phase 1 — Eval: full-text second read and variant composition

### Deliverables
- `sentinel/classification/policy.py` — (modify existing) Current state: builds the frozen v2
  system prompt and messages. Change: add `second_read_messages(...)` (1.1). Preserve:
  `system_prompt()`, `messages()`, `prompt_hash()` output byte-identical.
- `sentinel/classification/second_read.py` — (create) Trigger vocabulary and pure trigger
  functions (1.3).
- `sentinel/eval/suite/runner.py` — (modify existing) Current state: first read only. Change: add
  `--second-read` (1.5–1.13). Preserve: identical rows and behaviour when the flag is absent (the
  manifest only gains the `"second_read": false` key required by 1.11); resume semantics; budget
  accounting.
- `sentinel/eval/suite/variants.py` — (create) Offline composition of variant rows (1.14–1.22).
- `sentinel/eval/suite/score.py` — (modify existing) Change: baseline resolution for `#variant`
  specs (1.23), B-correction statistics (1.24), variant statistics (1.34), second-read cost basis
  (1.38), pairings against each spec's own `#A` (1.40). Preserve: all existing metrics and outputs
  for runs without `second`/`variant` data.
- `sentinel/eval/suite/price.py` — (modify existing) Change: the production snapshot also records
  the score mix (1.36). Preserve: existing snapshot keys and `price_table` behaviour.
- `sentinel/eval/suite/report.py` — (modify existing) Change: price lookup strips `#variant`
  (1.26), monthly cap from config (1.27), B section (1.28, 1.33), empty-sequence rendering (1.29),
  variant labels (1.32), variant statistics and caveat (1.34), production-mix variant cost (1.35),
  per-spec variant decisions (1.37), `n/d` price rendering (1.39). Preserve: existing sections and
  `decide()` margins.
- `docs/how-to/model-eval.md` — (modify existing) Change: add a variants section (1.31).
- `tests/test_second_read_triggers.py` — (create) Tests for 1.1–1.3.
- `tests/test_eval_suite_runner.py` — (modify existing) Add tests for 1.5–1.13; existing tests unchanged.
- `tests/test_eval_suite_variants.py` — (create) Tests for 1.14–1.22.
- `tests/test_eval_suite_score.py` — (modify existing) Add tests for 1.23–1.25, 1.34, 1.38, 1.40.
- `tests/test_eval_suite_price.py` — (modify existing) Add tests for 1.36.
- `tests/test_eval_suite_report.py` — (modify existing) Add tests for 1.26–1.35, 1.37, 1.39.

### Interfaces
- Provides (used by `variants`/`report` now and by the future production spec):
  - `sentinel.classification.policy.second_read_messages(article: Article, full_text: str, candidates: list[dict], policy: dict) -> list[dict]`
  - `sentinel.classification.second_read.TRIGGERS: tuple[str, ...] == ("band_5_8", "band_7_8", "facts_unclear")`
  - `sentinel.classification.second_read.TriggerLevels` — frozen dataclass `(alert: int, high: int, call: int)`
  - `sentinel.classification.second_read.trigger_levels(config: SentinelConfig) -> TriggerLevels`
  - `sentinel.classification.second_read.c_trigger_hits(urgency: int, facts: dict, triggers: Iterable[str], levels: TriggerLevels) -> list[str]`
  - `sentinel.eval.suite.score.request_cost(completion: dict) -> float` (moved from `runner.py`, 1.38)
  - `sentinel.eval.suite.report.variant_prices(score: dict, prices: dict, snapshot: dict) -> dict` (1.41)

### Requirements

**1.1** — `policy.second_read_messages(article, full_text, candidates, policy)` MUST return
exactly `messages(dataclasses.replace(article, summary=full_text), candidates, policy)`; the
input `article` object MUST NOT be mutated.

**1.2** — `policy.system_prompt`, `policy.messages` and `policy.prompt_hash` MUST produce
byte-identical output to before this change; for the policy in `config/config.yaml`,
`prompt_hash(policy)` MUST equal
`aa4d4ca8853bc1cc0852241bec01faeec065cbe163c1448c7828ba56a33f5115`.

**1.3** — `second_read.c_trigger_hits(urgency, facts, triggers, levels)` MUST return, in the
order given in `triggers`, the names that hit under these definitions, and `[]` whenever
`urgency >= levels.call`:
- `band_5_8`: `levels.alert <= urgency < levels.call`;
- `band_7_8`: `levels.high <= urgency < levels.call`;
- `facts_unclear`: `facts.get("status") == "unclear"` or `facts.get("protection") == "unclear"`.

**1.3a** — IF `triggers` contains a name not in `TRIGGERS` THEN `c_trigger_hits` MUST raise
`ValueError` whose message names the unknown trigger and lists the valid ones; this check comes
first and applies for every urgency, including `urgency >= levels.call`.

**1.3b** — `second_read.trigger_levels(config)` MUST derive, over the values of the dict
`config.alerts.urgency_levels`, `call` as the lowest `min_score` with `action == "phone_call"`
(9 if none), `alert` as the lowest `min_score` with `action == "sms"`, and `high` as the highest
`min_score` with `action == "sms"`; IF no value has `action == "sms"` THEN `alert` and `high` MUST
both equal `call` (no band can then hit). For `make_config("config/config.yaml")` (loader imported
from `sentinel.eval.compare_models`) it MUST return `TriggerLevels(alert=5, high=7, call=9)`.

**1.4** — [REMOVED — `b_triggered` had no consumer; the eval uses `score.action()` (1.24).]

**1.5** — WHERE the runner is started with `--second-read`, for every (model spec, repeat, item)
whose first read produced a valid answer (`urgency` set) AND whose item has
`full_text_status == "ok"` and a non-empty `full_text`, the runner MUST send one additional
request through the same client, model and `complete_with_retry`, with messages
`second_read_messages(article, item["full_text"], candidates, policy)` where `candidates` is the
exact list used for that item's first read (`[]` for single items).

**1.5a** — The row MUST then carry `row["second"]`, a dict with keys: `request_sha256, usage,
cost_usd, reserved_usd, latency_seconds, error_kind, http_status, attempts, retry_cost_usd,
error, raw_content, budget_stopped` (chain items also `candidate_ids`) and, when the answer is
valid, `urgency, countries, is_military_event, event_type, summary_pl, summary_polish, memory,
facts` (same meanings and validation as the first read, using `validate_output` and
`outcome_fields`).

**1.6** — IF the item has no usable full text THEN `row["second"]` MUST be
`{"skipped": "no_full_text"}` and no second request is sent. IF the first read has no valid answer
THEN `row["second"]` MUST be `{"skipped": "first_read_failed"}` and no second request is sent;
this takes precedence over `no_full_text`. IF the first completion carries `budget_stopped` or the
run is already stopped THEN no second request MUST be sent and `row["second"]` MUST be
`{"skipped": "run_stopped"}`.

**1.7** — IF the second answer fails validation THEN `row["second"]["error_kind"]` MUST be
`"invalid_output"`, `row["second"]` MUST have no `urgency` key, and the first-read fields of the
row MUST be unchanged.

**1.8** — For chain items the second read MUST use the same `candidates` as that item's first read,
and `row["second"]["candidate_ids"]` MUST equal `row["candidate_ids"]`; incident-memory
validation, grouping and alert replay MUST use only the first read.

**1.9** — The run's spending accounting MUST include second reads: `spent_so_far(rows)` MUST add
`request_cost(row["second"]) + row["second"].get("retry_cost_usd", 0)` for every row whose
`second` has a request, and all second requests MUST go through the run's shared `BudgetLedger`.

**1.9a** — The runner's `write()` MUST stop the run (same `stopped` flag and `stop_reason` values
as today) WHEN `row["second"].get("budget_stopped")` is true or `row["second"].get("http_status")`
is in `FATAL_HTTP`, exactly as it does for the first read's fields.

**1.10** — [assumed: resume re-pays the first read] IF a row's second read ended in an outage
(`score.is_outage(row["second"])` is true) or is `{"skipped": "run_stopped"}` THEN `load_done` MUST treat that row as retryable exactly like a first-read outage (superseded and
redone on resume; for a chain, the whole chain replay is redone). This deliberately pays for and
re-samples the first read again, so both reads of a row always come from the same session;
`docs/how-to/model-eval.md` MUST state this.

**1.11** — The manifest MUST record `"second_read": <bool>`; on resume, a manifest without the key
MUST be treated as `false`, and IF the stored value differs from the current flag THEN the runner
MUST exit with `SystemExit("Resume refused: second_read changed since this run started")`.

**1.12** — WHERE `--second-read` is absent, rows MUST NOT contain a `second` key and every row
key set MUST equal the key set produced before this change (all pre-existing runner tests pass
unmodified).

**1.13** — WHERE `--second-read` is given, the planning printout MUST add the line
`Planned second reads: up to <N> per model` where `N = repeats × (items with full_text_status "ok" and non-empty full_text)`.

**1.14** — `python -m sentinel.eval.suite.variants RUN_DIR [--out DIR] [--config PATH] [--rule NAME=TRIGGER[+TRIGGER...]]...`
MUST read `RUN_DIR/calls.jsonl` (ignoring rows with `superseded: true`) and `RUN_DIR/manifest.json`
and write `DIR/calls.jsonl` and `DIR/manifest.json`, `DIR` defaulting to `<RUN_DIR>-variants`
(sibling folder). `--config` defaults to `config/config.yaml` and is read with
`sentinel.eval.compare_models.make_config` only to compute `trigger_levels`. Without `--rule` the
rules MUST be `C-5-8=band_5_8`, `C-7-8=band_7_8`, `C-unclear=facts_unclear`,
`C-5-8-unclear=band_5_8+facts_unclear`.

**1.15** — IF the source manifest does not have `"second_read": true` THEN `variants` MUST exit
with `SystemExit("Run was not made with --second-read: nothing to compose")` and write nothing.

**1.16** — For every source row, `variants` MUST emit an A row: an exact copy with `model`
replaced by `"<model>#A"` (all other fields, including `second`, kept).

**1.17** — For every source row whose first read has a valid `urgency`, and every rule, `variants`
MUST emit a C row with `model = "<model>#<NAME>"`, computing `hits = c_trigger_hits(first urgency,
first facts, rule triggers, levels)`. IF `hits` is non-empty AND `row["second"]` has an `urgency`
THEN the outcome fields (`urgency, countries, is_military_event, event_type, summary_pl,
summary_polish, memory, facts`) MUST be taken from `row["second"]`; otherwise from the first read.
The C row MUST NOT contain `second` and MUST contain `variant = {"rule": NAME, "triggers": [...],
"hits": hits, "used_second": <bool>, "second_sent": <bool>, "second_cost_usd": <float>}` where
`second_sent` is true when `row["second"]` has no `skipped` key and `second_cost_usd` is
`request_cost(second) + second.retry_cost_usd` (0 when not sent).

**1.18** — IF a C row's `hits` is non-empty AND a second request was sent (no `skipped` key) THEN:
`cost_usd` MUST be `None` when the first read's `cost_usd` is `None`, else
`request_cost(first) + request_cost(second)`; `retry_cost_usd` MUST be the sum of both;
`latency_seconds` MUST be `None` when both are `None`, else the sum with a `None` side counted as
0; and each of `usage.prompt_tokens`, `usage.cached_tokens`, `usage.completion_tokens`,
`usage.total_tokens` and `usage.reasoning_tokens` MUST be the sum of both, where a `None` usage
dict counts as `{}` and a `None` or missing token count counts as 0. Otherwise the first read's
values MUST be kept unchanged. **Rationale:** the second request is paid whenever the trigger
fires and full text exists, even if its answer is then unusable.

**1.19** — C rows for chain items MUST have `chain_id` set to `None` and MUST NOT contain
`event_id`, `notification`, `channels` or `accepted_memory`, so sequence metrics are computed only
for A rows. **Rationale:** memory state is not replayed per variant; mixing would report wrong
notification behaviour.

**1.20** — IF the first read has no valid answer THEN every C row for it MUST carry the first
read's error fields unchanged (`error_kind`, `error`, `http_status`, no `urgency`) and
`variant = {"rule": NAME, "triggers": [...], "hits": [], "used_second": false, "second_sent":
false, "second_cost_usd": 0.0}` and MUST NOT contain `second`, so C's invalid/unavailable
accounting equals A's.

**1.21** — `variants` MUST NOT modify any file in `RUN_DIR`. `DIR/manifest.json` MUST be the
source manifest with these keys added — `"variants_of": <RUN_DIR name>`, `"rules": {NAME:
[triggers]}`, `"trigger_levels": {"alert": int, "high": int, "call": int}` — and the key `"models"`
replaced by the list of emitted variant model specs. Existing files in `DIR` MUST be replaced
atomically (write to a temp file, then `os.replace`).

**1.22** — [assumed: rule-name pattern] IF a `--rule` names an unknown trigger, has a name not matching `^C-[A-Za-z0-9-]+$`, or
repeats a rule name, or IF a source row's `model` contains `#`, or IF the resolved `DIR` equals
the resolved `RUN_DIR` or `DIR` already holds a `manifest.json` without a `variants_of` key (a
source run), THEN `variants` MUST exit with a `SystemExit` naming the problem and write nothing.

**1.23** — [assumed: `#A` tie-break] `score.score_run` baseline resolution: IF `baseline` matches no model exactly THEN it
MUST compare bare ids — the model and the `baseline` argument each with a `#...` suffix, then
`+reasoning`, then `@...` stripped; IF
several match, the one ending in `#A` MUST be chosen; IF still not exactly one, the existing
behaviour (baseline not found → no comparisons) applies.

**1.24** — [assumed: call threshold 9 from `score.action()`; counts are per row] `score.score_run`
MUST add `"b_corrections": {model: stats}` for every model that has at least one row with a
`second` dict. Over that model's **labelled rows** (rows whose item is in `expected`) with
first-read `urgency >= 9`: `stats` MUST contain `first_call_rows` (count), `no_full_text`,
`second_failed` (request sent, no valid `urgency`), `corrections` (second `urgency < 9`), and, for
corrections only and mutually exclusive in this order: `misleading` (`truth.critical` true),
`justified` (not critical and `truth.possible_call` false), `ambiguous` (the rest); plus
`misleading_items` (sorted unique item ids).

**1.25** — For runs without any `second` data, `score.json` MUST contain `"b_corrections": {}`,
`"variant_stats": {}`, `"second_read_cost": {}` and `"paired_vs_own_a": {}`, and all other keys
unchanged. `report` MUST treat any of these keys missing from an older `score.json` as `{}`.

**1.26** — `report.model_prices` MUST strip a `#...` suffix first, then `+reasoning`, then `@...`,
so `"openai/gpt-5.6-luna#C-5-8"`, `"openai/gpt-5.6-luna@openai#C-5-8"` and
`"z-ai/glm-5.3-flash@Together+reasoning#A"` price as `openai/gpt-5.6-luna`,
`openai/gpt-5.6-luna` and `z-ai/glm-5.3-flash`.

**1.27** — `report.main` MUST take a new `--config` argument (default `config/config.yaml`), and
`--monthly-cap` MUST default to `None`.
WHEN `--monthly-cap` is not given, it MUST read `classification.budget.monthly_usd` from that file
with `yaml.safe_load`, and IF the file or key is missing THEN exit with
`SystemExit("Monthly cap not found in <path>; pass --monthly-cap")`. WHEN `--monthly-cap` is
given, the config file MUST NOT be read. `report` MUST NOT read the config for any other purpose.

**1.28** — WHEN `score["b_corrections"]` is non-empty, `report.html` MUST contain a section
headed `Wariant B — korekty po telefonie` listing, per model, every count from 1.24 (labelled
`wiersze, każde powtórzenie osobno`), the `misleading_items`, the cost projection from 1.33, and
the sentence `Wariant B nigdy nie zmienia ani nie opóźnia samego telefonu.`

**1.29** — `report.build_html` MUST show `n/d` in the chain cells of a model whose `sequences`
dict is empty (instead of `0/0`).

**1.30** — For a variants run, the report's decision table MUST contain one `decide()` entry per
`#C-...` model, each against the `#A` model of the same source spec (1.37, 1.40), using the
unchanged margins in `report.py` (`RECALL_MARGIN`, `FALSE_CALL_MARGIN`, `TIER_MARGIN`,
`PESSIMISTIC_MARGIN`, `MAX_INVALID_RATE`).

**1.31** — `docs/how-to/model-eval.md` MUST gain a section `## 5. Full-text variants (A/B/C)`
with: the runner command with `--second-read`, the `variants` command, refreshing the production
snapshot (`price.snapshot_production`) so it contains the score mix, scoring the derived folder,
the variant glossary, that C variants face the same pre-registered rule against their own `#A`
with the cap from config and costs from the production score mix, that B is reported as
correction counts plus its projected cost, the resume behaviour of 1.10, the chain limitation
(1.19), the production caveat (1.34), and the headline-only exclusion with its data (1 of 35);
every existing mention of a "$10" cap in that file MUST be replaced by "the monthly cap from
`config/config.yaml` (`classification.budget.monthly_usd`)".

**1.32** — [assumed: label format] `report.build_html` display labels MUST keep the variant: for a
spec with a `#NAME` suffix the label MUST be: base label, then ` · NAME`, then `REASONING_NOTE`
WHEN the spec without its `#...` suffix ends with `+reasoning` (e.g. `gpt-5.6-luna · C-5-8`,
`glm-5.3-flash · C-5-8` + `REASONING_NOTE`). The base label is the `--labels` entry for the spec
without the suffix if present, else today's derived label without `REASONING_NOTE`. A `--labels`
entry for the full variant spec replaces the whole label.

**1.33** — The B section's cost projection MUST be computed by `variant_prices` (1.41) per model
in `b_corrections`, using `score["second_read_cost"][model.removesuffix("#A")]` (1.38), as `mean_second_cost × p_call × p_full_text_call ×
volume × 30.4`, where `p_call` is the production share of first reads with urgency ≥ 9 from the
snapshot's `urgency_mix` (1.36) and `p_full_text_call = first_call_sent / first_call_rows`; shown
for the `average_day` and `busy_day_p90` volumes of `price.volume_scenarios`, labelled
`górne oszacowanie (każdy wynik 9–10, nie tylko telefony; koszt drugiego czytania z ewaluacji)`,
next to the monthly cap. IF the snapshot has no `urgency_mix` (missing or empty list) THEN the cost cells MUST show
`n/d — odśwież snapshot produkcji`; IF `first_call_rows` is 0 THEN they MUST show `n/d`; IF
`mean_second_cost` is `None` (no second read was sent) THEN the projected cost MUST be `0` and the
cell MUST add `brak drugich czytań w przebiegu`.

**1.34** — [assumed: counts are per row] `score_run` MUST add `"variant_stats": {model: {"rows",
"triggered", "used_second", "all_triggered", "all_triggered_sent"}}` for every model whose rows
carry `variant`: `rows`, `triggered` (non-empty `hits`) and `used_second` counted over its
**labelled rows** (item in `expected`); `all_triggered` and `all_triggered_sent` (triggered rows
with `variant.second_sent`) counted over **all** its rows whose item is in the run's pool. WHEN
`variant_stats` is non-empty, `report.html` MUST show, per C variant, the text
`wyzwolone {triggered/rows:.0%} · drugie czytanie użyte {used_second/rows:.0%}` (e.g.
`wyzwolone 50% · drugie czytanie użyte 25%`) labelled `w puli ewaluacyjnej (warstwowanej)`, or
`wyzwolone n/d · drugie czytanie użyte n/d` WHEN `rows` is 0 (no labels yet), and the sentence `Na produkcji drugie czytania mają limit czasu na cykl i na artykuł, bez ponowień, więc
przy wielu artykułach naraz część z nich się nie odbędzie. Ewaluacja zakłada, że odbywa się każde.`

**1.35** — For every `#C-...` model, `variant_prices` (1.41) MUST replace its `price_table` entry by: `total =
A_total + extra`, where `A_total` is the per-article `total` of the same source spec's `#A` model
and `extra = mean_second_cost × p_rule × p_full_text_rule`, with `mean_second_cost` from
`score["second_read_cost"][spec]` (treated as 0 when `None`), `p_full_text_rule = all_triggered_sent / all_triggered` from
`variant_stats` (0 when `all_triggered` is 0), and `p_rule` the production share of first reads
for which `c_trigger_hits(urgency, facts_proxy, rule triggers, levels)` is non-empty, computed from
`urgency_mix` with `facts_proxy = {"status": "unclear"}` when the mix row's `unclear` is true, else
`{}`, the rule's triggers from `score["manifest"]["rules"]` and `levels = TriggerLevels(**score["manifest"]["trigger_levels"])`;
then `monthly`, `per_1000_articles`, `within_cap_busy_month` and `vs_baseline` recomputed from the
new `total` exactly as `price_table` does, and every other per-article field of the entry
(`classification`, `eval_cost_per_call`, `billed_to_list_ratio`, `production_prompt_tokens`,
`production_cached_tokens`, `retry_after_invalid`, `summary_repair`) set to `None`. IF the
snapshot has no `urgency_mix` (missing or empty list), or
`score["manifest"]` lacks `rules`/`trigger_levels`, or `A_total` is unavailable, THEN the C entry
MUST have `total = None`, `monthly` values `None`, `per_1000_articles = None`, `vs_baseline = None`
and `within_cap_busy_month = False`.

**1.36** — `price.snapshot_production` MUST also query and store `"urgency_mix"`: a list of
`{"urgency": int, "unclear": bool, "n": int}` from
`SELECT urgency_score AS urgency, COALESCE(json_extract(facts,'$.status')='unclear' OR json_extract(facts,'$.protection')='unclear', 0) AS unclear, count(*) AS n FROM classifications WHERE model_used = 'gpt-5.6-luna' AND classified_at >= '2026-09-20T21:30' GROUP BY 1, 2`,
with `unclear` converted to a bool (`None` → `False`) and rows with the same `(urgency, unclear)`
merged by summing `n`; existing keys MUST be unchanged. IF the mix query fails (non-zero exit or
invalid JSON) THEN the snapshot MUST still be written with `daily` and `baseline_usage` and without
`urgency_mix`, and a line `urgency_mix unavailable: <reason>` MUST be printed.

**1.37** — `report.build_html` MUST decide each `<spec>#C-...` model against `<spec>#A` (same
source spec) when that model exists, using `score["paired_vs_own_a"][model]` for the paired
quality checks and `<spec>#A`'s report for the baseline-side coverage and cost checks; all other
non-baseline models are decided against the run's baseline with `score["paired_vs_baseline"]` as
today. The missed-critical review list of a `<spec>#C-...` model MUST likewise come from
`score["paired_vs_own_a"][model]`. The run baseline's own `#A` model MUST NOT get a decision row.

**1.38** — `score_run` MUST add `"second_read_cost": {spec: {"mean_second_cost", "sent",
"first_call_rows", "first_call_sent"}}` for every model whose rows carry a `second` dict (a `#A`
model of a variants run, or a model of a raw `--second-read` run), keyed by the model with a
trailing `#A` removed, computed over **all** of that model's rows whose item is in the run's pool
and whose first read has a valid `urgency`: `sent` = rows whose `second` has no `skipped` key,
`mean_second_cost` = mean of `request_cost(second) + second.retry_cost_usd` over those rows (None
when `sent` is 0), `first_call_rows` = rows with first-read `urgency >= 9`, `first_call_sent` =
those among them with a sent second request. `request_cost` MUST move from `runner.py` to
`score.py` (runner imports it from there; `runner.request_cost` stays importable) so that
`score.py` does not import `runner.py`, which already imports `score.py`.

**1.39** — `report.build_html` MUST render a price-table entry whose `total` is `None` without
raising: such entries sort after all others, and every cost cell of the entry (per article,
monthly, `vs_baseline`, cap) MUST show `n/d — odśwież snapshot produkcji`.

**1.40** — `score_run` MUST add `"paired_vs_own_a": {model: paired(reports["<spec>#A"],
reports[model], items)}` for every `<spec>#C-...` model whose `<spec>#A` model is in the run,
computed before `_outcomes` are removed.

**1.41** — `report.variant_prices(score, prices, snapshot)` MUST return a new prices dict: a copy
of `prices` with every `#C-...` entry replaced per 1.35 and a new key `"b_costs": {model:
{"average_day", "busy_day_p90", "note"}}` per 1.33. `report.main` MUST call it right after
`price_table` and before `build_html`, write its result to `price.json`, and pass it to
`build_html`; `build_html` and `decide()` MUST use only that result, so the cap and
cheaper-or-proven-better checks for C variants see the production-mix cost.

### Acceptance Tests
1. `test_second_read_messages_puts_full_text_in_summary_slot` — (unit) [1.1] article with
   summary "Krótko", full_text "Pełny tekst artykułu" → user JSON `article.summary == "Pełny tekst artykułu"`, title unchanged, system message equals `messages(article, [], policy)[0]`; original `article.summary` still "Krótko".
2. `test_prompt_hash_unchanged` — (unit) [1.2] policy from `config/config.yaml` (via
   `yaml.safe_load`) → `prompt_hash(policy)` equals the 64-hex value in 1.2.
3. `test_c_trigger_bands_follow_levels` — (unit) [1.3] levels (5,7,9): urgency 4 → `[]` for
   `band_5_8`; 5 → `["band_5_8"]`; 7 with `["band_5_8","band_7_8"]` → both in that order; 9 → `[]`
   even with facts status "unclear"; property: for every urgency 1–10 and every trigger subset,
   the result is `[]` whenever urgency ≥ 9.
4. `test_facts_unclear_trigger` — (unit) [1.3] urgency 2, facts `{"status":"unclear","protection":"none"}` → `["facts_unclear"]`; facts `{"status":"active","protection":"unclear"}` → hit; `{"status":"active","protection":"none"}` → `[]`; `{}` → `[]`.
5. `test_unknown_trigger_rejected` — (unit) [1.3a] `["headline_only"]` → `ValueError` whose message contains `headline_only` and `band_5_8`; the same with urgency 9 → `ValueError` too.
6. `test_trigger_levels_from_config` — (unit) [1.3b] `make_config("config/config.yaml")` →
   `TriggerLevels(5, 7, 9)`; the same config with the phone_call level's `min_score` set to 8 →
   `call == 8`; with every sms level removed → `alert == high == call`.
7. `test_second_read_sent_with_full_text_and_same_candidates` — (integration) [1.5, 1.5a, 1.8]
   FakeClient queue (first valid urgency 9, second valid urgency 4); single item with full_text →
   2 requests; second request's user JSON `article.summary == item["full_text"]`; `row["second"]["urgency"] == 4`, `row["urgency"] == 9`; `row["second"]` has every 1.5a key. Chain of 2 items → each second request's `remembered_incidents` equals its first request's; `row["second"]["candidate_ids"] == row["candidate_ids"]`; with first urgency 9 and second 4 on
   the first chain item, that row's `notification == "initial"` and its `channels` include
   `phone_call` (the replay used the first read).
8. `test_second_read_skipped_without_full_text_or_first_answer` — (unit) [1.6] item with
   `full_text_status "http_403"` → 1 request, `second == {"skipped": "no_full_text"}`; first read
   invalid → 1 request, `second == {"skipped": "first_read_failed"}`; first read invalid on an item
   without full text → `first_read_failed`; first completion with `budget_stopped: True` → 1
   request, `second == {"skipped": "run_stopped"}`.
9. `test_invalid_second_answer_keeps_first` — (unit) [1.7] second payload with urgency 11 →
   `second["error_kind"] == "invalid_output"`, `"urgency" not in second`, `row["urgency"]` equals first.
10. `test_spent_so_far_counts_second_reads` — (unit) [1.9] rows with first cost 0.001 and second
    cost 0.002 + retry 0.0005 → `spent_so_far == 0.0035`.
11. `test_second_read_budget_stop_stops_the_run` — (integration) [1.9a] with `runner.RUNS` patched
    to `tmp_path`, `load_dotenv`, `fetch_model_catalogue` and `OpenRouterEvalClient` patched (no
    network, no real key): `--concurrency 1`, 3 single
    items with full text, FakeClient whose first item's second completion carries
    `budget_stopped: True` → exactly 2 requests sent in total, and the manifest session
    `stop_reason == "budget"`.
12. `test_second_read_outage_is_redone_on_resume` — (unit) [1.10] calls.jsonl with one single row
    whose `second.error_kind == "timeout"` and one with `second == {"skipped": "run_stopped"}` →
    `load_done` marks both superseded and excludes their keys from `done`; a chain whose second item
    has a second-read outage → every row of that chain replay superseded.
13. `test_resume_refused_when_second_read_flag_changes` — (integration) [1.11] with the same
    patches as test 11: manifest written without `second_read` key, resume with
    `--second-read --live` → `SystemExit` with message `Resume refused: second_read changed since
    this run started`; manifest with `"second_read": true`, resume without the flag → the same exit.
14. `test_rows_unchanged_without_flag` — (unit) [1.2, 1.12] `classify_single` without second read →
    row key set equals the explicit pre-change key list from Technical Context (single item), no
    `second` key; `messages(article, [], policy)[1]` user JSON has exactly the keys
    `evaluation_time`, `article`, `remembered_incidents` and `article` has exactly `title, summary,
    source_name, source_type, language, published_at`.
15. `test_planning_prints_second_read_count` — (unit) [1.13] dry (non-live) run over a 3-item fixture with 2 full texts, `--repeats 2 --second-read` → stdout contains `Planned second reads: up to 4 per model`.
16. `test_variants_requires_second_read_run` — (unit) [1.15] manifest without `second_read` →
    `SystemExit` with the 1.15 message; output dir not created.
17. `test_variants_a_rows_are_copies` — (unit) [1.16] source row → A row equal except `model` ends `#A`; `second` kept.
18. `test_variants_c_uses_second_only_when_triggered` — (unit) [1.17] rule `C-5-8=band_5_8`:
    first 6 + second 9 → C urgency 9, `used_second True`, `second_sent True`; first 3 + second 9 →
    C urgency 3, `used_second False`; first 6 + `second` invalid → urgency 6, `used_second False`,
    `second_sent True`; no `second` key in C rows.
19. `test_variants_c_cost_adds_second_only_when_triggered` — (unit) [1.17, 1.18] first cost 0.001 /
    prompt 100 / latency 1.0, second cost 0.002 / prompt 300 / latency 2.0; triggered → cost 0.003,
    prompt_tokens 400, latency 3.0, `variant.second_cost_usd == 0.002`; not triggered → 0.001 / 100;
    triggered but `second == {"skipped": "no_full_text"}` → 0.001, `second_sent False`; triggered
    with second `usage: None`, `latency_seconds: None`, `error_kind "timeout"`, `reserved_usd 0.004`
    → no exception, prompt_tokens 100, latency 1.0, cost 0.005; triggered with first `cost_usd None`
    → C `cost_usd is None`.
20. `test_variants_chain_rows_drop_sequence_fields` — (unit) [1.19] chain source row → C row
    `chain_id is None`, no `event_id/notification/channels/accepted_memory`; A row keeps them.
21. `test_variants_failed_first_read_propagates` — (unit) [1.20] first `error_kind "invalid_output"` → every C row has that `error_kind`, no `urgency`, no `second` key, `variant.hits == []`, `used_second False`, `second_sent False`.
22. `test_variants_leaves_source_untouched_and_writes_manifest` — (integration) [1.14, 1.21]
    tmp run dir → source files' bytes identical after; out manifest has `variants_of`, `rules`
    with the 4 default rules, `trigger_levels == {"alert":5,"high":7,"call":9}`, `models` lists exactly 5 specs per source spec.
23. `test_variants_rejects_bad_rule` — (unit) [1.22] `--rule C-x=headline_only`, `--rule bad=band_5_8`, two `--rule C-a=band_5_8`, a source row model `x/y#z`, `--out` equal to `RUN_DIR`, and `--out` pointing at another source run's folder → `SystemExit` each; nothing written.
24. `test_score_baseline_resolves_to_variant_a` — (unit) [1.23] models `luna@openai#A`,
    `luna@openai#C-5-8`, baseline `luna` → resolved baseline is `luna@openai#A`; comparisons exist
    for `#C-5-8`; baseline `luna@openai` → the same resolution.
25. `test_score_b_corrections_counts` — (unit) [1.24] labels: item X critical, item Y
    `possible_call` false, item V critical with `possible_call` false, item Z unlabelled; A rows
    first 10 → second 4 for X, Y, V and Z, first 9 → second 9 for W (labelled) → `corrections == 3`,
    `misleading == 2`, `justified == 1`, `ambiguous == 0`, `misleading_items == ["V", "X"]`, Z not counted.
26. `test_score_without_second_has_empty_new_keys` — (unit) [1.25] ordinary run →
    `b_corrections`, `variant_stats`, `second_read_cost`, `paired_vs_own_a` all `{}`; a
    `score.json` dict with those four keys deleted → `build_html` renders without raising.
27. `test_model_prices_strips_variant_suffix` — (unit) [1.26] patched catalogue with
    `openai/gpt-5.6-luna` and `z-ai/glm-5.3-flash` → all three specs from 1.26 get prices.
28. `test_report_cap_defaults_to_config` — (unit) [1.27] tmp YAML with
    `classification.budget.monthly_usd: 30` → price table `monthly_cap_usd == 30`; missing key →
    `SystemExit` with the 1.27 message; `--monthly-cap 12` with a non-existent `--config` path → cap 12, no exit.
29. `test_report_shows_b_section` — (unit) [1.28, 1.33, 1.41] score with `b_corrections` (one
    misleading item `item-misleading-X1`) and `second_read_cost` for one spec
    (`mean_second_cost 0.001`, `first_call_rows 10`, `first_call_sent 5`), snapshot with
    `urgency_mix` giving `p_call = 0.02` and average volume 500/day, passed through
    `variant_prices` then `build_html` → html contains `Wariant B — korekty po telefonie`,
    `item-misleading-X1`, `wiersze, każde powtórzenie osobno`,
    `górne oszacowanie`, `$0.15` (0.001 × 0.02 × 0.5 × 500 × 30.4 = 0.152), and
    `Wariant B nigdy nie zmienia ani nie opóźnia samego telefonu.`; the same score with a snapshot
    without `urgency_mix` → html contains `n/d — odśwież snapshot produkcji`; with
    `mean_second_cost None` → the cell shows `$0.00` and `brak drugich czytań w przebiegu`; for a
    raw (non-variants) run where the model key has no `#A` → the B cost is still computed.
30. `test_report_renders_empty_sequences` — (unit) [1.29] a model with `sequences == {}` → html chain cells show `n/d`, not `0/0`.
31. `test_variant_decisions_use_own_a_from_real_scoring` — (integration) [1.30, 1.37, 1.40] tmp run
    dir with rows for `luna#A`, `luna#C-5-8`, `haiku#A`, `haiku#C-5-8` over 4 labelled items, where
    `haiku#C-5-8` rows are identical to `haiku#A` rows and differ from `luna#A` on 2 critical items;
    run the real `score_run` (baseline `luna`) → `paired_vs_own_a["haiku#C-5-8"]["critical_hit"]["difference"][0] == 0`;
    `build_html` with `report.decide` wrapped by `unittest.mock.patch(..., wraps=decide)` → the
    recorded `(model, baseline)` call pairs are exactly `(luna#C-5-8, luna#A)`, `(haiku#C-5-8, haiku#A)`,
    `(haiku#A, luna#A)`; the recall check of `haiku#C-5-8` passes; no decision row for `luna#A`.
32. `test_model_eval_doc_has_variants_section` — (unit) [1.10, 1.31] (in `tests/test_eval_suite_report.py`)
    read `docs/how-to/model-eval.md` → contains `## 5. Full-text variants (A/B/C)`, `--second-read`,
    `sentinel.eval.suite.variants`, `snapshot_production`, `1 of 35` and the word `re-sample` (1.10
    resume note), and no longer contains `$10`.
33. `test_report_labels_keep_variant` — (unit) [1.32] specs `openai/gpt-5.6-luna@openai#A`,
    `openai/gpt-5.6-luna@openai#C-5-8`, `z-ai/glm-5.3-flash@Together+reasoning#C-5-8` → html
    contains `gpt-5.6-luna · A`, `gpt-5.6-luna · C-5-8` and `glm-5.3-flash · C-5-8` + `REASONING_NOTE`;
    with `--labels {"openai/gpt-5.6-luna@openai": "Luna"}` → `Luna · C-5-8`.
34. `test_variant_stats_and_caveat` — (unit) [1.34] variant rows: 4 labelled items (2 with hits,
    1 used_second, both triggered rows sent) plus 1 unlabelled pool item with hits and no sent
    second → `variant_stats[model] == {"rows": 4, "triggered": 2, "used_second": 1,
    "all_triggered": 3, "all_triggered_sent": 2}`; html contains
    `wyzwolone 50% · drugie czytanie użyte 25%`, `w puli ewaluacyjnej (warstwowanej)` and the 1.34
    sentence; the same model with no labelled rows → html contains
    `wyzwolone n/d · drugie czytanie użyte n/d` and no exception.
35. `test_c_variant_cost_uses_production_mix` — (unit) [1.35] `#A` total 0.001 per article;
    manifest `rules {"C-5-8": ["band_5_8"], "C-unclear": ["facts_unclear"]}`, `trigger_levels
    {"alert":5,"high":7,"call":9}`; `urgency_mix` `[{"urgency":6,"unclear":false,"n":12},{"urgency":2,"unclear":false,"n":88}]`
    (p_rule 0.12 for C-5-8, 0 for C-unclear); `mean_second_cost 0.002`; `variant_stats` giving
    `p_full_text_rule 0.5` → C-5-8 `total == pytest.approx(0.00112, rel=1e-9)`,
    `monthly.average_day == pytest.approx(0.00112 × average × 30.4, rel=1e-9)`; C-unclear
    `total == pytest.approx(0.001, rel=1e-9)`; C-5-8 `classification is None`; snapshot without `urgency_mix`, or with
    `urgency_mix: []` → C `total is None`, `within_cap_busy_month is False`.
36. `test_snapshot_records_urgency_mix` — (unit) [1.36] (in `tests/test_eval_suite_price.py`)
    patch `subprocess.run` to return JSON per SQL (daily rows, baseline usage, mix rows with
    `unclear` 0/1) → written snapshot has `daily`, `baseline_usage` unchanged and `urgency_mix`
    with bool `unclear`; the mix SQL contains `COALESCE(` and `json_extract(facts,'$.status')='unclear'`;
    mix rows `(3, null, 1)` and `(3, 0, 2)` → one entry `{"urgency": 3, "unclear": false, "n": 3}`;
    a failing mix query (`CalledProcessError`) → snapshot written with `daily` and `baseline_usage`,
    no `urgency_mix`, and stdout contains `urgency_mix unavailable:`.
37. `test_second_read_cost_basis` — (unit) [1.38] `luna#A` rows in the pool: 3 with sent second
    reads costing 0.001, 0.002, 0.003 (one of them first urgency 10), 1 skipped `no_full_text` with
    first urgency 9, 1 row outside the pool → `second_read_cost["luna"] == {"mean_second_cost": 0.002,
    "sent": 3, "first_call_rows": 2, "first_call_sent": 1}`.
38. `test_price_table_renders_missing_cost` — (unit) [1.39] prices with one C entry whose `total`
    is `None` → `build_html` does not raise; that entry's row is last and shows
    `n/d — odśwież snapshot produkcji`.
39. `test_decide_sees_production_mix_cost` — (unit) [1.41, 1.35] (in `tests/test_eval_suite_report.py`)
    `price_table` entry for `luna#C-5-8` with a stratified-pool `total` whose busy month exceeds the
    cap, and an `urgency_mix` whose production-mix `total` fits the cap → after `variant_prices`,
    `decide("luna#C-5-8", "luna#A", score, new_prices)["checks"]` has the cap check `True`; with the
    original `prices` it is `False`; `variant_prices` returns a copy (input `prices` unchanged) with a `b_costs` key.
40. `test_request_cost_lives_in_score` — (unit) [1.38] `from sentinel.eval.suite.score import request_cost`
    and `from sentinel.eval.suite.runner import request_cost` both work and are the same function;
    importing `sentinel.eval.suite.score` alone does not import `sentinel.eval.suite.runner`
    (checked in a fresh interpreter via `subprocess` with `sys.modules`).

### Gate Criteria
- `.venv/bin/pytest tests/test_second_read_triggers.py tests/test_eval_suite_runner.py tests/test_eval_suite_variants.py tests/test_eval_suite_score.py tests/test_eval_suite_price.py tests/test_eval_suite_report.py -v` — All acceptance tests pass
- `.venv/bin/pytest tests/ -q` — No regression anywhere in the suite
- `.venv/bin/ruff check sentinel/classification/policy.py sentinel/classification/second_read.py sentinel/eval/suite/ tests/test_second_read_triggers.py tests/test_eval_suite_runner.py tests/test_eval_suite_variants.py tests/test_eval_suite_score.py tests/test_eval_suite_price.py tests/test_eval_suite_report.py` — No lint errors
- `.venv/bin/ruff format --check sentinel/classification/policy.py sentinel/classification/second_read.py sentinel/eval/suite/ tests/test_second_read_triggers.py tests/test_eval_suite_runner.py tests/test_eval_suite_variants.py tests/test_eval_suite_score.py tests/test_eval_suite_price.py tests/test_eval_suite_report.py` — Formatting clean
