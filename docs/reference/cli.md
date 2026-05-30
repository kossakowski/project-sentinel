# CLI Reference — Project Sentinel

Two command-line entry points exist:

- **`sentinel.py`** — the monitoring runtime (fetch → classify → corroborate → alert). Run via the `./run.sh` wrapper.
- **`dashboard/cli.py`** — the local read-only Article Dashboard (Flask API). Run via the `./dashboard/run-dashboard.sh` wrapper or `python -m dashboard`.

Both `run.sh` and `dashboard/run-dashboard.sh` are thin venv-bootstrap wrappers: they create/activate `.venv` if needed, then `exec` the underlying Python and **forward all arguments unchanged**. Anything below works identically whether you call the wrapper or the Python entry point directly.

---

## `sentinel.py` (via `./run.sh`)

Flags are defined in `sentinel.py:build_parser()`.

| Flag | Argument | Default | Effect |
|---|---|---|---|
| `--dry-run` | — | off | Run the full pipeline (fetch + classify + corroborate) but suppress **all** Twilio calls/SMS (sets `testing.dry_run = True`). Safe for development. |
| `--test-headline` | `TEXT` | — | Feed a single headline through the classifier and print the `ClassificationResult` (military?, type, urgency, countries, aggressor, confidence, summary, token counts). Hits the live Anthropic API. Then exits. |
| `--test-file` | `FILE` | — | Load a YAML file with a `headlines:` list (optional per-entry `expected:` map), classify each headline under one event loop, print results and any expected-vs-actual mismatches. Then exits. |
| `--config` | `PATH` | `config/config.yaml` | Path to the config file to load. |
| `--once` | — | — | Run exactly one pipeline cycle, print a `CycleResult` summary, then exit (no scheduler). |
| `--log-level` | `{DEBUG,INFO,WARNING,ERROR}` | from config | Override `logging.level` for this run. |
| `--health` | — | — | Print `health.json` (co-located with the DB) and exit. Reports "No health data found" if the pipeline hasn't run. |
| `--diagnostic` | — | — | Force dry-run, run one cycle, and write an HTML report of every article to `data/diagnostic.html` (next to the DB). Then exits. |
| `--test-alert` | `[phone_call\|sms\|push]` | `phone_call` when bare | Fire a **real** test alert. Bypasses fetching/classification/corroboration by injecting a synthetic urgency-10 / source-count-2 event straight into the alert system, then calling the requested channel method directly. `phone_call` / `sms` go via Twilio; `push` goes via Expo (and is a no-op with a printed warning unless `alerts.push.enabled: true` and a token is configured). Then exits. |
| `--eval` | `[PATH]` | `testing.eval_set_file` when bare | Run the classifier eval harness against a labeled YAML eval set. With no path, uses `testing.eval_set_file` (default `tests/fixtures/eval_set.yaml`). Hits the live API, prints a report, saves JSON under `data/eval/`, and exits `0` only if the overall pass rate is `1.0` (else `1`) — useful for CI gating. |

With **no flags**, `sentinel.py` runs in **continuous mode**: it starts the pipeline, runs one cycle immediately, then drives the dual-lane APScheduler (fast lane every 3 min, slow lane every 15 min) until interrupted.

> `--test-alert push` only dispatches if `alerts.push.enabled: true` and `alerts.push.tokens` is non-empty; otherwise it prints a configuration hint and returns without sending. There is **no** `whatsapp` choice — that channel was removed.

### Examples

```bash
./run.sh                                      # continuous mode (production default)
./run.sh --once --dry-run                     # one cycle, no alerts
./run.sh --test-headline "Russian drones cross into Poland"
./run.sh --test-file tests/fixtures/eval_set.yaml
./run.sh --diagnostic                         # writes data/diagnostic.html
./run.sh --health                             # print health.json
./run.sh --test-alert                         # real phone call (synthetic event)
./run.sh --test-alert sms                     # real SMS instead
./run.sh --eval                               # eval harness, default set
./run.sh --eval tests/fixtures/eval_set_human.yaml
./run.sh --config config/config.yaml --log-level DEBUG
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

## See also

- [Config Reference](config-reference.md) — `--config` targets this file; `--eval` / `--test-alert` read keys documented there.
- [Testing how-to](../how-to/testing.md) — dry runs, fixtures, and the eval harness in context.
