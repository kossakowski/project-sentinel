# Media Sources Reference

> **Source of truth: `config/config.yaml`** (the live, running config). `config/config.example.yaml` is only a documented template. Update this doc when `config/config.yaml` changes.

Derived from `config/config.yaml`. Do not add sources not present in config — this doc tracks config state, not aspirations.

---

## RSS Sources

Fast lane (every 3 min): priority 1 only. Slow lane (every 15 min): all priorities.

| Name | URL | Lang | Priority | Enabled | keyword_bypass | Notes |
|---|---|---|---|---|---|---|
| PAP | `https://www.pap.pl/rss.xml` | pl | 1 | **false** | — | Blocked by Incapsula/Imperva WAF. Covered via Google News `site:pap.pl` query. |
| TVN24 | `https://tvn24.pl/najnowsze.xml` | pl | 1 | **false** | — | Disabled 2026-05-27. Cloudflare blocks Hetzner datacenter IPs (403 Forbidden) regardless of User-Agent. Polish news covered by Onet, RMF24, Gazeta Wyborcza, Polsat News, PAP via Google News. Re-evaluate if we move to a residential IP or add proxy support. |
| RMF24 | `https://www.rmf24.pl/feed` | pl | 1 | true | — | |
| Defence24 | `https://defence24.pl/_rss` | pl | 1 | true | **true** | Poland's leading defense portal. |
| Polsat News | `https://www.polsatnews.pl/rss/wszystkie.xml` | pl | 2 | true | — | |
| Rzeczpospolita | `https://www.rp.pl/rss_main` | pl | 2 | true | — | |
| Gazeta Wyborcza | `https://rss.gazeta.pl/pub/rss/najnowsze_wyborcza.xml` | pl | 2 | true | — | |
| ERR Estonia | `https://news.err.ee/rss` | en | 2 | true | — | Estonian public broadcaster. |
| LRT Lithuania | `https://www.lrt.lt/en/news-in-english?rss` | en | 2 | true | — | Lithuanian public broadcaster. |
| LSM Latvia | `https://eng.lsm.lv/rss/?lang=en&catid=318` | en | 2 | true | — | Latvian public broadcaster. URL corrected 2026-05-27 to proper English news feed endpoint. |
| BBC World | `https://feeds.bbci.co.uk/news/world/rss.xml` | en | 3 | true | — | |
| Al Jazeera | `https://www.aljazeera.com/xml/rss/all.xml` | en | 3 | true | — | |
| Defence24 EN | `https://defence24.com/_rss` | en | 2 | true | **true** | English edition of Defence24. |
| TASS | `https://tass.com/rss/v2.xml` | en | 3 | true | — | Russian state agency. Monitored for adversary narrative signals, not factual reporting. |
| Ukrainska Pravda UA | `https://www.pravda.com.ua/rss/view_news/` | uk | 1 | true | — | Ukrainian-language edition; publishes before EN edition. |
| Onet Wiadomości | `https://wiadomosci.onet.pl/.feed` | pl | 2 | true | — | |
| Interfax-Ukraine EN | `https://en.interfax.com.ua/news/last.rss` | en | 2 | true | — | |

---

## Telegram Channels

Polled on fast lane (every 3 min). Config key: `sources.telegram.channels`. All four channels have `keyword_bypass: true`.

| Name | channel_id | Lang | Priority | keyword_bypass |
|---|---|---|---|---|
| Ukrainian Air Force | `@kpszsu` | uk | 1 | **true** |
| General Staff of Ukraine | `@GeneralStaffZSU` | uk | 1 | **true** |
| NEXTA Live | `@nexta_live` | ru | 1 | **true** |
| DeepState UA | `@DeepStateUA` | uk | 2 | **true** |

---

## Google News

Polled on fast lane (every 3 min). Config key: `sources.google_news.queries`. All 16 queries use `when:1h` recency filter.

| Query | Lang | Lane |
|---|---|---|
| `military attack Poland` | en | fast |
| `invasion Baltic states` | en | fast |
| `Russia attack NATO` | en | fast |
| `NATO Article 5` | en | fast |
| `drone incursion Poland` | en | fast |
| `airspace violation Poland` | en | fast |
| `scrambled jets Poland` | en | fast |
| `atak wojskowy Polska` | pl | fast |
| `inwazja Polska` | pl | fast |
| `Rosja atak` | pl | fast |
| `rosyjskie drony Polska` | pl | fast |
| `naruszenie przestrzeni powietrznej` | pl | fast |
| `zamknięcie lotniska Polska` | pl | fast |
| `site:pap.pl` | pl | fast |
| `військовий напад Польща` | uk | fast |
| `дрони Польща` | uk | fast |

---

## GDELT — **DISABLED in production**

Config key: `sources.gdelt`. Slow lane only (every 15 min), **and only when `enabled: true`** — which it is **not** in the live config (`enabled: false`). The fetcher is instantiated only when enabled, so GDELT contributes nothing today.

**Why disabled:** IP-level 429 throttling from the Hetzner datacenter IP drove the success rate to ~20%, so it was switched off rather than burn slow-lane time on failures.

When enabled, the fetcher (`sentinel/fetchers/gdelt.py`) issues a single GDELT DOC 2.0 `ArtList` query built from only these parameters:

- **API:** `https://api.gdeltproject.org/api/v2/doc/doc` — free, no API key required.
- **Themes** (`sources.gdelt.themes`): `ARMEDCONFLICT`, `WB_2462_POLITICAL_VIOLENCE_AND_WAR`, `CRISISLEX_C03_WELLBEING_HEALTH`, `TAX_FNCACT_MILITARY`. OR-combined as `theme:...`.
- **Country filter:** `sourcecountry:` for each target country (PL, LT→`LH`, LV→`LG`, EE→`EN`, FIPS-mapped), OR-combined.
- **Window:** `TIMESPAN={lookback_minutes}min` — the config field is `lookback_minutes` (default `60`; the live config's stale `update_interval_minutes: 15` is a no-op for a non-existent field and is silently ignored). The API rejects spans below ~30 min with a `200 OK` + plain-text body `"Timespan is too short."`.
- **Other params:** `mode=ArtList`, `maxrecords=250`, `format=json`, `sort=DateDesc`. Articles arrive as headline + metadata only (no body summaries).

> There is **no CAMEO event-code filter and no Goldstein conflict-score threshold** — the fetcher sends only the theme + country + timespan parameters above. (Earlier versions of this doc claimed "CAMEO codes 18/19/…/20" and a "Goldstein −7.0" threshold; both were fabricated and have been removed.)

---

## Known Issues

| Source | Issue | Workaround |
|---|---|---|
| PAP | Blocked by Incapsula/Imperva WAF since ~2026. All non-browser HTTP requests rejected. | `site:pap.pl` Google News query — indexes PAP articles without hitting the WAF. |
| TVN24 | Cloudflare blocks Hetzner datacenter IPs (403 Forbidden). Not User-Agent related — tested with browser UA, still blocked. Disabled 2026-05-27 to stop spamming their servers. | Polish news well-covered by 5 other sources. Re-enable if we add proxy support or move to a residential IP. |
| GDELT | IP-level 429 throttling (~20% success) from the Hetzner datacenter IP. | Disabled (`sources.gdelt.enabled: false`). Re-enable behind a residential IP / proxy. |

---

## See also

- [Config Reference](config-reference.md) — the `sources.*` keys (`rss`, `gdelt`, `google_news`, `telegram`) in detail.
- [Architecture](../explanation/architecture.md) — how fetchers, the dual-lane scheduler, and corroboration fit together.
