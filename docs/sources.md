# Media Sources Reference

Derived from `config/config.yaml`. Do not add sources not present in config — this doc tracks config state, not aspirations.

---

## RSS Sources

Fast lane (every 3 min): priority 1 only. Slow lane (every 15 min): all priorities.

| Name | URL | Lang | Priority | keyword_bypass | Notes |
|---|---|---|---|---|---|
| PAP | `https://www.pap.pl/rss.xml` | pl | 1 | — | **DISABLED.** Blocked by Incapsula/Imperva WAF. Covered via Google News `site:pap.pl` query. |
| TVN24 | `https://tvn24.pl/najnowsze.xml` | pl | 1 | — | Intermittent 403 errors in production. |
| RMF24 | `https://www.rmf24.pl/feed` | pl | 1 | — | |
| Defence24 | `https://defence24.pl/_rss` | pl | 1 | **true** | Poland's leading defense portal. |
| Ukrainska Pravda EN | `https://www.pravda.com.ua/eng/rss/view_news/` | en | 1 | — | |
| Ukrainska Pravda UA | `https://www.pravda.com.ua/rss/view_news/` | uk | 1 | — | |
| Kyiv Independent | `https://kyivindependent.com/feed/rss/` | en | 1 | — | |
| Defence24 EN | `https://defence24.com/_rss` | en | 2 | **true** | English edition of Defence24. |
| Polsat News | `https://www.polsatnews.pl/rss/wszystkie.xml` | pl | 2 | — | |
| Rzeczpospolita | `https://www.rp.pl/rss_main` | pl | 2 | — | |
| Gazeta Wyborcza | `https://rss.gazeta.pl/pub/rss/najnowsze_wyborcza.xml` | pl | 2 | — | |
| Onet Wiadomości | `https://wiadomosci.onet.pl/.feed` | pl | 2 | — | |
| ERR Estonia | `https://news.err.ee/rss` | en | 2 | — | Estonian public broadcaster. |
| LRT Lithuania | `https://www.lrt.lt/en/news-in-english?rss` | en | 2 | — | Lithuanian public broadcaster. |
| LSM Latvia | `https://eng.lsm.lv/rss/` | en | 2 | — | Latvian public broadcaster. |
| Interfax-Ukraine EN | `https://en.interfax.com.ua/news/last.rss` | en | 2 | — | |
| BBC World | `https://feeds.bbci.co.uk/news/world/rss.xml` | en | 3 | — | |
| Al Jazeera | `https://www.aljazeera.com/xml/rss/all.xml` | en | 3 | — | |
| France 24 Europe | `https://www.france24.com/en/europe/rss` | en | 3 | — | |
| TASS | `https://tass.com/rss/v2.xml` | en | 3 | — | Russian state agency. Monitored for adversary narrative signals, not factual reporting. |

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

## GDELT

Config key: `sources.gdelt`. Slow lane only (every 15 min).

- **API:** `https://api.gdeltproject.org/api/v2/doc/doc` — free, no API key required.
- **Themes:** `ARMEDCONFLICT`, `WB_2462_POLITICAL_VIOLENCE_AND_WAR`, `CRISISLEX_C03_WELLBEING_HEALTH`, `TAX_FNCACT_MILITARY`.
- **CAMEO event codes:** 18, 19, 190, 191, 192, 193, 194, 195, 20.
- **Goldstein threshold:** −7.0 (only articles at or below this conflict score are processed). No article summaries — headlines and metadata only.

---

## keyword_bypass Behavior

By default, all articles must match at least one keyword from `monitoring.keywords` (EN/PL/UK/RU lists) before being sent to AI classification — a cost-control gate. Sources with `keyword_bypass: true` skip this filter entirely; every article goes straight to the classifier regardless of content. Applied to sources that are inherently defense-focused (Defence24 PL/EN) or are trusted military channels where any post may be operationally relevant (all four Telegram channels).

---

## Known Issues

| Source | Issue | Workaround |
|---|---|---|
| PAP | Blocked by Incapsula/Imperva WAF since ~2026. All non-browser HTTP requests rejected. | `site:pap.pl` Google News query — indexes PAP articles without hitting the WAF. |
| TVN24 | Intermittent 403 errors in production. | Monitor logs if coverage seems low. No automated fallback. |
