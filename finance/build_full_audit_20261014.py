#!/usr/bin/env python3
"""Build the full cost audit of Project Sentinel as of 2026-10-14 (end of day UTC).

Inputs (never modified):
  reports/2026-10-14-full-audit/input/lines.json       reconciled lines of all provider groups (public-safe)
  reports/2026-10-14-full-audit/input/nbp-table-a.csv  NBP table A mid rates for USD and EUR
  reports/2026-10-11-hetzner-provider/summary.json      previous audit, used only for the comparison
  reports/2026-10-11-hetzner-provider/cost-items.csv    previous audit, used only for the comparison

Outputs (in reports/2026-10-14-full-audit/):
  ledger.csv           every line with its PLN equivalent, FX date and rate
  monthly.csv          month x provider economic cost (native and PLN), month totals, grand total
  cash.csv             cash events by payment date with Sentinel's share and PLN
  current-monthly.csv  run-rate lines (in total) and scenario lines (outside the total)
  excluded.csv         spending that is deliberately not a Sentinel cost, with de-duplication
  summary.json         every total and every value the report shows
  report.html          Polish report for the owner, rendered from summary.json only

Living records (same bytes as the dated copies):
  finance/ledger.csv = ledger.csv, finance/current-monthly.csv = current-monthly.csv,
  finance/history-monthly.csv = monthly.csv

Usage:
  python3 finance/build_full_audit_20261014.py          write all outputs
  python3 finance/build_full_audit_20261014.py --check  recompute and compare; exit 1 on any mismatch

Stdlib only, Decimal arithmetic, deterministic (the script never reads the clock).
"""

import argparse
import csv
import hashlib
import html
import io
import json
import math
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

FIN = Path(__file__).resolve().parent
REPORT = FIN / "reports" / "2026-10-14-full-audit"
IN_LINES = REPORT / "input" / "lines.json"
IN_NBP = REPORT / "input" / "nbp-table-a.csv"
PREV = FIN / "reports" / "2026-10-11-hetzner-provider"
SCRIPT_NAME = "finance/build_full_audit_20261014.py"

AS_OF = "2026-10-14T23:59:59Z"
AS_OF_DATE = date(2026, 10, 14)
START_DATE = date(2026, 3, 21)
MONTHS = [f"2026-{m:02d}" for m in range(3, 11)]
PARTIAL_MONTH = "2026-10"
RUNRATE_DAYS = Decimal("30.44")
RUNRATE_FROM = date(2026, 10, 1)
ZERO = Decimal(0)
CENT = Decimal("0.01")

GROUP_ORDER = ["anthropic", "openai", "openrouter_typesafe", "twilio", "hetzner", "apple_expo", "other_and_excluded"]
PROVIDER_ORDER = [
    "Twilio",
    "Anthropic",
    "OpenAI",
    "Apple",
    "Hetzner",
    "OpenRouter",
    "TypeSafe (Jev)",
    "Expo",
    "GitHub",
    "Free news sources",
    "Backups (on the VPS disk)",
]
EVIDENCE_ORDER = [
    "provider_invoice",
    "provider_statement",
    "provider_portal",
    "measured_usage_x_tariff",
    "deleted_mail_snippet",
    "email_receipt",
    "estimate",
    "unknown",
]
REASON_ORDER = [
    "subscription",
    "coding_tool",
    "msigalert",
    "other_project",
    "personal",
    "pre_project",
    "failed_payment",
    "duplicate",
]

# The same GitHub months are booked by two groups (both USD 0). The other_and_excluded lines rest on
# the GitHub billing page, so they are kept; the apple_expo copies are marked as duplicates.
DUPLICATE_LINES = {f"github-2026-{m:02d}": f"other-github-2026-{m:02d}" for m in range(3, 11)}
DUPLICATE_RUNRATE = {("apple_expo", 2): ("other_and_excluded", 0, "GitHub")}

# Providers whose Sentinel invoices carry 0% VAT under the EU reverse charge on the owner's PL VAT number,
# each verified against a quote in its group's method notes: (provider, group, path, quote). The totals
# exclude that VAT by the agreed convention. Whether the self-assessed Polish VAT is deductible is an open
# tax question; summary.reverse_charge_vat states what it would add. Every other provider with a non-zero
# cost must be in VAT_PAID_PROVIDERS (VAT or fees actually paid and already inside the cost).
REVERSE_CHARGE = [
    ("Twilio", "twilio", ("method_notes",), "reverse charge, VAT 0"),
    ("Anthropic", "anthropic", ("method_notes",), "all reverse charge at 0% VAT"),
    ("OpenAI", "openai", ("method_notes",), "0% VAT under EU reverse charge"),
    ("Hetzner", "hetzner", ("method_notes",), "0% VAT under reverse charge"),
]
VAT_PAID_PROVIDERS = ("OpenRouter", "Apple")
PL_VAT_RATE = Decimal("0.23")
RC_NAMES = [p for p, _, _, _ in REVERSE_CHARGE]

CONVENTIONS = [
    "Primary table: economic cost by month of use. Usage-billed services by usage month, invoiced "
    "services by service-period month, one-off purchases and annual fees in the month of purchase.",
    "Prepaid credits count when consumed, not when bought. On shared prepaid accounts (Anthropic, "
    "OpenRouter, TypeSafe) Sentinel's share is set FIFO by credit grant.",
    "Reverse-charged VAT (0% on the " + ", ".join(RC_NAMES[:-1]) + " and " + RC_NAMES[-1] + " invoices) is "
    "excluded; whether that VAT is deductible is an open tax question (summary.reverse_charge_vat, outside "
    "every total). VAT and fees actually paid (OpenRouter 23% PL VAT and purchase fee; Apple gross price) "
    "are included pro rata in the consumed cost.",
    "Free or promotional credit consumed is a zero-cash note line (in_total=false), outside every total.",
    "Accrued unpaid charges (Twilio number rental while suspended) are economic cost of the month they "
    "accrue; they are owed, not paid.",
    "No amount is invented. Estimates carry evidence_class 'estimate', a method and low/high bounds.",
    "Secondary table: cash by payment date, Sentinel share only; a purchase and its consumption are "
    "never added together.",
    "Current monthly cost: usage services = Oct 1-14 daily average x 30.44; fixed fees at their monthly "
    "price; annual fees / 12; services no longer used = 0. Scenario lines stay outside the total.",
    "FX: NBP table A mid rate. Lines: last business day of the usage month (latest available day for the "
    "partial current month). Cash events: last business day before the payment date. Current monthly "
    "cost: latest available day.",
    "Excluded: the owner's time, Claude and ChatGPT subscriptions, Codex and other cross-project coding "
    "tools, the msigalert/InfoCentral product and other projects.",
]

# --------------------------------------------------------------------------------------------------
# Static Polish text. No digit may appear in hand-written text: every number in the report comes from
# a computed value or from a fact whose quote is verified against the inputs.
# --------------------------------------------------------------------------------------------------
_DIGIT = re.compile(r"\d")
_NAMES_WITH_DIGITS = ("Context7", "1Password")  # product names, not figures


def T(template, **values):
    """Format Polish text; refuse templates that contain hand-typed digits."""
    bare = re.sub(r"\{[^{}]*\}", "", template)
    for name in _NAMES_WITH_DIGITS:
        bare = bare.replace(name, "")
    if _DIGIT.search(bare):
        raise ValueError(f"hand-typed digit in Polish text: {template!r}")
    return template.format(**values)


MONTH_NAMES = {
    1: "styczeń",
    2: "luty",
    3: "marzec",
    4: "kwiecień",
    5: "maj",
    6: "czerwiec",
    7: "lipiec",
    8: "sierpień",
    9: "wrzesień",
    10: "październik",
    11: "listopad",
    12: "grudzień",
}
MONTH_SHORT = {
    1: "sty",
    2: "lut",
    3: "mar",
    4: "kwi",
    5: "maj",
    6: "cze",
    7: "lip",
    8: "sie",
    9: "wrz",
    10: "paź",
    11: "lis",
    12: "gru",
}

PROVIDER_PL = {
    "Twilio": (
        "Twilio",
        "Połączenia telefoniczne i SMS-y z alertami na Twój telefon oraz dzierżawa dwóch numerów. "
        "Konto jest zawieszone, więc dziś narastają tylko opłaty za numery (jako dług).",
    ),
    "Anthropic": (
        "Anthropic",
        "Model Claude Haiku, który do września oceniał każdy artykuł (klasyfikator). Dziś "
        "nieużywany, zostaje jako zapas na wypadek powrotu.",
    ),
    "OpenAI": (
        "OpenAI",
        "Model GPT Luna, który dziś ocenia każdy artykuł, sprawdza jakość streszczeń i tłumaczy je na polski.",
    ),
    "Apple": (
        "Apple",
        "Roczne członkostwo w programie deweloperów Apple; bez niego nie działa aplikacja na "
        "iPhone'a z powiadomieniami.",
    ),
    "Hetzner": ("Hetzner", "Serwer w chmurze, na którym działa cały Sentinel, razem z adresem IP."),
    "OpenRouter": (
        "OpenRouter",
        "Jednorazowe testy porównawcze modeli we wrześniu, przez pośrednika OpenRouter; "
        "z zapłaconym VAT i opłatą za zakup kredytów.",
    ),
    "TypeSafe (Jev)": (
        "TypeSafe (Jev)",
        "Eksperyment z modelem Jev we wrześniu, opłacony darmowym kredytem, więc zero złotych.",
    ),
    "Expo": ("Expo", "Wysyłka powiadomień push i budowanie aplikacji na iPhone'a; darmowy plan."),
    "GitHub": ("GitHub", "Przechowywanie kodu w publicznym repozytorium; darmowe."),
    "Free news sources": ("Źródła wiadomości", "Kanały RSS, Google News i Telegram; darmowe."),
    "Backups (on the VPS disk)": ("Kopie zapasowe", "Kopie bazy danych na dysku serwera; wliczone w cenę serwera."),
}

EVIDENCE_PL = {
    "provider_invoice": "faktura lub wyciąg dostawcy",
    "provider_statement": "potwierdzenie płatności od dostawcy",
    "provider_portal": "panel dostawcy",
    "measured_usage_x_tariff": "odczyt zużycia × cennik",
    "deleted_mail_snippet": "e-mail odtworzony po usunięciu",
    "email_receipt": "e-mail od dostawcy",
    "estimate": "szacunek",
    "unknown": "nieznane",
}

KIND_PL = {
    "credit_purchase": "zakup kredytu",
    "auto_recharge": "automatyczne doładowanie",
    "payment": "zapłata faktury",
    "annual_fee": "opłata roczna",
    "failed_not_charged": "nieudana, bez obciążenia",
}

LINE_LABEL_RULES = [
    (r"^anthropic-sentinel-haiku-", "Claude Haiku: klasyfikator artykułów"),
    (r"^openai-.*-gpt56luna-testing$", "GPT Luna: testy i sprawdzenie wdrożenia"),
    (r"^openai-.*-gpt6-eval$", "Ewaluacja nowszych modeli GPT (nieprzyjęta)"),
    (r"^openai-.*-oct.*-est$", "GPT Luna: ostatnie godziny dnia audytu (szacunek)"),
    (r"^openai-.*-oct", "GPT Luna: wieczór dnia audytu (pomiar z dziennika aplikacji)"),
    (r"^openai-.*-gpt56luna$", "GPT Luna: klasyfikator produkcyjny"),
    (r"^openai-.*-api-usage$", "OpenAI: brak użycia"),
    (r"^ORT-.*-openrouter-sentinel-eval$", "Testy porównawcze modeli (z VAT i opłatą)"),
    (r"^ORT-.*-openrouter-sentinel$", "OpenRouter: brak użycia przez Sentinel"),
    (r"^ORT-.*-typesafe-jev-eval-free$", "Eksperyment Jev: darmowy kredyt"),
    (r"^ORT-.*-typesafe-sentinel$", "TypeSafe: brak użycia przez Sentinel"),
    (r"^twilio-.*-messaging$", "SMS-y i wiadomości"),
    (r"^twilio-.*-calls-unbilled-exposure$", "Połączenia nierozliczone przez Twilio (ryzyko doliczenia)"),
    (r"^twilio-.*-calls$", "Połączenia alarmowe"),
    (r"^twilio-.*-number-pl-accrued$", "Numer polski: naliczony w zawieszeniu, niezapłacony"),
    (r"^twilio-.*-number-us-accrued$", "Numer amerykański: naliczony w zawieszeniu, niezapłacony"),
    (r"^twilio-.*-number-pl$", "Dzierżawa numeru polskiego"),
    (r"^twilio-.*-number-us$", "Dzierżawa numeru amerykańskiego"),
    (r"^twilio-.*-tts$", "Synteza mowy w połączeniach"),
    (r"^twilio-.*-amd$", "Wykrywanie poczty głosowej (tylko testy)"),
    (r"^twilio-.*-free-trial-credit$", "Darmowy kredyt próbny Twilio"),
    (r"^twilio-.*-usage$", "Twilio: brak zużycia (konto zawieszone)"),
    (r"^hetzner-vps-.*-fullmonth-projection$", "Serwer: prognoza pełnego października"),
    (r"^hetzner-vps-.*-mtd$", "Serwer: październik do wieczora (odczyt panelu)"),
    (r"^hetzner-vps-.*-eod-tail$", "Serwer: ostatnie godziny dnia audytu (szacunek)"),
    (r"^hetzner-vps-", "Serwer w chmurze i adres IP"),
    (r"^apple-devprog-", "Członkostwo Apple Developer"),
    (r"^expo-", "Expo: darmowy plan"),
    (r"^(other-)?github-", "GitHub: darmowy plan"),
    (r"^other-sources-", "Darmowe źródła wiadomości"),
    (r"^other-backups-", "Kopie zapasowe na dysku serwera"),
]

RUNRATE_PL = {
    ("anthropic", 0): ("Claude Haiku (nieużywany)", None),
    ("anthropic", 1): (
        "Scenariusz: powrót do Claude Haiku",
        "Gdyby klasyfikator wrócił do Claude Haiku przy dzisiejszej liczbie artykułów.",
    ),
    ("openai", 0): ("GPT Luna: klasyfikator", None),
    ("openai", 1): ("Ewaluacje nowszych modeli GPT", None),
    ("openai", 2): (
        "Scenariusz: limit projektu w OpenAI bez zmian (już nieaktualny)",
        "Już nieaktualny: limit podniesiono wieczorem w dniu audytu. Przy starym limicie rachunek "
        "nie przekroczyłby limitu, ale klasyfikacja stawałaby w drugiej połowie każdego miesiąca. "
        "To awaria, nie oszczędność.",
    ),
    ("openai", 3): (
        "Scenariusz: darmowe tokeny OpenAI za udostępnianie danych",
        "Włączyłeś udostępnianie danych OpenAI. Jeśli darmowe dzienne tokeny obejmują model "
        "Sentinela, płatna będzie tylko nadwyżka ponad dzienny limit, a spokojniejsze dni będą "
        "darmowe. Lista modeli w ustawieniach go nie wymienia, więc potwierdzi to dopiero panel "
        "zużycia. Gdyby model nie był objęty, koszt zostaje bez zmian (górna granica).",
    ),
    ("openrouter_typesafe", 0): ("OpenRouter: klucz testowy Sentinela", None),
    ("openrouter_typesafe", 1): ("TypeSafe: użycie przez Sentinel", None),
    ("openrouter_typesafe", 2): (
        "Scenariusz: powtórka wrześniowych testów modeli",
        "Jednorazowo, nie co miesiąc; zapłacona z salda, które już jest na koncie OpenRouter.",
    ),
    ("twilio", 0): ("Twilio: połączenia i SMS-y (konto zawieszone)", None),
    ("twilio", 1): ("Twilio: numer polski (narasta jako dług)", None),
    ("twilio", 2): ("Twilio: numer amerykański (narasta jako dług)", None),
    ("twilio", 3): (
        "Scenariusz A: doładowanie Twilio przy obecnych zasadach",
        "Telefon i SMS z kodem tylko przy najwyższej pilności. Liczone od liczby takich zdarzeń w "
        "październiku, nie od odrzuconych prób, które na zawieszonym koncie wielokrotnie się powtarzają. "
        "Górna granica to tempo od połowy września do dnia audytu, z doliczonymi połączeniami. Numery są już "
        "ujęte w sumie powyżej.",
    ),
    ("twilio", 4): (
        "Scenariusz B: doładowanie i SMS-y także dla niższych poziomów pilności",
        "Tak było do czerwca. Zastępuje scenariusz A, nie dodaje się do niego.",
    ),
    ("hetzner", 0): ("Hetzner: serwer i adres IP", None),
    ("apple_expo", 0): ("Apple Developer: opłata roczna podzielona na dwanaście", None),
    ("apple_expo", 1): ("Expo: darmowy plan", None),
    ("apple_expo", 2): ("GitHub", None),
    ("other_and_excluded", 0): ("GitHub: darmowy plan", None),
    ("other_and_excluded", 1): ("Źródła wiadomości: darmowe", None),
    ("other_and_excluded", 2): ("Kopie zapasowe: w cenie serwera", None),
}

REASON_PL = {
    "subscription": (
        "Subskrypcje asystentów AI",
        "Subskrypcje Claude, ChatGPT i Google służą całej Twojej pracy, nie samemu Sentinelowi. Tak ustaliliśmy.",
    ),
    "coding_tool": (
        "Narzędzia do programowania",
        "Narzędzia do pisania kodu i badań, używane we wszystkich projektach.",
    ),
    "msigalert": ("msigalert / InfoCentral", "Twój drugi produkt ma własne konta i własne rozliczenie."),
    "other_project": ("Inne projekty", "Kancelaria, narzędzia osobiste i inne eksperymenty."),
    "personal": ("Wydatki osobiste", "Wydatki prywatne, niezwiązane z Sentinelem."),
    "pre_project": ("Sprzed startu projektu", "Zakupy sprzed powstania Sentinela."),
    "failed_payment": ("Nieudane płatności", "Próby płatności, które się nie udały. Pieniądze nie wypłynęły."),
    "duplicate": (
        "Zapisy zdublowane lub zastąpione",
        "Te same pieniądze zapisane drugi raz albo stare szacunki zastąpione lepszymi danymi. "
        "Pominięte, żeby nic nie policzyć dwa razy.",
    ),
}

# (group, index) -> (expected item prefix, Polish label or None, duplicate target or None)
EXCLUDED_MAP = {
    ("anthropic", 0): ("MemSearchBacklog", None, ("other_and_excluded", 26)),
    ("anthropic", 1): ("msigalert-prod-accuracy-verifier", "Klucze API weryfikatora msigalert (Claude)", None),
    ("anthropic", 2): ("Claude Max plan 20x, owner's", None, ("other_and_excluded", 0)),
    ("anthropic", 3): ("Claude Max plan 20x on the second", None, ("other_and_excluded", 5)),
    ("anthropic", 4): ("Claude 'Prepaid extra usage", None, ("other_and_excluded", 2)),
    ("anthropic", 5): ("Console banner offer", "Oferta kredytów API w planie Max (nieaktywowana)", None),
    ("anthropic", 6): ("2024 Console monthly invoices", "Stare faktury konsoli Anthropic sprzed projektu", None),
    ("anthropic", 7): ("Failed API credit", "Nieudane zakupy kredytów API Anthropic", None),
    ("anthropic", 8): ("Failed claude.ai subscription", "Nieudane obciążenia subskrypcji Claude (ponowione)", None),
    ("anthropic", 9): ("ChatGPT Pro subscription invoice", None, ("other_and_excluded", 8)),
    ("anthropic", 10): ("Google One 'Google AI Ultra", None, ("other_and_excluded", 11)),
    ("openai", 0): ("OpenAI API credit purchase on the same org", "Zakup kredytów API OpenAI sprzed projektu", None),
    ("openai", 1): ("ChatGPT Pro subscription, period", None, ("other_and_excluded", 8)),
    ("openai", 2): ("ChatGPT Business workspace", None, ("other_and_excluded", 9)),
    ("openai", 3): ("Codex (CLI and plugins)", None, ("other_and_excluded", 10)),
    ("openai", 4): (
        "OpenAI models called through OpenRouter",
        "Modele OpenAI przez OpenRouter (policzone w OpenRouter)",
        None,
    ),
    ("openai", 5): ("Sentinel server usage ledger", "Własny dziennik kosztów aplikacji (tylko do kontroli)", None),
    ("openai", 6): ("Repo runner and ledger estimates", "Szacunki testów z repozytorium i z poprzedniego audytu", None),
    ("openai", 7): ("Auto-recharge attempt that failed", "Nieudane automatyczne doładowanie OpenAI", None),
    ("openrouter_typesafe", 0): ("Usage on the 'OpenCode' API key (8", "OpenCode przez OpenRouter (sierpień)", None),
    ("openrouter_typesafe", 1): (
        "Usage on the 'OpenCode' API key (Kimi",
        "OpenCode przez OpenRouter (październik)",
        None,
    ),
    ("openrouter_typesafe", 2): (
        "Two Stripe invoices re-issued",
        "Ponownie wystawione faktury za te same, już zapłacone zakupy",
        None,
    ),
    ("openrouter_typesafe", 3): (
        "Deleted-mail receipt snippets",
        "Usunięte maile z tymi samymi paragonami OpenRouter",
        None,
    ),
    ("openrouter_typesafe", 4): (
        "Jev usage by the owner's k87 mailbox cleanup",
        "TypeSafe: porządkowanie skrzynki pocztowej",
        None,
    ),
    ("openrouter_typesafe", 5): ("jev CLI / jev-skill", "TypeSafe: testy narzędzia jev", None),
    ("openrouter_typesafe", 6): (
        "gpt-5.6-luna side of Sentinel's Jev+Luna",
        "Część OpenAI eksperymentu Jev i Luna (policzona w OpenAI)",
        None,
    ),
    ("twilio", 0): ("Failed auto-recharge 2026-04-17", "Nieudane automatyczne doładowanie Twilio", None),
    ("twilio", 1): ("Failed auto-recharge 2026-04-20", "Nieudane automatyczne doładowanie Twilio", None),
    ("twilio", 2): ("Rejected call and SMS attempts", "Odrzucone połączenia i SMS-y w zawieszeniu (bez opłat)", None),
    ("twilio", 3): (
        "Phone number renewals scheduled after",
        "Odnowienia numerów po dniu audytu (ujęte w koszcie miesięcznym)",
        None,
    ),
    ("twilio", 4): ("Console usage summary March 2026", "Podsumowanie zużycia z panelu za marzec", None),
    ("twilio", 5): ("Owner's approximate figures", "Twoje przybliżone kwoty (potwierdzone wyciągami)", None),
    ("twilio", 6): ("Email-agent inferred recharge windows", "Domniemane doładowania z maili (zastąpione)", None),
    ("twilio", 7): (
        "Statement records inside the portal",
        "Wyciągi Twilio w danych panelu (zużycie, nie płatności)",
        None,
    ),
    ("twilio", 8): ("Prior audit (2026-10-11) back-cast", "Szacunek Twilio z poprzedniego audytu (zastąpiony)", None),
    ("twilio", 9): ("Forwarded copies of March-April", None, ("other_and_excluded", 0)),
    ("twilio", 10): ("Google One AI Ultra invoices (2)", None, ("other_and_excluded", 11)),
    ("hetzner", 0): ("VPS Lite 1 G12s", None, ("other_and_excluded", 15)),
    ("hetzner", 1): ("Hetzner Cloud project 'msigalert'", "Pusty projekt msigalert w Hetzner", None),
    ("hetzner", 2): ("Domains infocentral.pl and infocentrala.pl", None, ("other_and_excluded", 17)),
    ("hetzner", 3): ("Law-firm website domain, 1-year", None, ("other_and_excluded", 34)),
    ("hetzner", 4): ("Business Standard for the law-firm domain, first", None, ("other_and_excluded", 35)),
    ("hetzner", 5): ("Domain 638204.xyz", None, ("other_and_excluded", 16)),
    ("hetzner", 6): ("Web analytics, 5K events", None, ("other_and_excluded", 19)),
    ("hetzner", 7): ("Google AI Ultra (2 monthly invoices", None, ("other_and_excluded", 11)),
    ("hetzner", 8): (
        "Card payments of the four Hetzner invoices",
        "Płatności kartą za faktury Hetzner (tylko w widoku gotówki)",
        None,
    ),
    ("hetzner", 9): ("Duplicate copies of the four Hetzner invoice", "Kopie tych samych faktur Hetzner", None),
    ("hetzner", 10): ("Deleted-mail rows", "Usunięte maile Hetzner o fakturach", None),
    ("hetzner", 11): (
        "Previous audit's October accrual",
        "Szacunek października z poprzedniego audytu (zastąpiony)",
        None,
    ),
    ("apple_expo", 0): ("Apple invoice notice for the same", "Faktura Apple do tego samego zamówienia", None),
    ("apple_expo", 1): ("Apple Developer non-billing notices", "Powiadomienia Apple bez opłat", None),
    ("apple_expo", 2): ("2026-10-11 audit Apple rows", "Wpisy Apple z poprzedniego audytu (zastąpione)", None),
    ("apple_expo", 3): ("2026-10-11 audit row 'CI/builds", "Wiersz o budowaniu aplikacji z poprzedniego audytu", None),
    ("apple_expo", 4): ("iScanner 'Pro' weekly subscription", "Aplikacja do skanowania dokumentów (iScanner)", None),
    ("apple_expo", 5): ("Domain infocentral.pl, one year", None, ("other_and_excluded", 17)),
    ("apple_expo", 6): ("Domain infocentrala.pl, one year", None, ("other_and_excluded", 18)),
    ("apple_expo", 7): ("Law-firm website domain, one year", None, ("other_and_excluded", 34)),
    ("apple_expo", 8): ("5K events per month", None, ("other_and_excluded", 19)),
    ("apple_expo", 9): ("Domain 638204.xyz", None, ("other_and_excluded", 16)),
    ("apple_expo", 10): ("Uptime monitors (7", None, ("other_and_excluded", 21)),
    ("apple_expo", 11): ("Web-scraping API", None, ("other_and_excluded", 42)),
    ("apple_expo", 12): ("Cursor editor", None, ("other_and_excluded", 44)),
    ("apple_expo", 13): ("Google AI Plus (2 TB), monthly", None, ("other_and_excluded", 14)),
    ("apple_expo", 14): ("Business Standard for the law-firm domain", None, ("other_and_excluded", 35)),
    ("apple_expo", 15): ("1Password annual plan", None, ("other_and_excluded", 46)),
    ("other_and_excluded", 0): (
        "Claude Max 20x plan, monthly renewal of 2026-03",
        "Plan Claude Max, Twoje konto (odnowienie marcowe)",
        None,
    ),
    ("other_and_excluded", 1): (
        "Claude Max 20x plan, monthly renewal of 2026-04",
        "Plan Claude Max, Twoje konto (odnowienie kwietniowe)",
        None,
    ),
    ("other_and_excluded", 2): ("Claude prepaid extra usage", "Dodatkowe użycie Claude (przedpłata)", None),
    ("other_and_excluded", 3): ("Claude Max 20x plan, renewals of Feb", "Plan Claude Max: pozostałe odnowienia", None),
    ("other_and_excluded", 4): (
        "Claude Max 20x plan, monthly renewal of 2026-10",
        "Plan Claude Max, Twoje konto (odnowienie październikowe)",
        None,
    ),
    ("other_and_excluded", 5): (
        "Second claude.ai Max 20x plan in a separate",
        "Drugi plan Claude Max (osobna organizacja)",
        None,
    ),
    ("other_and_excluded", 6): (
        "Second claude.ai Max 20x plan, renewal",
        "Drugi plan Claude Max: odnowienie wrześniowe",
        None,
    ),
    ("other_and_excluded", 7): ("Claude Code coding sessions", "Sesje Claude Code, w których powstał Sentinel", None),
    ("other_and_excluded", 8): ("ChatGPT Pro, one seat", "ChatGPT Pro", None),
    ("other_and_excluded", 9): ("ChatGPT Business workspace", "ChatGPT Business dla kancelarii", None),
    ("other_and_excluded", 10): ("Codex CLI and other tools", "Codex i inne narzędzia na loginie ChatGPT", None),
    ("other_and_excluded", 11): ("Google AI Ultra (30 TB), invoice of 2026-03", "Google AI Ultra (marzec)", None),
    ("other_and_excluded", 12): ("Google AI Ultra (30 TB), invoice of 2026-04", "Google AI Ultra (kwiecień)", None),
    ("other_and_excluded", 13): ("Google AI Ultra, May to Sep", "Google AI Ultra (maj–wrzesień)", None),
    ("other_and_excluded", 14): ("Google AI Plus (2 TB), from", "Google AI Plus", None),
    ("other_and_excluded", 15): ("msigalert VPS", "Serwer VPS msigalert (Netcup)", None),
    ("other_and_excluded", 16): ("msigalert sending domain", "Domena wysyłkowa msigalert (.xyz)", None),
    ("other_and_excluded", 17): ("msigalert domain infocentral.pl", "Domena infocentral.pl", None),
    ("other_and_excluded", 18): ("msigalert domain infocentrala.pl", "Domena infocentrala.pl", None),
    ("other_and_excluded", 19): ("msigalert product analytics", "Analityka OpenPanel dla msigalert", None),
    ("other_and_excluded", 20): ("msigalert accuracy-verifier keys", None, ("anthropic", 1)),
    ("other_and_excluded", 21): ("Uptime monitors for msigalert", "Monitoring Better Stack dla msigalert", None),
    ("other_and_excluded", 22): ("Transactional email for msigalert", "Poczta Resend dla msigalert", None),
    ("other_and_excluded", 23): ("DNS zones for the msigalert", "Strefy DNS Cloudflare dla msigalert", None),
    ("other_and_excluded", 24): ("Zone activation of konsumencka.ai", "Cloudflare: inne domeny", None),
    ("other_and_excluded", 25): ("msigalert tooling on free plans", "Backblaze, Tailscale i Slack (darmowe)", None),
    ("other_and_excluded", 26): ("MemSearchBacklog key", "Klucz MemSearchBacklog (zasilenie pamięci rozmów)", None),
    ("other_and_excluded", 27): (
        "Billing account for the gtasks-cli project, payment of 2026-09",
        "Google Cloud: projekt gtasks-cli (płatność wrześniowa)",
        None,
    ),
    ("other_and_excluded", 28): (
        "Billing account for the gtasks-cli project, payment of 2026-10",
        "Google Cloud: projekt gtasks-cli (płatność październikowa)",
        None,
    ),
    ("other_and_excluded", 29): (
        "Google Cloud free-trial start",
        "Google Cloud i Gemini: powiadomienia bez opłat",
        None,
    ),
    ("other_and_excluded", 30): ("OCR for CourtOCR", "Google Cloud Vision (OCR dla innych narzędzi)", None),
    ("other_and_excluded", 31): ("Embeddings for the legal-rag", "Voyage AI (projekt legal-rag)", None),
    ("other_and_excluded", 32): ("jev-skill usage for mail", None, ("openrouter_typesafe", 5)),
    ("other_and_excluded", 33): ("Domain registration for another project", "Domena konsumencka.ai", None),
    ("other_and_excluded", 34): ("Law-firm website domain", "Domena strony kancelarii", None),
    ("other_and_excluded", 35): ("Law-firm email domain", "Google Workspace dla kancelarii", None),
    ("other_and_excluded", 36): ("Email sending for the law-firm", "Amazon SES dla formularzy kancelarii", None),
    ("other_and_excluded", 37): ("LEX and Legalis", "Bazy prawnicze i księgowość kancelarii", None),
    ("other_and_excluded", 38): ("Office stamps", "Koszty biurowe kancelarii", None),
    ("other_and_excluded", 39): (
        "Online purchase of unstated purpose",
        "KartotekaOnline.pl: zakup o nieznanym celu",
        None,
    ),
    ("other_and_excluded", 40): ("OpenCode coding-agent key, usage on 2026-08", None, ("openrouter_typesafe", 0)),
    ("other_and_excluded", 41): ("OpenCode coding-agent key, usage on 2026-10", None, ("openrouter_typesafe", 1)),
    ("other_and_excluded", 42): ("Web-scraping MCP", "Firecrawl (narzędzie badawcze w sesjach kodowania)", None),
    ("other_and_excluded", 43): (
        "Search and documentation MCPs",
        "Exa i Context7 (narzędzia w sesjach kodowania)",
        None,
    ),
    ("other_and_excluded", 44): ("Code editor", "Edytor Cursor", None),
    ("other_and_excluded", 45): ("Dictation app", "Wispr Flow (dyktowanie)", None),
    ("other_and_excluded", 46): ("Personal password manager", "Menedżer haseł 1Password", None),
    ("other_and_excluded", 47): ("Personal document-scanner", None, ("apple_expo", 4)),
    ("other_and_excluded", 48): ("Owner's personal mobile phone plan", "Twój abonament komórkowy", None),
    ("other_and_excluded", 49): ("Personal and household spending", "Wydatki osobiste i domowe", None),
    ("other_and_excluded", 50): ("Learning-platform receipt", "Boot.dev (nauka)", None),
    ("other_and_excluded", 51): ("AI prompt-tool receipt", "Prompt Genie", None),
    ("other_and_excluded", 52): ("Credit-card repayment", "Spłata karty kredytowej (dublowałaby zakupy)", None),
    ("other_and_excluded", 53): ("Declined card payment", "Odrzucona płatność Google Cloud", None),
}

# Facts used in the Polish prose. Each value is extracted from a quote that must appear verbatim in
# the named input field, so the report never carries a hand-typed date or number.
FACT_SPECS = [
    ("anthropic_outage_start", "anthropic", ("operational_risks", 0), "from 2026-09-17 10:07 UTC", "datetime"),
    ("anthropic_outage_end", "anthropic", ("operational_risks", 0), "to 2026-09-19 23:19 UTC", "datetime"),
    (
        "anthropic_switch_date",
        "anthropic",
        ("run_rate", 0, "notes"),
        "moved its classifier to OpenAI on 2026-09-20",
        "date",
    ),
    ("twilio_suspended_since", "twilio", ("operational_risks", 0), "Since 2026-08-23 17:21 UTC", "datetime"),
    ("twilio_rejected_attempts", "twilio", ("operational_risks", 0), "290 call and 290 SMS attempts rejected", "int"),
    ("twilio_rejected_from", "twilio", ("operational_risks", 0), "between 2026-09-15 and", "date"),
    ("twilio_next_us_renewal", "twilio", ("run_rate", 2, "basis"), "next 2026-10-21", "date"),
    ("twilio_next_pl_renewal", "twilio", ("run_rate", 1, "basis"), "next 2026-10-28", "date"),
    ("openai_busiest_day_usd", "openai", ("run_rate", 0, "notes"), "Oct 13 cost $0.880", "money"),
    ("openai_app_budget_usd", "openai", ("operational_risks", 3), "Sentinel's own app budget is $30 a month", "money"),
    ("apple_licence_deadline", "apple_expo", ("operational_risks", 0), "by 2026-11-13", "date"),
    ("apple_membership_end", "apple_expo", ("operational_risks", 1), "the membership ends on 2027-06-01", "date"),
    ("mail_cleanup_date", "anthropic", ("operational_risks", 4), "the 2026-10-02 cleanup", "date"),
    ("twilio_u9_events", "twilio", ("operational_risks", 0), "48 distinct urgency 9-10 events", "int"),
    ("openai_topup_time", "openai", ("cash_events", 3, "notes"), "sent 2026-10-14 20:15", "datetime"),
    ("cash_evidence_checked", "openai", ("cash_events", 3, "notes"), "up to 2026-10-14 21:38", "datetime"),
    ("openai_reload_trigger_usd", "openai", ("operational_risks", 0), "when the balance falls to $5", "money"),
    ("openai_reload_target_usd", "openai", ("operational_risks", 0), "it reloads to $20", "money"),
    ("openai_cap_raised_date", "openai", ("operational_risks", 1), "Resolved 2026-10-14", "date"),
    ("openai_cap_old_usd", "openai", ("operational_risks", 1), "spend limit from $10", "money"),
    ("openai_cap_new_usd", "openai", ("operational_risks", 1), "to $30 (still 'Limit enforced')", "money"),
    ("openai_cap_used_usd", "openai", ("operational_risks", 1), "the portal showed $8.48", "money"),
    ("openai_cap_read_time", "openai", ("operational_risks", 1), "at about 2026-10-14 22:00 UTC", "datetime"),
    ("openai_spend_alert_usd", "openai", ("operational_risks", 1), "existing $10 spend alert", "money"),
    ("openai_sharing_check_from", "openai", ("open_questions", 5), "After 2026-10-15 00:00 UTC", "date"),
]

# Every open question of the inputs, sorted for the owner: (group, index) -> (expected English prefix,
# category, urgent, Polish summary). Categories: decide = his decision; document = a document to provide
# or a check to make; info = for information only. The English original is shown under each summary.
QUESTION_CATEGORIES = [
    ("decide", "Do decyzji"),
    ("document", "Do zrobienia: dokument lub sprawdzenie"),
    ("info", "Do wiadomości"),
]
QUESTION_MAP = {
    ("anthropic", 0): (
        "Owner decision: the Sep 19",
        "decide",
        False,
        "Czy w widoku gotówki przypisać Sentinelowi cały wrześniowy zakup kredytu Anthropic, który "
        "ratował go po awarii? Domyślnie liczę tylko część, którą Sentinel z niego zużył.",
    ),
    ("anthropic", 1): (
        "Invoice numbers",
        "info",
        False,
        "Brakujące numery faktur w konsoli Anthropic pasują do nieudanych płatności. Saldo się zgadza, "
        "więc nie ma ukrytych zakupów; potwierdzenie ma niski priorytet.",
    ),
    ("anthropic", 2): (
        "Billing settings history",
        "decide",
        False,
        "Czy automatyczne doładowanie w Anthropic ma zostać włączone, skoro konta używa już tylko "
        "msigalert? Czy powiadomienie o progu wydatków usunięto celowo?",
    ),
    ("anthropic", 3): (
        "Should the still-active Project Sentinel",
        "decide",
        False,
        "Wycofać wciąż aktywny klucz API Sentinela w Anthropic czy zostawić go na wypadek powrotu do "
        "Claude Haiku? Jeśli zostaje, dodaj powiadomienie o wydatkach i kontrolę salda w monitoringu "
        "Sentinela.",
    ),
    ("anthropic", 4): (
        "The repo note of an",
        "info",
        False,
        "Kwota rachunku za Claude Haiku zapisana w repozytorium nie pasuje do żadnego miesiąca; to "
        "prawdopodobnie widok z ostatnich trzydziestu dni. Nie zmienia żadnej kwoty.",
    ),
    ("anthropic", 5): (
        "Evidence quality",
        "document",
        False,
        "Pobierz ponownie z konsoli Anthropic miesięczne eksporty kosztów dla klucza Sentinela; część "
        "z nich przepisano ze strony zamiast pobrać plik.",
    ),
    ("openai", 0): (
        "The 2026-10-14 top-up is recorded",
        "document",
        True,
        "Pobierz fakturę i paragon za dzisiejsze doładowanie OpenAI. Automatyczne doładowanie jest "
        "już znowu włączone; zostaje sprawdzić, czy karta przyjmie następne automatyczne obciążenie.",
    ),
    ("openai", 1): (
        "Will the owner raise the Project Sentinel",
        "info",
        False,
        "Rozwiązane {cap_date}: limit projektu Sentinel w OpenAI podniesiony z {cap_old} do {cap_new} "
        "(potwierdzone w panelu).",
    ),
    ("openai", 2): (
        "Why did the 2026-10-08 auto-recharge",
        "document",
        False,
        "Ustal, dlaczego karta została odrzucona przy automatycznym doładowaniu OpenAI (wcześniej także "
        "w Anthropic): ważność, limit, blokada w banku czy weryfikacja płatności.",
    ),
    ("openai", 3): (
        "After 2026-10-15 00:00 UTC",
        "document",
        False,
        "Po północy UTC wyeksportuj z panelu OpenAI koszty października według projektu i pozycji; "
        "dokładna kwota zastąpi pomiar i szacunek ostatnich godzin dnia audytu.",
    ),
    ("openai", 4): (
        "While the owner has the portal open",
        "document",
        True,
        "Skoro panel OpenAI jest otwarty: zapisz eksport kosztów według projektu za miesiące przed "
        "wrześniowym zakupem kredytu (powinien być pusty) oraz zrzuty ekranu historii płatności, "
        "przyznanych kredytów i limitów projektu Sentinel.",
    ),
    ("openai", 5): (
        "After 2026-10-15 00:00 UTC, check the OpenAI usage dashboard",
        "document",
        False,
        "Po {share_check} sprawdzić w panelu OpenAI (Usage, grupowanie po „service tier”), czy darmowe "
        "tokeny za udostępnianie danych obejmują model Sentinela. Jeśli tak, koszt OpenAI spadnie z ok. "
        "{rr_now} do ok. {rr_shared} miesięcznie.",
    ),
    ("openai", 6): (
        "Should data sharing be limited to Project Sentinel only",
        "decide",
        False,
        "Czy ograniczyć udostępnianie danych OpenAI do samego projektu Sentinel? Dziś konto obsługuje "
        "tylko Sentinela, ale zmiana chroni przyszłe projekty na tym koncie.",
    ),
    ("openrouter_typesafe", 0): (
        "The TypeSafe console",
        "document",
        False,
        "Otwórz panel TypeSafe (rozliczenia i zużycie). Potwierdzi darmowy kredyt, wrześniowe "
        "zużycie Jev, kwotę październikowego zakupu i brak innych zakupów.",
    ),
    ("openrouter_typesafe", 1): (
        "Informational, not a blocker",
        "decide",
        False,
        "Wrześniowe doładowanie OpenRouter kupiono przy testach Sentinela, ale nic z niego "
        "jeszcze nie zużyto, więc według zasady FIFO udział Sentinela to zero. Jeśli wolisz "
        "przypisywać zakupy według ich celu, daj znać.",
    ),
    ("openrouter_typesafe", 2): (
        "OpenRouter credit expiry",
        "document",
        False,
        "Sprawdź w regulaminie OpenRouter, czy niewykorzystane kredyty wygasają. Ewentualna "
        "strata dotyczyłaby wspólnego salda, nie kosztu Sentinela.",
    ),
    ("twilio", 0): (
        "Why do the July and August statements",
        "document",
        False,
        "Wyeksportuj z Twilio zużycie połączeń głosowych za czerwiec, lipiec i sierpień. Rozstrzygnie, "
        "czy Twilio doliczy nierozliczone połączenia z lipca i sierpnia.",
    ),
    ("twilio", 1): (
        "The USD 9.15 of accrued renewals",
        "document",
        False,
        "Październikowy wyciąg Twilio albo eksport transakcji oczekujących potwierdzi opłaty za numery "
        "naliczone w czasie zawieszenia.",
    ),
    ("twilio", 2): (
        "Owner decision: keep both numbers",
        "decide",
        False,
        "Numery Twilio: zostawić oba (dług rośnie co miesiąc), zwolnić nieużywany numer amerykański czy "
        "zwolnić oba? Warto też ustalić, jak długo Twilio odnawia numery na zawieszonym koncie.",
    ),
    ("twilio", 3): (
        "In which currency were the three cards",
        "document",
        False,
        "Wyciągi z kart pokażą dokładne kwoty w złotych za płatności Twilio, razem z prowizją za przewalutowanie.",
    ),
    ("twilio", 4): (
        "Trial credit",
        "info",
        False,
        "Niewykorzystana reszta darmowego kredytu próbnego Twilio przepadła przy przejściu na konto "
        "płatne; Twilio nigdzie tego nie pokazuje.",
    ),
    ("twilio", 5): (
        "Usage summaries for April-July",
        "document",
        False,
        "Otwórz w konsoli Twilio podsumowania zużycia od kwietnia do lipca i potwierdź, że od lipca nie "
        "było żadnych płatności.",
    ),
    ("hetzner", 0): (
        "The October 2026 invoice",
        "document",
        False,
        "Gdy Hetzner wystawi fakturę za październik, zastąpi ona naliczenie z tego audytu.",
    ),
    ("hetzner", 1): (
        "Actual PLN cost of the four card",
        "document",
        False,
        "Wyciąg z karty pokaże rzeczywisty koszt płatności Hetzner w złotych i ewentualne prowizje.",
    ),
    ("hetzner", 2): (
        "Second CX23 in March",
        "info",
        False,
        "Drugi serwer w marcu działał tylko kilka godzin w projekcie Sentinel; wpływ na koszt jest pomijalny.",
    ),
    ("apple_expo", 0): (
        "Apple invoice",
        "document",
        False,
        "Pobierz fakturę Apple za majowe członkostwo w Developer Program (status zamówienia albo "
        "zakładka Membership). Potwierdzi kwotę, VAT i kartę.",
    ),
    ("apple_expo", 1): (
        "Apple charge",
        "document",
        False,
        "Wyciąg z karty pokaże dokładną datę i kwotę obciążenia za członkostwo Apple.",
    ),
    ("apple_expo", 2): (
        "Apple renewal",
        "decide",
        False,
        "Czy odnowisz ręcznie członkostwo Apple Developer przed jego wygaśnięciem? Automatyczne "
        "odnowienie jest wyłączone.",
    ),
    ("apple_expo", 3): (
        "Expo evidence",
        "document",
        False,
        "Zapisz zrzuty stron rozliczeń i paragonów w expo.dev i sprawdź, czy jest tam zapisana karta.",
    ),
    ("apple_expo", 4): (
        "Fourth mailbox",
        "decide",
        False,
        "Czy przeszukać czwartą skrzynkę Gmail, której audyt nie przeszukał (konto Expo założone "
        "logowaniem Google oraz konto Claude Code), pod kątem rachunków Expo lub Apple?",
    ),
    ("apple_expo", 5): (
        "GitHub plan",
        "info",
        False,
        "Możesz potwierdzić w ustawieniach rozliczeń GitHub, że konto jest na darmowym planie; koszt "
        "Sentinela i tak wynosi zero.",
    ),
    ("other_and_excluded", 0): (
        "KartotekaOnline.pl",
        "decide",
        False,
        "Co kupiono w KartotekaOnline.pl? Domyślnie nie jest to koszt Sentinela; potwierdź.",
    ),
    ("other_and_excluded", 1): (
        "Google Cloud billing account",
        "info",
        False,
        "Konto rozliczeniowe Google Cloud (projekt gtasks-cli) nie dotyczy Sentinela; podgląd "
        "projektów i faktur w konsoli Google Cloud by to potwierdził.",
    ),
    ("other_and_excluded", 2): (
        "Side note with no cost impact",
        "info",
        False,
        "Bez wpływu na koszty: w Hetznerze nie ma żadnej zapory sieciowej, choć dokumentacja "
        "opisuje zaporę dla Sentinela.",
    ),
}

# Questions that no single provider group owns: key -> (summary group, category, urgent, Polish template).
# The VAT amounts are computed in build(). The CLAUDE.md line is only a proposal: CLAUDE.md changes are
# presented to the owner first and never applied by the audit.
CLAUDE_MD_PROPOSED_LINE = "Cost register and new-cost rule → [docs/reference/costs.md](docs/reference/costs.md)"
CROSS_QUESTIONS = {
    "reverse_charge_vat": (
        "cross_provider",
        "decide",
        False,
        "Pytanie podatkowe: {names} wystawiają faktury bez VAT (odwrotne obciążenie na Twój "
        "NIP), więc sumy w raporcie nie zawierają tego VAT. Jeśli naliczonego VAT nie odliczasz, "
        "prawdziwy koszt tych dostawców rośnie o VAT ({rate}): o około {econ} od początku "
        "projektu i o około {month} miesięcznie. VAT w OpenRouter i w cenie Apple jest już w "
        "koszcie. Sumy zostawiam bez zmian, zgodnie z przyjętą zasadą.",
    ),
    "claude_md_pointer": (
        "maintenance",
        "decide",
        False,
        "Propozycja (w CLAUDE.md niczego nie zmieniłem): agenci czytają plik CLAUDE.md "
        "automatycznie, ale nie ma w nim odnośnika do rejestru kosztów. Zasada „agent, który "
        "zauważy nowy koszt, najpierw pyta Ciebie” jest tylko w docs/reference/costs.md. Czy "
        "dopisać w sekcji Docs pliku CLAUDE.md jedną linię: „{line}”?",
    ),
}


# --------------------------------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------------------------------
def dec(x):
    if x is None:
        return None
    if isinstance(x, bool):
        raise TypeError("boolean where a number was expected")
    if isinstance(x, Decimal):
        return x
    if isinstance(x, int):
        return Decimal(x)
    raise TypeError(f"not a number: {x!r}")


def num(x):
    return None if x is None else format(x, "f")


def q2(x):
    return x.quantize(CENT, rounding=ROUND_HALF_UP)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tf(x):
    return "true" if x else "false"


def csv_bytes(header, rows):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    for row in rows:
        w.writerow(["" if v is None else v for v in row])
    return buf.getvalue().encode("utf-8")


def month_last_day(month):
    y, m = map(int, month.split("-"))
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    return nxt - timedelta(days=1)


class FX:
    def __init__(self, path):
        self.rates = defaultdict(list)
        with path.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                self.rates[row["currency"]].append(
                    (date.fromisoformat(row["date"]), Decimal(row["mid_pln"]), row["nbp_table"])
                )
        for cur in self.rates:
            self.rates[cur].sort()

    def on_or_before(self, cur, d):
        if cur == "PLN":
            return None, Decimal(1), None
        best = None
        for row in self.rates.get(cur, []):
            if row[0] <= d:
                best = row
            else:
                break
        if best is None:
            raise ValueError(f"no NBP rate for {cur} on or before {d}")
        return best

    def month_end(self, cur, month):
        return self.on_or_before(cur, min(month_last_day(month), AS_OF_DATE))

    def before(self, cur, d):
        return self.on_or_before(cur, d - timedelta(days=1))


def fx_fields(fxrow):
    d, rate, table = fxrow
    return (d.isoformat() if d else None), rate, table


def field(result, path):
    obj = result
    for key in path:
        obj = obj[key]
    return obj


def extract_fact(text, quote, kind):
    if quote not in text:
        raise ValueError(f"fact quote not found in input: {quote!r}")
    if kind == "datetime":
        m = re.search(r"(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2})", quote)
        return f"{m.group(1)}T{m.group(2)}Z"
    if kind == "date":
        return re.search(r"\d{4}-\d{2}-\d{2}", quote).group(0)
    if kind == "int":
        return re.search(r"\d+", quote).group(0)
    if kind == "money":
        return re.search(r"\$(\d+(?:\.\d+)?)", quote).group(1)
    raise ValueError(kind)


def line_label(line_id):
    for pattern, label in LINE_LABEL_RULES:
        if re.search(pattern, line_id):
            return label
    raise ValueError(f"no Polish label for line {line_id}")


def period_iso(text):
    """First date or date range in a period string, as ISO parts (None when there is none)."""
    if not text:
        return None
    m = re.search(r"(\d{4}-\d{2}(?:-\d{2})?)(?:\.\.(\d{4}-\d{2}(?:-\d{2})?))?", text)
    if not m:
        return None
    return [m.group(1), m.group(2)]


def check_static_text():
    texts = []
    texts += [v for v in MONTH_NAMES.values()] + [v for v in MONTH_SHORT.values()]
    for name, desc in PROVIDER_PL.values():
        texts += [name, desc]
    texts += list(EVIDENCE_PL.values()) + list(KIND_PL.values())
    texts += [label for _, label in LINE_LABEL_RULES]
    for label, expl in RUNRATE_PL.values():
        texts += [label] + ([expl] if expl else [])
    for title, why in REASON_PL.values():
        texts += [title, why]
    texts += [v[1] for v in EXCLUDED_MAP.values() if v[1]]
    texts += [label for _, label in QUESTION_CATEGORIES]
    for t in texts:
        T(t)
    for _, category, _, template in QUESTION_MAP.values():  # may carry placeholders filled in build()
        if category not in dict(QUESTION_CATEGORIES):
            raise ValueError(f"unknown question category {category}")
        T(template, **{k: "" for k in re.findall(r"\{(\w+)\}", template)})
    for _, category, _, template in CROSS_QUESTIONS.values():  # templates with placeholders: digits only
        if category not in dict(QUESTION_CATEGORIES):
            raise ValueError(f"unknown question category {category}")
        T(template, **{k: "" for k in re.findall(r"\{(\w+)\}", template)})


# --------------------------------------------------------------------------------------------------
# Build: compute every table and the summary
# --------------------------------------------------------------------------------------------------
def build():
    check_static_text()
    data = json.loads(IN_LINES.read_text(encoding="utf-8"), parse_float=Decimal)
    if [g["group"] for g in data] != GROUP_ORDER:
        raise ValueError("unexpected provider groups in lines.json")
    groups = {g["group"]: g["result"] for g in data}
    fx = FX(IN_NBP)

    # ---------------- ledger (economic lines) ----------------
    ledger = []
    seen = set()
    for gname in GROUP_ORDER:
        for ln in groups[gname]["lines"]:
            lid = ln["line_id"]
            if lid in seen:
                raise ValueError(f"duplicate line_id {lid}")
            seen.add(lid)
            month = ln["month"]
            if month not in MONTHS:
                raise ValueError(f"{lid}: month {month} outside the audit")
            if ln["evidence_class"] not in EVIDENCE_PL:
                raise ValueError(f"{lid}: unknown evidence class {ln['evidence_class']}")
            amt = dec(ln["amount_native"])
            in_total = bool(ln["in_total"])
            if amt is None and (in_total or ln["evidence_class"] != "unknown"):
                raise ValueError(f"{lid}: unknown amount must be evidence_class unknown and out of total")
            fxd, rate, table = fx_fields(fx.month_end(ln["currency"], month))
            dup = DUPLICATE_LINES.get(lid)
            ledger.append(
                {
                    "line_id": lid,
                    "group": gname,
                    "provider": ln["provider"],
                    "item": ln["item"],
                    "label_pl": line_label(lid),
                    "basis": ln["basis"],
                    "month": month,
                    "period_start": ln.get("period_start"),
                    "period_end": ln.get("period_end"),
                    "currency": ln["currency"],
                    "amount": amt,
                    "in_total": in_total,
                    "duplicate_of": dup,
                    "counted": in_total and dup is None and amt is not None,
                    "evidence_class": ln["evidence_class"],
                    "sentinel_share": dec(ln.get("sentinel_share")),
                    "gross": dec(ln.get("gross_account_amount_native")),
                    "fx_date": fxd,
                    "fx_table": table,
                    "fx_rate": rate,
                    "pln": None if amt is None else amt * rate,
                    "label": ln["public_evidence_label"],
                    "notes": ln.get("notes", ""),
                }
            )
    by_id = {r["line_id"]: r for r in ledger}
    for lid, canon in DUPLICATE_LINES.items():
        a, b = by_id[lid], by_id[canon]
        if (a["month"], a["amount"], a["currency"]) != (b["month"], b["amount"], b["currency"]):
            raise ValueError(f"duplicate {lid} does not match {canon}")
    counted = [r for r in ledger if r["counted"]]
    for r in counted:
        if r["provider"] not in PROVIDER_ORDER:
            raise ValueError(f"provider {r['provider']} missing from PROVIDER_ORDER")
    pidx = {p: i for i, p in enumerate(PROVIDER_ORDER)}

    # ---------------- monthly matrix ----------------
    cells = {}
    for r in counted:
        key = (r["month"], r["provider"], r["currency"])
        c = cells.setdefault(
            key,
            {
                "native": ZERO,
                "pln": ZERO,
                "n": 0,
                "fx_date": r["fx_date"],
                "fx_rate": r["fx_rate"],
                "fx_table": r["fx_table"],
            },
        )
        if (c["fx_date"], c["fx_rate"]) != (r["fx_date"], r["fx_rate"]):
            raise ValueError(f"inconsistent FX inside cell {key}")
        c["native"] += r["amount"]
        c["pln"] += r["pln"]
        c["n"] += 1
    month_tot = {m: ZERO for m in MONTHS}
    for (m, _p, _cur), c in cells.items():
        month_tot[m] += c["pln"]
    grand = sum(month_tot.values(), ZERO)
    if grand != sum((r["pln"] for r in counted), ZERO):
        raise ValueError("monthly total does not equal ledger total")
    econ_native = defaultdict(lambda: ZERO)
    prov = defaultdict(lambda: {"native": defaultdict(lambda: ZERO), "pln": ZERO})
    for r in counted:
        econ_native[r["currency"]] += r["amount"]
        prov[r["provider"]]["native"][r["currency"]] += r["amount"]
        prov[r["provider"]]["pln"] += r["pln"]
    notes_out = [r for r in ledger if not r["in_total"] and r["duplicate_of"] is None]

    # ---------------- cash ----------------
    cash = []
    for gname in GROUP_ORDER:
        for ev in groups[gname]["cash_events"]:
            d = date.fromisoformat(ev["date"])
            fxd, rate, table = fx_fields(fx.before(ev["currency"], d))
            amt = dec(ev["amount_native"])
            s_amt = dec(ev["sentinel_amount_native"])
            failed = ev["kind"] == "failed_not_charged"
            if ev["kind"] not in KIND_PL:
                raise ValueError(f"unknown cash kind {ev['kind']}")
            cash.append(
                {
                    "date": ev["date"],
                    "group": gname,
                    "provider": ev["provider"],
                    "kind": ev["kind"],
                    "amount": amt,
                    "currency": ev["currency"],
                    "share": dec(ev.get("sentinel_share")),
                    "sentinel_amount": s_amt,
                    "counted": (not failed) and s_amt is not None,
                    "fx_date": fxd,
                    "fx_table": table,
                    "fx_rate": rate,
                    "pln": None if amt is None else amt * rate,
                    "sentinel_pln": None if s_amt is None else s_amt * rate,
                    "evidence_class": ev["evidence_class"],
                    "label": ev["public_evidence_label"],
                    "notes": ev.get("notes", ""),
                }
            )
    cash.sort(key=lambda e: (e["date"], pidx.get(e["provider"], 99)))  # stable: input order within a day
    cash_native = defaultdict(lambda: ZERO)
    cash_prov = defaultdict(lambda: {"native": defaultdict(lambda: ZERO), "pln": ZERO})
    for e in cash:
        if e["counted"]:
            cash_native[e["currency"]] += e["sentinel_amount"]
            cash_prov[e["provider"]]["native"][e["currency"]] += e["sentinel_amount"]
            cash_prov[e["provider"]]["pln"] += e["sentinel_pln"]
    cash_total = sum((e["sentinel_pln"] for e in cash if e["counted"]), ZERO)

    # ---------------- current monthly (run-rate) ----------------
    runrate = []
    for gname in GROUP_ORDER:
        for i, it in enumerate(groups[gname]["run_rate"]):
            per, lo, hi = dec(it["per_month_native"]), dec(it.get("low")), dec(it.get("high"))
            fxd, rate, table = fx_fields(fx.on_or_before(it["currency"], AS_OF_DATE))
            dup = DUPLICATE_RUNRATE.get((gname, i))
            if dup and not it["item"].startswith(dup[2]):
                raise ValueError(f"run-rate duplicate mapping mismatch at {gname}[{i}]")
            label, expl = RUNRATE_PL[(gname, i)]
            in_total = bool(it["in_total"])
            runrate.append(
                {
                    "group": gname,
                    "index": i,
                    "provider": it["provider"],
                    "item": it["item"],
                    "label_pl": label,
                    "explain_pl": expl,
                    "currency": it["currency"],
                    "per": per,
                    "low": lo,
                    "high": hi,
                    "fx_date": fxd,
                    "fx_table": table,
                    "fx_rate": rate,
                    "pln": per * rate,
                    "low_pln": None if lo is None else lo * rate,
                    "high_pln": None if hi is None else hi * rate,
                    "in_total": in_total,
                    "scenario": not in_total,
                    "duplicate_of": f"{dup[0]}#{dup[1]}" if dup else None,
                    "counted": in_total and dup is None,
                    "basis": it["basis"],
                    "notes": it.get("notes", ""),
                }
            )
    rr_counted = [r for r in runrate if r["counted"]]
    rr_total = sum((r["pln"] for r in rr_counted), ZERO)
    rr_low = sum((r["low_pln"] if r["low_pln"] is not None else r["pln"] for r in rr_counted), ZERO)
    rr_high = sum((r["high_pln"] if r["high_pln"] is not None else r["pln"] for r in rr_counted), ZERO)
    rr_native = defaultdict(lambda: ZERO)
    rr_prov = defaultdict(lambda: ZERO)
    for r in rr_counted:
        rr_native[r["currency"]] += r["per"]
        rr_prov[r["provider"]] += r["pln"]

    # ---------------- reverse-charge VAT (outside every total) ----------------
    for p, gname, path, quote in REVERSE_CHARGE:
        if quote not in field(groups[gname], path):
            raise ValueError(f"reverse-charge evidence for {p} not found in {gname} inputs: {quote!r}")
    for p in set(prov) | set(rr_prov):
        nonzero = (p in prov and prov[p]["pln"] != 0) or rr_prov.get(p, ZERO) != 0
        if nonzero and p not in RC_NAMES and p not in VAT_PAID_PROVIDERS:
            raise ValueError(f"{p} has a cost but no stated VAT treatment (REVERSE_CHARGE or VAT_PAID_PROVIDERS)")
    rc_rows = []
    for p in RC_NAMES:
        e_pln = prov[p]["pln"] if p in prov else ZERO
        m_pln = rr_prov.get(p, ZERO)
        rc_rows.append(
            {
                "provider": p,
                "economic_pln": num(e_pln),
                "economic_vat_pln": num(e_pln * PL_VAT_RATE),
                "current_monthly_pln": num(m_pln),
                "current_monthly_vat_pln": num(m_pln * PL_VAT_RATE),
            }
        )
    rc_econ = sum((prov[p]["pln"] for p in RC_NAMES if p in prov), ZERO)
    rc_month = sum((rr_prov.get(p, ZERO) for p in RC_NAMES), ZERO)
    rc_vat_econ = rc_econ * PL_VAT_RATE
    rc_vat_month = rc_month * PL_VAT_RATE

    # ---------------- excluded catalogue ----------------
    excluded = []
    for gname in GROUP_ORDER:
        for i, e in enumerate(groups[gname]["excluded"]):
            spec = EXCLUDED_MAP.get((gname, i))
            if spec is None or not e["item"].startswith(spec[0]):
                raise ValueError(f"excluded mapping missing or stale at {gname}[{i}]: {e['item'][:40]!r}")
            excluded.append(
                {
                    "group": gname,
                    "index": i,
                    "provider": e["provider"],
                    "item": e["item"],
                    "reason": e["reason"],
                    "amount": dec(e.get("amount_native")),
                    "currency": e.get("currency"),
                    "period": e.get("period"),
                    "notes": e.get("notes", ""),
                    "label_pl": spec[1],
                    "duplicate_of": f"{spec[2][0]}#{spec[2][1]}" if spec[2] else None,
                }
            )
    if len(excluded) != len(EXCLUDED_MAP):
        raise ValueError("EXCLUDED_MAP has entries that match no excluded item")
    ex_key = {f"{e['group']}#{e['index']}": e for e in excluded}
    for e in excluded:
        if e["duplicate_of"]:
            target = ex_key[e["duplicate_of"]]
            if target["duplicate_of"]:
                raise ValueError(f"duplicate chain at {e['duplicate_of']}")
        if e["reason"] not in REASON_PL:
            raise ValueError(f"unknown exclusion reason {e['reason']}")

    # ---------------- previous audit (comparison only) ----------------
    prev_summary = json.loads((PREV / "summary.json").read_text(encoding="utf-8"))
    prev_prov = defaultdict(lambda: ZERO)
    with (PREV / "cost-items.csv").open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["pln_aggregation_basis"]:
                prev_prov[row["provider"]] += Decimal(row["pln_aggregation_basis"])
    prev_total = Decimal(prev_summary["historical"]["PLN"]["reconstructed_total"])
    if sum(prev_prov.values(), ZERO) != prev_total:
        raise ValueError("previous audit cost items do not add up to its total")
    prev_rr_prov = defaultdict(lambda: ZERO)
    with (PREV / "current-monthly.csv").open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["included_in_total"] == "true" and row["pln_equivalent"]:
                prev_rr_prov[row["provider"]] += Decimal(row["pln_equivalent"])
    prev_current = Decimal(prev_summary["current_monthly_pln_equivalent"])
    if sum(prev_rr_prov.values(), ZERO) != prev_current:
        raise ValueError("previous audit current-monthly lines do not add up to its total")
    prev_months = {m["month"]: Decimal(m["reconstructed_total"]) for m in prev_summary["monthly_changes"]}
    prev_est_share = Decimal(prev_summary["historical"]["PLN"]["estimated_additions"]) / prev_total * 100

    # ---------------- facts ----------------
    facts = {}
    for key, gname, path, quote, kind in FACT_SPECS:
        text = field(groups[gname], path)
        facts[key] = {
            "value": extract_fact(text, quote, kind),
            "source": f"{gname}." + ".".join(map(str, path)),
            "quote": quote,
        }
    F = {k: v["value"] for k, v in facts.items()}

    # ---------------- derived values for the prose ----------------
    def one(seq, what):
        seq = list(seq)
        if len(seq) != 1:
            raise ValueError(f"expected exactly one {what}, found {len(seq)}")
        return seq[0]

    G = groups
    anth_bal = one((b for b in G["anthropic"]["balances"] if b["amount"] and b["amount"] > 10), "Anthropic balance")
    anth_failed_reload = sorted(
        e["date"]
        for e in cash
        if e["provider"] == "Anthropic" and e["kind"] == "failed_not_charged" and "auto-reload" in e["notes"]
    )
    t0 = datetime.fromisoformat(F["anthropic_outage_start"].replace("Z", "+00:00"))
    t1 = datetime.fromisoformat(F["anthropic_outage_end"].replace("Z", "+00:00"))
    outage_hours = Decimal(int((t1 - t0).total_seconds())) / Decimal(3600)
    tw_bal = one(
        (b for b in G["twilio"]["balances"] if b["as_of"].startswith(AS_OF_DATE.isoformat())),
        "Twilio balance on the as-of day",
    )
    tw_pl = one((r for r in runrate if r["group"] == "twilio" and r["index"] == 1), "Twilio PL number")
    tw_us = one((r for r in runrate if r["group"] == "twilio" and r["index"] == 2), "Twilio US number")
    tw_accrual = tw_pl["per"] + tw_us["per"]
    tw_debt = dec(tw_bal["amount"])
    tw_debt_after_us = tw_debt - tw_us["per"]
    tw_debt_after_pl = tw_debt_after_us - tw_pl["per"]
    tw_trial = one((r for r in ledger if r["basis"] == "free_credit" and r["provider"] == "Twilio"), "Twilio trial")
    tw_exposure = sum((r["amount"] for r in ledger if r["line_id"].endswith("-calls-unbilled-exposure")), ZERO)
    tw_accrued = sum(
        (r["amount"] for r in ledger if r["provider"] == "Twilio" and r["basis"] == "accrued_unpaid"), ZERO
    )
    tw_scen_a = one((r for r in runrate if r["group"] == "twilio" and r["index"] == 3), "Twilio scenario A")
    oa_bal = one(G["openai"]["balances"], "OpenAI balance")
    oa_bal_time = re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}Z", oa_bal["as_of"]).group(0)
    oa_bought = cash_prov["OpenAI"]["native"]["USD"]
    oa_used = prov["OpenAI"]["native"]["USD"]
    oa_eod = oa_bought - oa_used
    oa_oct = sum((r["amount"] for r in counted if r["provider"] == "OpenAI" and r["month"] == PARTIAL_MONTH), ZERO)
    oa_days = Decimal((AS_OF_DATE - RUNRATE_FROM).days + 1)
    oa_avg = oa_oct / oa_days
    oa_rr = one((r for r in runrate if r["group"] == "openai" and r["index"] == 0), "OpenAI run-rate")
    if abs(oa_avg * RUNRATE_DAYS - oa_rr["per"]) > Decimal("0.0000001"):
        raise ValueError("OpenAI run-rate does not equal the October daily average x 30.44")
    oa_cap = one((r for r in runrate if r["group"] == "openai" and r["index"] == 2), "OpenAI cap scenario")["per"]
    oa_cap_new = Decimal(F["openai_cap_new_usd"])
    if Decimal(F["openai_cap_old_usd"]) != oa_cap:
        raise ValueError("the old OpenAI cap in the risk text and the cap scenario disagree")
    if oa_cap_new <= oa_rr["high"]:
        raise ValueError("the raised OpenAI cap is not above the run-rate high bound; rewrite the risk text")
    if oa_cap_new != Decimal(F["openai_app_budget_usd"]):
        raise ValueError("the OpenAI cap no longer equals the app budget; rewrite the risk text")
    oa_busiest = Decimal(F["openai_busiest_day_usd"])
    oa_days_left = Decimal((month_last_day(PARTIAL_MONTH) - AS_OF_DATE).days)
    oa_oct_avg = oa_oct + oa_avg * oa_days_left
    oa_oct_busy = oa_oct + oa_busiest * oa_days_left
    if oa_oct_busy >= oa_cap_new:
        raise ValueError("October at the busiest day's pace would reach the raised cap; rewrite the risk text")
    oa_trigger = Decimal(F["openai_reload_trigger_usd"])
    oa_share = one((r for r in runrate if r["group"] == "openai" and r["index"] == 3), "OpenAI data-sharing scenario")
    if oa_share["high"] != oa_rr["per"] or not ZERO <= oa_share["per"] < oa_rr["per"]:
        raise ValueError("OpenAI data-sharing scenario must lie between zero and the run-rate")
    oa_failed = one(
        (e for e in cash if e["provider"] == "OpenAI" and e["kind"] == "failed_not_charged"), "OpenAI failed recharge"
    )
    oa_topup = one(
        (
            e
            for e in cash
            if e["provider"] == "OpenAI" and e["kind"] == "credit_purchase" and e["date"] == AS_OF_DATE.isoformat()
        ),
        "OpenAI top-up on the as-of day",
    )
    if not F["openai_topup_time"].startswith(oa_topup["date"]):
        raise ValueError("OpenAI top-up time and cash event date disagree")
    oa_est = one(
        (r for r in ledger if r["provider"] == "OpenAI" and r["evidence_class"] == "estimate"), "OpenAI estimate line"
    )
    oa_measured = one(
        (
            r
            for r in ledger
            if r["provider"] == "OpenAI"
            and r["month"] == PARTIAL_MONTH
            and r["evidence_class"] == "measured_usage_x_tariff"
        ),
        "OpenAI measured tail",
    )
    an_sep19 = one(
        (
            e
            for e in cash
            if e["provider"] == "Anthropic" and e["kind"] == "credit_purchase" and e["date"] == "2026-09-19"
        ),
        "Anthropic Sep-19 purchase",
    )
    or_bal = one(
        (b for b in G["openrouter_typesafe"]["balances"] if b["provider"] == "OpenRouter" and "Credits" in b["as_of"]),
        "OpenRouter balance",
    )
    or_unused_lot = one(
        (e for e in cash if e["provider"] == "OpenRouter" and e["sentinel_amount"] == 0), "OpenRouter unconsumed lot"
    )
    ts_buy = one((e for e in cash if e["provider"] == "TypeSafe (Jev)"), "TypeSafe purchase")
    ts_free = one(
        (r for r in ledger if r["provider"] == "TypeSafe (Jev)" and r["basis"] == "free_credit"), "TypeSafe free credit"
    )
    apple_fee = one((r for r in counted if r["provider"] == "Apple" and r["amount"] > 0), "Apple fee line")
    apple_rr = one((r for r in runrate if r["group"] == "apple_expo" and r["index"] == 0), "Apple run-rate")
    hz_oct = sum((r["amount"] for r in counted if r["provider"] == "Hetzner" and r["month"] == PARTIAL_MONTH), ZERO)
    kartoteka = ex_key["other_and_excluded#39"]

    # ---------------- summary ----------------
    total = grand
    providers_sorted = sorted(prov, key=lambda p: (-prov[p]["pln"], pidx[p]))
    by_provider = []
    for p in providers_sorted:
        by_provider.append(
            {
                "provider": p,
                "name_pl": PROVIDER_PL[p][0],
                "what_pl": PROVIDER_PL[p][1],
                "native": {c: num(v) for c, v in sorted(prov[p]["native"].items())},
                "pln": num(prov[p]["pln"]),
                "share_pct": num(prov[p]["pln"] / total * 100 if total else ZERO),
                "current_monthly_pln": num(rr_prov.get(p, ZERO)),
                "previous_audit_pln": num(prev_prov.get(p, ZERO)),
            }
        )
    by_month = []
    for m in MONTHS:
        parts = []
        for (mm, p, cur), c in sorted(cells.items(), key=lambda kv: (kv[0][0], pidx[kv[0][1]], kv[0][2])):
            if mm == m:
                parts.append(
                    {
                        "provider": p,
                        "name_pl": PROVIDER_PL[p][0],
                        "currency": cur,
                        "native": num(c["native"]),
                        "pln": num(c["pln"]),
                        "fx_date": c["fx_date"],
                        "fx_rate": num(c["fx_rate"]),
                        "fx_table": c["fx_table"],
                        "lines": c["n"],
                    }
                )
        by_month.append(
            {
                "month": m,
                "partial": m == PARTIAL_MONTH,
                "pln": num(month_tot[m]),
                "previous_audit_pln": num(prev_months.get(m, ZERO)),
                "by_provider": parts,
            }
        )
    top_month = max(MONTHS, key=lambda m: (month_tot[m], m))

    chart_series = [
        ("Twilio", ["Twilio"]),
        ("Anthropic", ["Anthropic"]),
        ("OpenAI", ["OpenAI"]),
        ("Apple", ["Apple"]),
        ("Hetzner", ["Hetzner"]),
        (
            "Pozostałe",
            ["OpenRouter", "TypeSafe (Jev)", "Expo", "GitHub", "Free news sources", "Backups (on the VPS disk)"],
        ),
    ]
    chart_months = []
    for m in MONTHS:
        vals = []
        for _, members in chart_series:
            vals.append(num(sum((c["pln"] for (mm, p, cur), c in cells.items() if mm == m and p in members), ZERO)))
        chart_months.append({"month": m, "partial": m == PARTIAL_MONTH, "total": num(month_tot[m]), "values": vals})

    ev_rows = []
    for cls in EVIDENCE_ORDER:
        rows = [r for r in counted if r["evidence_class"] == cls]
        if not rows:
            continue
        s = sum((r["pln"] for r in rows), ZERO)
        ev_rows.append(
            {
                "class": cls,
                "label_pl": EVIDENCE_PL[cls],
                "pln": num(s),
                "share_pct": num(s / total * 100),
                "lines": len(rows),
                "lines_nonzero": sum(1 for r in rows if r["amount"] != 0),
            }
        )
    hard = sum((r["pln"] for r in counted if r["evidence_class"] in ("provider_invoice", "provider_portal")), ZERO)
    est_now = sum((r["pln"] for r in counted if r["evidence_class"] == "estimate"), ZERO)

    cash_vs = []
    for p in PROVIDER_ORDER:
        if p not in prov and p not in cash_prov:
            continue
        e_pln = prov[p]["pln"] if p in prov else ZERO
        c_pln = cash_prov[p]["pln"] if p in cash_prov else ZERO
        e_nat = dict(prov[p]["native"]) if p in prov else {}
        c_nat = dict(cash_prov[p]["native"]) if p in cash_prov else {}
        natives = {}
        for cur in sorted(set(e_nat) | set(c_nat)):
            natives[cur] = {"economic": num(e_nat.get(cur, ZERO)), "cash": num(c_nat.get(cur, ZERO))}
        cash_vs.append(
            {
                "provider": p,
                "name_pl": PROVIDER_PL[p][0],
                "economic_pln": num(e_pln),
                "cash_pln": num(c_pln),
                "difference_pln": num(e_pln - c_pln),
                "native": natives,
            }
        )

    # Polish prose with computed values
    def money(x, cur):
        return f"{pl_num(x)} {cur}" if cur != "PLN" else f"{pl_num(x)} zł"

    reason_pl = {
        "Anthropic": T(
            "Kredyty kupowane z góry na konto wspólne z innymi projektami. Sentinelowi przypisano "
            "tylko część, którą sam zużył (najstarszy kredyt idzie pierwszy). Pozostałe {bal} na "
            "koncie zużywają inne projekty.",
            bal=money(dec(anth_bal["amount"]), "USD"),
        ),
        "OpenAI": T(
            "Kupiono {bought} kredytu, a do końca dnia audytu zużyto {used}. Reszta, około {left}, "
            "czeka na koncie i stanie się kosztem dopiero po zużyciu.",
            bought=money(oa_bought, "USD"),
            used=money(oa_used, "USD"),
            left=money(oa_eod, "USD"),
        ),
        "OpenRouter": T(
            "Gotówka to część zakupu odpowiadająca temu, co zużył Sentinel. Reszta salda ({bal}) "
            "nie jest kosztem Sentinela.",
            bal=money(dec(or_bal["amount"]), "USD"),
        ),
        "TypeSafe (Jev)": T(
            "Eksperyment opłacono darmowym kredytem wartym {free}. Nie wchodzi ani do kosztu, ani do gotówki.",
            free=money(ts_free["amount"], "USD"),
        ),
        "Twilio": T(
            "Do zapłaty zostaje {debt}: numery naliczane w czasie zawieszenia i drobne przekroczenie "
            "salda. Darmowy kredyt próbny ({trial}) jest poza sumą.",
            debt=money(-tw_debt, "USD"),
            trial=money(tw_trial["amount"], "USD"),
        ),
        "Hetzner": T(
            "Październik ({oct}) jest naliczony, ale faktura przyjdzie dopiero w listopadzie.", oct=money(hz_oct, "EUR")
        ),
        "Apple": T(
            "Opłatę roczną liczymy w całości w miesiącu zakupu, tak samo w koszcie i w gotówce. W "
            "koszcie miesięcznym rozkładamy ją na dwanaście miesięcy ({monthly} miesięcznie).",
            monthly=money(apple_rr["per"], "PLN"),
        ),
    }
    for row in cash_vs:
        row["why_pl"] = reason_pl.get(row["provider"], T("Usługa darmowa; brak kosztu i płatności."))

    risks = [
        {
            "level": "pilne",
            "title": T("Twilio: telefon przy najpilniejszym alercie dziś nie zadzwoni"),
            "text": T(
                "Od {since} konto Twilio jest zawieszone z braku środków i dziś celowo niedoładowane. Żadne "
                "połączenie ani SMS "
                "nie wychodzi; od {from_} dziennik pokazuje {n} odrzuconych połączeń i tyle samo SMS-ów. "
                "Dotyczyły one tylko {ev} zdarzeń najwyższej pilności: na zawieszonym koncie żadne zdarzenie "
                "nie zostaje potwierdzone, a odrzucone połączenie nie zostawia śladu, więc system ponawia próby "
                "wielokrotnie. "
                "Dług na koncie wynosi {debt} i rośnie o {accr} miesięcznie za dwa numery: do {after_us} po "
                "odnowieniu {next_us} i do {after_pl} po odnowieniu {next_pl}. Doładowanie najpierw spłaci "
                "dług. Przy obecnych zasadach wysyłki zużycie po doładowaniu, liczone od liczby zdarzeń, a nie "
                "prób, to około {scen} miesięcznie (przedział {lo} – {hi}) plus numery.",
                since=pl_datetime(F["twilio_suspended_since"]),
                from_=pl_date(F["twilio_rejected_from"]),
                n=F["twilio_rejected_attempts"],
                ev=F["twilio_u9_events"],
                debt=money(-tw_debt, "USD"),
                accr=money(tw_accrual, "USD"),
                after_us=money(-tw_debt_after_us, "USD"),
                next_us=pl_date(F["twilio_next_us_renewal"]),
                after_pl=money(-tw_debt_after_pl, "USD"),
                next_pl=pl_date(F["twilio_next_pl_renewal"]),
                scen=money(tw_scen_a["per"], "USD"),
                lo=money(tw_scen_a["low"], "USD"),
                hi=money(tw_scen_a["high"], "USD"),
            ),
        },
        {
            "level": "ważne",
            "title": T("OpenAI: limit podniesiony, doładowanie włączone, karta niesprawdzona"),
            "text": T(
                "Wieczorem {cap_date} podniosłeś twardy limit miesięczny projektu Sentinel w OpenAI z {cap_old} "
                "do {cap_new}; panel pokazywał wtedy {cap_used} z {cap_new} ({cap_when}). Nowy limit jest wyższy "
                "niż bieżące tempo {rr} miesięcznie i jego górna granica {rr_hi}, więc przy zwykłej liczbie "
                "artykułów klasyfikacja nie stanie już w połowie miesiąca. Październik zamknie się na około "
                "{oct_avg} przy średnim tempie ({avg} dziennie) i na około {oct_busy} przy najwyższym dziennym "
                "zużyciu ({busy}). Powiadomienie o wydatkach przy {alert} zostało jako wczesne ostrzeżenie. "
                "Limit równa się teraz własnemu budżetowi aplikacji, więc prawdziwy kryzys z wielokrotnie "
                "większą liczbą artykułów nadal może go wyczerpać. Saldo po doładowaniu z {twhen} ({top}) "
                "wynosiło {bal} ({when}). Automatyczne doładowanie jest znowu włączone: gdy saldo spadnie do "
                "{trig}, OpenAI doładuje je do {target}, bez miesięcznego limitu doładowań. Karta nie przeszła "
                "jednak jeszcze automatycznego obciążenia od nieudanej płatności {failed}. Gdyby znów została "
                "odrzucona, OpenAI wyłączy doładowanie przy saldzie {trig}, a to starczy na około {d_avg} dnia "
                "przy średnim tempie i {d_busy} dnia przy najwyższym zużyciu.",
                cap_date=pl_date(F["openai_cap_raised_date"]),
                cap_old=money(oa_cap, "USD"),
                cap_new=money(oa_cap_new, "USD"),
                cap_used=money(Decimal(F["openai_cap_used_usd"]), "USD"),
                cap_when=pl_datetime(F["openai_cap_read_time"]),
                rr=money(oa_rr["per"], "USD"),
                rr_hi=money(oa_rr["high"], "USD"),
                oct_avg=money(oa_oct_avg, "USD"),
                oct_busy=money(oa_oct_busy, "USD"),
                avg=money(oa_avg, "USD"),
                busy=money(oa_busiest, "USD"),
                alert=money(Decimal(F["openai_spend_alert_usd"]), "USD"),
                twhen=pl_datetime(F["openai_topup_time"]),
                top=money(oa_topup["amount"], "USD"),
                bal=money(dec(oa_bal["amount"]), "USD"),
                when=pl_datetime(oa_bal_time),
                trig=money(oa_trigger, "USD"),
                target=money(Decimal(F["openai_reload_target_usd"]), "USD"),
                failed=pl_date(oa_failed["date"]),
                d_avg=pl_num(oa_trigger / oa_avg, 1),
                d_busy=pl_num(oa_trigger / oa_busiest, 1),
            ),
        },
        {
            "level": "ważne",
            "title": T("Apple: termin na nową umowę i wyłączone odnowienie"),
            "text": T(
                "Do {deadline} trzeba zaakceptować nową umowę licencyjną Apple Developer. Do tego czasu nie "
                "da się zbudować nowej wersji aplikacji na iPhone'a. Automatyczne odnowienie członkostwa jest "
                "wyłączone: członkostwo wygasa {end}. Bez ręcznego odnowienia powiadomienia push na iPhone'a "
                "prawdopodobnie przestaną działać.",
                deadline=pl_date(F["apple_licence_deadline"]),
                end=pl_date(F["apple_membership_end"]),
            ),
        },
        {
            "level": "ważne",
            "title": T("Push to dziś jedyny działający kanał alertów"),
            "text": T(
                "Telefony i SMS-y nie działają, więc wszystkie alerty idą tylko jako powiadomienia push "
                "przez Expo i Apple. Utrata konta Apple Developer albo Expo wyciszyłaby wszystkie alerty. "
                "Push nie budzi w nocy tak jak telefon."
            ),
        },
        {
            "level": "lekcja",
            "title": T("Anthropic: kredyty skończyły się po cichu i Sentinel był ślepy"),
            "text": T(
                "Od {start} do {end} (około {hours} godzin) skończył się przedpłacony kredyt w Anthropic i "
                "każde wywołanie klasyfikatora kończyło się błędem. W tym czasie żaden alert nie mógł "
                "zostać wysłany. Przyczyna: automatyczne doładowania nie przeszły ({f1} i {f2}, za drugim "
                "razem karta została odrzucona). Dziś Sentinel nie korzysta z Anthropic (od {switch}), ale "
                "powrót do Claude Haiku zacząłby się od wspólnego salda {bal}.",
                start=pl_datetime(F["anthropic_outage_start"]),
                end=pl_datetime(F["anthropic_outage_end"]),
                hours=pl_num(outage_hours, 0),
                f1=pl_date(anth_failed_reload[0]),
                f2=pl_date(anth_failed_reload[-1]),
                switch=pl_date(F["anthropic_switch_date"]),
                bal=money(dec(anth_bal["amount"]), "USD"),
            ),
        },
        {
            "level": "ważne",
            "title": T("Ostrzeżenia o płatnościach giną w poczcie"),
            "text": T(
                "Porządkowanie poczty ({date}) usunęło maile rozliczeniowe, w tym ostrzeżenia o niskim "
                "saldzie i wyłączeniu dostępu. Przyszłe ostrzeżenia od OpenAI, Twilio czy Hetznera mogą "
                "zniknąć, zanim je zobaczysz. Ta sama karta była odrzucana u kilku dostawców.",
                date=pl_date(F["mail_cleanup_date"]),
            ),
        },
        {
            "level": "obserwuj",
            "title": T("Jeden serwer i brak zewnętrznego monitoringu"),
            "text": T(
                "Cały Sentinel działa na jednym serwerze Hetzner. Kopie bazy leżą na tym samym dysku, a kopie "
                "zapasowe Hetznera są wyłączone. Nic z zewnątrz nie sprawdza, czy Sentinel działa: awaria "
                "byłaby widoczna tylko jako brak powiadomień. Własny budżet aplikacji na OpenAI to {budget} "
                "miesięcznie; prawdziwy kryzys z dużą liczbą artykułów może go wyczerpać.",
                budget=money(Decimal(F["openai_app_budget_usd"]), "USD"),
            ),
        },
    ]

    open_items = [
        T(
            "Twilio nie rozliczyło połączeń alarmowych z lipca i sierpnia. Gdyby je doliczyło, doszłoby około "
            "{exp} (poza sumą). Zaległe opłaty za numery ({acc}) wyliczono z salda w panelu; potwierdzi je "
            "październikowy wyciąg.",
            exp=money(tw_exposure, "USD"),
            acc=money(tw_accrued, "USD"),
        ),
        T(
            "Wieczór dnia audytu w OpenAI to pomiar z dziennika aplikacji ({meas}) i szacunek ostatnich godzin "
            "({est}). Eksport z panelu po północy zastąpi je dokładną kwotą.",
            meas=money(oa_measured["amount"], "USD"),
            est=money(oa_est["amount"], "USD"),
        ),
        T(
            "Do decyzji: zakup {amt} w Anthropic z {date} ratował Sentinela po awarii, ale według zasady FIFO "
            "Sentinel zużył z niego tylko {share}. Czy w widoku gotówki przypisać Sentinelowi cały zakup?",
            amt=money(an_sep19["amount"], "USD"),
            date=pl_date(an_sep19["date"]),
            share=money(an_sep19["sentinel_amount"], "USD"),
        ),
        T(
            "Do decyzji: doładowanie OpenRouter za {amt} z {date} kupiono w trakcie testów Sentinela, ale nic z "
            "niego jeszcze nie zużyto, więc udział Sentinela wynosi zero.",
            amt=money(or_unused_lot["amount"], "USD"),
            date=pl_date(or_unused_lot["date"]),
        ),
        T(
            "Panelu TypeSafe nie odczytano. Kwota zakupu z {date} jest nieznana; nie dotyczy Sentinela.",
            date=pl_date(ts_buy["date"]),
        ),
        T(
            "Kwota Apple ({amt}) opiera się na odtworzonym mailu z zamówieniem i Twojej kopii. Faktura Apple nie "
            "została pobrana, a data obciążenia karty jest niepotwierdzona.",
            amt=money(apple_fee["amount"], "PLN"),
        ),
        T(
            "Październikowej faktury Hetznera jeszcze nie ma; do tego czasu październik to naliczenie ({oct}).",
            oct=money(hz_oct, "EUR"),
        ),
        T("Darmowy plan Expo odczytano w panelu, ale bez zrzutu ekranu."),
        T(
            "Zakup w KartotekaOnline.pl ({amt}, {date}) ma nieznany cel. Domyślnie nie jest kosztem Sentinela; "
            "potwierdź.",
            amt=money(kartoteka["amount"], kartoteka["currency"]),
            date=pl_date(period_iso(kartoteka["period"])[0]),
        ),
        T(
            "Przy płatnościach w obcej walucie rzeczywisty koszt w złotych zależy od kursu i prowizji Twojego "
            "banku. Raport używa kursów NBP; wyciągi z karty dałyby dokładne kwoty."
        ),
    ]

    qvals = {
        "cap_date": pl_date(F["openai_cap_raised_date"]),
        "cap_old": money(oa_cap, "USD"),
        "cap_new": money(oa_cap_new, "USD"),
        "share_check": pl_date(F["openai_sharing_check_from"]),
        "rr_now": money(oa_rr["per"], "USD"),
        "rr_shared": money(oa_share["per"], "USD"),
    }
    questions = []
    for gname in GROUP_ORDER:
        for i, text in enumerate(G[gname]["open_questions"]):
            spec = QUESTION_MAP.get((gname, i))
            if spec is None or not text.startswith(spec[0]):
                raise ValueError(f"open question not mapped or stale at {gname}[{i}]: {text[:40]!r}")
            questions.append(
                {
                    "group": gname,
                    "index": i,
                    "category": spec[1],
                    "urgent": spec[2],
                    "text_pl": T(spec[3], **qvals),
                    "text_en": text,
                }
            )
    if len(questions) != len(QUESTION_MAP):
        raise ValueError("QUESTION_MAP has entries that match no open question")
    rc_names_en = ", ".join(RC_NAMES[:-1]) + " and " + RC_NAMES[-1]
    rate_pct = PL_VAT_RATE * 100
    cross_en = {
        "reverse_charge_vat": (
            f"VAT on reverse-charged invoices: {rc_names_en} invoice Sentinel's services at 0% under the EU "
            f"reverse charge on the owner's PL VAT number, and the totals exclude that VAT by the agreed "
            f"convention. If the self-assessed {format(rate_pct.normalize(), 'f')}% Polish VAT is not deductible, "
            f"it is a real cost missing from all {len(RC_NAMES)} providers: about PLN {q2(rc_vat_econ)} to date "
            f"({format(rate_pct.normalize(), 'f')}% of PLN {q2(rc_econ)}) and about PLN {q2(rc_vat_month)} a "
            f"month at the current run-rate ({format(rate_pct.normalize(), 'f')}% of PLN {q2(rc_month)}). "
            f"OpenRouter's VAT and Apple's gross price are already inside the cost. This is a tax question for "
            f"the owner and his accountant, not an owner switch, so it has no run-rate line and the totals stay "
            f"as they are; summary.reverse_charge_vat has the per-provider split."
        ),
        "claude_md_pointer": (
            "Proposal, not applied: CLAUDE.md, which agents load automatically, does not point to the cost "
            "register. The new-cost rule ('an agent that notices a new cost must ask the owner') lives only in "
            "docs/reference/costs.md, which only docs/README.md links. Proposed one-line addition to the Docs "
            f"section of CLAUDE.md: '{CLAUDE_MD_PROPOSED_LINE}'. CLAUDE.md changes need the owner's approval "
            "first, so nothing was edited. finance/maintenance-policy.html (October 11 proposal, never adopted) "
            "is marked as superseded by costs.md."
        ),
    }
    pl_names = ", ".join(RC_NAMES[:-1]) + " i " + RC_NAMES[-1]
    cross_values = {
        "reverse_charge_vat": {
            "names": pl_names,
            "rate": pl_num(rate_pct, 0) + " %",
            "econ": money(rc_vat_econ, "PLN"),
            "month": money(rc_vat_month, "PLN"),
        },
        "claude_md_pointer": {
            "line": CLAUDE_MD_PROPOSED_LINE.replace(
                "[docs/reference/costs.md](docs/reference/costs.md)", "docs/reference/costs.md"
            )
        },
    }
    if set(cross_en) != set(CROSS_QUESTIONS):
        raise ValueError("cross-provider questions and their English texts disagree")
    cross_questions = []
    for k, key in enumerate(CROSS_QUESTIONS):  # listed first: they span providers and carry the largest amounts
        sgroup, category, urgent, template = CROSS_QUESTIONS[key]
        cross_questions.append(
            {
                "group": sgroup,
                "index": k,
                "key": key,
                "category": category,
                "urgent": urgent,
                "text_pl": T(template, **cross_values[key]),
                "text_en": cross_en[key],
            }
        )
    questions = cross_questions + questions
    cat_rank = {c: k for k, (c, _) in enumerate(QUESTION_CATEGORIES)}
    questions.sort(key=lambda q: (cat_rank[q["category"]], not q["urgent"]))  # stable: input order otherwise

    cash_cutoff = {
        "as_of": AS_OF,
        "evidence_checked_to": F["cash_evidence_checked"],
        "note": "Cash events come from provider portals and the billing mailbox; the mailbox was last checked at "
        "evidence_checked_to, so a payment made later on the as-of day is not included.",
        "text_pl": T(
            "Gotówka obejmuje płatności do końca dnia {d} (UTC), także Twoje doładowanie OpenAI z {t}. "
            "Pocztę z rachunkami sprawdziłem ostatnio {c}; płatność zrobiona później tego dnia nie jest "
            "ujęta.",
            d=pl_date(AS_OF),
            t=pl_datetime(F["openai_topup_time"]),
            c=pl_datetime(F["cash_evidence_checked"]),
        ),
    }

    changes = {
        "Twilio": T(
            "Zamiast odtworzenia z liczby SMS-ów i połączeń: miesięczne wyciągi Twilio. Doszły zaległe "
            "opłaty za numery naliczane w czasie zawieszenia."
        ),
        "Anthropic": T(
            "Zamiast szacunku z tokenów w bazie: dane z panelu Anthropic dla klucza Sentinela. Panel "
            "pokazuje więcej, bo obejmuje też wywołania, których baza nie zapisywała."
        ),
        "OpenAI": T(
            "Zamiast szacunku z dziennika aplikacji: eksporty kosztów z panelu OpenAI, policzone do końca dnia audytu."
        ),
        "Apple": T(
            "Zamiast ceny katalogowej w dolarach: rzeczywista cena {amt} z zamówienia.",
            amt=money(apple_fee["amount"], "PLN"),
        ),
        "Hetzner": T(
            "Faktury bez zmian; październik naliczony do końca dnia audytu. Kursy liczone teraz na "
            "koniec miesiąca zamiast na dzień faktury."
        ),
        "OpenRouter": T("Doliczono VAT i opłatę za zakup kredytów, które faktycznie zapłaciłeś."),
        "TypeSafe (Jev)": T("Wrześniowy eksperyment opłacono darmowym kredytem, więc koszt to zero."),
    }
    change_rows = []
    for p in PROVIDER_ORDER:
        now_p = prov[p]["pln"] if p in prov else ZERO
        old_p = prev_prov.get(p, ZERO)
        if now_p == 0 and old_p == 0:
            continue
        change_rows.append(
            {
                "provider": p,
                "name_pl": PROVIDER_PL[p][0],
                "previous_pln": num(old_p),
                "now_pln": num(now_p),
                "difference_pln": num(now_p - old_p),
                "why_pl": changes[p],
            }
        )

    method_pl = [
        T(
            "Koszt liczę według miesiąca zużycia. Usługi płatne za zużycie trafiają do miesiąca zużycia, "
            "faktury do miesiąca, którego dotyczą, a opłaty jednorazowe i roczne do miesiąca zakupu."
        ),
        T(
            "Kredyty kupione z góry liczę dopiero wtedy, gdy zostaną zużyte. Na kontach wspólnych z innymi "
            "projektami (Anthropic, OpenRouter, TypeSafe) Sentinel dostaje tylko swoją część; najstarszy kredyt "
            "zużywa się pierwszy."
        ),
        T(
            "VAT pomijam tam, gdzie rozlicza się go odwrotnie (zero na fakturze: {names}). Tam, gdzie VAT i "
            "opłaty faktycznie zapłaciłeś (OpenRouter, Apple), są w koszcie. Czy pominięty VAT możesz odliczyć, "
            "to otwarte pytanie podatkowe w części „Pytania i decyzje”.",
            names=pl_names,
        ),
        T(
            "Darmowe kredyty pokazuję jako notatkę bez gotówki, poza sumą. Opłaty naliczone, ale niezapłacone "
            "(numery Twilio w czasie zawieszenia), są kosztem miesiąca, w którym je naliczono."
        ),
        T("Nie zgaduję kwot. Każdy szacunek jest oznaczony i ma opisaną metodę oraz przedział."),
        T(
            "Koszt miesięczny teraz: usługi za zużycie to średnia dzienna od {f} do {t} razy {days} (przeciętna "
            "liczba dni w miesiącu); opłaty stałe po cenie miesięcznej; opłaty roczne podzielone na dwanaście; "
            "usługi już nieużywane to zero.",
            f=pl_date(RUNRATE_FROM.isoformat()),
            t=pl_date(AS_OF_DATE.isoformat()),
            days=pl_num(RUNRATE_DAYS),
        ),
        T(
            "Kursy: średnie kursy NBP (tabela A). Koszt przeliczam po kursie z ostatniego dnia roboczego miesiąca "
            "zużycia, a dla niepełnego października po najnowszym kursie ({latest}). Gotówkę przeliczam po kursie "
            "z dnia roboczego przed płatnością. Koszt miesięczny teraz: kurs z {latest}.",
            latest=pl_date(fx.on_or_before("USD", AS_OF_DATE)[0].isoformat()),
        ),
        T(
            "Kwoty w plikach CSV mają pełną precyzję. W raporcie zaokrąglam je do grosza, więc suma wierszy może "
            "się różnić od sumy całości o grosz."
        ),
    ]

    fx_table = []
    for m in MONTHS:
        row = {"month": m}
        for cur in ("USD", "EUR"):
            d, r, t = fx.month_end(cur, m)
            row[cur] = {"date": d.isoformat(), "rate": num(r), "table": t}
        fx_table.append(row)
    fx_now = {}
    for cur in ("USD", "EUR"):
        d, r, t = fx.on_or_before(cur, AS_OF_DATE)
        fx_now[cur] = {"date": d.isoformat(), "rate": num(r), "table": t}

    # excluded catalogue for the report (canonical items only)
    ex_cats = []
    for reason in REASON_ORDER:
        items = [e for e in excluded if e["reason"] == reason and e["duplicate_of"] is None]
        if not items:
            continue
        ex_cats.append(
            {
                "reason": reason,
                "title_pl": REASON_PL[reason][0],
                "why_pl": REASON_PL[reason][1],
                "items": [
                    {
                        "provider": e["provider"],
                        "label_pl": e["label_pl"],
                        "amount": num(e["amount"]),
                        "currency": e["currency"],
                        "period": period_iso(e["period"]),
                        "merged_duplicates": sum(
                            1 for x in excluded if x["duplicate_of"] == f"{e['group']}#{e['index']}"
                        ),
                    }
                    for e in items
                ],
            }
        )

    notes_rows = [
        {
            "line_id": r["line_id"],
            "provider": r["provider"],
            "name_pl": PROVIDER_PL[r["provider"]][0],
            "label_pl": r["label_pl"],
            "month": r["month"],
            "basis": r["basis"],
            "evidence_class": r["evidence_class"],
            "currency": r["currency"],
            "native": num(r["amount"]),
            "pln": num(r["pln"]),
        }
        for r in notes_out
    ]

    lines_nonzero = [
        {
            "line_id": r["line_id"],
            "month": r["month"],
            "provider": r["provider"],
            "name_pl": PROVIDER_PL[r["provider"]][0],
            "label_pl": r["label_pl"],
            "currency": r["currency"],
            "native": num(r["amount"]),
            "pln": num(r["pln"]),
            "evidence_class": r["evidence_class"],
            "evidence_pl": EVIDENCE_PL[r["evidence_class"]],
        }
        for r in sorted(counted, key=lambda r: (r["month"], pidx[r["provider"]], r["line_id"]))
        if r["amount"] != 0
    ]

    def rr_out(r):
        return {
            "group": r["group"],
            "index": r["index"],
            "provider": r["provider"],
            "item": r["item"],
            "label_pl": r["label_pl"],
            "explain_pl": r["explain_pl"],
            "currency": r["currency"],
            "per_month_native": num(r["per"]),
            "low_native": num(r["low"]),
            "high_native": num(r["high"]),
            "per_month_pln": num(r["pln"]),
            "low_pln": num(r["low_pln"]),
            "high_pln": num(r["high_pln"]),
            "fx_date": r["fx_date"],
            "fx_rate": num(r["fx_rate"]),
            "duplicate_of": r["duplicate_of"],
        }

    summary = {
        "schema": "sentinel-cost-audit/2026-10-14",
        "project": "project-sentinel",
        "as_of": AS_OF,
        "period_start": START_DATE.isoformat(),
        "months": MONTHS,
        "partial_month": PARTIAL_MONTH,
        "generator": SCRIPT_NAME,
        "inputs": {
            "input/lines.json": sha256(IN_LINES),
            "input/nbp-table-a.csv": sha256(IN_NBP),
            "../2026-10-11-hetzner-provider/summary.json": sha256(PREV / "summary.json"),
            "../2026-10-11-hetzner-provider/cost-items.csv": sha256(PREV / "cost-items.csv"),
            "../2026-10-11-hetzner-provider/current-monthly.csv": sha256(PREV / "current-monthly.csv"),
        },
        "conventions": CONVENTIONS,
        "fx": {
            "month_end": fx_table,
            "current": fx_now,
            "rule_lines": "NBP table A mid rate of the last business day of the usage month "
            "(latest available day for the partial current month)",
            "rule_cash": "NBP table A mid rate of the last business day before the payment date",
            "rule_current_monthly": "NBP table A mid rate of the latest available day",
        },
        "economic": {
            "total_pln": num(total),
            "total_pln_rounded": num(q2(total)),
            "native": {c: num(v) for c, v in sorted(econ_native.items())},
            "by_month": by_month,
            "by_provider": by_provider,
            "top_month": top_month,
            "by_evidence_class": ev_rows,
            "provider_document_share_pct": num(hard / total * 100),
            "estimate_share_pct": num(est_now / total * 100),
            "lines_total": len(ledger),
            "lines_counted": len(counted),
            "lines_duplicates": sum(1 for r in ledger if r["duplicate_of"]),
            "notes_not_in_total": notes_rows,
            "lines_nonzero": lines_nonzero,
        },
        "chart": {
            "series": [{"label": lab, "slot": i + 1, "providers": mem} for i, (lab, mem) in enumerate(chart_series)],
            "months": chart_months,
        },
        "cash": {
            "cutoff": cash_cutoff,
            "total_pln": num(cash_total),
            "total_pln_rounded": num(q2(cash_total)),
            "native": {c: num(v) for c, v in sorted(cash_native.items())},
            "by_provider": [
                {
                    "provider": p,
                    "name_pl": PROVIDER_PL[p][0],
                    "native": {c: num(v) for c, v in sorted(cash_prov[p]["native"].items())},
                    "pln": num(cash_prov[p]["pln"]),
                }
                for p in PROVIDER_ORDER
                if p in cash_prov
            ],
            "events": [
                {
                    "date": e["date"],
                    "provider": e["provider"],
                    "name_pl": PROVIDER_PL[e["provider"]][0],
                    "kind": e["kind"],
                    "kind_pl": KIND_PL[e["kind"]],
                    "currency": e["currency"],
                    "amount": num(e["amount"]),
                    "sentinel_share": num(e["share"]),
                    "sentinel_amount": num(e["sentinel_amount"]),
                    "counted": e["counted"],
                    "fx_date": e["fx_date"],
                    "fx_rate": num(e["fx_rate"]),
                    "sentinel_pln": num(e["sentinel_pln"]),
                    "evidence_class": e["evidence_class"],
                }
                for e in cash
            ],
        },
        "cash_vs_economic": {
            "economic_pln": num(total),
            "cash_pln": num(cash_total),
            "difference_pln": num(total - cash_total),
            "by_provider": cash_vs,
        },
        "current_monthly": {
            "total_pln": num(rr_total),
            "total_pln_rounded": num(q2(rr_total)),
            "low_pln": num(rr_low),
            "high_pln": num(rr_high),
            "native": {c: num(v) for c, v in sorted(rr_native.items())},
            "window": [RUNRATE_FROM.isoformat(), AS_OF_DATE.isoformat()],
            "days_factor": num(RUNRATE_DAYS),
            "items": [rr_out(r) for r in runrate if r["counted"]],
            "scenarios": [rr_out(r) for r in runrate if r["scenario"]],
            "duplicates": [rr_out(r) for r in runrate if r["duplicate_of"]],
        },
        "excluded": {
            "records": len(excluded),
            "listed": sum(1 for e in excluded if not e["duplicate_of"]),
            "merged_duplicates": sum(1 for e in excluded if e["duplicate_of"]),
            "categories": ex_cats,
        },
        "previous_audit": {
            "report": "reports/2026-10-11-hetzner-provider/report.html",
            "as_of": prev_summary["as_of_utc"],
            "total_pln": num(prev_total),
            "low_pln": prev_summary["historical"]["PLN"]["reconstructed_low"],
            "high_pln": prev_summary["historical"]["PLN"]["reconstructed_high"],
            "estimate_share_pct": num(prev_est_share),
            "current_monthly_pln": num(prev_current),
            "current_monthly_by_provider_pln": {p: num(v) for p, v in sorted(prev_rr_prov.items())},
            "unpriced_categories": prev_summary["unpriced_current_categories"],
            "by_provider": change_rows,
            "difference_total_pln": num(total - prev_total),
            "difference_current_monthly_pln": num(rr_total - prev_current),
        },
        "facts": facts,
        "balances": [
            {
                "group": g,
                "provider": b["provider"],
                "as_of": b["as_of"],
                "amount": num(dec(b["amount"])),
                "currency": b["currency"],
                "meaning": b["meaning"],
            }
            for g in GROUP_ORDER
            for b in G[g]["balances"]
        ],
        "operational_risks": [{"group": g, "text": t} for g in GROUP_ORDER for t in G[g]["operational_risks"]],
        "open_questions": (
            [{"group": q["group"], "text": q["text_en"]} for q in cross_questions]
            + [{"group": g, "text": t} for g in GROUP_ORDER for t in G[g]["open_questions"]]
        ),
        "reverse_charge_vat": {
            "in_total": False,
            "providers": RC_NAMES,
            "rate": num(PL_VAT_RATE),
            "economic_base_pln": num(rc_econ),
            "economic_vat_pln": num(rc_vat_econ),
            "current_monthly_base_pln": num(rc_month),
            "current_monthly_vat_pln": num(rc_vat_month),
            "by_provider": rc_rows,
            "note": "These providers invoice Sentinel's services at 0% VAT under the EU reverse charge on the "
            "owner's PL VAT number. The agreed convention excludes that VAT, so it is in no total. It "
            "would be a real cost only if the self-assessed Polish VAT is not deductible: an open tax "
            "question for the owner and his accountant.",
        },
        "report_pl": {
            "risks": risks,
            "open_items": open_items,
            "method": method_pl,
            "question_categories": [{"category": c, "title_pl": t} for c, t in QUESTION_CATEGORIES],
            "questions": questions,
        },
        "files": {
            "ledger": "ledger.csv",
            "monthly": "monthly.csv",
            "cash": "cash.csv",
            "current_monthly": "current-monthly.csv",
            "excluded": "excluded.csv",
            "summary": "summary.json",
            "report": "report.html",
            "living_records": ["../../ledger.csv", "../../current-monthly.csv", "../../history-monthly.csv"],
        },
    }

    # ---------------- CSV files ----------------
    ledger_csv = csv_bytes(
        [
            "line_id",
            "group",
            "provider",
            "item",
            "basis",
            "month",
            "period_start",
            "period_end",
            "currency",
            "amount_native",
            "in_total",
            "counted",
            "duplicate_of",
            "evidence_class",
            "sentinel_share",
            "gross_account_amount_native",
            "fx_date",
            "fx_table",
            "fx_rate_pln",
            "amount_pln",
            "public_evidence_label",
            "notes",
        ],
        [
            [
                r["line_id"],
                r["group"],
                r["provider"],
                r["item"],
                r["basis"],
                r["month"],
                r["period_start"],
                r["period_end"],
                r["currency"],
                num(r["amount"]),
                tf(r["in_total"]),
                tf(r["counted"]),
                r["duplicate_of"],
                r["evidence_class"],
                num(r["sentinel_share"]),
                num(r["gross"]),
                r["fx_date"],
                r["fx_table"],
                num(r["fx_rate"]),
                num(r["pln"]),
                r["label"],
                r["notes"],
            ]
            for r in ledger
        ],
    )

    mrows = []
    for m in MONTHS:
        for (mm, p, cur), c in sorted(cells.items(), key=lambda kv: (kv[0][0], pidx[kv[0][1]], kv[0][2])):
            if mm == m:
                mrows.append(
                    [
                        "provider_month",
                        m,
                        p,
                        cur,
                        num(c["native"]),
                        c["fx_date"],
                        c["fx_table"],
                        num(c["fx_rate"]),
                        num(c["pln"]),
                        c["n"],
                        "true",
                        "partial month (to the as-of time)" if m == PARTIAL_MONTH else "",
                    ]
                )
        mrows.append(
            [
                "month_total",
                m,
                "ALL",
                "PLN",
                None,
                None,
                None,
                None,
                num(month_tot[m]),
                None,
                "true",
                "sum of provider_month PLN",
            ]
        )
    for cur, v in sorted(econ_native.items()):
        mrows.append(
            [
                "native_total",
                f"{MONTHS[0]}..{MONTHS[-1]}",
                "ALL",
                cur,
                num(v),
                None,
                None,
                None,
                None,
                None,
                "true",
                "native subtotal of counted lines",
            ]
        )
    mrows.append(
        [
            "grand_total",
            f"{MONTHS[0]}..{MONTHS[-1]}",
            "ALL",
            "PLN",
            None,
            None,
            None,
            None,
            num(total),
            len(counted),
            "true",
            f"economic cost {START_DATE.isoformat()} to {AS_OF}",
        ]
    )
    for r in notes_out:
        mrows.append(
            [
                "note_not_in_total",
                r["month"],
                r["provider"],
                r["currency"],
                num(r["amount"]),
                r["fx_date"],
                r["fx_table"],
                num(r["fx_rate"]),
                num(r["pln"]),
                1,
                "false",
                f"{r['line_id']} ({r['basis']}, {r['evidence_class']})",
            ]
        )
    monthly_csv = csv_bytes(
        [
            "row_type",
            "month",
            "provider",
            "currency",
            "amount_native",
            "fx_date",
            "fx_table",
            "fx_rate_pln",
            "amount_pln",
            "lines",
            "in_total",
            "note",
        ],
        mrows,
    )

    crows = [
        [
            e["date"],
            e["group"],
            e["provider"],
            e["kind"],
            num(e["amount"]),
            e["currency"],
            num(e["share"]),
            num(e["sentinel_amount"]),
            tf(e["counted"]),
            e["fx_date"],
            e["fx_table"],
            num(e["fx_rate"]),
            num(e["pln"]),
            num(e["sentinel_pln"]),
            e["evidence_class"],
            e["label"],
            e["notes"],
        ]
        for e in cash
    ]
    for p in PROVIDER_ORDER:
        if p in cash_prov:
            for cur, v in sorted(cash_prov[p]["native"].items()):
                crows.append(
                    [
                        None,
                        None,
                        p,
                        "provider_total",
                        None,
                        cur,
                        None,
                        num(v),
                        "true",
                        None,
                        None,
                        None,
                        None,
                        num(cash_prov[p]["pln"]),
                        None,
                        None,
                        "Sentinel share of counted cash events",
                    ]
                )
    crows.append(
        [
            None,
            None,
            "ALL",
            "grand_total",
            None,
            "PLN",
            None,
            None,
            "true",
            None,
            None,
            None,
            None,
            num(cash_total),
            None,
            None,
            "Sentinel cash paid, by payment date, PLN at NBP rate before date",
        ]
    )
    cash_csv = csv_bytes(
        [
            "date",
            "group",
            "provider",
            "kind",
            "amount_native",
            "currency",
            "sentinel_share",
            "sentinel_amount_native",
            "counted_in_cash_total",
            "fx_date",
            "fx_table",
            "fx_rate_pln",
            "amount_pln",
            "sentinel_amount_pln",
            "evidence_class",
            "public_evidence_label",
            "notes",
        ],
        crows,
    )

    rrows = []
    for r in runrate:
        kind = "duplicate" if r["duplicate_of"] else ("scenario" if r["scenario"] else "run_rate")
        rrows.append(
            [
                kind,
                r["group"],
                r["provider"],
                r["item"],
                r["currency"],
                num(r["per"]),
                num(r["low"]),
                num(r["high"]),
                r["fx_date"],
                r["fx_table"],
                num(r["fx_rate"]),
                num(r["pln"]),
                num(r["low_pln"]),
                num(r["high_pln"]),
                tf(r["in_total"]),
                tf(r["counted"]),
                r["duplicate_of"],
                r["basis"],
                r["notes"],
            ]
        )
    for cur, v in sorted(rr_native.items()):
        rrows.append(
            [
                "native_total",
                None,
                "ALL",
                "current monthly cost, native subtotal",
                cur,
                num(v),
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                "true",
                "true",
                None,
                None,
                None,
            ]
        )
    rrows.append(
        [
            "total",
            None,
            "ALL",
            "current monthly cost (in total)",
            "PLN",
            None,
            None,
            None,
            fx_now["USD"]["date"],
            None,
            None,
            num(rr_total),
            num(rr_low),
            num(rr_high),
            "true",
            "true",
            None,
            "Oct 1-14 daily average x 30.44 for usage; fixed fees monthly; annual fees / 12",
            None,
        ]
    )
    current_csv = csv_bytes(
        [
            "row_type",
            "group",
            "provider",
            "item",
            "currency",
            "per_month_native",
            "low_native",
            "high_native",
            "fx_date",
            "fx_table",
            "fx_rate_pln",
            "per_month_pln",
            "low_pln",
            "high_pln",
            "in_total",
            "counted",
            "duplicate_of",
            "basis",
            "notes",
        ],
        rrows,
    )

    excluded_csv = csv_bytes(
        [
            "group",
            "index",
            "provider",
            "item",
            "reason",
            "amount_native",
            "currency",
            "period",
            "status",
            "duplicate_of",
            "label_pl",
            "notes",
        ],
        [
            [
                e["group"],
                e["index"],
                e["provider"],
                e["item"],
                e["reason"],
                num(e["amount"]),
                e["currency"],
                e["period"],
                "duplicate" if e["duplicate_of"] else "listed",
                e["duplicate_of"],
                e["label_pl"],
                e["notes"],
            ]
            for e in excluded
        ],
    )

    summary_bytes = (json.dumps(summary, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    report_bytes = render_report(json.loads(summary_bytes.decode("utf-8"))).encode("utf-8")

    outputs = {
        REPORT / "ledger.csv": ledger_csv,
        REPORT / "monthly.csv": monthly_csv,
        REPORT / "cash.csv": cash_csv,
        REPORT / "current-monthly.csv": current_csv,
        REPORT / "excluded.csv": excluded_csv,
        REPORT / "summary.json": summary_bytes,
        REPORT / "report.html": report_bytes,
        FIN / "ledger.csv": ledger_csv,
        FIN / "current-monthly.csv": current_csv,
        FIN / "history-monthly.csv": monthly_csv,
    }
    return outputs, summary


# --------------------------------------------------------------------------------------------------
# Polish formatting
# --------------------------------------------------------------------------------------------------
def pl_num(x, dp=2):
    d = Decimal(str(x)) if not isinstance(x, Decimal) else x
    d = d.quantize(Decimal(1).scaleb(-dp), rounding=ROUND_HALF_UP)
    if d == 0:
        d = abs(d)
    sign = "−" if d < 0 else ""
    ip, _, fp = format(abs(d), "f").partition(".")
    groups = []
    while len(ip) > 3:
        groups.insert(0, ip[-3:])
        ip = ip[:-3]
    groups.insert(0, ip)
    out = " ".join(groups)
    return sign + out + ("," + fp if dp else "")


def pl_date(iso):
    d = date.fromisoformat(iso[:10])
    return f"{d.day:02d}.{d.month:02d}.{d.year}"


def pl_datetime(iso):
    return f"{pl_date(iso)}, {iso[11:16]} UTC"


def pl_month(m, short=False):
    y, mm = m.split("-")
    return (MONTH_SHORT if short else MONTH_NAMES)[int(mm)] + ("" if short else " " + y)


# --------------------------------------------------------------------------------------------------
# Report rendering: uses only the summary (already round-tripped through JSON)
# --------------------------------------------------------------------------------------------------
CSS = """
:root{color-scheme:light;--bg:#fcfcfb;--card:#ffffff;--soft:#f4f3f0;--text:#0b0b0b;--text2:#52514e;
--muted:#6f6e69;--line:#e4e2dc;--grid:#e9e8e4;--accent:#2a78d6;--crit:#b42727;--crit-bg:#fdeceb;
--warn:#8a5a00;--warn-bg:#fff4dc;--info:#1c5cab;--info-bg:#eaf2fd;--ok:#0b6b0b;--ok-bg:#e8f5e8;
--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--s4:#eda100;--s5:#e87ba4;--s6:#008300}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--bg:#1a1a19;
--card:#232322;--soft:#2a2a28;--text:#f0efec;--text2:#c3c2b7;--muted:#9b9a92;--line:#383835;--grid:#33332f;
--accent:#3987e5;--crit:#f08a8a;--crit-bg:#3a2020;--warn:#f0c060;--warn-bg:#3a3018;--info:#86b6ef;
--info-bg:#1c2a3d;--ok:#7fd07f;--ok-bg:#1d331d;--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;
--s5:#d55181;--s6:#008300}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#1a1a19;--card:#232322;--soft:#2a2a28;--text:#f0efec;
--text2:#c3c2b7;--muted:#9b9a92;--line:#383835;--grid:#33332f;--accent:#3987e5;--crit:#f08a8a;
--crit-bg:#3a2020;--warn:#f0c060;--warn-bg:#3a3018;--info:#86b6ef;--info-bg:#1c2a3d;--ok:#7fd07f;
--ok-bg:#1d331d;--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--s5:#d55181;--s6:#008300}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--text);font:16px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,
"Helvetica Neue",Arial,sans-serif}
main{max-width:880px;margin:0 auto;padding:24px 16px 72px}
h1{font-size:26px;line-height:1.25;margin:0 0 6px}
h2{font-size:21px;margin:44px 0 10px;padding-top:12px;border-top:1px solid var(--line)}
h3{font-size:17px;margin:24px 0 6px}
p{margin:8px 0}
a{color:var(--accent)}
.sub{color:var(--text2);margin:0 0 16px}
.muted{color:var(--muted);font-size:14px}
nav.toc{background:var(--soft);border-radius:10px;padding:12px 16px;margin:16px 0 8px;font-size:15px}
nav.toc ol{margin:4px 0 0;padding-left:22px}
.hero{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px 18px 14px;margin:16px 0}
.hero .label{color:var(--text2);font-size:15px}
.hero .value{font-size:48px;font-weight:600;line-height:1.1;margin:4px 0;font-variant-numeric:proportional-nums}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px;margin:12px 0}
.tile{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px}
.tile .label{color:var(--text2);font-size:14px}
.tile .value{font-size:26px;font-weight:600;margin:2px 0}
.tile .note{color:var(--muted);font-size:13px}
.table-wrap{overflow-x:auto;-webkit-overflow-scrolling:touch;margin:10px 0}
table{border-collapse:collapse;width:100%;font-size:14px}
th,td{padding:7px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{color:var(--text2);font-weight:600;font-size:13px}
td.num,th.num{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
tr.total td{font-weight:600;border-top:2px solid var(--line)}
td .small,.small{font-size:12px;color:var(--muted)}
details{background:var(--soft);border-radius:10px;padding:8px 12px;margin:12px 0}
details summary{cursor:pointer;font-weight:600}
details.q{background:none;padding:0;margin:2px 0 0}
details.q summary{font-weight:400;font-size:13px;color:var(--muted)}
.legend{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:13px;color:var(--text2);margin:10px 0 4px}
.legend span.sw{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:6px;vertical-align:-1px}
.chart{width:100%;height:auto;display:block}
.chart .grid{stroke:var(--grid);stroke-width:1}
.chart text{fill:var(--text2);font-size:12px;font-family:inherit}
.chart{max-width:640px}
.c1{fill:var(--s1)}.c2{fill:var(--s2)}.c3{fill:var(--s3)}.c4{fill:var(--s4)}.c5{fill:var(--s5)}.c6{fill:var(--s6)}
.b1{background:var(--s1)}.b2{background:var(--s2)}.b3{background:var(--s3)}.b4{background:var(--s4)}
.b5{background:var(--s5)}.b6{background:var(--s6)}
.risk{border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin:12px 0;background:var(--card)}
.risk h3{margin:6px 0}
.badge{display:inline-block;font-size:12px;font-weight:600;border-radius:999px;padding:2px 10px}
.badge.crit{background:var(--crit-bg);color:var(--crit)}
.badge.warn{background:var(--warn-bg);color:var(--warn)}
.badge.info{background:var(--info-bg);color:var(--info)}
.badge.watch{background:var(--soft);color:var(--text2)}
ul.plain{padding-left:20px}
ul.plain li{margin:6px 0}
footer{margin-top:48px;color:var(--muted);font-size:13px;border-top:1px solid var(--line);padding-top:12px}
@media (max-width:520px){.hero .value{font-size:40px}h1{font-size:23px}th,td{padding:6px 5px}}
"""

BADGE = {
    "pilne": ("crit", "⚠ Pilne"),
    "ważne": ("warn", "▲ Ważne"),
    "lekcja": ("info", "◆ Lekcja z przeszłości"),
    "obserwuj": ("watch", "● Do obserwacji"),
}


def render_report(S):
    e = lambda s: html.escape(str(s), quote=True)  # noqa: E731
    D = lambda s: Decimal(s)  # noqa: E731

    def zl(x, dp=2):
        return "—" if x is None else pl_num(D(x), dp) + " zł"

    def nat(x, cur, dp=2):
        if x is None:
            return "kwota nieznana"
        return zl(x, dp) if cur == "PLN" else pl_num(D(x), dp) + " " + (cur or "")

    def pct(x):
        return pl_num(D(x), 2 if D(x) < 1 else 1) + " %"

    def natives(d):
        return " + ".join(nat(v, c) for c, v in d.items())

    def delta(x):
        return ("+" if D(x) > 0 else "") + zl(x)

    econ, cash, cur_m, prev = S["economic"], S["cash"], S["current_monthly"], S["previous_audit"]
    as_of_pl = pl_date(S["as_of"])
    start_pl = pl_date(S["period_start"])
    out = []
    w = out.append

    w('<!doctype html><html lang="pl"><head><meta charset="utf-8">')
    w('<meta name="viewport" content="width=device-width,initial-scale=1">')
    w(f"<title>{e(T('Koszty Sentinela'))}</title>")
    w(f'<meta name="description" content="{e(T("Pełny audyt kosztów Sentinela na dzień {d}", d=as_of_pl))}">')
    w(f"<style>{CSS}</style></head><body><main>")
    w(f"<h1>{e(T('Ile kosztuje Sentinel'))}</h1>")
    w(
        f'<p class="sub">{e(T("Pełny audyt kosztów od {s} do {d} (koniec dnia UTC). Liczy tylko Sentinela.", s=start_pl, d=as_of_pl))}</p>'
    )
    toc = [
        ("a", T("Najważniejsze liczby")),
        ("b", T("Koszty według dostawców")),
        ("c", T("Gotówka a koszt")),
        ("d", T("Czego nie liczę")),
        ("e", T("Ryzyka operacyjne")),
        ("q", T("Pytania i decyzje")),
        ("f", T("Pewność danych")),
        ("g", T("Co się zmieniło od audytu z {d}", d=pl_date(prev["as_of"]))),
        ("h", T("Metoda i kursy NBP")),
    ]
    w('<nav class="toc"><strong>Spis treści</strong><ol type="a">')
    for key, title in toc:
        w(f'<li><a href="#{key}">{e(title)}</a></li>')
    w("</ol></nav>")

    # (a) key numbers ------------------------------------------------------------------------------
    w(f'<h2 id="a">{e(T("Najważniejsze liczby"))}</h2>')
    w('<div class="hero">')
    w(f'<div class="label">{e(T("Łączny koszt Sentinela od {s} do {d}", s=start_pl, d=as_of_pl))}</div>')
    w(f'<div class="value">{e(zl(econ["total_pln"]))}</div>')
    w(f'<div class="muted">{e(T("W walutach dostawców: {n}.", n=natives(econ["native"])))}</div></div>')
    w('<div class="tiles">')
    w(
        f'<div class="tile"><div class="label">{e(T("Obecny koszt miesięczny"))}</div>'
        f'<div class="value">{e(zl(cur_m["total_pln"]))}</div>'
        f'<div class="note">{e(T("przedział {lo} – {hi}", lo=zl(cur_m["low_pln"]), hi=zl(cur_m["high_pln"])))}</div></div>'
    )
    w(
        f'<div class="tile"><div class="label">{e(T("Zapłacona gotówka (część Sentinela)"))}</div>'
        f'<div class="value">{e(zl(cash["total_pln"]))}</div>'
        f'<div class="note">{e(T("różnica wobec kosztu wyjaśniona w części c"))}</div></div>'
    )
    w(
        f'<div class="tile"><div class="label">{e(T("Oparte na fakturach i panelach dostawców"))}</div>'
        f'<div class="value">{e(pct(econ["provider_document_share_pct"]))}</div>'
        f'<div class="note">{e(T("szacunki: {p} kosztu", p=pct(econ["estimate_share_pct"])))}</div></div>'
    )
    w("</div>")
    top_p = econ["by_provider"][0]
    top_m = next(m for m in econ["by_month"] if m["month"] == econ["top_month"])
    top_now = [it for it in sorted(cur_m["items"], key=lambda r: -D(r["per_month_pln"])) if D(it["per_month_pln"]) > 0]
    now_txt = "; ".join(f"{it['label_pl']} ({zl(it['per_month_pln'])})" for it in top_now)
    w(
        "<p>"
        + e(
            T(
                "Najwięcej kosztował {p}: {amt}, czyli {share} całości. Najdroższy miesiąc to {m} ({mamt}). "
                "Dziś co miesiąc płacisz za: {now}.",
                p=top_p["name_pl"],
                amt=zl(top_p["pln"]),
                share=pct(top_p["share_pct"]),
                m=pl_month(top_m["month"]),
                mamt=zl(top_m["pln"]),
                now=now_txt,
            )
        )
        + "</p>"
    )
    w(f"<h3>{e(T('Koszt w każdym miesiącu'))}</h3>")
    w(render_chart(S, e))
    w(
        '<div class="table-wrap"><table><thead><tr>'
        f'<th>{e(T("Miesiąc"))}</th><th class="num">{e(T("Koszt"))}</th><th>{e(T("Największe pozycje"))}</th>'
        "</tr></thead><tbody>"
    )
    for m in econ["by_month"]:
        parts = sorted([p for p in m["by_provider"] if D(p["pln"]) > 0], key=lambda p: -D(p["pln"]))[:3]
        top = ", ".join(f"{p['name_pl']} {zl(p['pln'], 0)}" for p in parts)
        star = " *" if m["partial"] else ""
        w(f'<tr><td>{e(pl_month(m["month"]))}{star}</td><td class="num">{e(zl(m["pln"]))}</td><td>{e(top)}</td></tr>')
    w(f'<tr class="total"><td>{e(T("Razem"))}</td><td class="num">{e(zl(econ["total_pln"]))}</td><td></td></tr>')
    w("</tbody></table></div>")
    w(
        '<p class="muted">'
        + e(
            T(
                "* Październik do końca dnia {d}. Darmowe kredyty, prognozy i ryzyka doliczenia "
                "są poza sumą (część c).",
                d=as_of_pl,
            )
        )
        + "</p>"
    )

    # (b) providers ---------------------------------------------------------------------------------
    w(f'<h2 id="b">{e(T("Koszty według dostawców"))}</h2>')
    w(
        '<div class="table-wrap"><table><thead><tr>'
        f'<th>{e(T("Dostawca i za co płacisz"))}</th><th class="num">{e(T("Łącznie (udział)"))}</th>'
        f'<th class="num">{e(T("Teraz / mies."))}</th></tr></thead><tbody>'
    )
    for p in econ["by_provider"]:
        native_txt = natives(p["native"])
        w(
            f'<tr><td><strong>{e(p["name_pl"])}</strong><br><span class="small">{e(p["what_pl"])}</span></td>'
            f'<td class="num">{e(zl(p["pln"]))}<br><span class="small">{e(native_txt)}<br>{e(pct(p["share_pct"]))}</span></td>'
            f'<td class="num">{e(zl(p["current_monthly_pln"]))}</td></tr>'
        )
    w(
        f'<tr class="total"><td>{e(T("Razem"))}</td><td class="num">{e(zl(econ["total_pln"]))}</td>'
        f'<td class="num">{e(zl(cur_m["total_pln"]))}</td></tr></tbody></table></div>'
    )
    w(f'<details><summary>{e(T("Pełna tabela: miesiąc × dostawca (zł)"))}</summary><div class="table-wrap"><table>')
    provs = [p["provider"] for p in econ["by_provider"]]
    names = {p["provider"]: p["name_pl"] for p in econ["by_provider"]}
    w(
        "<thead><tr><th>"
        + e(T("Miesiąc"))
        + "</th>"
        + "".join(f'<th class="num">{e(names[p])}</th>' for p in provs)
        + f'<th class="num">{e(T("Razem"))}</th></tr></thead><tbody>'
    )
    for m in econ["by_month"]:
        vals = {}
        for part in m["by_provider"]:
            vals[part["provider"]] = vals.get(part["provider"], Decimal(0)) + D(part["pln"])
        w(
            f"<tr><td>{e(pl_month(m['month'], short=True))}</td>"
            + "".join(f'<td class="num">{e(pl_num(vals.get(p, Decimal(0))))}</td>' for p in provs)
            + f'<td class="num">{e(pl_num(D(m["pln"])))}</td></tr>'
        )
    w("</tbody></table></div></details>")

    w(f"<h3>{e(T('Z czego składa się obecny koszt miesięczny'))}</h3>")
    w(
        '<div class="table-wrap"><table><thead><tr>'
        f'<th>{e(T("Pozycja"))}</th><th class="num">{e(T("Miesięcznie"))}</th></tr></thead><tbody>'
    )
    paid = [it for it in sorted(cur_m["items"], key=lambda r: -D(r["per_month_pln"])) if D(it["per_month_pln"]) != 0]
    free = [it for it in cur_m["items"] if D(it["per_month_pln"]) == 0]
    for it in paid:
        rng = "" if it["low_pln"] is None else T("przedział {lo} – {hi}", lo=zl(it["low_pln"]), hi=zl(it["high_pln"]))
        w(
            f'<tr><td>{e(it["label_pl"])}<br><span class="small">{e(rng)}</span></td>'
            f'<td class="num">{e(zl(it["per_month_pln"]))}<br><span class="small">'
            f"{e(nat(it['per_month_native'], it['currency']))}</span></td></tr>"
        )
    if free:
        w(
            f'<tr><td>{e(T("Bez kosztu (darmowe albo nieużywane)"))}<br><span class="small">'
            f'{e("; ".join(it["label_pl"] for it in free))}</span></td><td class="num">{e(zl("0"))}</td></tr>'
        )
    w(
        f'<tr class="total"><td>{e(T("Razem"))}<br><span class="small">'
        f"{e(T('przedział {lo} – {hi}', lo=zl(cur_m['low_pln']), hi=zl(cur_m['high_pln'])))}</span></td>"
        f'<td class="num">{e(zl(cur_m["total_pln"]))}</td></tr></tbody></table></div>'
    )
    w(
        '<p class="muted">'
        + e(
            T(
                "Kurs NBP z {d}. Numery Twilio narastają jako dług, dopóki konto jest zawieszone.",
                d=pl_date(S["fx"]["current"]["USD"]["date"]),
            )
        )
        + "</p>"
    )
    w(f"<h3>{e(T('Scenariusze (poza sumą)'))}</h3>")
    w(
        '<div class="table-wrap"><table><thead><tr>'
        f'<th>{e(T("Co, jeśli…"))}</th><th class="num">{e(T("Miesięcznie"))}</th></tr></thead><tbody>'
    )
    for it in cur_m["scenarios"]:
        rng = "" if it["low_pln"] is None else T("przedział {lo} – {hi}", lo=zl(it["low_pln"]), hi=zl(it["high_pln"]))
        w(
            f'<tr><td><strong>{e(it["label_pl"])}</strong><br><span class="small">{e(it["explain_pl"])}</span></td>'
            f'<td class="num">{e(zl(it["per_month_pln"]))}<br><span class="small">'
            f"{e(nat(it['per_month_native'], it['currency']))}<br>{e(rng)}</span></td></tr>"
        )
    w("</tbody></table></div>")

    # (c) cash vs cost -----------------------------------------------------------------------------
    cve = S["cash_vs_economic"]
    w(f'<h2 id="c">{e(T("Gotówka a koszt"))}</h2>')
    w(
        "<p>"
        + e(
            T(
                "Koszt to wartość tego, co Sentinel zużył: {k}. Gotówka to część Twoich płatności przypisana "
                "Sentinelowi, według dnia płatności: {g}. Różnica wynosi {d}.",
                k=zl(cve["economic_pln"]),
                g=zl(cve["cash_pln"]),
                d=zl(cve["difference_pln"]),
            )
        )
        + "</p>"
    )
    w('<p class="muted">' + e(cash["cutoff"]["text_pl"]) + "</p>")
    w('<ul class="plain">')
    for t in [
        T(
            "Kredyty kupowane z góry (Anthropic, OpenAI, OpenRouter): koszt liczę, gdy kredyt zostanie zużyty, "
            "a gotówkę, gdy zapłaciłeś. Niezużyta reszta leży na koncie."
        ),
        T(
            "Darmowe kredyty (próbny kredyt Twilio, kredyt powitalny TypeSafe): zużycie pokazuję osobno, ale nie "
            "liczę go ani do kosztu, ani do gotówki."
        ),
        T("Opłata roczna Apple: w całości w miesiącu zakupu; w koszcie miesięcznym podzielona na dwanaście."),
        T("Dług w Twilio: numery naliczają opłaty mimo zawieszenia konta. To koszt, ale jeszcze nie zapłacony."),
        T("Hetzner: październik jest naliczony, faktura przyjdzie w listopadzie."),
        T(
            "Kursy: koszt przeliczam po kursie z końca miesiąca zużycia, gotówkę po kursie z dnia przed płatnością, "
            "więc nawet przy tej samej kwocie w dolarach złotówki trochę się różnią."
        ),
    ]:
        w(f"<li>{e(t)}</li>")
    w("</ul>")
    w(
        '<div class="table-wrap"><table><thead><tr>'
        f'<th>{e(T("Dostawca i dlaczego się różni"))}</th><th class="num">{e(T("Koszt / gotówka"))}</th>'
        "</tr></thead><tbody>"
    )
    for r in cve["by_provider"]:
        if D(r["economic_pln"]) == 0 and D(r["cash_pln"]) == 0 and r["provider"] != "TypeSafe (Jev)":
            continue
        w(
            f'<tr><td><strong>{e(r["name_pl"])}</strong><br><span class="small">{e(r["why_pl"])}</span></td>'
            f'<td class="num">{e(T("koszt {v}", v=zl(r["economic_pln"])))}<br>'
            f'{e(T("gotówka {v}", v=zl(r["cash_pln"])))}<br><span class="small">'
            f"{e(T('różnica {v}', v=delta(r['difference_pln'])))}</span></td></tr>"
        )
    w(
        f'<tr class="total"><td>{e(T("Razem"))}</td><td class="num">{e(T("koszt {v}", v=zl(cve["economic_pln"])))}<br>'
        f'{e(T("gotówka {v}", v=zl(cve["cash_pln"])))}<br><span class="small">'
        f"{e(T('różnica {v}', v=delta(cve['difference_pln'])))}</span></td></tr>"
    )
    w("</tbody></table></div>")
    w(f"<h3>{e(T('Notatki poza sumą'))}</h3>")
    w(
        '<div class="table-wrap"><table><thead><tr>'
        f'<th>{e(T("Pozycja"))}</th><th>{e(T("Miesiąc"))}</th><th class="num">{e(T("Kwota"))}</th>'
        f"<th>{e(T('Rodzaj dowodu'))}</th></tr></thead><tbody>"
    )
    for n in econ["notes_not_in_total"]:
        w(
            f"<tr><td>{e(n['name_pl'])}: {e(n['label_pl'])}</td><td>{e(pl_month(n['month']))}</td>"
            f'<td class="num">{e(nat(n["native"], n["currency"]))}</td><td>{e(EVIDENCE_PL[n["evidence_class"]])}</td></tr>'
        )
    w("</tbody></table></div>")
    w(
        f'<details><summary>{e(T("Wszystkie płatności i próby płatności"))}</summary><div class="table-wrap"><table>'
        f'<thead><tr><th>{e(T("Data i dostawca"))}</th><th class="num">{e(T("Kwota"))}</th>'
        f'<th class="num">{e(T("Część Sentinela"))}</th></tr></thead><tbody>'
    )
    for ev in cash["events"]:
        rate = (
            ""
            if ev["fx_date"] is None
            else T("kurs {r} z {d}", r=pl_num(D(ev["fx_rate"]), 4), d=pl_date(ev["fx_date"]))
        )
        w(
            f'<tr><td>{e(pl_date(ev["date"]))}<br><span class="small">{e(ev["name_pl"])}, {e(ev["kind_pl"])}</span></td>'
            f'<td class="num">{e(nat(ev["amount"], ev["currency"]))}</td>'
            f'<td class="num">{e(zl(ev["sentinel_pln"]) if ev["counted"] else "—")}<br><span class="small">'
            f"{e(nat(ev['sentinel_amount'], ev['currency']))}<br>{e(rate)}</span></td></tr>"
        )
    w(
        f'<tr class="total"><td colspan="2">{e(T("Razem gotówka Sentinela"))}</td>'
        f'<td class="num">{e(zl(cash["total_pln"]))}</td></tr></tbody></table></div></details>'
    )

    # (d) excluded ---------------------------------------------------------------------------------
    ex = S["excluded"]
    w(f'<h2 id="d">{e(T("Czego nie liczę"))}</h2>')
    w(
        "<p>"
        + e(
            T(
                "Te wydatki znalazłem w poczcie i w panelach dostawców, ale nie są kosztem Sentinela. Nie wchodzą "
                "do żadnej sumy. Kwoty są w walucie dokumentu; wpisów zdublowanych w różnych częściach audytu "
                "połączyłem {n}.",
                n=ex["merged_duplicates"],
            )
        )
        + "</p>"
    )
    for cat in ex["categories"]:
        wrap_details = cat["reason"] in ("duplicate", "failed_payment", "pre_project")
        if wrap_details:
            w(f"<details><summary>{e(cat['title_pl'])}</summary>")
        else:
            w(f"<h3>{e(cat['title_pl'])}</h3>")
        w(f'<p class="muted">{e(cat["why_pl"])}</p>')
        w(
            '<div class="table-wrap"><table><thead><tr>'
            f'<th>{e(T("Pozycja"))}</th><th class="num">{e(T("Kwota"))}</th></tr></thead><tbody>'
        )
        for it in cat["items"]:
            per = it["period"]
            per_txt = "" if not per else (fmt_period(per[0]) + (" – " + fmt_period(per[1]) if per[1] else ""))
            sub = it["provider"] + (" · " + per_txt if per_txt else "")
            w(
                f'<tr><td>{e(it["label_pl"])}<br><span class="small">{e(sub)}</span></td>'
                f'<td class="num">{e(nat(it["amount"], it["currency"]))}</td></tr>'
            )
        w("</tbody></table></div>")
        if wrap_details:
            w("</details>")

    # (e) risks ------------------------------------------------------------------------------------
    w(f'<h2 id="e">{e(T("Ryzyka operacyjne"))}</h2>')
    w(
        "<p>"
        + e(
            T(
                "Kredyty i salda kończyły się już po cichu i wyłączały alerty. Dziś działa tylko kanał push. Poniżej "
                "najpierw to, co wymaga działania teraz."
            )
        )
        + "</p>"
    )
    for r in S["report_pl"]["risks"]:
        cls, badge = BADGE[r["level"]]
        w(
            f'<div class="risk"><span class="badge {cls}">{e(badge)}</span>'
            f"<h3>{e(r['title'])}</h3><p>{e(r['text'])}</p></div>"
        )

    # (q) questions and decisions -----------------------------------------------------------------
    qs = S["report_pl"]["questions"]
    w(f'<h2 id="q">{e(T("Pytania i decyzje"))}</h2>')
    w(
        "<p>"
        + e(
            T(
                "Wszystkie otwarte pytania z audytu ({n}), w trzech grupach. W każdej grupie najpierw to, co "
                "pilne. Pod każdym pytaniem są szczegóły po angielsku.",
                n=len(qs),
            )
        )
        + "</p>"
    )
    for cat in S["report_pl"]["question_categories"]:
        items = [q for q in qs if q["category"] == cat["category"]]
        if not items:
            continue
        w(f'<h3>{e(cat["title_pl"])} ({len(items)})</h3><ul class="plain">')
        for q in items:
            badge = f'<span class="badge crit">{e(BADGE["pilne"][1])}</span> ' if q["urgent"] else ""
            w(
                f'<li>{badge}{e(q["text_pl"])}<details class="q"><summary>{e(T("Szczegóły"))}</summary>'
                f'<p class="small" lang="en">{e(q["text_en"])}</p></details></li>'
            )
        w("</ul>")

    # (f) data confidence --------------------------------------------------------------------------
    w(f'<h2 id="f">{e(T("Pewność danych"))}</h2>')
    w(
        "<p>"
        + e(
            T(
                "Każda pozycja ma rodzaj dowodu. {p} kosztu opiera się na fakturach, wyciągach i panelach "
                "dostawców; szacunki to {s}.",
                p=pct(econ["provider_document_share_pct"]),
                s=pct(econ["estimate_share_pct"]),
            )
        )
        + "</p>"
    )
    w(
        '<div class="table-wrap"><table><thead><tr>'
        f'<th>{e(T("Rodzaj dowodu"))}</th><th class="num">{e(T("Kwota"))}</th><th class="num">{e(T("Udział"))}</th>'
        f'<th class="num">{e(T("Pozycji z kwotą"))}</th></tr></thead><tbody>'
    )
    for r in econ["by_evidence_class"]:
        w(
            f'<tr><td>{e(r["label_pl"])}</td><td class="num">{e(zl(r["pln"]))}</td>'
            f'<td class="num">{e(pct(r["share_pct"]))}</td><td class="num">{e(r["lines_nonzero"])}</td></tr>'
        )
    w("</tbody></table></div>")
    w(f"<h3>{e(T('Co pozostaje otwarte'))}</h3>")
    w(
        '<p class="muted">'
        + e(T("Najważniejsze niepewności co do kwot. Pełna lista pytań i decyzji jest w części "))
        + f'<a href="#q">{e(T("Pytania i decyzje"))}</a>.</p><ul class="plain">'
    )
    for t in S["report_pl"]["open_items"]:
        w(f"<li>{e(t)}</li>")
    w("</ul>")
    w(
        f'<details><summary>{e(T("Wszystkie pozycje z kwotą i ich dowody"))}</summary><div class="table-wrap"><table>'
        f'<thead><tr><th>{e(T("Pozycja"))}</th><th class="num">{e(T("Kwota"))}</th></tr></thead><tbody>'
    )
    for r in econ["lines_nonzero"]:
        w(
            f'<tr><td>{e(r["name_pl"])}: {e(r["label_pl"])}<br><span class="small">{e(pl_month(r["month"]))} · '
            f'{e(r["evidence_pl"])}</span></td><td class="num">{e(zl(r["pln"]))}<br><span class="small">'
            f"{e(nat(r['native'], r['currency']))}</span></td></tr>"
        )
    w("</tbody></table></div></details>")

    # (g) changes vs previous audit -----------------------------------------------------------------
    w(f'<h2 id="g">{e(T("Co się zmieniło od audytu z {d}", d=pl_date(prev["as_of"])))}</h2>')
    w(
        "<p>"
        + e(
            T(
                "Poprzedni audyt opierał się głównie na szacunkach z liczby wywołań i tokenów: szacunki stanowiły "
                "{p} jego kwoty. Teraz {now} kosztu pochodzi z faktur, wyciągów i paneli dostawców, a szacunki to "
                "{est}.",
                p=pct(prev["estimate_share_pct"]),
                now=pct(econ["provider_document_share_pct"]),
                est=pct(econ["estimate_share_pct"]),
            )
        )
        + "</p>"
    )
    w(
        '<div class="table-wrap"><table><thead><tr>'
        f'<th>{e(T("Wielkość"))}</th><th class="num">{e(T("Wtedy"))}</th><th class="num">{e(T("Teraz"))}</th>'
        f'<th class="num">{e(T("Zmiana"))}</th></tr></thead><tbody>'
    )
    w(
        f'<tr><td>{e(T("Łączny koszt"))}<br><span class="small">'
        f"{e(T('wtedy przedział {lo} – {hi}', lo=zl(prev['low_pln']), hi=zl(prev['high_pln'])))}</span></td>"
        f'<td class="num">{e(zl(prev["total_pln"]))}</td><td class="num">{e(zl(econ["total_pln"]))}</td>'
        f'<td class="num">{e(delta(prev["difference_total_pln"]))}</td></tr>'
    )
    w(
        f'<tr><td>{e(T("Obecny koszt miesięczny"))}</td><td class="num">{e(zl(prev["current_monthly_pln"]))}</td>'
        f'<td class="num">{e(zl(cur_m["total_pln"]))}</td>'
        f'<td class="num">{e(delta(prev["difference_current_monthly_pln"]))}</td></tr>'
    )
    w("</tbody></table></div>")
    w(f"<h3>{e(T('Według dostawców'))}</h3>")
    w(
        '<div class="table-wrap"><table><thead><tr>'
        f'<th>{e(T("Dostawca i co się zmieniło"))}</th><th class="num">{e(T("Wtedy"))}</th>'
        f'<th class="num">{e(T("Teraz"))}</th><th class="num">{e(T("Zmiana"))}</th></tr></thead><tbody>'
    )
    for r in prev["by_provider"]:
        w(
            f'<tr><td><strong>{e(r["name_pl"])}</strong><br><span class="small">{e(r["why_pl"])}</span></td>'
            f'<td class="num">{e(zl(r["previous_pln"]))}</td><td class="num">{e(zl(r["now_pln"]))}</td>'
            f'<td class="num">{e(delta(r["difference_pln"]))}</td></tr>'
        )
    w("</tbody></table></div>")
    w(f"<h3>{e(T('Według miesięcy'))}</h3>")
    w(
        '<div class="table-wrap"><table><thead><tr>'
        f'<th>{e(T("Miesiąc"))}</th><th class="num">{e(T("Wtedy"))}</th><th class="num">{e(T("Teraz"))}</th>'
        f'<th class="num">{e(T("Zmiana"))}</th></tr></thead><tbody>'
    )
    for m in econ["by_month"]:
        diff = D(m["pln"]) - D(m["previous_audit_pln"])
        w(
            f'<tr><td>{e(pl_month(m["month"]))}</td><td class="num">{e(zl(m["previous_audit_pln"]))}</td>'
            f'<td class="num">{e(zl(m["pln"]))}</td><td class="num">{e(delta(diff))}</td></tr>'
        )
    w("</tbody></table></div>")
    w(
        "<p>"
        + e(
            T(
                "Poprzedni audyt zostawił {n} kategorii bez kwoty (budowanie aplikacji, domeny i poczta, testy, "
                "kopie zapasowe, monitoring i płatne źródła). Teraz każda jest sprawdzona: koszt zero albo kwota "
                "ujęta u właściwego dostawcy.",
                n=len(prev["unpriced_categories"]),
            )
        )
        + "</p>"
    )
    w(
        '<p class="muted">'
        + e(
            T(
                "Poprzedni audyt policzył październik tylko do {d}; ten liczy do końca dnia {n}.",
                d=pl_date(prev["as_of"]),
                n=as_of_pl,
            )
        )
        + "</p>"
    )

    # (h) method -----------------------------------------------------------------------------------
    w(f'<h2 id="h">{e(T("Metoda i kursy NBP"))}</h2><ul class="plain">')
    for t in S["report_pl"]["method"]:
        w(f"<li>{e(t)}</li>")
    w("</ul>")
    w(f"<h3>{e(T('Kursy użyte dla kosztu (koniec miesiąca)'))}</h3>")
    w(
        '<div class="table-wrap"><table><thead><tr>'
        f'<th>{e(T("Miesiąc"))}</th><th>{e(T("Dzień kursu"))}</th><th class="num">USD</th><th class="num">EUR</th>'
        f"<th>{e(T('Tabela NBP'))}</th></tr></thead><tbody>"
    )
    for r in S["fx"]["month_end"]:
        w(
            f"<tr><td>{e(pl_month(r['month']))}</td><td>{e(pl_date(r['USD']['date']))}</td>"
            f'<td class="num">{e(pl_num(D(r["USD"]["rate"]), 4))}</td><td class="num">{e(pl_num(D(r["EUR"]["rate"]), 4))}</td>'
            f"<td>{e(r['USD']['table'])}</td></tr>"
        )
    w("</tbody></table></div>")
    w(
        '<p class="muted">'
        + e(T("Kursy dla każdej płatności są w tabeli płatności (część c) i w pliku cash.csv."))
        + "</p>"
    )
    w(f'<h3>{e(T("Pliki"))}</h3><ul class="plain">')
    for fname, desc in [
        ("summary.json", T("wszystkie sumy i wartości z tego raportu")),
        ("ledger.csv", T("każda pozycja kosztu z kursem i kwotą w złotych")),
        ("monthly.csv", T("miesiąc × dostawca, sumy miesięcy i całości")),
        ("cash.csv", T("płatności według dnia zapłaty")),
        ("current-monthly.csv", T("obecny koszt miesięczny i scenariusze")),
        ("excluded.csv", T("czego nie liczę i dlaczego")),
        ("input/lines.json", T("dane wejściowe: uzgodnione pozycje wszystkich dostawców")),
    ]:
        w(f'<li><a href="{e(fname)}">{e(fname)}</a>: {e(desc)}</li>')
    w("</ul>")
    w(
        "<footer>"
        + e(
            T(
                "Każda liczba w tym raporcie pochodzi z pliku summary.json, który skrypt {s} liczy z plików "
                "wejściowych. Polecenie z opcją --check sprawdza, czy pliki zgadzają się z wejściem.",
                s=S["generator"],
            )
        )
        + "</footer>"
    )
    w("</main></body></html>\n")
    return "\n".join(out)


def fmt_period(p):
    if len(p) == 7:
        return pl_month(p)
    return pl_date(p)


def render_chart(S, e):
    series = S["chart"]["series"]
    months = S["chart"]["months"]
    Wd, H, ml, mr, mt, mb = 480, 280, 44, 6, 26, 34
    pw, ph = Wd - ml - mr, H - mt - mb
    maxv = max(Decimal(m["total"]) for m in months)
    step = None
    for cand in (10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 2500, 5000, 10000):
        if math.ceil(maxv / cand) <= 5:
            step = Decimal(cand)
            break
    ymax = step * max(1, math.ceil(maxv / step))
    y = lambda v: mt + ph - float(v) / float(ymax) * ph  # noqa: E731
    parts = []
    legend = "".join(f'<span><span class="sw b{s["slot"]}"></span>{e(s["label"])}</span>' for s in series)
    parts.append(f'<div class="legend" aria-hidden="true">{legend}</div>')
    parts.append(
        f'<svg class="chart" viewBox="0 0 {Wd} {H}" role="img" '
        f'aria-label="{e(T("Wykres słupkowy: koszt w kolejnych miesiącach, w podziale na dostawców"))}">'
    )
    t = Decimal(0)
    while t <= ymax:
        yy = y(t)
        parts.append(f'<line class="grid" x1="{ml}" x2="{Wd - mr}" y1="{yy:.1f}" y2="{yy:.1f}"/>')
        parts.append(f'<text x="{ml - 8}" y="{yy + 4:.1f}" text-anchor="end">{e(pl_num(t, 0))}</text>')
        t += step
    slot = pw / len(months)
    bw = min(24.0, slot * 0.5)
    gap = 2.0
    for i, m in enumerate(months):
        cx = ml + slot * (i + 0.5)
        x0 = cx - bw / 2
        segs = [(series[k], Decimal(v)) for k, v in enumerate(m["values"]) if Decimal(v) > 0]
        base = mt + ph
        for k, (s, v) in enumerate(segs):
            h = float(v) / float(ymax) * ph
            top = base - h
            last = k == len(segs) - 1
            title = e(T("{s}, {m}: {v}", s=s["label"], m=pl_month(m["month"]), v=pl_num(v) + " zł"))
            hh = h if last else h - gap
            if hh > 0.6:
                if last:
                    r = min(4.0, hh / 2, bw / 2)
                    d = (
                        f"M{x0:.1f},{base:.1f} V{top + r:.1f} Q{x0:.1f},{top:.1f} {x0 + r:.1f},{top:.1f} "
                        f"H{x0 + bw - r:.1f} Q{x0 + bw:.1f},{top:.1f} {x0 + bw:.1f},{top + r:.1f} V{base:.1f} Z"
                    )
                    parts.append(f'<path class="c{s["slot"]}" d="{d}"><title>{title}</title></path>')
                else:
                    parts.append(
                        f'<rect class="c{s["slot"]}" x="{x0:.1f}" y="{top + gap:.1f}" width="{bw:.1f}" '
                        f'height="{hh:.1f}"><title>{title}</title></rect>'
                    )
            base = top
        parts.append(
            f'<text x="{cx:.1f}" y="{y(Decimal(m["total"])) - 6:.1f}" text-anchor="middle">'
            f"{e(pl_num(Decimal(m['total']), 0))}</text>"
        )
        label = pl_month(m["month"], short=True) + ("*" if m["partial"] else "")
        parts.append(f'<text x="{cx:.1f}" y="{H - mb + 18}" text-anchor="middle">{e(label)}</text>')
    parts.append(f'<text x="{ml - 8}" y="{mt - 12}" text-anchor="end">zł</text>')
    parts.append("</svg>")
    return "\n".join(parts)


# --------------------------------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="recompute and compare with the written files")
    args = ap.parse_args()
    outputs, summary = build()
    econ = summary["economic"]["total_pln_rounded"]
    cashv = summary["cash"]["total_pln_rounded"]
    cur = summary["current_monthly"]["total_pln_rounded"]
    if args.check:
        bad = []
        for path, content in outputs.items():
            if not path.exists():
                bad.append(f"missing: {path.relative_to(FIN.parent)}")
            elif path.read_bytes() != content:
                bad.append(f"differs: {path.relative_to(FIN.parent)}")
        if bad:
            print("CHECK FAILED")
            for b in bad:
                print("  " + b)
            sys.exit(1)
        print(
            f"CHECK OK: {len(outputs)} files match the inputs. Economic cost {econ} PLN; "
            f"cash {cashv} PLN; current monthly {cur} PLN."
        )
        return
    for path, content in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    print(f"Wrote {len(outputs)} files. Economic cost {econ} PLN; cash {cashv} PLN; current monthly {cur} PLN.")


if __name__ == "__main__":
    main()
