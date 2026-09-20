# Luna production deployment — 2026-09-20

The operator explicitly approved deployment after the local migration and Polish
summary fix were verified. The local Claude Code
[`/deploy` workflow](../../.claude/skills/deploy/SKILL.md) and server runbook were
read and applied with the migration-specific adaptations below.

## Release and backup

| Item | Verified value |
|---|---|
| Source branch | `eval/clarified-policy` |
| Master update | Fast-forward from `2cad033` to `7048a91` |
| Deployment tag | `deploy-20260920-232235` |
| Deployed code | `7048a910cab7296b3f1bf24e04f3bc07985e1d47` |
| Previous server code | `2cad0334a56cfa1d0a5a25abfc1967a6f35b49b6` |
| Remote | `deploy@178.104.76.254`, port `2222` |
| Backup | `/home/deploy/backups/deploy-20260920-232235/` |
| Restart | `2026-09-20T21:29:49.307602+00:00` |

Master and the tag were pushed before the server fetched and checked out that
exact tag. Master was already checked out in the clean `sentinel-mobile` worktree,
so the fast-forward was performed there, preserving the worktree assignments.
The pre-flight full local test run passed **581 tests**.

The protected backup directory contains `code.tar.gz` (including the old venv,
excluding Git metadata and any repository `.env`), `config.yaml`, `sentinel.db`,
`sentinel_session.session`, and `sentinel.service`. Both SQLite files were backed
up with SQLite's backup API and passed integrity checks. Original credentials
were neither copied into the backup nor changed. Normal backup retention kept
the ten newest deployment snapshots.

## Migration-specific configuration

- Live settings outside `classification` were preserved, including source lists,
  notification channels, push token, database/log paths and Telegram session path.
- Existing corroboration and similarity settings were preserved. The tested
  incident-memory path was enabled with the approved configuration.
- The model is direct OpenAI `gpt-5.6-luna`, with reasoning `none` and the Polish
  summary guard. A summary repair cannot change danger or incident identity.
- The application allowance is $10/month. Its ledger is
  `/var/lib/sentinel/model-usage.db`, owned by `sentinel:sentinel`, mode `0600`.
  It was seeded from the 51 settled local verification calls ($0.01801648 estimated).
  The OpenAI project also has the separately verified $10 enforced monthly cap.
- `/etc/sentinel/openai.env` contains the dedicated OpenAI key, owned by `root:root`,
  mode `0600`. It was transferred over SSH without appearing in arguments or output.
- `/etc/systemd/system/sentinel.service.d/20-openai.conf` adds that environment
  file. `/etc/sentinel/sentinel.env` remains byte-for-byte unchanged and continues
  to provide the original credentials. This honours the old skill's restriction
  on modifying that file.

Unlike the old generic skill's wholesale config copy, this deployment merged only
reviewed classifier fields and used an absolute writable usage-ledger path.
Dependencies were installed and verified before activating the new config.
`pip check` passed; installed versions include OpenAI 2.54.0, Lingua 2.2.0,
jsonschema 4.26.0, Anthropic 0.86.0 and Pydantic 2.12.5.

Before restart, a process running as the service user validated the staged config,
provider construction, direct model access (HTTP 200) and additive schema migration
on a copy of the backup database. The copy retained all row counts. The live
configuration and existing credential file remained untouched during this check.

## Post-deployment verification

- The service is `active/running`, with zero automatic restarts.
- The initial real cycle fetched 789 articles, selected four for classification,
  and persisted four `openai` / `gpt-5.6-luna` results. All summaries were Polish.
  One normal urgency-5 push was delivered. No synthetic production alert was used.
- The scheduled fast cycle at `2026-09-20T21:32:53.807446+00:00` completed and wrote
  fresh healthy status. The pending/failed classification counts were both zero;
  `degraded` was false. RSS, Google News and Telegram fetcher health were true.
- SQLite integrity checks passed. Every article, classification, event and alert
  ID from the backup remains present after migration. Historical alert state was
  not wiped or replayed wholesale.
- The original secrets-file hash still matches. The production usage ledger had
  58 settled entries, estimated total $0.02193252, after the first real cycle.

The only observed error was an existing Rzeczpospolita RSS HTTP 403. Fourteen such
errors were found in the pre-deployment journal between 18:00 UTC and restart,
including 21:19 UTC. Its configuration was preserved; this is not a new Luna failure.

Server-side details are retained beside the backup in `migration-state.json`,
`database-counts.json`, `health-before.json`, `verification.json` and `pip-install.log`.

## Rollback plan — only on explicit instruction

Stop the service, select the previous code commit/tag, restore the backed-up live
config with owner `root:sentinel` and mode `0640`, remove only the newly added
`20-openai.conf` drop-in, reload systemd, then restart and verify. The old Anthropic
credential remains available in the unchanged original environment file.

**Keep the current production database and alert history.** The migration is additive;
restoring the pre-deployment database over newer alert records could cause repeated
notifications or lost history. The database backup is a recovery artifact, not a
routine rollback step. Preserve the OpenAI usage ledger for cost accounting. The
dedicated OpenAI environment file can remain protected and inactive after removing
its drop-in. The old code/venv archive is available if dependency recovery is needed.
