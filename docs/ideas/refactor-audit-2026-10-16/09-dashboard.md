# 09 — Dashboard refactoring audit (`dashboard/` + `dashboard/frontend/`)

Auditor scope: local-only read-only Article Dashboard. Read-only audit; no repo file changed.

## What I ran (all local, no network, no paid calls)

- `.venv/bin/pytest tests/test_dashboard*.py -q -p no:cacheprovider` → **111 passed** (43–56 s; 8.3 s of it is one test importing the legacy classifier module, see D15).
- `.venv/bin/ruff check dashboard` → all checks passed.
- Frontend: `dashboard/frontend/node_modules` does **not** exist, so `tsc` / `vitest` were **not run** (unverified).
- Read-only timings against the local synced snapshot `dashboard/data/sentinel.db` (37,121 articles, 5,774 classifications, 549 events, 433 alert records; snapshot dated 2026-05-27, **pre-Luna schema**: no `classification_queue`, no `provider_used`).
- Two scratch probes on temp files in the scratchpad (SQLite ATTACH semantics; annotation POST validation on a temp `annotations.db`, deleted afterwards).

## Sacred data note

The owner's dashboard labels live in `dashboard/data/annotations.db` (16 KB, last written 2026-05-23, gitignored, no backup or export). Nothing below proposes altering, migrating or rewriting existing rows. D07, D08, D13 and D14 exist to *protect* that file.

## TODO.md §6.2 cross-check (reference, not rediscovered)

| §6.2 bullet | Status | Mis-description to fix in TODO |
|---|---|---|
| 1 — ignores `classification_queue` | Accurate. `dashboard/` never references the table. | The quoted text is in `ClassifierView.tsx:46` ("This article was not classified (filtered out before classification stage)"). The list badge only says "Unclassified" (`badges.ts:55`). |
| 2 — classifier-input view is the legacy prompt | Accurate. | Add the test coupling (D15): the dashboard test suite imports the legacy `USER_PROMPT_TEMPLATE`, so deleting the legacy classifier breaks dashboard tests. |
| 3 — `push` has no icon/label, missing from the union | Accurate for `EventTimeline.tsx:21-31` and `types.ts:112`. | `EventDetailPage.tsx:277` renders the raw `alert_type` string, so there "push" appears as text, not "•". Two different renderers (D11). |
| 4 — language filter lacks `ru` | Accurate (`FilterBar.tsx:47-52`). | The `Language` type (`types.ts:19`) also lacks `ru`. Better fix: derive options from data (D10), not another literal. |
| 5 — `--sync` copies only `sentinel.db` from a WAL DB | Accurate for `sync.py:56-71`. | Tunnel mode has the **same** single-file SCP in `db.py:203-224`. The bullet names only `--sync`. |
| 6 — optional `provider_used`, `prompt_version`, `estimated_cost_usd` | Accurate. | Note the local snapshot lacks these columns, so the code must tolerate both shapes (D05). |

---

## Findings

### D01 — Per-row correlated `json_each` subqueries make filtered list queries take minutes
- **File:line:** `dashboard/db.py:586-612` (`_EVENT_COUNT_SQL`, `_ALERT_COUNT_SQL`, `_EVENT_ID_SQL`), used in the SELECT list at `db.py:669-671` / `691-693` and in WHERE at `db.py:532-544`.
- **Category:** performance / latent bug.
- **Severity:** high (for this subsystem; it does not touch the monitoring runtime).
- **What's wrong:** Every output row runs three correlated subqueries that scan **all** events and parse each `article_ids` JSON. `EXPLAIN QUERY PLAN` shows that SQLite evaluates them *before* `USE TEMP B-TREE FOR ORDER BY`, so the cost is (matching rows × events), not (page size × events). Used in WHERE (`pipeline_status=event_created|alert_sent`, `has_alert`), the cost is (all articles × events). Measured on the local snapshot:
  - default list page: 2.8–5.0 s;
  - `pipeline_status=classified` page (fired by **every** Articles page load for the tab count, D10): **72.7 s**;
  - `COUNT(*)` with the `event_created` predicate: **> 108 s** (killed);
  - the same three counts done set-based with one CTE: **0.175 s**.
- **Proposed refactor:** Replace the three SQL constants with one membership CTE prepended to every list, search and count query:
  `WITH ae AS (SELECT je.value AS article_id, e.id AS event_id, e.first_seen_at FROM events e, json_each(e.article_ids) je), aa AS (SELECT DISTINCT ae.article_id FROM ae JOIN alert_records ar ON ar.event_id = ae.event_id)`.
  Then derive `event_count`, `alert_count` and `event_id` with `LEFT JOIN`s on aggregated forms of these CTEs. For `event_id`, take the MIN `first_seen_at` within the retention window to keep the tie-break from spec req 2.2c. Filters become `a.id IN (SELECT article_id FROM ae)`. A single `_membership_cte()` helper owns this.
- **Behavior-preserving:** yes (same fields and the same tie-break).
- **Effort:** M.
- **Test that proves it:** existing `test_dashboard_db.py` / `test_dashboard_api.py` stay green. Add a parity test that runs the old and new SQL on the fixture and compares the JSON for every `pipeline_status` and `has_alert` combination. Add a perf guard: 5,000 synthetic articles × 300 events, where `get_articles(filters={"pipeline_status": "alert_sent"})` finishes in < 1 s.

### D02 — `db.py` (1,326 lines) is a monolith with triplicated query plumbing
- **File:line:** `db.py:701-762` (`get_articles`), `1029-1085` (`_search_fts`), `1102-1165` (`_search_like`). Sort, direction, COUNT, `total_pages` and the response envelope are copied three times. Page-size normalisation is copied twice (`725-728`, `986-989`). The classification column list is duplicated in `_list_select_columns` and `_detail_select_columns` (`663-695`). The alert-record dict is built twice (`836-847`, `926-939`) and the event dict twice (`852-867`, `941-956`). `get_articles(sort="published_at")` ignores its own `DEFAULT_SORT` constant (`704`).
- **Category:** duplication / oversized module.
- **Severity:** med.
- **Proposed refactor:**
  1. Add `_paged(base_from: str, where: str, params: list, order_clause: str, page, page_size) -> dict`, which owns COUNT, LIMIT/OFFSET and the envelope.
  2. All three public paths call `_paged` with only their FROM, WHERE and ORDER BY differing.
  3. Add a `_CLASSIFICATION_COLUMNS` constant, plus `_event_from_row` and `_alert_from_row` static helpers.
  4. Split the file into `dashboard/store/connection.py` (open/attach/tunnel), `articles.py` (list/search/detail), `events.py`, `stats.py` and `sql.py` (fragments plus the D01 CTE), with `DashboardDB` as a thin facade so imports and tests keep working.
  - Option: reuse the `sentinel.models.*.from_row` mappers instead of the dashboard's own dicts. Trade-off: those mappers expect the post-migration columns and would break on old local snapshots. Keep the dashboard mappers, but in one place.
- **Behavior-preserving:** yes.
- **Effort:** M.
- **Test that proves it:** the 111 existing tests, plus a golden-JSON snapshot of `/api/articles` (list, FTS, LIKE), `/api/articles/<id>`, `/api/events/<id>` and `/api/stats` captured before the split and diffed after.

### D03 — Duplicate classification rows per article would duplicate list rows and inflate counts
- **File:line:** the schema has no `UNIQUE(article_id)` (`sentinel/database.py:52-70`). `insert_classification` dedupes only on the PK `id` (`database.py:241`). The incident-memory replay path inserts a fresh result for an article already linked to an event (`sentinel/classification/corroborator.py:53-68`). The dashboard joins classifications with a bare `LEFT JOIN classifications c ON c.article_id = a.id` at `db.py:736, 780, 913, 1053, 1133` and `annotations.py:260`, and counts rows at `db.py:1179`.
- **Category:** latent bug.
- **Severity:** med.
- **What's wrong:** A second classification for one article, for example a re-run after a crash between grouping and `classification_complete`, would show the article twice in the list, inflate `total`, `total_pages` and the tab counts, make `get_article_detail` pick an arbitrary row, and double-count `total_classified` and `urgency_distribution`. The local snapshot has 0 duplicates, but it predates incident memory. Production is **unverified**; a one-line read-only check would settle it: `SELECT COUNT(*) FROM (SELECT article_id FROM classifications GROUP BY 1 HAVING COUNT(*) > 1)`.
- **Proposed refactor:** Add one `_LATEST_CLASSIFICATION_JOIN` fragment, `LEFT JOIN classifications c ON c.rowid = (SELECT MAX(rowid) FROM classifications WHERE article_id = a.id)` (the index exists), and use it everywhere. Stats switch to `COUNT(DISTINCT article_id)`. `AnnotationDB.list` gets the same join.
- **Behavior-preserving:** yes for today's data.
- **Effort:** S.
- **Test that proves it:** a fixture with two classification rows for one article. The list returns one row, `total` is unchanged, detail shows the latest row, and `total_classified` counts the article once.

### D04 — Test fixtures freeze the May-2026 SPEC.md schema, so live-schema drift is invisible
- **File:line:** `tests/test_dashboard_db.py:21-80` (a hand-copied `_SCHEMA` "verbatim from SPEC.md"). `tests/test_dashboard_api.py:23` and `tests/test_dashboard_annotations.py:19` import `_build_sentinel_db` from another test module.
- **Category:** test design / schema drift.
- **Severity:** med.
- **What's wrong:** The fixture DB has no `classification_queue`, `provider_used`, `incident_memory`, `notification_revision` or `event_revision`. No dashboard test can fail when `sentinel/database.py` changes, which is exactly how the TODO §6.2 drift accumulated unnoticed.
- **Proposed refactor:** Build the fixture with `sentinel.database.Database(tmp_path / "sentinel.db")`, which runs the real `_create_tables` and `_migrate_schema`, then insert the same sample rows. Keep a second "legacy snapshot" fixture with the old schema, because real local syncs can be old. Move both into `tests/conftest.py` as fixtures. Parametrise the DB tests over both schemas.
- **Behavior-preserving:** yes (tests only).
- **Effort:** S–M.
- **Test that proves it:** the suite stays green on both schemas. Add a sentinel test that the live-schema fixture contains `classification_queue`, which guards D05.

### D05 — Schema catch-up (TODO §6.2 bullets 1, 3 and 6) has no single place to land
- **File:line:** `db.py:351-373` (classification projection), `db.py:438-451` (`_derive_pipeline_status`), `types.ts:9-13, 89-119`.
- **Category:** schema drift / unclear boundary.
- **Severity:** med.
- **Proposed refactor:** At connect time, probe once with `PRAGMA table_info` / `sqlite_master` and store `self.schema = SchemaCaps(has_queue, has_provider_cols, has_revisions)`.
  - The classification projection adds `provider_used`, `prompt_version`, `estimated_cost_usd`, `cached_input_tokens` and the `incident_memory.decision` (useful for the open event-grouping bug) only when present; otherwise it emits null.
  - The pipeline status gains `queued` and `classification_failed` (queue row with `attempts > 0`) when `has_queue`.
  - Alert records carry `event_revision`.
  - `types.ts` gains the fields as optional and `PipelineStatus` gains the two states.
  - All of this goes through D02's single mapper.
- **Behavior-preserving:** no (additive API fields and new statuses).
- **Effort:** M.
- **Test that proves it:** D04's dual-schema fixtures. On the live schema, a queued article reports `queued`; on the legacy schema, every new field is null and nothing raises.

### D06 — SCP code duplicated; sync overwrites the live DB non-atomically and leaves stale WAL sidecars
- **File:line:** `db.py:181-227` vs `sync.py:49-71` (same `scp -P … -o BatchMode=yes` invocation in both). `sync.py:141` SCPs straight onto `dest`, the file the request threads have open. `sync.py:96-97` deletes the FTS index before rebuilding it.
- **Category:** duplication / error handling.
- **Severity:** med.
- **What's wrong:**
  - A failed or partial SCP leaves a truncated `sentinel.db`, and the 503 path cannot recover it.
  - Stale `-wal` / `-shm` sidecars survive. The local data dir has `sentinel.db-shm` and `sentinel.db-wal` dated 2026-10-11 next to a `sentinel.db` from 2026-05-27. A non-empty stale WAL would be replayed onto a different DB file.
  - The WAL single-file problem (TODO §6.2 bullet 5) is duplicated in tunnel mode.
- **Proposed refactor:** Add one `sync.fetch_remote_db(dest) -> None`:
  1. SCP to `dest + ".part"` (plus the `-wal` file, or the owner-approved server-side `.backup` from TODO §6.2).
  2. Run `PRAGMA quick_check` on the copy.
  3. Remove stale `dest-wal` / `dest-shm`.
  4. `os.replace(part, dest)`.
  5. Build FTS into `fts.part`, then `os.replace`.

  `DashboardDB._connect_via_tunnel` calls the same function.
- **Behavior-preserving:** yes, except that failure no longer corrupts the existing copy.
- **Effort:** S–M.
- **Test that proves it:** mock `subprocess.run` to write half a file and exit 1. The original `sentinel.db` stays byte-identical and the FTS index still exists. A second test pre-creates a non-empty `sentinel.db-wal` and asserts it is gone after a successful sync.

### D07 — Annotation form pre-selects "Correct" on unannotated articles
- **File:line:** `dashboard/frontend/src/components/AnnotationPanel.tsx:49` (`DEFAULT_FORM = { label: "correct", … }`), used by `formFromAnnotation(null)` at `52-53`.
- **Category:** latent bug (label integrity).
- **Severity:** med.
- **What's wrong:** On a fresh article the "Correct" radio is already `aria-checked`, so one click on Save writes a `correct` label the owner never chose. This contradicts the owner rule "never pre-fill labels; the user is the sole ground truth". SPEC req 4.3a requires pre-fill only when an annotation *exists*.
- **Proposed refactor:** Use `label: AnnotationLabel | null` in `FormState`. With no annotation the default is `null`, no radio is checked, and Save is disabled until a label is picked. This does not touch any stored row.
- **Behavior-preserving:** no (intended UI change).
- **Effort:** S.
- **Test that proves it:** a vitest case in `AnnotationPanel.test.tsx`. Rendering with `initialAnnotation = null` shows no `aria-checked="true"` and a disabled Save. After clicking Incorrect, the POST payload has `label: "incorrect"`.

### D08 — The "read-only" `DashboardDB` attaches `annotations.db` (and FTS) **writable**
- **File:line:** `db.py:278`, `db.py:309` (`ATTACH DATABASE ? AS annotations` with a plain path).
- **Category:** defence-in-depth / unclear boundary.
- **Severity:** low–med (no code writes today, but the file holds the owner's labels).
- **What's wrong:** I verified in a scratch probe that ATTACH on a `mode=ro` main connection still opens the attached file read-write. The module docstring promises read-only access.
- **Proposed refactor:** Attach `f"file:{abs}?mode=ro"` (the pattern `annotations.py:243` already uses, verified to work and to enforce read-only). Only `AnnotationDB` may write.
- **Behavior-preserving:** yes.
- **Effort:** S.
- **Test that proves it:** `DashboardDB(...).conn.execute("DELETE FROM annotations.annotations")` raises `sqlite3.OperationalError: attempt to write a readonly database`.

### D09 — Five copies of the fetch-hook pattern and `toApiError`
- **File:line:** `hooks/useStats.ts:22-62`, `useArticleDetail.ts:22-63`, `useEventDetail.ts:20-67`, `useArticles.ts:24-84`, `useAnnotations.ts:86-153`. Each one defines its own `toApiError` (useStats.ts:58, useArticleDetail.ts:59, useEventDetail.ts:63, useArticles.ts:80, useAnnotations.ts:149). There is also `errorMessage` in `ArticlesPage.tsx:439` and an inline copy in `ArticleTable.tsx:209-214`. The Articles page bypasses `useStats` with its own `fetchStats` effect (`ArticlesPage.tsx:107-131`).
- **Category:** duplication.
- **Severity:** med.
- **Proposed refactor:**
  - Export `toApiError` and `errorMessage` from `api/client.ts`.
  - Add `useApiResource<T>(key: string | null, fetcher: (signal) => Promise<T>, opts: { keepStaleOnError?, silentStatuses?: number[], label })`, which owns the requestId guard, the AbortController and the toast.
  - The four hooks become 5-line wrappers.
  - `useArticles` keeps `stableStringify` as its key. This also fixes the missing `notify` dependency hidden by an `eslint-disable` (`useArticles.ts:65`).
- **Behavior-preserving:** yes.
- **Effort:** S–M.
- **Test that proves it:** the existing vitest suites (`ArticlesPage`, `OverviewPage`, `EventDetailPage`, `ArticleDetailPage`), plus a new `useApiResource` race test: two keys in quick succession, and the slow first response never overwrites the second.

### D10 — Each Articles-page change fires 5 backend requests, including the heaviest endpoint
- **File:line:** `ArticlesPage.tsx:171-209` (three `fetchArticles` calls only to read `.total`; each still materialises 25 full rows, and the "classified" one costs ~73 s, D01). `ArticlesPage.tsx:107-131` calls the full `/api/stats` (all distributions, the funnel and the per-day series) only for the dropdown options. `FilterBar.tsx:47-52` hardcodes the languages.
- **Category:** API design / performance.
- **Severity:** med.
- **Proposed refactor:**
  - Backend: `/api/articles` returns `counts: {all, classified, unclassified}` from one `SELECT COUNT(*), SUM(c.id IS NOT NULL)` over the same WHERE minus the pipeline predicate.
  - Backend: a new `GET /api/filters` returns `DISTINCT source_name`, `event_type` and `language`.
  - Frontend: drop `fetchTabCount` and the options effect, and build `LANGUAGES` from `/api/filters`. That closes TODO §6.2 bullet 4 without another literal.
- **Behavior-preserving:** no (additive API; same UI).
- **Effort:** M.
- **Test that proves it:** an API test where `counts` equals the totals of the three separate pipeline-status queries; a vitest case where a filter change triggers exactly one `/api/articles` request and no `/api/stats` request.

### D11 — Display maps duplicated across components and against the backend
- **File:line:**
  - Alert channels: `EventTimeline.tsx:21-31` (icon/label maps) vs `EventDetailPage.tsx:277` (raw text).
  - Urgency tiers 9/7/5: written twice in `badges.ts:8-25` (`urgencyClass` and `urgencyTier`).
  - `formatConfidence`: `ArticleTable.tsx:607` and `ClassifierView.tsx:21`.
  - Annotation labels: `AnnotationPanel.tsx:39-47`, `badges.ts:78-82`, `annotations.py:37`, and a hardcoded tuple in `db.py:1297`.
- **Category:** duplication.
- **Severity:** low.
- **Proposed refactor:**
  - Add `components/alertChannels.ts` with one map including `push` (icon and label). Both timelines use it, and `AlertRecord.alert_type` becomes `"sms" | "phone_call" | "push" | "whatsapp" | string`.
  - `urgencyClass = s => s == null ? null : \`urgency-${urgencyTier(s)}\``.
  - Add `utils/format.ts`.
  - `AnnotationPanel` builds its options from `ANNOTATION_BADGE`.
  - `db.py` imports `ALLOWED_LABELS`.
- **Behavior-preserving:** yes, except that `push` gains an icon (TODO §6.2 bullet 3).
- **Effort:** S.
- **Test that proves it:** `EventTimeline.test.tsx` and `EventDetailPage.test.tsx` render a `push` record with the same label in both; the existing badge tests stay green.

### D12 — Dead code
- **File:line:**
  - `dashboard/frontend/src/styles/index.dark-backup.css` (1,195 lines, tracked, imported nowhere; only `index.css` is imported in `main.tsx:7`).
  - `AnnotationDB.get_stats` (`annotations.py:373-387`) is unused; `/api/stats` uses `DashboardDB._annotation_stats`, which duplicates it.
  - `export type { Article }` re-export (`api/client.ts:228-230`) has no importer.
  - An inline import inside the handler (`api/annotations.py:83`).
- **Category:** dead code.
- **Severity:** low.
- **Proposed refactor:** Delete the backup CSS (git history keeps it). Delete `AnnotationDB.get_stats`, or make `_annotation_stats` call the shared label tuple. Remove the re-export. Hoist the import.
- **Behavior-preserving:** yes.
- **Effort:** S.
- **Test that proves it:** `npx tsc --noEmit`, `npx vitest run` and pytest stay green; `grep -r dark-backup` returns nothing.

### D13 — Annotation POST returns 500 on a non-string `notes`; orphan article IDs accepted
- **File:line:** `api/annotations.py:71-77`, `annotations.py:343-361`.
- **Category:** inconsistent error handling.
- **Severity:** low.
- **What's wrong:** Verified on a temp DB: `{"notes": {"a": 1}}` raises `sqlite3.ProgrammingError` and returns HTTP 500. `article_id: "x"` (no such article) is stored silently. There is no length cap on `notes`.
- **Proposed refactor:** Add `validate_notes(value) -> str | None` next to `validate_label` (str or None, ≤ 10k chars). Optionally check that the article exists when the sentinel DB is attached, returning 404 with `{"error": "Article not found"}`. Never delete existing orphans.
- **Behavior-preserving:** no (400 instead of 500).
- **Effort:** S.
- **Test that proves it:** POSTs with a dict, an int and an over-long `notes` value each return 400 and leave the DB unchanged.

### D14 — The owner's labels have no export or backup path
- **File:line:** `config.py:234` (single file under gitignored `dashboard/data/`). `sync.py` never touches it, which is correct, but nothing copies it either.
- **Category:** data safety (additive tooling).
- **Severity:** low–med.
- **Proposed refactor:** Add a read-only `python -m dashboard export-annotations [--out FILE]` that writes JSON or CSV via `AnnotationDB.list`, plus an optional timestamped `.bak` copy taken by `run-dashboard.sh` at startup. The code only reads the file and never rewrites it.
- **Behavior-preserving:** yes (additive).
- **Effort:** S.
- **Test that proves it:** the export round-trips every row of a fixture annotations DB, and the fixture file's bytes are unchanged afterwards.

### D15 — Classifier-input view is hand-rebuilt from the legacy prompt; tests are coupled to the legacy module
- **File:line:** `dashboard/classifier_input.py:41-102`. `tests/test_dashboard_api.py:410-470` imports `sentinel.classification.classifier.USER_PROMPT_TEMPLATE` (the 8.3 s import).
- **Category:** unclear boundary / schema drift (TODO §6.2 bullet 2).
- **Severity:** med.
- **What's wrong:** Removing the legacy Haiku path breaks dashboard tests. The live payload is not shown for `provider_used = 'openai'` rows.
- **Proposed refactor:** Make `build_classifier_input(article, classification)` provider-aware. For OpenAI rows, call the real `sentinel.classification.policy.messages(Article.from_row(row), candidates=[], policy)` and render its user JSON, labelled "approximate: remembered_incidents and enrichment are not stored" (TODO §7.3). Optionally compare against `classifications.request_hash` to show whether the reconstruction is exact. Keep the legacy block only for `provider_used = 'legacy'` and missing-column rows, under a "Legacy (Haiku) prompt" heading.
- **Behavior-preserving:** no.
- **Effort:** M.
- **Test that proves it:** for an OpenAI fixture row, the output equals `json.loads(messages(...)[1]["content"])`; a legacy row still yields the current block.

### D16 — Frontend tooling gaps
- **File:line:**
  - `package.json` has no `lint` or `typecheck` script and no ESLint dependency, yet the code carries `eslint-disable` comments (`useArticles.ts:65`, `ArticlesPage.tsx:211`), so the hook-dependency suppressions are unchecked.
  - `dist/` is untracked and built 2026-05-24 11:45, with no freshness check; Flask serves it at `/`.
  - `dashboard/CLAUDE.md` says `npx tsc --noEmit` while `build` runs `tsc -b`.
- **Category:** build/test tooling.
- **Severity:** low.
- **Proposed refactor:**
  - Add `"typecheck": "tsc -b --noEmit"` and `"lint": "eslint src"` with `eslint-plugin-react-hooks`, or delete the dead disable comments.
  - In `app.py`, log a warning when any `src/**` mtime is newer than `dist/index.html`.
- **Behavior-preserving:** yes.
- **Effort:** S.
- **Test that proves it:** `npm run lint` and `npm run typecheck` pass; a unit test of the staleness check with touched temp files.

### D17 — Minor: event-retention comparison mixes ISO `T` with SQLite's space format
- **File:line:** `db.py:608` (`e.first_seen_at >= datetime('now', '-N days')`). Stored values look like `2026-05-27T10:48:44+00:00`; `datetime()` returns `2026-05-27 10:48:44`.
- **Category:** latent bug (boundary).
- **Severity:** low.
- **What's wrong:** On the boundary day, `'T' > ' '` makes the window up to one day wider than N.
- **Proposed refactor:** Compare `julianday(e.first_seen_at) >= julianday('now', ?)`, or pass a Python-computed ISO cutoff as a parameter. Fold this into the D01 CTE.
- **Behavior-preserving:** effectively yes.
- **Effort:** S.
- **Test that proves it:** a fixture event at exactly `now - 30 d - 1 h` gets `event_id = null` with a 30-day retention.

---

## Proposed phase grouping

| Phase | Goal | Findings | Effort | Why this order |
|---|---|---|---|---|
| P0 — Protect labels | Nothing can silently create, alter or lose an owner label. | D07, D08, D13, D14 | S each | Cheap, independent, and guards the only irreplaceable data in the subsystem. |
| P1 — Test foundation | Tests run on the real live schema plus a legacy snapshot. | D04, D12 | S–M | Every later phase needs fixtures that can fail on drift. |
| P2 — Query core | Fast, correct list, search and count. | D01, D03, D17, then D02 (split on top of the new SQL) | M | D01 makes the Articles page usable. Splitting `db.py` after the SQL rewrite avoids moving code twice. |
| P3 — API and frontend slimming | One request per view; shared hooks and maps. | D10, D09, D11, D16 | M | Depends on P2 for cheap `counts`. D11 also closes the TODO §6.2 push bullet. |
| P4 — Live-schema catch-up (= TODO §6.2) | Queue states, provider and cost fields, live classifier input, WAL-safe sync. | D05, D15, D06 | M | Additive features built on P1's dual-schema fixtures and P2's single mapper. |

Overall: functionally solid and well tested (111 pytest tests green; 23 vitest files exist, but are unrun here because `node_modules` is missing). The real problems are an O(articles × events) SQL design that makes the filtered views take minutes, a 1.3k-line `db.py` with triplicated plumbing, and test fixtures frozen on the May-2026 schema, which is why the TODO §6.2 drift went unnoticed.
