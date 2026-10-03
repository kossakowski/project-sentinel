# CLI Reference — Project Sentinel

Last verified: 2026-10-03 (deployed commit 6429124)

Contents: [`sentinel.py`](#sentinelpy-via-runsh) · [Mode precedence and exit codes](#mode-precedence-and-exit-codes) · [`dashboard/cli.py`](#dashboardclipy-via-dashboardrun-dashboardsh) · [Other entry points](#other-entry-points) · [See also](#see-also)

The two main command-line entry points are:

- **`sentinel.py`** — the monitoring runtime (fetch → classify → corroborate → alert). Run via the `./run.sh` wrapper.
- **`dashboard/cli.py`** — the local read-only Article Dashboard (Flask API). Run via the `./dashboard/run-dashboard.sh` wrapper or `python -m dashboard`.

Both `run.sh` and `dashboard/run-dashboard.sh` are thin venv-bootstrap wrappers: they create/activate `.venv` if needed, then `exec` the underlying Python and **forward all arguments unchanged**. Anything below works identically whether you call the wrapper or the Python entry point directly.

Further evaluation and test scripts are listed under [Other entry points](#other-entry-points).

---

## `sentinel.py` (via `./run.sh`)

Flags are defined in `sentinel.py:build_parser()`.

The classifier flags (`--test-headline`, `--test-file`, `--eval`, and every pipeline run) make live, paid calls to the provider named in `classification.provider`. In `config/config.yaml` and the template that is OpenAI (`gpt-5.6-luna`); the Anthropic (Haiku) client is built only when `classification.provider` is not `openai`, which is the legacy rollback path. The cost is recorded in the ledger at `classification.budget.ledger_path`.

| Flag | Argument | Default | Effect |
|---|---|---|---|
| `--dry-run` | — | off | Sets `testing.dry_run = True`. Runs the full pipeline but skips alert dispatch, so events trigger no call, SMS or push. It still makes live, paid classifier calls and writes articles, classifications and events to the configured DB. In continuous mode the system-health SMS (10 consecutive failures of one fetcher, 3 consecutive pipeline failures) are not suppressed. The cycle also still checks phone calls left pending in the configured DB (`check_pending_calls`) and can retry such a call or send its fallback SMS; `--diagnostic` skips that check (see TODO.md, `--dry-run` does not skip the pending-call check). |
| `--test-headline` | `TEXT` | — | Feed a single headline through the classifier and print the `ClassificationResult` (military?, type, urgency, countries, aggressor, confidence, summary, token counts). Makes a live, paid call to the configured classifier provider. Then exits. |
| `--test-file` | `FILE` | — | Load a YAML mapping with a `headlines:` list and classify each entry under one event loop. Then exits. Each entry is a plain string or a map with `text:` (or `headline:`) and an optional `expected:` map of `ClassificationResult` fields; mismatches are printed. Makes live, paid classifier calls. The eval-set fixtures (`tests/fixtures/eval_set*.yaml`) are top-level lists for `--eval`, not inputs for this flag; a top-level list ends in an `AttributeError` traceback (tracked in `TODO.md`). The repo ships no ready-made `--test-file` input. |
| `--config` | `PATH` | `config/config.yaml` | Path to the config file to load. See [Which config to pass](#which-config-to-pass). |
| `--once` | — | — | Run exactly one pipeline cycle, print a `CycleResult` summary, then exit (no scheduler). |
| `--log-level` | `{DEBUG,INFO,WARNING,ERROR}` | from config | Override `logging.level` for this run. |
| `--health` | — | — | Print `health.json` from the DB's directory (`/var/lib/sentinel/health.json` with `config/config.yaml`). Only the scheduled cycles of continuous mode write that file; `--once`, `--diagnostic` and the immediate first cycle of continuous mode do not. Without the file it prints "No health data found. Has the pipeline run yet?" and exits 0. |
| `--diagnostic` | — | — | Force dry-run, run one cycle, and write an HTML report of every article to `diagnostic.html` next to the DB: `data/diagnostic.html` with `config/config.example.yaml`, `/var/lib/sentinel/diagnostic.html` with `config/config.yaml`. Classification calls are still live and paid; only alerts are suppressed. Then exits. |
| `--test-alert` | `[phone_call\|sms\|push]` | `phone_call` when bare | Fire a real test alert. Forces `dry_run` off, writes a synthetic `[TEST]` article and urgency-10 / source-count-2 event (plus the alert records) into the configured DB, then calls the requested channel method directly, bypassing fetching, classification, corroboration and tier routing. `phone_call` / `sms` go via Twilio; `push` goes via Expo. Then exits 0, even when delivery fails. See the note below. |
| `--eval` | `[PATH]` | `testing.eval_set_file` when bare | Run the classifier eval harness against a labeled YAML eval set. With no path, uses `testing.eval_set_file` (code default `tests/fixtures/eval_set.yaml`). Makes live, paid classifier calls, prints a report, saves JSON under `data/eval/`, and exits `0` only if the overall pass rate is `1.0` (else `1`) — useful for CI gating. |

With **no flags**, `sentinel.py` runs in **continuous mode**: it starts the pipeline, runs one cycle immediately, then drives the dual-lane APScheduler (fast lane every 3 min, slow lane every 15 min) until interrupted.

### Which config to pass

- `config/config.yaml` (the default) is the production config. It is byte-identical to `/etc/sentinel/config.yaml` on the server, and the systemd unit passes `--config /etc/sentinel/config.yaml` explicitly (`deploy/configs/sentinel.service`).
- It uses absolute server paths (`/var/lib/sentinel/…`, `/var/log/sentinel/…`) and the `${EXPO_PUSH_TOKEN}` placeholder. On a development machine without that variable, every `./run.sh` command with the default `--config` exits 1 with `Error: Environment variable 'EXPO_PUSH_TOKEN' is not set (referenced as ${EXPO_PUSH_TOKEN} in config)`. With the variable set, it would still try to write to the root-owned `/var/log/sentinel` and `/var/lib/sentinel`.
- `config/config.example.yaml` is the template. It uses relative `data/` and `logs/` paths and has push disabled, so local runs pass `--config config/config.example.yaml` (or a local copy of it).

### `--test-alert` notes

- **Database writes.** The synthetic `[TEST]` article, event and alert records land in the configured DB. Run on the server, that is the production DB.
- **Exit code.** `main()` exits 0 after `--test-alert` in every case, so the printed output and the logs show whether delivery worked.
- **Twilio state.** The owner keeps the Twilio account unfunded on purpose since 2026-09-21. Until the owner recharges it, `phone_call` and `sms` test alerts fail with HTTP 401 ("account … is not active"). This is the expected state. Phone calls stay configured.
- **`sms` bypasses tier routing.** `--test-alert sms` sends an SMS directly, although live tiers 5–8 are push-only (`alerts.urgency_levels.*.channel`).
- **`push` is a raw smoke test.** It calls the Expo push path directly and does not consult `alerts.urgency_levels.*.channel`. It runs neither the per-tier channel routing nor the 9–10 additive-push dispatch. In normal operation, push for the SMS tiers (5–8) is routed per tier by that `channel` setting (`sms` / `push` / `both`), and the urgency 9–10 call fires an additive push — see the [Config Reference](config-reference.md). The flag only dispatches if `alerts.push.enabled: true` and `alerts.push.tokens` is non-empty; otherwise it prints a configuration hint and returns without sending.
- There is no `whatsapp` choice — that channel was removed.

### Mode precedence and exit codes

`main()` checks the mode flags in a fixed order and runs only the first one present: `--test-alert`, `--test-headline`, `--test-file`, `--eval`, `--health`, `--diagnostic`, `--once`, then continuous mode. `--dry-run`, `--config` and `--log-level` are modifiers and combine with any mode.

Exit code 1 occurs on:

- a config load error (any mode);
- a `--test-headline` classification failure;
- a `--test-file` file that is missing, is invalid YAML or holds no headlines;
- an `--eval` set file that is missing, or a pass rate below `1.0`.

`--test-alert` returns 0 even when the call, SMS or push fails.

### Examples

```bash
./run.sh                                                    # continuous mode (production default config)
./run.sh --config config/config.example.yaml --once --dry-run    # one cycle, no alerts (paid classifier calls)
./run.sh --config config/config.example.yaml --test-headline "Russian drones cross into Poland"
./run.sh --config config/config.example.yaml --test-file my_headlines.yaml
./run.sh --config config/config.example.yaml --diagnostic        # writes data/diagnostic.html
./run.sh --config config/config.example.yaml --health            # print data/health.json
./run.sh --config config/config.example.yaml --test-alert        # real phone call (synthetic event)
./run.sh --config config/config.example.yaml --test-alert sms    # real SMS instead
./run.sh --config config/config.example.yaml --eval              # eval harness, default set
./run.sh --config config/config.example.yaml --eval tests/fixtures/eval_set_human.yaml
./run.sh --config config/config.example.yaml --log-level DEBUG
```

`my_headlines.yaml` stands for a file you create in this shape:

```yaml
headlines:
  - "Russian drones cross into Poland"
  - text: "Explosions reported near Rzeszów airport"
    expected:
      urgency_score: 9
```

---

## `dashboard/cli.py` (via `./dashboard/run-dashboard.sh`)

The dashboard is a **separate, local-only** subsystem — a read-only Flask API over a copy of the production SQLite DB. It is never deployed. Flags are defined in `dashboard/cli.py:build_parser()`.

| Flag | Argument | Default | Effect |
|---|---|---|---|
| `--port` | `INT` | `5001` | Port for the Flask server (binds `127.0.0.1`). |
| `--db` | `PATH` | dashboard default | Path to the local sentinel SQLite DB to serve. The FTS index is derived next to a custom DB path. |
| `--tunnel` | — | off | Connect to the production DB via an SSH tunnel (SCP-fresh-fetch at startup; LIKE-only search). |
| `--sync` | — | off | Sync (SCP) the production DB locally **before** starting the server, then start. |

### Examples

```bash
./dashboard/run-dashboard.sh                  # start on :5001 against the local DB
./dashboard/run-dashboard.sh --sync           # pull prod DB, then serve
./dashboard/run-dashboard.sh --tunnel         # serve over an SSH tunnel
./dashboard/run-dashboard.sh --port 5005      # custom port
./dashboard/run-dashboard.sh --db path/to/sentinel.db
```

---

## Other entry points

These scripts are for evaluation and testing only. None of them is part of the monitoring runtime. Each `python -m sentinel.eval.*` module prints its options with `--help`.

| Entry point | Purpose | Side effects | Covered in |
|---|---|---|---|
| `python -m sentinel.eval.compare_models` | Compare candidate classifier models on a labeled dataset. | Offline by default; `--live` makes paid model calls and requires `--budget-usd` (at most 5). | [Model comparison](../how-to/model-comparison.md) |
| `python -m sentinel.eval.rescore_dimensions` | Re-score an existing comparison report without new model calls. | Offline. Writes a new report. | [Model comparison](../how-to/model-comparison.md) |
| `python -m sentinel.eval.cached_runtime` | Replay a finished model report through the current runtime logic. | Offline. Writes a new report. | [Model comparison](../how-to/model-comparison.md) |
| `python -m sentinel.eval.direct_luna` | Repeated-input checks of Luna through the direct OpenAI API, with fake alert transports. | Offline by default; `--live` makes paid calls (capped by `--max-cost-usd`). | [Model comparison](../how-to/model-comparison.md), [API setup](../how-to/api-setup.md) |
| `python -m sentinel.eval.incident_memory` | Smoke test of incident-memory decisions on `tests/fixtures/incident_memory_eval.yaml`. | `--live` makes paid classifier calls; never sends alerts. Default `--config` is `config/config.example.yaml`. | Not documented elsewhere. |
| `python -m sentinel.eval.export_candidates --from-production` | Sample production articles for a benchmark dataset. | Connects to production over SSH as `deploy@` and runs a read-only `sudo sqlite3 -readonly` query. Writes `data/eval/production-candidates.json` by default. | [Model comparison](../how-to/model-comparison.md) |
| `test_e2e_live.py` (repo root) | Live end-to-end test of the whole pipeline. | Places a real phone call and makes paid classifier calls. It always loads `config/config.yaml`. Its docstring still says "Claude Haiku"; the classifier it uses is whatever `classification.provider` names. | — |

---

## See also

- [Config Reference](config-reference.md) — `--config` targets this file; `--eval` / `--test-alert` read keys documented there.
- [Testing how-to](../how-to/testing.md) — dry runs, fixtures, and the eval harness in context.
- [Model comparison how-to](../how-to/model-comparison.md) — the `python -m sentinel.eval.*` evaluation runners.
