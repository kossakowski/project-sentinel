# 05 — Ingestion audit: `sentinel/fetchers/` + `sentinel/processing/`

Auditor scope: `fetchers/{base,rss,google_news,gdelt,telegram}.py`, `processing/{__init__,normalizer,deduplicator,enricher,fulltext,keyword_filter}.py`, their tests, `docs/reference/sources.md`, and the call sites in `sentinel/scheduler.py` (`_fetch_all`, `run_cycle`).
Repo state: master `835ed8e`, clean. Read-only audit.

What I ran (all local, no network, no paid calls):
- `.venv/bin/pytest tests/test_rss.py tests/test_google_news.py tests/test_gdelt.py tests/test_telegram.py tests/test_normalizer.py tests/test_enricher.py tests/test_fulltext.py tests/test_keyword_filter.py tests/test_deduplicator.py -q` → 82 passed.
- `KeywordFilter.diagnose` run against the live `config/config.yaml` keyword lists, and against the 20,430 Polish articles in the local dashboard snapshot `dashboard/data/sentinel.db` (fetched 2026-04-27 to 2026-05-27, opened read-only).
- Small Python checks of `Normalizer._clean_text`, `ArticleEnricher._strip_outlet`, `is_garbage_summary` on a short Telegram post, and of SQLite `datetime('now', …)` vs ISO string comparison.

Known TODO items I reference by title instead of rediscovering them:
- "Telegram fetcher mislabels every channel as Ukrainian Air Force" (section 0). The description is correct, but it is incomplete. See F05.
- "Cyrillic titles normalize to empty (UA/RU never count as independent)" (section 0). The description is correct. See K1.
- "Google News decoder can stall the whole cycle" (section 7 item 7). It names only the enricher, but `fulltext.py:47` has the same synchronous call. See F10.
- "Enrichment is never persisted" (7.3) and "Enriched body truncated to 500 characters" (7.5). These are correct, and I do not repeat them.
- "`config/config.yaml` — stale GDELT field" (6.1 item 1). It is correct. F18 proposes the structural guard against it.
- "Dead enabled feed: Rzeczpospolita RSS" (section 2). It is correct. F02 explains why the app never notices it.

Legend: **BP** means behavior-preserving. "9–10 risk" is the risk to the urgency 9–10 phone-call path, either today or from the change itself.

---

## F01 — Polish exclude keyword `gra` (substring match) silently drops real military articles; four high keywords cancel themselves
- **Where:** `sentinel/processing/keyword_filter.py:63-78` (exclude check), `:184-189` (Slavic substring match), `:67-69` (English excludes added to non-English articles and matched as substrings). Config: `config/config.yaml` `monitoring.exclude_keywords.pl` (`gra`, `manewry`, `film`) and `.en`.
- **Category:** latent bug (live), keyword filter structure.
- **Severity:** HIGH.
- **What's wrong:**
  - Slavic languages use plain substring matching for exclude keywords too. As a result, `gra` ("game") matches `granica/granicy` (border), `program/programu`, `nagranie` (footage), `ogranicza`, `zagraniczny`, `integracja`, `wygrać` and `Kaliningrad`.
  - An article with only a high keyword (no critical one) is then dropped before classification.
  - Verified on the live keyword lists: `"Rosyjskie drony nad granicą z Polską"` gives `high=['dron'], excluded_by=['gra']`, so it is dropped. `"Kaliningrad: rosyjskie wojska w gotowości"` is dropped as well.
  - Four PL **high** keywords can never pass on their own, because each one contains an exclude keyword: `incydent graniczny`, `zamknięcie granicy`, `Kaliningrad` (all three hit `gra`) and `podejrzane manewry` (hits `manewry`).
  - Measured on the local snapshot (one month, PL only): **172 articles** had a real high keyword other than GRU and were dropped only because `gra` appeared inside another word. Examples: "Chmura dymu setki kilometrów od granicy. Rosja ogłosiła alarm – PolsatNews.pl" and "Rosja: ukraińskie drony uderzyły w obiekty… od granicy".
  - English excludes are also substring-matched against Polish text: `film` matches `filmik`, and `game` and `book` also caused drops in the snapshot.
  - The inverse substring bug exists too. The high keyword `GRU` matches `grupa`, `grudnia` and `grozi`. These false matches are often cancelled by `gra`, so the two bugs partly mask each other. Fixing only `gra` would therefore raise classification volume through `GRU` noise.
- **9–10 risk:** MEDIUM.
  - Critical keywords skip the exclude check, so an article with `inwazja`, `nalot` or `ostrzał` still passes.
  - But a Polish-only first report phrased without a critical phrase is dropped before the classifier ever sees it. Example: "Rosyjskie drony uderzyły w Rzeszów, eksplozje przy granicy". The PL critical list has no `atak dronów`, `eksplozja` or `zestrzel*`.
  - Telegram (bypass) and the English feeds may still cover the same incident.
- **Proposed refactor (behavior change, owner-approved and eval-gated):**
  1. Add a match mode per keyword. One option is a config convention: `kw` = whole word, `kw*` = word prefix, `*kw*` = substring. The other is an explicit `{term, match}` object.
  2. Default every exclude keyword to whole word in every language. List inflected forms explicitly (`gra`, `gry`, `grze`, `grę`, `grą`).
  3. Make acronyms like `GRU` whole word and case-sensitive.
  4. Precompile one regex per (language, tier) in `__init__`.
- **Test:**
  - `tests/test_keyword_config_lint.py` loads the tracked `config/config.yaml` and asserts that no critical or high keyword matches any exclude keyword under the language's match rule. It would fail today with exactly the four keywords above.
  - Plus a fixture of real PL headlines (`granicy`, `programu`, `nagranie`, `Kaliningrad`) that must pass, and `grupa` / `grudnia` headlines that must not match `GRU`.
- **Effort:** M (code S; the owner must review the keyword list).

## F02 — Fetcher health monitoring is dead: fetchers swallow every error, so failure counters never move
- **Where:**
  - `rss.py:51-57` and `google_news.py:63-71` catch every exception per source/query and return `[]`. `gdelt.py:93-97` does the same for the whole fetch. `telegram.py:71-78` always succeeds.
  - `scheduler.py:428-445` counts failures only when `fetch()` raises, and `:448-470` sends the "źródło nie odpowiada" SMS on the 10th failure.
  - `scheduler.py:572-576` builds health.json `fetcher_status` from that counter.
- **Category:** inconsistent error handling, missing observability.
- **Severity:** HIGH.
- **What's wrong:**
  - Rzeczpospolita has returned 403 on every cycle (TODO section 2), yet the RSS fetcher reports success.
  - Health is tracked per fetcher, not per feed: one RSS fetcher covers 18 feeds.
  - If `TelegramFetcher.start()` raises (expired session, bad credentials), `startup()` only logs it (`scheduler.py:191-196`). `fetch()` then returns `[]` forever with health "OK". There is no reconnect logic and no `client.is_connected()` check.
  - Telegram is the fastest 9–10 source (Air Force alerts).
  - There are no tests for `record_fetcher_failure`, `_check_fetcher_health` or `fetcher_status`.
- **9–10 risk:** HIGH, but indirect. The fastest source can die silently.
- **Proposed refactor (behavior change in what gets reported only):**
  1. `fetch()` returns `FetchResult(articles, outcomes: list[SourceOutcome(name, ok, status, error)])`.
  2. The scheduler records health per source.
  3. `TelegramFetcher.fetch()` reports `ok=False` when `self.client is None or not self.client.is_connected()`.
  4. Route the "source dead" notice through push, not `_send_system_sms`. Twilio SMS is unfunded and off.
- **Test:** an RSS feed mocked to return 403 for N cycles increments that source's counter and flips `fetcher_status["rss:Rzeczpospolita"]` to false. A Telegram fetcher with `client=None` reports unhealthy.
- **Effort:** M.

## F03 — The enricher fetches t.me pages for short Telegram posts and replaces the summary with another post's text
- **Where:** `enricher.py:116-139` (`is_garbage_summary`), `:255-263`, `:206-235` (`_fetch_body` and og:description). `telegram.py:113-120` sets title = text[:200] and summary = text[:500].
- **Category:** latent bug that compounds the known Telegram mislabel.
- **Severity:** HIGH.
- **What's wrong:**
  - A Telegram post shorter than 200 characters gets title == summary. Most Air Force alerts are that short, for example "Загроза застосування балістичного озброєння з півночі!".
  - `is_garbage_summary` therefore returns True. I verified this on a normalized Telegram article.
  - The enricher then fetches `https://t.me/kpszsu/<id>`. Because of the known mislabel, that URL is the wrong channel plus another channel's message id.
  - The page's og:description (another post, or the channel description) replaces the summary.
  - The classifier then sees the real headline next to unrelated body text.
  - Even after the mislabel is fixed, the fetch is pointless, because the full message is already in hand. It also adds up to 5 s per article on the serial incident-memory path.
  - Not verifiable on live data, because enrichment is never persisted (TODO 7.3).
- **9–10 risk:** HIGH. It corrupts classifier input for the source most likely to carry the first 9–10 signal.
- **Proposed refactor (behavior change):** add a per-source-type rule, `processing.enrichment.skip_source_types: [telegram]`. Mark Telegram articles with `raw_metadata["enrichment"] = {"method": "none", "reason": "full_text_source"}`. Long term, a Telegram article should carry its full text and no artificial title/summary split.
- **Test:** `enrich_batch([short_telegram_article])` makes no HTTP request (assert `_fetch_body` is not awaited) and leaves the summary unchanged.
- **Effort:** S.

## F04 — The OpenAI enrichment gate fails closed: one failed gate call aborts the article's classification for `retry_delay_seconds`
- **Where:** `enricher.py:80-98` (`_check_vagueness_direct`, no try/except) and `:267-272`; `scheduler.py:252-261` (enrich, then classify, inside one `try`, then `classification_failed(… retry_delay_seconds)`). The legacy `_check_vagueness_llm` (`:171-173`) fails open.
- **Category:** inconsistent error handling.
- **Severity:** MEDIUM-HIGH.
- **What's wrong:**
  - `OpenAIProvider.request` raises `ClassificationError` on refusal, invalid structured output, incomplete response, timeout or rate limit (`openai_provider.py:180-226`).
  - That error stops the article before the classifier call. The article is re-queued after `classification.retry_delay_seconds` (300 s live).
  - So a quality gate that exists only to improve input can delay a critical article by at least 5 minutes per transient failure.
  - The `fulltext.py` docstring states the opposite principle: "a missing full text must never block or delay an alert".
- **9–10 risk:** MEDIUM. It adds a second failure point in front of every non-garbage article, and refusals on war content are plausible.
- **Proposed refactor (behavior change, which restores parity with the legacy path):** wrap the gate. On any exception, log a warning and record `enrichment={"method": "gate_error", "error": type}`. Then either continue unenriched or fetch the body anyway. Never raise out of `enrich_batch`.
- **Test:** the provider mock raises `ClassificationError`. `run_cycle` (incident-memory path) still calls `classifier.classify` for the article, and `classification_failed` is not called.
- **Effort:** S.

## F05 — Telegram mislabel (known TODO): concrete fix, plus a test that encodes the bug, plus an incomplete TODO
- **Where:** `telegram.py:55-63`, `:96-111`; `tests/test_telegram.py:113-139`; `corroborator.py:448-456` (`_extract_domain`).
- **Category:** known bug; test gap; the TODO is incomplete.
- **Severity:** HIGH (already tracked).
- **Notes beyond the TODO:**
  - `test_message_to_article` uses `chat_id=123` against `channel_id="@test_channel"` with one channel configured. It passes only through the "fallback: first channel" branch, so the test asserts the bug.
  - The TODO says the mislabel makes "all Telegram channels count as one source". That is only half the cause. Every Telegram URL has the domain `t.me`, and `Corroborator._extract_domain` compares bare netlocs. Fixing the channel map alone still leaves all channels as one source. The owner-decision item "corroboration 1 vs 2 sources" lists prerequisites that miss this point (and F06).
- **Proposed fix (behavior change):**
  1. In `start()`, resolve each channel once: `peer = await client.get_peer_id(ch.channel_id)`. Key the map by that numeric peer id, which matches `message.chat_id`.
  2. Delete the fallback. Log and drop unmatched messages, or use `event.chat.username`.
  3. Make the source-identity function aware of channels (`t.me/<channel>`) for corroboration.
- **Test:** two channels configured, and a message with the peer id of the second channel gets that channel's name, language and URL. Rewrite the existing test so it does not depend on the fallback.
- **Effort:** S (fetcher) + S (domain helper).

## F06 — Google News: every article carries a `news.google.com` URL, so all of them count as one source, and the real publisher is discarded
- **Where:** `google_news.py:139-169` (`source_url` = the GN redirect link; `source_name=f"GoogleNews:{query}"`; `entry.source` is never read); `corroborator.py:312-317`.
- **Category:** latent bug (corroboration input), data loss.
- **Severity:** MEDIUM.
- **What's wrong:**
  - A PAP story and an Onet story arriving through Google News share the domain `news.google.com`. `_is_independent_source` therefore says "not independent".
  - `source_name` groups articles by query string, not by outlet.
  - feedparser exposes the outlet as `entry.source.title` / `entry.source.href`, but the fetcher drops it.
- **9–10 risk:** none today, because one source triggers a call. It would block the two-source option.
- **Proposed refactor (behavior change):**
  - Store `raw_metadata["publisher"] = {"name", "url"}`.
  - Set `source_name = f"GoogleNews:{publisher}"` and keep the query in `raw_metadata["query"]`.
  - Give the corroborator a shared `source_identity(article)` helper (publisher domain for GN, channel for Telegram, netloc otherwise).
- **Test:** two GN entries with different `<source url=…>` count as independent. Two with the same publisher do not.
- **Effort:** S-M.

## F07 — Fetchers run sequentially, and httpx `timeout=30` limits each phase, not the whole request
- **Where:** `scheduler.py:428-446` (a `for` loop with an `await` per fetcher; Telegram is drained last); `rss.py:76`, `google_news.py:78`, `gdelt.py:116` (`timeout=30.0`).
- **Category:** structure, latency.
- **Severity:** MEDIUM.
- **What's wrong:**
  - The fast lane waits for every RSS feed (up to 30 s per phase, and a server that trickles bytes can stretch this), then for Google News (same), and only then drains the already-buffered Telegram messages.
  - The `_cycle_lock` serializes fast and slow cycles, so a slow full cycle also delays the next fast one.
  - No fetcher has an overall deadline.
- **9–10 risk:** MEDIUM (latency only).
- **Proposed refactor:**
  - Run `asyncio.gather` over the fetchers, each wrapped in `asyncio.timeout(cfg.sources.http.total_timeout_seconds)`.
  - Use `httpx.Timeout(connect=…, read=…, total via asyncio)`.
- **BP:** yes for outputs. Pending order is by `fetched_at`, so only timing changes.
- **Test:** an RSS fetcher mocked to sleep 60 s does not delay the Telegram buffer drain, and the cycle finishes within the deadline.
- **Effort:** S.

## F08 — HTTP and feed plumbing is duplicated three times, with diverging details
- **Where:**
  - Status handling: `rss.py:78-90`, `google_news.py:87-101`, `gdelt.py:128-136` (429 / 5xx / `raise_for_status`).
  - Published-date parsing is duplicated verbatim: `rss.py:167-178` and `google_news.py:143-155`. The GN copy also has `import calendar` inside the function.
  - Summary stripping: `rss.py:147-148` and `google_news.py:157-158`.
  - Each request builds a new `httpx.AsyncClient` (18 feeds + 16 queries per cycle, with no connection reuse).
  - Five different User-Agent strings: `rss.py:64`, `google_news.py:82`, `gdelt.py:124` (contains the owner's personal email in a public repo), `enricher.py:213`, `fulltext.py:19`.
  - Mixed `UTC` / `timezone.utc`.
- **Category:** duplication, hardcoded values.
- **Severity:** MEDIUM.
- **What's wrong:** each fixed edge case has to be fixed again elsewhere. RSS has WAF detection and conditional GET. Google News has neither, so a consent or HTML page there produces a `bozo` "malformed XML" error instead.
- **Proposed refactor (BP):**
  - `sentinel/fetchers/http.py`: one shared `AsyncClient` per fetcher lifetime, and `get_feed(url, *, headers, source_label) -> Response | Skip(reason)` with the 304/429/5xx/WAF rules.
  - `sentinel/fetchers/feeds.py`: `entry_published_at(entry)`, `entry_summary(entry)`, and `parse_entries(feed, to_article, label)`.
  - UA and timeouts come from config (F17).
  - Give Google News WAF detection as a separate, explicit behavior change.
- **Test:** the existing `test_rss.py` and `test_google_news.py` pass unchanged. Add a parametrized test of `get_feed` over 200/304/403/429/503/HTML.
- **Effort:** M.

## F09 — `BaseFetcher` is a nominal interface: callers special-case fetchers by name
- **Where:**
  - `base.py:24-26`: `is_enabled` raises `NotImplementedError` instead of being abstract.
  - `rss.py:30`: `fetch(*, max_priority=…)` extends the signature.
  - `scheduler.py:435`: `if fetcher.name == "rss" and fast_only: fetch(max_priority=1)`, with a hardcoded 1.
  - `scheduler.py:191-205`: `start` / `stop` are discovered with `hasattr`.
  - `scheduler.py:416-418`: `_FAST_LANE_FETCHERS` is defined but unused, and lane membership is a set of name strings.
  - `telegram.py:23,65,87`: `_running` is written and never read.
  - The Telegram channel `priority` is dead config (sources.md admits it).
  - `is_enabled` is checked three times (`_init_fetchers`, each `fetch`, `KeywordFilter._build_bypass_sources`).
- **Category:** unclear boundaries, dead code, hardcoded values.
- **Severity:** MEDIUM.
- **Proposed refactor (BP):**
  - `class BaseFetcher(ABC)` with `async def start(self): pass`, `async def stop(self): pass`, `def lanes(self) -> set[Lane]` and `async def fetch(self, lane: Lane) -> FetchResult`.
  - RSS maps `Lane.FAST` to `scheduler.fast_lane_rss_max_priority` (new config key, default 1).
  - Delete `_FAST_LANE_FETCHERS` and `_running`. Either use the Telegram `priority` or drop it from the config model.
- **Test:** a scheduler test with fake fetchers asserts that the fast lane calls GDELT zero times and RSS with `Lane.FAST`. Existing tests stay green.
- **Effort:** M.

## F10 — Two article-page fetchers, and `fulltext` reaches into a private enricher method (the Google News decoder stall exists in both)
- **Where:**
  - `enricher.py:179-235`: `_resolve_url` and `_fetch_body` (og:description, 5 s, 500 characters).
  - `fulltext.py:42-60`: `fetch_full_text` (trafilatura, 10 s, 8000 characters) calls `ArticleEnricher._resolve_url` (`:47`), a private static method.
  - Importing `fulltext` pulls in `enricher`, which pulls in `anthropic`, `openai_provider` and `googlenewsdecoder`.
  - `googlenewsdecoder.new_decoderv1` is synchronous with no timeout, and it is called from both places on the event loop. TODO 7.7 names only the enricher.
- **Category:** duplication, boundary violation, latent bug (event-loop stall).
- **Severity:** MEDIUM. The stall is HIGH, but TODO 7.7 already tracks it.
- **Proposed refactor:**
  - `sentinel/processing/article_page.py` with `async resolve_url(url, *, deadline)`, which runs the decoder in a bounded `ThreadPoolExecutor` under `asyncio.wait_for`.
  - One `fetch_page(url, timeout)` and two extractors (`og_description`, `main_text`).
  - The enricher and fulltext both use it.
- **BP:** yes, except the deadline, which is a fix.
- **Test:** monkeypatch `new_decoderv1` to block for 30 s. `enrich_batch` returns within the deadline and other coroutines keep running (a sentinel task ticks).
- **Effort:** M.

## F11 — The enricher embeds two LLM back ends; the legacy one blocks the event loop
- **Where:** `enricher.py:15` (`import anthropic` even when the provider is openai), `:100-104`, `:145-173` (synchronous `anthropic.messages.create` in async code; hand-rolled code-fence JSON stripping), `:267-272` (back end chosen by the string compare `provider == "openai"`, one serial call per article).
- **Category:** structure, duplication with `sentinel/classification/*` provider code.
- **Severity:** MEDIUM (affects the legacy/rollback path; the serial calls also matter in the live path).
- **Proposed refactor:**
  - A `VaguenessGate` protocol built by the same provider factory the classifier uses, so the prompt and schema live in one place (`classification/policy.py` style).
  - Run the Anthropic back end through `asyncio.to_thread`.
  - In the batch path, use `asyncio.gather` with a small semaphore.
- **BP:** yes, apart from concurrency.
- **Test:** with an Anthropic back-end mock that sleeps synchronously, other tasks still progress. Existing enricher tests stay green. Note that those tests use `MagicMock` config, so `provider == "openai"` is False and only the legacy path is exercised. Add fixtures for both providers.
- **Effort:** M.

## F12 — Dead and duplicated processing API
- **Where:**
  - `processing/__init__.py:18-37`: `process_articles` has no callers. It also diverges from the real pipeline (no transaction, no `enqueue_classification`, no diagnostic flag).
  - `deduplicator.py:64-66`: `is_duplicate` is used only by tests.
  - `keyword_filter.py:33-93` and `:118-168`: `matches()` and `diagnose()` each re-implement keyword-set selection, the English fallback and the exclude merge. The `diagnose` docstring promises a `bypass` key, but the non-bypass returns omit it.
- **Category:** dead code, duplication.
- **Severity:** MEDIUM. Two copies of the keyword logic can drift, and the diagnostic HTML would then misreport why an alert was missed.
- **Proposed refactor (BP):**
  - Delete `process_articles`.
  - Add `KeywordFilter.evaluate(article) -> KeywordDecision` (a dataclass with `passed`, `level`, `critical`, `high`, `excluded_by`, `bypass`, `language_matched`). `matches`, `filter_batch` and `diagnose` become thin views of it.
- **Test:** a property test: for random articles from fixtures, `matches(a) is not None == diagnose(a)["passed"]`.
- **Effort:** S.

## F13 — The normalizer unescapes HTML entities before stripping tags, which deletes real text between `<` and `>`
- **Where:** `normalizer.py:76-92`. Also `rss.py:148` and `google_news.py:158` already ran `strip_html`, so HTML is cleaned twice by two different methods. `_LANGUAGE_MAP` (`normalizer.py:23-33`) duplicates `GDELT_LANGUAGE_MAP`. The truncation appends "..." beyond `max_length`.
- **Category:** latent bug, duplication.
- **Severity:** LOW-MEDIUM.
- **What's wrong:** verified that `"Dron spadł &lt;5 km od granicy, &gt;100 osób ewakuowano"` becomes `"Dron spadł 100 osób ewakuowano"`. The location clause is lost before the keyword filter and the classifier.
- **Proposed refactor (behavior change, low):** strip tags with `html.parser` first, then unescape, in one place (the normalizer only; remove the copies in the fetchers). Keep a single language-name map in `sentinel/utils/lang.py`.
- **Test:** the entity case above keeps "od granicy". Existing normalizer tests stay green.
- **Effort:** S.

## F14 — Legacy fuzzy-dedup window is wrong: an ISO `T` string is compared with SQLite `datetime('now')`
- **Where:** `database.py:222-231` (`get_recent_titles`); the same pattern is in `database.py:293` (`get_active_events`, the corroborator's legacy window, which is another auditor's area); `deduplicator.py:38-39` (one DB query per article).
- **Category:** latent bug (rollback path only, because incident memory skips fuzzy dedup at `deduplicator.py:34-35`).
- **Severity:** LOW today. It becomes MEDIUM if incident memory is rolled back.
- **What's wrong:** `'2026-10-16T00:00:01+00:00' > datetime('now','-60 minutes')` is TRUE at 17:52 UTC (verified). `T` sorts after a space, so the "60-minute" lookback really means "since 00:00 UTC of the cutoff date". Combined with Cyrillic titles normalizing to empty (K1), every Cyrillic article dedups against every earlier Cyrillic article of the day.
- **Proposed refactor (behavior change in the rollback path):** pass a cutoff computed in Python, `(now - timedelta).isoformat()`, and compare like with like. Load recent titles once per batch and append accepted ones in memory.
- **Test:** insert an article fetched 3 h ago today; `get_recent_titles(60)` must not return it.
- **Effort:** S.

## F15 — Entries without a link all share `url_hash(sha256(""))`
- **Where:** `rss.py:141`, `google_news.py:141`, `gdelt.py:176` (`link`/`url` default to `""`); `models.py:80`; `deduplicator.py:27`.
- **Category:** latent bug.
- **Severity:** LOW.
- **What's wrong:** the first link-less entry is stored. Every later link-less entry from any source is then dropped as "URL already seen" until retention cleanup.
- **Proposed refactor (behavior change):** reject entries without a link with a warning, or derive the key from `source_name|title|published_at`.
- **Test:** two link-less entries with different titles are both kept, or both rejected with a log line.
- **Effort:** S.

## F16 — No ingestion age gate
- **Where:** `normalizer.py:124-140` caps future timestamps but not old ones. There is no age check anywhere before classification (grep found none). Only Google News has a recency limit (`when:1h`, hardcoded at `google_news.py:41`).
- **Category:** missing guard.
- **Severity:** LOW-MEDIUM.
- **What's wrong:**
  - After a database restore or a fresh database, every feed's backlog is classified as new.
  - After `article_retention_days` (30), any feed item older than that which is still listed is re-ingested.
  - Old critical-sounding items can then ring the phone. The prompt gets `published_at`, but that is a soft defense.
- **Proposed refactor (behavior change):** add `sources.max_article_age_hours` (generous, for example 48). Apply it only when `published_at` was parsed from the source, never when it fell back to `fetched_at`.
- **Test:** an RSS entry dated 10 days ago is dropped with a debug reason. An entry with no date is kept.
- **Effort:** S.

## F17 — Hardcoded values that the project rule says belong in `config/config.yaml`
- **Where:**
  - `google_news.py:14-19` (`LANG_MAP`), `:40-42` (base URL and `when:1h`).
  - `gdelt.py:10` (API URL), `:13-52` (language and FIPS maps), `:109` (`maxrecords 250`).
  - The User-Agent strings (F08).
  - Timeouts 30/10/5 s (`rss.py:76`, `google_news.py:78`, `gdelt.py:119`, `fulltext.py:43`, `enricher.py:212`).
  - `fulltext.py:18` (`MAX_CHARS`).
  - Enrichment thresholds `0.85`, `1.4`, `500`, `50`, `100`, `1000` (`enricher.py:132,139,202-203,224,229-230`).
  - `_SLAVIC_LANGUAGES` (`keyword_filter.py:10`).
  - `VAGUENESS_CHECK_PROMPT` (`enricher.py:24-56`); it is not versioned the way `classification/policy.py` is.
- **Category:** hardcoded values.
- **Severity:** LOW.
- **Proposed refactor (BP):** add config blocks `sources.http.{user_agent, timeout_seconds}`, `sources.google_news.{base_url, recency, locales}`, `sources.gdelt.{api_url, max_records}` and `processing.enrichment.{…}`. Put the code defaults in `config.py` with the current values.
- **Test:** a config round-trip test, plus the existing fetcher tests unchanged.
- **Effort:** S-M.

## F18 — Config models accept unknown keys silently (the cause of the stale GDELT field)
- **Where:** `config.py:18-75`, `:316-323`. These are pydantic `BaseModel` without `extra="forbid"`. TODO 6.1 item 1 is the symptom.
- **Category:** weak typing.
- **Severity:** LOW.
- **Proposed refactor (behavior change at load):** set `model_config = ConfigDict(extra="forbid")` on the source and processing models. Remove `update_interval_minutes` first.
- **9–10 risk:** a key typo would stop startup. Add a test that loads the tracked `config/config.yaml` (with `${VAR}` placeholders stubbed), so the `/deploy` pre-flight test step catches it before deploy.
- **Test:** `SentinelConfig(**yaml_with_typo)` raises. The tracked config loads.
- **Effort:** S.

## F19 — The outlet-suffix regex runs on lowercased text, so it is mostly a no-op and sometimes strips real words
- **Where:** `enricher.py:58-62`, `:118-125`.
- **Category:** latent bug.
- **Severity:** LOW. It only decides which articles get a body fetch.
- **What's wrong:** the regex expects an uppercase or accented first letter (`[A-ZÀ-Ž]`) but runs after `.lower()`. Verified results:
  - `"alarm w kraju nato - radio zet"` stays unchanged, because ASCII outlet names are never stripped.
  - The range `À-Ž` contains lowercase `ł ą ś…`, so `"drony nad polską - łódzkie wiadomości"` loses its suffix, and `"… nad łotwą"` loses `"łotwą"`.
  - The heuristic works anyway, through the containment and ratio checks.
- **Proposed refactor (behavior change, minor):** apply a case-sensitive, separator-required pattern (`\s[-–—|]\s+\S.*$`) to the original text before lowercasing, and drop the second alternative.
- **Test:** add cases for an ASCII outlet suffix and for a trailing Polish word beginning with `ł`.
- **Effort:** S.

## F20 — Weak typing at the ingestion boundary
- **Where:**
  - `rss.py:51,59,138` (`source`, `entry` untyped).
  - `telegram.py:89` (`channel_map: dict`).
  - `keyword_filter.py:33` (`-> dict | None`), `:118` (`-> dict`).
  - `gdelt.py:81` (`c["code"]` on `target_countries: list[dict]`, `config.py:83`).
  - `raw_metadata["enrichment"]` and `["keyword_match"]` are free-form dicts that the dashboard reads (`tests/test_dashboard_api.py:473-520`).
- **Category:** weak typing.
- **Severity:** LOW.
- **Proposed refactor (BP):** add `TargetCountry` and `AggressorCountry` pydantic models, `KeywordDecision` (F12), and `EnrichmentInfo` (a TypedDict with a fixed `method` Literal). Annotate `RSSSource`, `GoogleNewsQuery` and `TelegramChannel` parameters.
- **Test:** mypy or pyright on `sentinel/fetchers sentinel/processing`, with no new runtime tests.
- **Effort:** S.

## K1 — Known: "Cyrillic titles normalize to empty"
- **Location:** `sentinel/models.py:11-15`. The TODO is accurate.
- **Proposed fix (behavior change):** `re.sub(r"[^\w\s]", "", stripped, flags=re.UNICODE)`. NFKD combined with dropping combining marks maps й→и and ё→е, which is fine for fuzzy matching.
- **Impact:** it touches `title_normalized` (stored in the DB) and therefore corroborator syndication (`corroborator.py:322`) and the legacy dedup.
- **Test:**
  - `_normalize_title("Атака дронів на Львів") != ""`.
  - Two different Cyrillic headlines score below `syndication_similarity_threshold`.
- **Order:** do it together with F05/F06 as the prerequisites for the two-source option.

---

## Test gaps on critical paths (summary)
1. No test loads the tracked `config/config.yaml` keyword lists. F01 is invisible to the suite.
2. `test_telegram.py::test_message_to_article` passes only through the mislabel fallback (F05). There is no multi-channel test.
3. There are no tests for fetcher health accounting, the 10-failure notice, or `fetcher_status` (F02).
4. The enricher tests use `MagicMock` config, so the live OpenAI gate is only covered by a happy-path test (`test_direct_openai.py:288`). No test checks a gate failure (F04) or Telegram skipping (F03).
5. No test checks that the Google News decoder, or any fetch, cannot stall the loop (F07, F10).
6. No test covers the `get_recent_titles` time window (F14).

## Overall health
- The ingestion code is small and readable, and it has unit tests. The main problems are matching semantics and error handling, not file size.
- The keyword filter's substring rules drop real Polish military news today.
- The enricher can corrupt or delay Telegram and critical articles.
- Fetcher failures are invisible because every fetcher swallows its errors.
- The structural refactors (F08–F12, F17, F20) are low-risk and behavior-preserving. They should follow the safety fixes, not precede them.

## Proposed phase grouping (ingestion area)

| Phase | Content | Behavior | Gate |
|---|---|---|---|
| **P1 — Safety fixes (small, owner-approved)** | F03 (skip Telegram enrichment), F04 (enrichment fail-open), F05 (Telegram peer-id map + test rewrite), TODO 7.7 + F10 deadline part (decoder off the loop, in both the enricher and fulltext) | changes | unit tests above; no prompt change, so no eval needed |
| **P2 — Keyword matching** | F01 (match modes, exclude whole-word, `GRU` acronym, config lint test), F12 (single `evaluate()`; do it first so the change lands in one place) | changes | config lint test + a PL headline fixture; the owner reviews the exclude and keyword list diff; watch classification volume and cost for a week (`docs/reference/costs.md`) |
| **P3 — Observability and latency** | F02 (`FetchResult`, per-source health, Telegram connected check, push notice), F07 (concurrent fetchers with deadlines), F09 (interface: lanes, `start`/`stop`, no name checks) | mostly preserving; F02 adds notices | scheduler tests with fake fetchers |
| **P4 — Structural cleanup (behavior-preserving)** | F08 (shared http/feeds helpers), F10 rest (one `article_page` module), F11 (vagueness gate provider), F17 (config extraction), F20 (typing), F18 (`extra="forbid"` + tracked-config load test) | preserving (F18 changes load) | the full suite stays green |
| **P5 — Corroboration prerequisites (only if the owner picks 2 sources)** | K1 (Cyrillic normalization), F06 (GN publisher identity), the `t.me/<channel>` identity from F05 | changes `source_count` | corroborator tests; the owner's decision in TODO §0 |
| **P6 — Low / rollback path** | F13, F14 (and the same pattern in `get_active_events`), F15, F16, F19 | changes, low | unit tests |
