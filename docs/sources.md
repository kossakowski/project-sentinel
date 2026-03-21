# Media Sources Reference

Comprehensive list of all data sources Sentinel can monitor, organized by type and priority. Based on analysis of the September 2025 Russian drone incursion into Poland and general military intelligence monitoring best practices.

## Source Speed Tiers

Based on the September 9-10, 2025 drone incursion case study:

| Tier | Speed | Sources |
|---|---|---|
| **1** | Seconds to minutes | Ukrainian military Telegram, OSINT X accounts, flight trackers |
| **2** | 2-15 minutes | Wire services (Reuters, AP, PAP), NEXTA |
| **3** | 15-60 minutes | GDELT, 24h news portals (TVN24, RMF24), defense outlets |
| **4** | 1-6 hours | TV special editions, official military statements |
| **5** | 6+ hours | Government citizen alerts (RCB) |

Sentinel targets **Tiers 2-3** for automated monitoring, with **Tier 1** via Telegram.

---

## Polish Media

### Wire Service

| Source | URL | RSS Feed | Language | Priority | Notes |
|---|---|---|---|---|---|
| **PAP** (Polish Press Agency) | pap.pl | `pap.pl/rss.xml` | PL | 1 | National wire service. First with official Polish govt statements. |

### 24-Hour News

| Source | URL | RSS Feed | Language | Priority | Notes |
|---|---|---|---|---|---|
| **TVN24** | tvn24.pl | `tvn24.pl/najnowsze.xml` | PL | 1 | Leading 24h news channel (Warner Bros. Discovery) |
| **RMF24** | rmf24.pl | `rmf24.pl/feed` | PL | 1 | Online portal of Poland's most popular radio station |
| **Polsat News** | polsatnews.pl | `polsatnews.pl/rss/wszystkie.xml` | PL | 2 | Major 24h TV news |
| **TVP Info** | tvp.info | -- | PL | 3 | Public broadcaster (no reliable RSS) |

### Defense Specialist

| Source | URL | RSS Feed | Language | Priority | Notes |
|---|---|---|---|---|---|
| **Defence24** | defence24.pl | `defence24.pl/_rss` | PL | 1 | Poland's leading defense portal |
| **Defence24 EN** | defence24.com | `defence24.com/_rss` | EN | 2 | English edition |

### Major Portals / Newspapers

| Source | URL | RSS Feed | Language | Priority | Notes |
|---|---|---|---|---|---|
| **Rzeczpospolita** | rp.pl | `rp.pl/rss_main` | PL | 2 | Major daily, strong on security |
| **Gazeta Wyborcza** | wyborcza.pl | `wyborcza.pl/pub/rss/najnowsze` | PL | 2 | Major daily |
| **Onet** | onet.pl | `wiadomosci.onet.pl/rss` | PL | 3 | Major portal |

---

## Baltic Media

| Source | URL | RSS Feed | Language | Priority | Country | Notes |
|---|---|---|---|---|---|---|
| **ERR News** | news.err.ee | `news.err.ee/rss` | EN | 2 | Estonia | Estonian public broadcaster |
| **LRT** | lrt.lt/en | `lrt.lt/en/news-in-english?rss` | EN | 2 | Lithuania | Lithuanian public broadcaster |
| **LSM** | eng.lsm.lv | `eng.lsm.lv/rss/` | EN | 2 | Latvia | Latvian public broadcaster |
| **Delfi** | en.delfi.lt | -- | EN | 3 | LT/LV/EE | Largest commercial Baltic portal |
| **BNS** | bns.lt | -- (paid only) | EN | 1 | LT/LV/EE | Baltic wire service (subscription required) |

---

## International Wire Services

| Source | URL | RSS/API | Language | Priority | Notes |
|---|---|---|---|---|---|
| **Reuters** | reuters.com | No free RSS/API | EN | 1 | Fastest international wire. Monitor via Google News or X. |
| **AP** | apnews.com | Developer API (key required) | EN | 1 | Major global wire service |
| **AFP** | afp.com | No free RSS/API | EN/FR | 2 | Strong European bureau network |

---

## International News

| Source | URL | RSS Feed | Language | Priority | Notes |
|---|---|---|---|---|---|
| **BBC World** | bbc.com/news/world | `feeds.bbci.co.uk/news/world/rss.xml` | EN | 3 | Comprehensive global coverage |
| **Al Jazeera** | aljazeera.com | `aljazeera.com/xml/rss/all.xml` | EN | 3 | Strong conflict coverage |
| **CNN** | cnn.com | `rss.cnn.com/rss/edition_world.rss` | EN | 3 | Fast on major events |
| **Sky News** | news.sky.com | `feeds.skynews.com/feeds/rss/world.xml` | EN | 3 | Fast on European events |

---

## Russian Media (Counter-Indicator Monitoring)

Monitored for adversary narrative signals, NOT for factual reporting.

| Source | URL | RSS Feed | Language | Priority | Notes |
|---|---|---|---|---|---|
| **TASS** | tass.com | `tass.com/rss/v2.xml` | EN | 3 | Russian state news agency. Watch for "provocation" framing. |
| **Interfax** | interfax.com | `interfax.ru/rss.asp` | RU | 3 | Semi-independent Russian wire. Sometimes faster than TASS. |

**Why monitor Russian media:** Before the 2022 Ukraine invasion, Russian state media published justification narratives. A sudden TASS/RIA article framing Poland/Baltics as "provocateurs" or describing a "need to protect Russian speakers" is a potential leading indicator.

---

## Automated Data Sources

### GDELT (Global Database of Events, Language, and Tone)

| Field | Value |
|---|---|
| URL | gdeltproject.org |
| API | `api.gdeltproject.org/api/v2/doc/doc` |
| Cost | Free |
| Update frequency | Every 15 minutes |
| Coverage | 100+ languages, global |
| API key required | No |

**Key features for Sentinel:**
- Theme filtering: `ARMEDCONFLICT`, `WB_2462_POLITICAL_VIOLENCE_AND_WAR`
- CAMEO event codes: 18 (Assault), 19 (Fight), 20 (Mass Violence)
- Goldstein scale: -10 (max conflict) to +10 (max cooperation)
- Translingual: search in English, matches across 65 languages

### Google News RSS

| Field | Value |
|---|---|
| URL | `news.google.com/rss/search?q=QUERY` |
| Cost | Free |
| Update frequency | Near real-time |
| API key required | No |

**URL format:**
```
https://news.google.com/rss/search?q={query}+when:1h&hl={lang}&gl={country}&ceid={country}:{lang}
```

Language/country codes: `en/US`, `pl/PL`, `uk/UA`, `ru/RU`

---

## Social Media / OSINT

### Telegram Channels

| Channel | Username | Language | Priority | Notes |
|---|---|---|---|---|
| Ukrainian Air Force | `@ps_ukr` | UK | 1 | Fastest source for cross-border drone events (broke the Sep 2025 story 1h before anyone else) |
| NEXTA Live | `@nexta_live` | EN/RU | 1 | Belarusian opposition media, very fast on military events |
| Rybar | `@rybar_force` | RU | 2 | Russian mil-blogger, detailed maps, cited by Western analysts |
| DeepState | (varies) | UK | 2 | Ukrainian front-line mapping |

**Note:** Telegram channel usernames can change. Verify before configuring.

### X/Twitter OSINT Accounts (for reference, not directly monitored)

| Account | Focus |
|---|---|
| @sentdefender | Europe-focused conflict monitoring |
| @OSINTtechnical | Military OSINT, equipment tracking |
| @IntelCrab | Real-time conflict intelligence |
| @RALee85 | Russian military analysis |
| @GeoConfirmed | Geolocation verification |
| @Bellingcat | Investigation-grade OSINT |

**Note:** X/Twitter API is too expensive ($42K+/year for streaming) for this project. These accounts are listed for manual reference. Key OSINT accounts often post to Telegram simultaneously.

### Official Military/Government X Accounts

| Account | Entity |
|---|---|
| @Poland_MOD | Polish Ministry of National Defence (English) |
| @MON_GOV_PL | Polish MOD (Polish) |
| @dowopersz | Polish Military Operational Command |
| @MoD_Estonia | Estonian Ministry of Defence |
| @Lithuanian_MoD | Lithuanian Ministry of National Defence |
| @AizsardzibasMin | Latvian Ministry of Defence |
| @NATO | NATO |

---

## Sources NOT Included (and Why)

| Source | Reason |
|---|---|
| **Flightradar24 API** | $9/month, indirect signal (no direct conflict reporting), would require custom anomaly detection |
| **MarineTraffic API** | Similar -- indirect signal, complex to interpret |
| **ACLED** | Updated weekly, too slow for real-time alerting |
| **Twitter/X API** | $42K+/year for streaming access, prohibitively expensive |
| **Janes** | Enterprise subscription ($$$), not real-time breaking news |
| **ICEWS** | Government/military access only |
| **Reddit** | Optional; slow compared to other sources; adds noise |

These can be added later if needed. The current source set provides sufficient coverage at minimal cost.

---

## Adding New Sources

To add a new RSS source:
1. Find the RSS feed URL
2. Add an entry to `config/config.yaml` under `sources.rss`
3. Restart Sentinel

To add a new Telegram channel:
1. Find the channel username
2. Add to `config/config.yaml` under `sources.telegram.channels`
3. Restart Sentinel

No code changes needed -- all sources are config-driven.
