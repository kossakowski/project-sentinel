"""
Test harness for the vagueness pre-check prompt.
Runs against 25+ real production articles and 25+ synthetic hard cases.
"""

import json
import os
import anthropic

client = anthropic.Anthropic()
MODEL = "claude-haiku-4-5-20251001"

VAGUENESS_CHECK_PROMPT = """\
You are an input quality gate for a military threat classifier. Your job is to determine \
whether a news article's title and summary provide SUFFICIENT FACTUAL INFORMATION for a \
classifier to make a reliable threat assessment.

An article has SUFFICIENT information if it answers BOTH:
1. WHAT happened? (a specific event: strike, drone incursion, explosion, military movement — not just "alarm" or "tensions")
2. WHERE did it happen? (a specific country or city — not just "NATO country", "the region", or "near the border")

Flag as INSUFFICIENT if ANY of these apply:
- The summary adds no information beyond the title (duplicate or near-duplicate)
- The title uses vague geographic references ("NATO country", "a country", "the border region") instead of naming the specific country
- The title is primarily emotional/clickbait ("Horror!", "Truth revealed", "Shocking", "Sad words") rather than factual
- The title describes REACTIONS (resignation, political fallout, analysis) but is phrased to sound like an active threat
- The title is clearly a debunking or explainer ("truth came out", "what really happened", "fact check") but contains alarming keywords
- The summary is just the title with an outlet name appended

Flag as SUFFICIENT if:
- The title names a specific country AND describes a specific event, even if the summary is poor
- The title + summary together provide enough context to determine what happened and where
- The article is clearly about a non-threatening topic (diplomacy, economics, historical) regardless of keywords

Respond with JSON only:
{"needs_enrichment": true/false, "reason": "one sentence"}
"""

REAL_ARTICLES = [
    # --- GOOGLE NEWS: VAGUE/CLICKBAIT (should flag) ---
    {
        "id": "real_01",
        "title": "Zawalone budynki, ludzie pod gruzami. Wśród rannych dzieci, dramatyczny atak Rosji - NewMedia24",
        "summary": "Zawalone budynki, ludzie pod gruzami. Wśród rannych dzieci, dramatyczny atak Rosji NewMedia24",
        "source_type": "google_news",
        "source_name": "GoogleNews:atak wojskowy Polska",
        "language": "pl",
        "expected": True,
        "why": "Emotional clickbait, no country specified, summary=title. Actually about Ukraine."
    },
    {
        "id": "real_02",
        "title": "Alarm w kraju NATO, rosyjski dron zniszczył budynek. Wszystkie służby w akcji - NewMedia24",
        "summary": "Alarm w kraju NATO, rosyjski dron zniszczył budynek. Wszystkie służby w akcji NewMedia24",
        "source_type": "google_news",
        "source_name": "GoogleNews:Rosja atak",
        "language": "pl",
        "expected": True,
        "why": "'kraj NATO' — deliberately vague about which country. summary=title."
    },
    {
        "id": "real_03",
        "title": "Alarm w państwie NATO. Dron naruszył przestrzeń powietrzną. „Znajdźcie ochronę\" - Radio Zet",
        "summary": "Alarm w państwie NATO. Dron naruszył przestrzeń powietrzną. „Znajdźcie ochronę\" Radio Zet",
        "source_type": "google_news",
        "source_name": "GoogleNews:rosyjskie drony Polska",
        "language": "pl",
        "expected": True,
        "why": "'państwo NATO' — vague country. summary=title."
    },
    {
        "id": "real_04",
        "title": "\"Shahedy\" nad wschodnią Polską. Prawda wyszła na jaw - WP Tech",
        "summary": "\"Shahedy\" nad wschodnią Polską. Prawda wyszła na jaw WP Tech",
        "source_type": "google_news",
        "source_name": "GoogleNews:rosyjskie drony Polska",
        "language": "pl",
        "expected": True,
        "why": "Debunking article ('prawda wyszła na jaw'). summary=title."
    },
    {
        "id": "real_05",
        "title": "Dron wleciał w przestrzeń powietrzną Łotwy. Armia alarmuje - Wiadomości Onet",
        "summary": "Dron wleciał w przestrzeń powietrzną Łotwy. Armia alarmuje Wiadomości Onet",
        "source_type": "google_news",
        "source_name": "GoogleNews:rosyjskie drony Polska",
        "language": "pl",
        "expected": True,
        "why": "Names Latvia but summary=title, no details on what happened beyond 'army alarmed'."
    },
    {
        "id": "real_06",
        "title": "Niepokój w Łotwie po incydencie z dronami. Premierka o kolejnych ruchach - Wiadomości Onet",
        "summary": "Niepokój w Łotwie po incydencie z dronami. Premierka o kolejnych ruchach Wiadomości Onet",
        "source_type": "google_news",
        "source_name": "GoogleNews:rosyjskie drony Polska",
        "language": "pl",
        "expected": True,
        "why": "Political aftermath framed as ongoing concern. summary=title."
    },
    {
        "id": "real_07",
        "title": "DRONE ALERT IN VILNIUS Lithuania Fears Provocations and \"False Flag\" Attacks That Could Pull the Baltic States Into a Crisis - The Baltic Sentinel",
        "summary": "DRONE ALERT IN VILNIUS Lithuania Fears Provocations and \"False Flag\" Attacks That Could Pull the Baltic States Into a Crisis The Baltic Sentinel",
        "source_type": "google_news",
        "source_name": "GoogleNews:Russia attack NATO",
        "language": "en",
        "expected": True,
        "why": "Analysis/speculation ('fears', 'could pull'), not reporting a specific event. summary=title."
    },
    {
        "id": "real_08",
        "title": "Russian Military Accuses Ukraine of Launching Drone Attacks From Latvian Airspace - The Moscow Times",
        "summary": "Russian Military Accuses Ukraine of Launching Drone Attacks From Latvian Airspace The Moscow Times",
        "source_type": "google_news",
        "source_name": "GoogleNews:Russia attack NATO",
        "language": "en",
        "expected": True,
        "why": "Russian accusation/propaganda, not a confirmed event. summary=title."
    },
    {
        "id": "real_09",
        "title": "Alarm na Litwie. Zawieszono loty w stolicy. Władze w schronach - Polska Agencja Prasowa SA",
        "summary": "Alarm na Litwie. Zawieszono loty w stolicy. Władze w schronach Polska Agencja Prasowa SA",
        "source_type": "google_news",
        "source_name": "GoogleNews:site:pap.pl",
        "language": "pl",
        "expected": True,
        "why": "Names Lithuania, describes specific actions — BUT summary=title, no detail on what caused the alarm."
    },
    {
        "id": "real_10",
        "title": "Wilno zamknęło lotnisko po alarmie dronowym. Władze zeszły do schronów - geopolityka.org",
        "summary": "Wilno zamknęło lotnisko po alarmie dronowym. Władze zeszły do schronów geopolityka.org",
        "source_type": "google_news",
        "source_name": "GoogleNews:naruszenie przestrzeni powietrznej",
        "language": "pl",
        "expected": True,
        "why": "Names Vilnius, specific actions — but summary=title, no detail on the drone itself."
    },

    # --- GOOGLE NEWS: CLEAR/FACTUAL (but still summary=title — borderline) ---
    {
        "id": "real_11",
        "title": "Two drones from Russia crash in Latvia, army says - The Straits Times",
        "summary": "Two drones from Russia crash in Latvia, army says The Straits Times",
        "source_type": "google_news",
        "source_name": "GoogleNews:Russia attack NATO",
        "language": "en",
        "expected": True,
        "why": "Specific country + event BUT summary=title, no additional detail on location/damage/type."
    },
    {
        "id": "real_12",
        "title": "A Romanian plane shot down a drone that entered the airspace of Estonia - Informat.ro",
        "summary": "A Romanian plane shot down a drone that entered the airspace of Estonia Informat.ro",
        "source_type": "google_news",
        "source_name": "GoogleNews:Russia attack NATO",
        "language": "en",
        "expected": True,
        "why": "Specific event but summary=title — unknown drone origin, no detail on type/intent."
    },
    {
        "id": "real_13",
        "title": "Latvian government collapses after Ukrainian drones possibly controlled by AI strike oil facility - The Globe and Mail",
        "summary": "Latvian government collapses after Ukrainian drones possibly controlled by AI strike oil facility The Globe and Mail",
        "source_type": "google_news",
        "source_name": "GoogleNews:Russia attack NATO",
        "language": "en",
        "expected": True,
        "why": "Political aftermath headline. Complex: govt collapse + drone + AI. summary=title."
    },
    {
        "id": "real_14",
        "title": "Dron spadł na terytorium Litwy. Policja: zawierał ładunek wybuchowy - Polska Agencja Prasowa SA",
        "summary": "Dron spadł na terytorium Litwy. Policja: zawierał ładunek wybuchowy Polska Agencja Prasowa SA",
        "source_type": "google_news",
        "source_name": "GoogleNews:site:pap.pl",
        "language": "pl",
        "expected": True,
        "why": "Names Lithuania, specific detail (explosives) — but summary=title."
    },

    # --- GOOGLE NEWS: LOW URGENCY (correctly handled, should NOT need enrichment) ---
    {
        "id": "real_15",
        "title": "Największy atak na Ukrainę od miesięcy: 430 dronów i 68 rakiet. Obrona zestrzeliła 58 celów - 112.ua",
        "summary": "Największy atak na Ukrainę od miesięcy: 430 dronów i 68 rakiet. Obrona zestrzeliła 58 celów 112.ua",
        "source_type": "google_news",
        "source_name": "GoogleNews:Rosja atak",
        "language": "pl",
        "expected": False,
        "why": "Specific country (Ukraine), specific event (430 drones, 68 missiles). Title is self-sufficient."
    },
    {
        "id": "real_16",
        "title": "Reports Say Russia Is Sending Drone Components to Iran - HOKANEWS.COM",
        "summary": "Reports Say Russia Is Sending Drone Components to Iran HOKANEWS.COM",
        "source_type": "google_news",
        "source_name": "GoogleNews:Russia attack NATO",
        "language": "en",
        "expected": False,
        "why": "Clear geopolitical report, not a threat to monitored countries."
    },
    {
        "id": "real_17",
        "title": "Ataki dronów paraliżują 40% eksportu ropy Rosji: straty Kremla - 112.ua",
        "summary": "Ataki dronów paraliżują 40% eksportu ropy Rosji: straty Kremla 112.ua",
        "source_type": "google_news",
        "source_name": "GoogleNews:Rosja atak",
        "language": "pl",
        "expected": False,
        "why": "About attacks on Russia's oil exports. Clear what and where."
    },
    {
        "id": "real_18",
        "title": "Перший транш з 90 млрд від ЄС піде на дрони: названо терміни виплати - kontrakty.ua.",
        "summary": "Перший транш з 90 млрд від ЄС піде на дрони: названо терміни виплати kontrakty.ua.",
        "source_type": "google_news",
        "source_name": "GoogleNews:дрони Польща",
        "language": "uk",
        "expected": False,
        "why": "EU funding for drones. Economic/policy, not a military event."
    },

    # --- RSS: GOOD SUMMARIES (should NOT flag) ---
    {
        "id": "real_19",
        "title": "Alarm w Wilnie. Zamknięte zostało lotnisko, władze ewakuowane do schronów",
        "summary": "W Wilnie został ogłoszony alarm z powodu zagrożenia z powietrza. Nie kursuje transport publiczny, zamknięte jest lotnisko — informuje AFP. Mieszkańców stolicy Litwy wezwano do schronienia się w bezpiecznych miejscach.",
        "source_type": "rss",
        "source_name": "Onet Wiadomości",
        "language": "pl",
        "expected": False,
        "why": "Summary adds real context: Vilnius, air threat, public transport stopped, AFP source."
    },
    {
        "id": "real_20",
        "title": "Dwa obce drony, które wleciały z Rosji, rozbiły się na Łotwie",
        "summary": "Dwa obce drony wleciały na Łotwę z Rosji i rozbiły się – podała w czwartek rano agencja Reutera, powołując się na siły zbrojne. Według publicznego nadawcy LSM jeden z dronów uderzył w skład ropy naftowej w mieście położonym 40 kilometrów od granicy z Rosją.",
        "source_type": "rss",
        "source_name": "Defence24",
        "language": "pl",
        "expected": False,
        "why": "Rich summary: Latvia, from Russia, oil depot hit, 40km from border, Reuters source."
    },
    {
        "id": "real_21",
        "title": "Polska otrzymała tekst umowy pożyczkowej SAFE",
        "summary": "Komisja Europejska w czwartek późnym popołudniem wysłała tekst umowy pożyczkowej SAFE do 18 z 19 państw członkowskich uczestniczących w tym programie, w tym Polski – potwierdził rzecznik KE Thomas Regnier.",
        "source_type": "rss",
        "source_name": "Defence24",
        "language": "pl",
        "expected": False,
        "why": "Economic/policy article, no military threat. Clear what and where."
    },

    # --- RSS: BAD SUMMARIES (should flag) ---
    {
        "id": "real_22",
        "title": "Alarm powietrzny na Litwie. Rządzący udali się do schronów",
        "summary": "Rządzący udali się do schronów.",
        "source_type": "rss",
        "source_name": "RMF24",
        "language": "pl",
        "expected": True,
        "why": "Summary is one sentence that partially repeats title. No detail on cause of alarm."
    },
    {
        "id": "real_23",
        "title": "Drone falls on Latvian oil depot, damaging four tanks — news outlet",
        "summary": "According to the report, four tanks were damaged as a result of the drone crash",
        "source_type": "rss",
        "source_name": "TASS",
        "language": "en",
        "expected": False,
        "why": "Title + summary together: Latvia, oil depot, 4 tanks damaged. Enough for classification."
    },
    {
        "id": "real_24",
        "title": "Łotewska armia alarmuje. Dron wleciał w przestrzeń powietrzną",
        "summary": "Dron wleciał w przestrzeń powietrzną",
        "source_type": "rss",
        "source_name": "RMF24",
        "language": "pl",
        "expected": True,
        "why": "Summary repeats part of title. No country in summary, 'Łotewska' only in title."
    },
    {
        "id": "real_25",
        "title": "NATO jets scramble as drone breaches Latvian airspace for 3rd day in a row",
        "summary": "Residents in affected areas were urged to remain indoors and seek shelter.",
        "source_type": "rss",
        "source_name": "Kyiv Independent",
        "language": "en",
        "expected": False,
        "why": "Title has Latvia + specific event. Summary adds shelter orders. Borderline but enough."
    },

    # --- TELEGRAM (good content, should NOT flag) ---
    {
        "id": "real_26",
        "title": "⚖️ Уже 36 стран поддержали создание спецтрибунала против Путина",
        "summary": "⚖️ Уже 36 стран поддержали создание спецтрибунала против Путина Совет Европы официально запускает в Гааге специальный трибунал по преступлению агрессии России против Украины. К инициативе присоединились Андорра, Австрия, Бельгия, Хорватия...",
        "source_type": "telegram",
        "source_name": "Ukrainian Air Force",
        "language": "uk",
        "expected": False,
        "why": "Detailed message about tribunal, lists countries. Not a military event."
    },
    {
        "id": "real_27",
        "title": "Россияне стали пить больше водки",
        "summary": "Россияне стали пить больше водки После нового подорожания алкоголя в РФ выросли продажи водки. В апреле россияне купили почти 6 млн декалитров — это примерно на 3% больше, чем год назад.",
        "source_type": "telegram",
        "source_name": "Ukrainian Air Force",
        "language": "uk",
        "expected": False,
        "why": "Not military. Clear topic. Detailed summary."
    },
]

SYNTHETIC_ARTICLES = [
    # --- TRICKY: Vague but sounds specific ---
    {
        "id": "synth_01",
        "title": "Atak na strategiczny obiekt. Kluczowa infrastruktura zniszczona",
        "summary": "Atak na strategiczny obiekt. Kluczowa infrastruktura zniszczona Portal Wojskowy",
        "source_type": "google_news",
        "source_name": "GoogleNews:atak wojskowy Polska",
        "language": "pl",
        "expected": True,
        "why": "No country, no specifics. 'Strategic object' and 'key infrastructure' are meaningless without location."
    },
    {
        "id": "synth_02",
        "title": "Eksplozja w pobliżu granicy. Służby na miejscu",
        "summary": "Eksplozja w pobliżu granicy. Służby na miejscu Fakt",
        "source_type": "google_news",
        "source_name": "GoogleNews:atak wojskowy Polska",
        "language": "pl",
        "expected": True,
        "why": "Which border? Which country? 'Near the border' is deliberately vague."
    },
    {
        "id": "synth_03",
        "title": "To nie były ćwiczenia. Mieszkańcy usłyszeli potężny wybuch",
        "summary": "To nie były ćwiczenia. Mieszkańcy usłyszeli potężny wybuch Onet",
        "source_type": "google_news",
        "source_name": "GoogleNews:rosyjskie drony Polska",
        "language": "pl",
        "expected": True,
        "why": "Emotional clickbait ('not exercises', 'powerful explosion'). No location, no event type."
    },
    {
        "id": "synth_04",
        "title": "Pilne! Samoloty bojowe poderwane nad Europą Wschodnią",
        "summary": "Pilne! Samoloty bojowe poderwane nad Europą Wschodnią WP Wiadomości",
        "source_type": "google_news",
        "source_name": "GoogleNews:naruszenie przestrzeni powietrznej",
        "language": "pl",
        "expected": True,
        "why": "'Eastern Europe' — could be any of 15 countries. 'Pilne!' is emotional."
    },
    {
        "id": "synth_05",
        "title": "Generał ostrzega: to dopiero początek. Najbliższe godziny będą kluczowe",
        "summary": "Generał ostrzega: to dopiero początek. Najbliższe godziny będą kluczowe TVN24",
        "source_type": "google_news",
        "source_name": "GoogleNews:Rosja atak",
        "language": "pl",
        "expected": True,
        "why": "Pure rhetoric/analysis. No event, no location. 'This is just the beginning' is empty."
    },
    # --- TRICKY: Specific but sounds vague ---
    {
        "id": "synth_06",
        "title": "Rosyjski pocisk manewrujący uderzył w Rzeszów. Zginęły 3 osoby",
        "summary": "Rosyjski pocisk manewrujący uderzył w Rzeszów. Zginęły 3 osoby Radio Zet",
        "source_type": "google_news",
        "source_name": "GoogleNews:Rosja atak",
        "language": "pl",
        "expected": False,
        "why": "Specific: Russian cruise missile, Rzeszów (Poland), 3 dead. Title is self-sufficient even without summary."
    },
    {
        "id": "synth_07",
        "title": "Dwa Shahedy zestrzelone nad Lubaczowem. Szczątki spadły na pole",
        "summary": "Dwa Shahedy zestrzelone nad Lubaczowem. Szczątki spadły na pole Rzeczpospolita",
        "source_type": "google_news",
        "source_name": "GoogleNews:rosyjskie drony Polska",
        "language": "pl",
        "expected": False,
        "why": "Specific: 2 Shaheds, Lubaczów (Poland), debris on field. Clear factual headline."
    },
    {
        "id": "synth_08",
        "title": "Russian Su-34 drops FAB-500 on Tallinn suburb, 12 casualties reported",
        "summary": "Russian Su-34 drops FAB-500 on Tallinn suburb, 12 casualties reported BBC",
        "source_type": "google_news",
        "source_name": "GoogleNews:Russia attack NATO",
        "language": "en",
        "expected": False,
        "why": "Extremely specific: aircraft type, weapon, city (Tallinn, Estonia), casualties."
    },
    {
        "id": "synth_09",
        "title": "Trzy pociski balistyczne Iskander uderzyły w bazę NATO w Łasku",
        "summary": "Trzy pociski balistyczne Iskander uderzyły w bazę NATO w Łasku Polsat News",
        "source_type": "google_news",
        "source_name": "GoogleNews:atak wojskowy Polska",
        "language": "pl",
        "expected": False,
        "why": "Specific: 3 Iskander missiles, NATO base, Łask (Poland). Self-sufficient."
    },
    # --- TRICKY: Debunking/explainer with alarming keywords ---
    {
        "id": "synth_10",
        "title": "Atak na Polskę? Eksperci wyjaśniają, co naprawdę się stało",
        "summary": "Atak na Polskę? Eksperci wyjaśniają, co naprawdę się stało Newsweek",
        "source_type": "google_news",
        "source_name": "GoogleNews:atak wojskowy Polska",
        "language": "pl",
        "expected": True,
        "why": "Explainer/debunking ('experts explain what really happened'). Question mark = uncertainty."
    },
    {
        "id": "synth_11",
        "title": "Nie, Polska nie została zaatakowana. Oto co wiemy o incydencie",
        "summary": "Nie, Polska nie została zaatakowana. Oto co wiemy o incydencie TVN24",
        "source_type": "google_news",
        "source_name": "GoogleNews:atak wojskowy Polska",
        "language": "pl",
        "expected": True,
        "why": "Explicit denial ('No, Poland was not attacked'). Debunking."
    },
    {
        "id": "synth_12",
        "title": "Prawda o dronach nad Polską. MON dementuje plotki",
        "summary": "Prawda o dronach nad Polską. MON dementuje plotki Onet",
        "source_type": "google_news",
        "source_name": "GoogleNews:rosyjskie drony Polska",
        "language": "pl",
        "expected": True,
        "why": "MON denies rumors. Debunking article with scary keywords."
    },
    # --- TRICKY: Emotional but actually informative ---
    {
        "id": "synth_13",
        "title": "PILNE: Rosyjski dron Shahed-136 spadł w Przewodowie. Dwie osoby nie żyją",
        "summary": "PILNE: Rosyjski dron Shahed-136 spadł w Przewodowie. Dwie osoby nie żyją Onet",
        "source_type": "google_news",
        "source_name": "GoogleNews:atak wojskowy Polska",
        "language": "pl",
        "expected": False,
        "why": "Despite 'PILNE', has all facts: Shahed-136, Przewodów (Poland), 2 dead."
    },
    {
        "id": "synth_14",
        "title": "BREAKING: Multiple explosions reported in Klaipeda, Lithuania. Military confirms missile strike",
        "summary": "BREAKING: Multiple explosions reported in Klaipeda, Lithuania. Military confirms missile strike Reuters",
        "source_type": "google_news",
        "source_name": "GoogleNews:Russia attack NATO",
        "language": "en",
        "expected": False,
        "why": "Despite 'BREAKING', has specifics: Klaipeda, Lithuania, missile strike, military confirmed."
    },
    # --- TRICKY: Ukraine events with Poland-adjacent language ---
    {
        "id": "synth_15",
        "title": "Rosjanie uderzyli w ważne dla Polski miejsca. Drony nad Lwowem",
        "summary": "Rosjanie uderzyli w ważne dla Polski miejsca. Drony nad Lwowem Gazeta",
        "source_type": "google_news",
        "source_name": "GoogleNews:Rosja atak",
        "language": "pl",
        "expected": True,
        "why": "'Places important for Poland' — culturally, not territorially. Actually about Lviv, Ukraine."
    },
    {
        "id": "synth_16",
        "title": "Atak w pobliżu polskiej granicy. Rosyjskie rakiety spadły na Lwów",
        "summary": "Atak w pobliżu polskiej granicy. Rosyjskie rakiety spadły na Lwów RMF24",
        "source_type": "google_news",
        "source_name": "GoogleNews:atak wojskowy Polska",
        "language": "pl",
        "expected": True,
        "why": "'Near Polish border' but event is in Lviv, Ukraine. Misleading framing. Summary=title."
    },
    {
        "id": "synth_17",
        "title": "Missiles rain down on city just 70km from Polish border",
        "summary": "Missiles rain down on city just 70km from Polish border Daily Mail",
        "source_type": "google_news",
        "source_name": "GoogleNews:Russia attack NATO",
        "language": "en",
        "expected": True,
        "why": "Doesn't name the city (Lviv). '70km from Polish border' implies Poland threat but event is Ukraine."
    },
    # --- TRICKY: Source credibility baked into headline ---
    {
        "id": "synth_18",
        "title": "Stan podwyższonego zagrożenia w całej Polsce. Wojsko w stanie gotowości",
        "summary": "Stan podwyższonego zagrożenia w całej Polsce. Wojsko w stanie gotowości Warszawa w Pigułce",
        "source_type": "google_news",
        "source_name": "GoogleNews:atak wojskowy Polska",
        "language": "pl",
        "expected": True,
        "why": "From a hyperlocal blog. Extraordinary claim (whole Poland on alert) from unreliable source. Summary=title."
    },
    {
        "id": "synth_19",
        "title": "Russia threatens nuclear strike on Warsaw within 24 hours - claim",
        "summary": "Russia threatens nuclear strike on Warsaw within 24 hours - claim Express.co.uk",
        "source_type": "google_news",
        "source_name": "GoogleNews:Russia attack NATO",
        "language": "en",
        "expected": True,
        "why": "Tabloid rhetoric. 'Claim' and 'threatens' — this is posturing, not an event. Summary=title."
    },
    # --- TRICKY: Non-military with military keywords ---
    {
        "id": "synth_20",
        "title": "Poland's military budget hits record $50 billion as NATO spending soars",
        "summary": "Poland's military budget hits record $50 billion as NATO spending soars Bloomberg",
        "source_type": "google_news",
        "source_name": "GoogleNews:NATO Article 5",
        "language": "en",
        "expected": False,
        "why": "Budget/economic news. Clear what it's about despite military keywords."
    },
    {
        "id": "synth_21",
        "title": "Polska armia testuje nowe drony kamikaze na poligonie w Drawsku",
        "summary": "Polska armia testuje nowe drony kamikaze na poligonie w Drawsku Defence24",
        "source_type": "google_news",
        "source_name": "GoogleNews:rosyjskie drony Polska",
        "language": "pl",
        "expected": False,
        "why": "Military exercises/testing at Drawsko range. Clear, non-threatening."
    },
    # --- TRICKY: Multiple countries, ambiguous ---
    {
        "id": "synth_22",
        "title": "Drony nad krajami bałtyckimi. NATO zwołuje nadzwyczajne posiedzenie",
        "summary": "Drony nad krajami bałtyckimi. NATO zwołuje nadzwyczajne posiedzenie WP Wiadomości",
        "source_type": "google_news",
        "source_name": "GoogleNews:rosyjskie drony Polska",
        "language": "pl",
        "expected": True,
        "why": "'Baltic countries' — which ones? All three? One? Summary=title."
    },
    {
        "id": "synth_23",
        "title": "NATO jets intercept Russian bombers over Baltic Sea near Gotland",
        "summary": "NATO jets intercept Russian bombers over Baltic Sea near Gotland Reuters",
        "source_type": "google_news",
        "source_name": "GoogleNews:Russia attack NATO",
        "language": "en",
        "expected": False,
        "why": "Specific: Baltic Sea, near Gotland (Sweden). Interception, not attack."
    },
    # --- TRICKY: Past tense / aftermath phrased as present danger ---
    {
        "id": "synth_24",
        "title": "Po ataku: Polska wzmacnia obronę powietrzną na wschodniej flance",
        "summary": "Po ataku: Polska wzmacnia obronę powietrzną na wschodniej flance Rzeczpospolita",
        "source_type": "google_news",
        "source_name": "GoogleNews:atak wojskowy Polska",
        "language": "pl",
        "expected": True,
        "why": "'After the attack' — aftermath, not active threat. Which attack? No detail."
    },
    {
        "id": "synth_25",
        "title": "W cieniu rosyjskiego ataku: jak Litwa zmieniła się w 24 godziny",
        "summary": "W cieniu rosyjskiego ataku: jak Litwa zmieniła się w 24 godziny Newsweek",
        "source_type": "google_news",
        "source_name": "GoogleNews:Rosja atak",
        "language": "pl",
        "expected": True,
        "why": "Analysis piece ('how Lithuania changed'). Past tense framed dramatically."
    },
    # --- RSS with good summary (should NOT flag) ---
    {
        "id": "synth_26",
        "title": "Russian drone crosses into Polish airspace during massive strike on Ukraine",
        "summary": "A Shahed-type drone crossed into Polish airspace near Lubaczów for approximately 39 seconds before returning to Ukrainian territory, Polish military confirmed. No interception was attempted. The incident occurred during a large-scale Russian drone attack on western Ukraine.",
        "source_type": "rss",
        "source_name": "Defence24 EN",
        "language": "en",
        "expected": False,
        "why": "Detailed summary: drone type, location, duration, no interception, context."
    },
    {
        "id": "synth_27",
        "title": "Nagły alarm w mieście NATO. Ewakuacja tysięcy mieszkańców",
        "summary": "W Rydze ogłoszono alarm dronowy po wykryciu niezidentyfikowanego obiektu nad dzielnicą portową. Ewakuowano ok. 3 tys. mieszkańców z okolic terminalu LNG. Łotewska armia poderwała myśliwce NATO.",
        "source_type": "rss",
        "source_name": "Polsat News",
        "language": "pl",
        "expected": False,
        "why": "Vague TITLE ('NATO city') but rich SUMMARY: Riga, port district, 3000 evacuated, LNG terminal."
    },
    {
        "id": "synth_28",
        "title": "Horror w kraju NATO! Dron eksplodował w centrum miasta!",
        "summary": "Na Łotwie, w mieście Daugavpils, dron typu Shahed-136 eksplodował na parkingu w pobliżu centrum handlowego. Odłamki uszkodziły 4 samochody, jedna osoba ranna. Łotewskie władze zwołały posiedzenie kryzysowe.",
        "source_type": "rss",
        "source_name": "Fakt",
        "language": "pl",
        "expected": False,
        "why": "Clickbait TITLE but detailed SUMMARY: Latvia, Daugavpils, Shahed, specific damage."
    },
]


def run_check(article, max_retries=5):
    import time
    user_msg = (
        f"Source: {article['source_name']} ({article['source_type']})\n"
        f"Language: {article['language']}\n"
        f"Title: {article['title']}\n"
        f"Summary: {article['summary']}"
    )
    for attempt in range(max_retries):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=100,
                temperature=0,
                system=VAGUENESS_CHECK_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
            )
            raw = response.content[0].text.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            data = json.loads(raw)
            return {
                "needs_enrichment": data.get("needs_enrichment", None),
                "reason": data.get("reason", ""),
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            }
        except anthropic.APIStatusError as e:
            if e.status_code == 529 and attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            return {"needs_enrichment": None, "reason": f"ERROR: {e}", "input_tokens": 0, "output_tokens": 0}
        except Exception as e:
            return {"needs_enrichment": None, "reason": f"ERROR: {e}", "input_tokens": 0, "output_tokens": 0}


def main():
    all_articles = REAL_ARTICLES + SYNTHETIC_ARTICLES
    results = []
    total_input_tokens = 0
    total_output_tokens = 0

    print(f"Testing {len(all_articles)} articles ({len(REAL_ARTICLES)} real, {len(SYNTHETIC_ARTICLES)} synthetic)\n")
    print("=" * 120)

    correct = 0
    wrong = 0
    errors = 0

    for art in all_articles:
        result = run_check(art)
        total_input_tokens += result["input_tokens"]
        total_output_tokens += result["output_tokens"]

        got = result["needs_enrichment"]
        expected = art["expected"]
        match = got == expected

        if got is None:
            errors += 1
            status = "ERR"
        elif match:
            correct += 1
            status = "OK "
        else:
            wrong += 1
            status = "MISS"

        flag_str = "ENRICH" if got else "PASS  " if got is not None else "ERROR "
        exp_str = "ENRICH" if expected else "PASS  "

        title_short = art["title"][:75] + ("..." if len(art["title"]) > 75 else "")
        print(f"[{status}] {art['id']:10s} | got={flag_str} exp={exp_str} | {title_short}")
        if not match:
            print(f"       Reason: {result['reason']}")
            print(f"       Why expected {exp_str}: {art['why']}")

        results.append({**art, **result, "match": match})

    print("\n" + "=" * 120)
    print(f"\nRESULTS: {correct}/{len(all_articles)} correct, {wrong} wrong, {errors} errors")
    print(f"Accuracy: {correct/(correct+wrong)*100:.1f}%" if (correct+wrong) > 0 else "N/A")

    # Breakdown by category
    real_correct = sum(1 for r in results[:len(REAL_ARTICLES)] if r["match"])
    synth_correct = sum(1 for r in results[len(REAL_ARTICLES):] if r["match"])
    print(f"  Real: {real_correct}/{len(REAL_ARTICLES)}")
    print(f"  Synthetic: {synth_correct}/{len(SYNTHETIC_ARTICLES)}")

    # False negatives (missed vague articles) vs false positives (flagged clear articles)
    fn = sum(1 for r in results if r["expected"] and not r.get("needs_enrichment", True))
    fp = sum(1 for r in results if not r["expected"] and r.get("needs_enrichment", False))
    print(f"\n  False negatives (missed vague): {fn}")
    print(f"  False positives (flagged clear): {fp}")

    # Token stats
    n = len(all_articles)
    print(f"\nTOKEN USAGE:")
    print(f"  Total: {total_input_tokens} input, {total_output_tokens} output")
    print(f"  Average per article: {total_input_tokens/n:.0f} input, {total_output_tokens/n:.0f} output")

    haiku_input_cost = 0.80  # per MTok
    haiku_output_cost = 4.00  # per MTok
    cost_per_article = (total_input_tokens/n * haiku_input_cost + total_output_tokens/n * haiku_output_cost) / 1_000_000
    print(f"  Cost per article: ${cost_per_article:.6f}")
    print(f"  Cost per cycle (10 articles): ${cost_per_article * 10:.5f}")
    print(f"  Cost per day (480 cycles × 10): ${cost_per_article * 10 * 480:.2f}")

    # Show all misses in detail
    misses = [r for r in results if not r["match"] and r.get("needs_enrichment") is not None]
    if misses:
        print(f"\n{'='*120}")
        print("DETAILED MISSES:")
        for r in misses:
            print(f"\n  {r['id']}: {r['title'][:90]}")
            print(f"    Summary: {r['summary'][:90]}")
            print(f"    Expected: {'ENRICH' if r['expected'] else 'PASS'} | Got: {'ENRICH' if r['needs_enrichment'] else 'PASS'}")
            print(f"    LLM reason: {r['reason']}")
            print(f"    Ground truth: {r['why']}")


if __name__ == "__main__":
    main()
