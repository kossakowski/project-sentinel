"""One-page plain-language report: verdict, quality, price, and a quality-vs-price chart.

Inputs are the offline score (``score.py``) and the substitute-cost table (``price.py``).
The pre-registered decision rule is applied here, so the verdict never depends on
reading the numbers by hand.
"""

import argparse
import asyncio
import html
import json
import math
from datetime import UTC, datetime
from pathlib import Path

from sentinel.eval.openrouter_client import fetch_model_catalogue
from sentinel.eval.suite.price import price_table

MAX_INVALID_RATE = 0.005
# Pre-registered on 2026-09-24 (operator chose the strict variant): the paired
# difference must stay within these limits both on average and at the pessimistic end of
# its 95% interval. Doubt keeps the current model.
RECALL_MARGIN = 0.02
TIER_MARGIN = 0.02
FALSE_CALL_MARGIN = 0.01
PESSIMISTIC_MARGIN = 0.05


def pct(value, digits=0) -> str:
    return "–" if value is None else f"{value * 100:.{digits}f}%"


def rate_cell(rate) -> str:
    """'92% (85–96%) n=60' from a (p, low, high, n) tuple."""
    if not rate:
        return "–"
    p, low, high, n = rate
    return f"{pct(p)} <span class=muted>({pct(low)}–{pct(high)}) n={n}</span>"


def seconds(value) -> str:
    return "–" if value is None else f"{value:.1f} s"


def usd(value, digits=2) -> str:
    return "–" if value is None else f"${value:,.{digits}f}"


def decide(model: str, baseline: str, score: dict, prices: dict) -> dict:
    """Pre-registered rule: every check must pass for a candidate to replace the baseline.

    Quality checks use the paired difference on items both models answered, so a model
    that skipped hard items cannot look better; each must hold on average and at the
    pessimistic end of the 95% interval. The coverage check fails any model that left
    items unanswered after retries.
    """
    report = score["models"][model]
    paired = score["paired_vs_baseline"].get(model, {})
    cost = prices["models"].get(model, {})
    base_cost = prices["models"].get(baseline, {})

    def diff(key):
        """(average, pessimistic low, pessimistic high, verdict) of candidate minus baseline."""
        entry = paired.get(key) or {}
        interval = entry.get("difference")
        return (*(interval or (None, None, None)), entry.get("verdict", ""))

    recall, recall_low, _, recall_verdict = diff("critical_hit")
    false_call, _, false_high, _ = diff("false_call")
    tier, tier_low, _, tier_verdict = diff("tier_ok")
    invalid = (report["invalid_call_rate"] or (0.0,))[0]
    checks = {
        "Odpowiedział na każdy artykuł": report.get("missing_answers", 1) == 0,
        "Nie przegapia więcej sytuacji „uciekaj”": recall is not None
        and recall >= -RECALL_MARGIN
        and recall_low >= -PESSIMISTIC_MARGIN,
        f"Telefonów bez powodu najwyżej {pct(FALSE_CALL_MARGIN)} pkt więcej": false_call is None
        or (false_call <= FALSE_CALL_MARGIN and false_high <= PESSIMISTIC_MARGIN),
        f"Zepsute odpowiedzi ≤ {pct(MAX_INVALID_RATE, 1)}": invalid <= MAX_INVALID_RATE,
        f"Trafność reakcji najwyżej {pct(TIER_MARGIN)} pkt gorsza": tier is not None
        and tier >= -TIER_MARGIN
        and tier_low >= -PESSIMISTIC_MARGIN,
        "Mieści się w limicie w tłocznym miesiącu": bool(cost.get("within_cap_busy_month")),
        "Tańszy albo udowodnienie lepszy": bool(
            (cost.get("total") and base_cost.get("total") and cost["total"] < base_cost["total"])
            or recall_verdict.startswith("lepszy")
            or tier_verdict.startswith("lepszy")
        ),
    }
    return {"checks": checks, "replace": all(checks.values())}


def pareto(points: list[tuple[str, float, float]]) -> set[str]:
    """Models no other model beats on both price (lower) and quality (higher)."""
    front = set()
    for name, cost, quality in points:
        if not any(c <= cost and q >= quality and (c < cost or q > quality) for n, c, q in points if n != name):
            front.add(name)
    return front


def chart_svg(rows: list[dict], baseline: str, front: set[str]) -> str:
    """Quality (tier accuracy with its interval) against busy-month cost, log price axis."""
    rows = [r for r in rows if r["cost"] and r["quality"]]
    if not rows:
        return "<p class=muted>Brak danych do wykresu.</p>"
    width, height, left, right, top, bottom = 760, 420, 64, 150, 20, 56
    costs = [r["cost"] for r in rows]
    x_min, x_max = math.log10(min(costs) * 0.8), math.log10(max(costs) * 1.25)
    y_min = max(0.0, min(r["quality"][1] for r in rows) - 0.05)
    y_max = min(1.0, max(r["quality"][2] for r in rows) + 0.03)

    def x(cost):
        return left + (math.log10(cost) - x_min) / (x_max - x_min) * (width - left - right)

    def y(value):
        return top + (1 - (value - y_min) / (y_max - y_min)) * (height - top - bottom)

    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Jakość względem ceny" class=chart>']
    for tick in [0.5, 1, 2, 5, 10, 20, 50, 100, 200]:
        if x_min <= math.log10(tick) <= x_max:
            parts.append(f'<line class=grid x1="{x(tick):.1f}" x2="{x(tick):.1f}" y1="{top}" y2="{height - bottom}"/>')
            parts.append(
                f'<text class=axis x="{x(tick):.1f}" y="{height - bottom + 18}" text-anchor=middle>${tick:g}</text>'
            )
    step = 0.05 if y_max - y_min <= 0.4 else 0.1
    value = math.ceil(y_min / step) * step
    while value <= y_max + 1e-9:
        parts.append(f'<line class=grid x1="{left}" x2="{width - right}" y1="{y(value):.1f}" y2="{y(value):.1f}"/>')
        parts.append(
            f'<text class=axis x="{left - 8}" y="{y(value) + 4:.1f}" text-anchor=end>{value * 100:.0f}%</text>'
        )
        value += step
    parts.append(
        f'<text class=axis x="{(left + width - right) / 2}" y="{height - 12}" text-anchor=middle>'
        "Koszt miesięczny w tłocznym miesiącu (skala logarytmiczna)</text>"
    )
    parts.append(
        f'<text class=axis transform="translate(16 {(top + height - bottom) / 2}) rotate(-90)" text-anchor=middle>'
        "Trafność reakcji</text>"
    )
    for r in sorted(rows, key=lambda r: (r["model"] == baseline, r["model"] in front)):
        group = "base" if r["model"] == baseline else ("front" if r["model"] in front else "other")
        cx, cy = x(r["cost"]), y(r["quality"][0])
        tip = html.escape(
            f"{r['label']} · trafność {pct(r['quality'][0])} ({pct(r['quality'][1])}–{pct(r['quality'][2])}) · "
            f"{usd(r['cost'])}/mies. · krytyczne {pct(r['recall'])}"
        )
        parts.append(f'<g class="pt {group}"><title>{tip}</title>')
        parts.append(
            f'<line class=err x1="{cx:.1f}" x2="{cx:.1f}" y1="{y(r["quality"][1]):.1f}" y2="{y(r["quality"][2]):.1f}"/>'
        )
        if group == "base":
            parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="7"/>')
        elif group == "front":
            parts.append(
                f'<rect x="{cx - 6:.1f}" y="{cy - 6:.1f}" width="12" height="12" transform="rotate(45 {cx:.1f} {cy:.1f})"/>'
            )
        else:
            parts.append(f'<rect x="{cx - 5:.1f}" y="{cy - 5:.1f}" width="10" height="10" rx="2"/>')
        parts.append(f'<rect class=hit x="{cx - 14:.1f}" y="{cy - 14:.1f}" width="28" height="28"/>')
        parts.append(f'<text class=lbl x="{cx + 10:.1f}" y="{cy + 4:.1f}">{html.escape(r["label"])}</text></g>')
    parts.append("</svg>")
    legend = (
        '<div class=legend><span><i class="sw base"></i>Luna – dziś w produkcji</span>'
        '<span><i class="sw front"></i>Najlepszy stosunek jakości do ceny</span>'
        '<span><i class="sw other"></i>Pozostałe</span></div>'
    )
    return legend + "".join(parts)


STYLE = """
:root { color-scheme: light; --bg:#fcfcfb; --card:#ffffff; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781;
  --line:#e4e2dc; --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a; --good:#1a7f37; --bad:#c62828; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { color-scheme: dark; --bg:#1a1a19; --card:#222221;
  --ink:#ffffff; --ink2:#c3c2b7; --line:#34332f; --s1:#3987e5; --s2:#d95926; --s3:#199e70; --good:#4ac26b; --bad:#ff7b72; } }
:root[data-theme="dark"] { color-scheme: dark; --bg:#1a1a19; --card:#222221; --ink:#ffffff; --ink2:#c3c2b7; --line:#34332f;
  --s1:#3987e5; --s2:#d95926; --s3:#199e70; --good:#4ac26b; --bad:#ff7b72; }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--ink); font:15px/1.5 system-ui,"Segoe UI",sans-serif; }
main { max-width:1100px; margin:0 auto; padding:24px 16px 64px; }
h1 { font-size:26px; margin:0 0 4px; } h2 { font-size:19px; margin:32px 0 10px; }
.muted { color:var(--muted); } .card { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:16px; }
.scroll { overflow-x:auto; } table { border-collapse:collapse; width:100%; font-variant-numeric:tabular-nums; }
th, td { text-align:left; padding:7px 10px; border-bottom:1px solid var(--line); vertical-align:top; white-space:nowrap; }
th { color:var(--ink2); font-weight:600; font-size:13px; }
.yes { color:var(--good); font-weight:600; } .no { color:var(--bad); font-weight:600; }
.verdict { font-size:17px; } ul.tight li { margin:3px 0; }
svg.chart { width:100%; max-width:900px; height:auto; } .grid { stroke:var(--line); } .axis { fill:var(--muted); font-size:12px; }
.err { stroke:var(--ink2); stroke-width:2; opacity:.45; } .lbl { fill:var(--ink2); font-size:12px; }
.pt.base circle { fill:var(--s1); stroke:var(--card); stroke-width:2; } .pt.front rect { fill:var(--s2); stroke:var(--card); stroke-width:2; }
.pt.other rect { fill:var(--s3); stroke:var(--card); stroke-width:2; } .pt rect.hit { fill:transparent !important; stroke:none !important; }
.pt:hover .lbl { fill:var(--ink); font-weight:600; }
.legend { display:flex; gap:18px; flex-wrap:wrap; color:var(--ink2); font-size:13px; margin-bottom:6px; }
.sw { display:inline-block; width:11px; height:11px; margin-right:6px; vertical-align:-1px; border-radius:2px; }
.sw.base { background:var(--s1); border-radius:50%; } .sw.front { background:var(--s2); transform:rotate(45deg); } .sw.other { background:var(--s3); }
"""


REASONING_NOTE = " (z myśleniem – inne warunki niż produkcja)"


def build_html(score: dict, prices: dict, labels: dict) -> str:
    """``labels`` maps spec -> display name; +reasoning specs are always flagged."""
    labels = {
        m: labels.get(m, m.split("/")[-1].partition("@")[0].removesuffix("+reasoning"))
        + (REASONING_NOTE if m.endswith("+reasoning") else "")
        for m in score["models"]
    }
    baseline = score["baseline"]
    models = list(score["models"])
    decisions = {m: decide(m, baseline, score, prices) for m in models if m != baseline}
    rows = []
    for m in models:
        report, cost = score["models"][m], prices["models"].get(m, {})
        rows.append(
            {
                "model": m,
                "label": labels[m],
                "cost": (cost.get("monthly") or {}).get("busy_day_p90"),
                "quality": report["tier_accuracy"],
                "recall": (report["critical_recall"] or (None,))[0],
            }
        )
    front = pareto([(r["model"], r["cost"], r["quality"][0]) for r in rows if r["cost"] and r["quality"]])
    winners = [m for m, d in decisions.items() if d["replace"]]
    retest = score.get("retest", {})
    out = [
        "<!doctype html><html lang=pl><head><meta charset=utf-8><meta name=viewport content='width=device-width, initial-scale=1'>"
    ]
    out.append(f"<title>Porównanie modeli</title><style>{STYLE}</style></head><body><main>")
    out.append("<h1>Porównanie modeli dla Sentinela</h1>")
    out.append(
        f"<p class=muted>Przebieg {html.escape(score['run'])} · pula {html.escape(str(score['manifest'].get('pool')))} · "
        f"{score['labelled_items']} ocenionych artykułów, w tym {score['critical_items']} sytuacji „uciekaj” · "
        f"{score['manifest'].get('repeats')} powtórzenia na model · wygenerowano {datetime.now(UTC):%Y-%m-%d %H:%M} UTC</p>"
    )
    verdict = (
        "Żaden kandydat nie spełnia wszystkich warunków – zostajemy przy obecnym modelu."
        if not winners
        else "Warunki spełnia: " + ", ".join(html.escape(labels.get(m, m)) for m in winners) + "."
    )
    not_run = [m for m in score["manifest"].get("models", []) if m not in score["models"]]
    if not_run:
        verdict += " Nie uruchomiono: " + ", ".join(html.escape(m) for m in not_run) + "."
    if score["manifest"].get("pool") == "locked" and score.get("unlabelled_items_in_pool", 0):
        verdict = (
            f"Brak werdyktu: {score['unlabelled_items_in_pool']} artykułów z puli nie ma jeszcze Twojej oceny. "
            "Podgląd: " + verdict
        )
    if score["manifest"].get("pool") != "locked":
        verdict = (
            "To pula robocza – wynik służy do sprawdzenia testu, nie do decyzji. "
            "Decyzję daje dopiero jednorazowy przebieg na puli zablokowanej. Podgląd: " + verdict
        )
    out.append(f"<div class='card verdict'><b>Werdykt:</b> {verdict}</div>")
    if retest.get("pairs"):
        same = retest["same_action"]
        out.append(
            f"<p class=muted>Twoja spójność: w {retest['pairs']} ukrytych powtórkach ta sama reakcja w {pct(same[0])} "
            f"przypadków. Różnice między modelami mniejsze niż ten szum nie są rozstrzygające.</p>"
        )
    out.append(
        "<h2>Czy kandydat może zastąpić Lunę? (warunki ustalone przed testem)</h2><div class='card scroll'><table><tr><th>Model</th>"
    )
    check_names = list(next(iter(decisions.values()))["checks"]) if decisions else []
    out += [f"<th>{html.escape(c)}</th>" for c in check_names] + ["<th>Wynik</th></tr>"]
    for m, d in decisions.items():
        out.append(f"<tr><td>{html.escape(labels.get(m, m))}</td>")
        out += [f"<td class={'yes' if ok else 'no'}>{'tak' if ok else 'nie'}</td>" for ok in d["checks"].values()]
        out.append(
            f"<td class={'yes' if d['replace'] else 'no'}>{'może zastąpić' if d['replace'] else 'nie'}</td></tr>"
        )
    out.append("</table></div>")
    out.append(
        "<h2>Jakość</h2><div class='card scroll'><table><tr><th>Model</th><th>Sytuacje „uciekaj” – zadzwonił</th>"
        "<th>Telefon bez powodu</th><th>Trafna reakcja</th><th>Kraje dokładnie</th><th>Zepsute odpowiedzi</th>"
        "<th>Zmienia zdanie</th><th>Czas p95</th></tr>"
    )
    for m in models:
        r = score["models"][m]
        out.append(
            f"<tr><td>{html.escape(labels.get(m, m))}</td><td>{rate_cell(r['critical_recall'])}</td><td>{rate_cell(r['false_call_rate'])}</td>"
            f"<td>{rate_cell(r['tier_accuracy'])}</td><td>{rate_cell(r['countries_exact'])}</td>"
            f"<td>{rate_cell(r['invalid_call_rate'])}</td><td>{rate_cell(r['flip_rate'])}</td>"
            f"<td>{seconds(r['latency_p95'])}</td></tr>"
        )
    out.append("</table></div>")
    review = [
        (m, (score["paired_vs_baseline"].get(m, {}).get("critical_hit") or {}).get("baseline_only_items", []))
        for m in models
        if m != baseline
    ]
    if any(ids for _, ids in review):
        out.append(
            "<h2>Sytuacje „uciekaj”, które Luna złapała, a kandydat przegapił</h2><div class=card><ul class=tight>"
        )
        for m, ids in review:
            if ids:
                out.append(f"<li><b>{html.escape(labels[m])}</b>: {html.escape(', '.join(ids))}</li>")
        out.append("</ul></div>")
    out.append("<h2>Jakość względem ceny</h2><div class=card>" + chart_svg(rows, baseline, front) + "</div>")
    out.append(
        "<h2>Ile kosztowałby zamiast Luny</h2><div class='card scroll'><table><tr><th>Model</th><th>Za 1000 artykułów</th>"
        f"<th>Miesiąc średni ({prices['volumes']['average_day']:.0f}/dzień)</th>"
        f"<th>Miesiąc tłoczny ({prices['volumes']['busy_day_p90']}/dzień)</th>"
        f"<th>Jak w rekordowy dzień ({prices['volumes']['busiest_day']}/dzień)</th><th>Względem Luny</th>"
        f"<th>Limit ${prices['monthly_cap_usd']:.0f}</th></tr>"
    )
    for m in sorted(prices["models"], key=lambda k: prices["models"][k]["total"]):
        c = prices["models"][m]
        out.append(
            f"<tr><td>{html.escape(labels.get(m, m))}</td><td>{usd(c['per_1000_articles'])}</td>"
            f"<td>{usd(c['monthly']['average_day'])}</td><td>{usd(c['monthly']['busy_day_p90'])}</td>"
            f"<td>{usd(c['monthly']['busiest_day'])}</td><td>{c['vs_baseline']:.2f}×</td>"
            f"<td class={'yes' if c['within_cap_busy_month'] else 'no'}>{'mieści się' if c['within_cap_busy_month'] else 'przekracza'}</td></tr>"
        )
    out.append(
        "</table><p class=muted>Koszt zmierzony z rzeczywistych opłat za zapytania w teście, przeliczony na długość zapytań "
        "w produkcji (z pamięcią incydentów), plus ponowienia po zepsutych odpowiedziach i poprawki streszczeń nie po polsku.</p></div>"
    )
    out.append(
        "<h2>Serie artykułów o jednym zdarzeniu</h2><div class='card scroll'><table><tr><th>Model</th><th>Poprawnie „to samo”</th>"
        "<th>Błędne złączenie</th><th>…w tym przy sytuacji „uciekaj”</th><th>Zbędne powiadomienie</th><th>Brakujące powiadomienie</th></tr>"
    )
    for m in models:
        s = score["models"][m]["sequences"]
        out.append(
            f"<tr><td>{html.escape(labels.get(m, m))}</td><td>{s.get('same_ok', 0)}/{s.get('same_expected', 0)}</td>"
            f"<td>{s.get('wrong_merge', 0)}/{s.get('new_expected', 0)}</td><td>{s.get('wrong_merge_critical', 0)}</td>"
            f"<td>{s.get('duplicate_notification', 0)}/{s.get('silent_expected', 0)}</td>"
            f"<td>{s.get('missed_notification', 0)}/{s.get('notify_expected', 0)}</td></tr>"
        )
    out.append("</table></div>")
    out.append("<h2>Trafna reakcja według rodzaju tekstu</h2><div class='card scroll'><table><tr><th>Model</th>")
    slice_names = list(score["models"][models[0]]["slices"]) if models else []
    names = {
        "prod:9-10": "produkcja 9–10",
        "prod:7-8": "produkcja 7–8",
        "prod:5-6": "produkcja 5–6",
        "prod:1-4": "produkcja 1–4",
        "lang:pl": "polski",
        "lang:en": "angielski",
        "lang:uk": "ukraiński",
        "lang:ru": "rosyjski",
        "input:headline_only": "sam nagłówek",
        "input:enriched": "dociągnięty tekst",
        "input:full_summary": "pełny opis",
        "origin:synthetic": "trudne syntetyczne",
    }
    out += [f"<th>{names.get(s, s)}</th>" for s in slice_names] + ["</tr>"]
    for m in models:
        out.append(f"<tr><td>{html.escape(labels.get(m, m))}</td>")
        out += [f"<td>{rate_cell(score['models'][m]['slices'][s]['tier_ok'])}</td>" for s in slice_names]
        out.append("</tr>")
    out.append("</table></div>")
    out.append(
        "<h2>Jak to czytać</h2><ul class=tight>"
        "<li>W nawiasie jest zakres, w którym z 95% pewnością leży prawdziwy wynik. Nakładające się zakresy oznaczają brak dowodu różnicy.</li>"
        "<li>„Zadzwonił” liczy się tylko przy ocenie 9–10. Zepsuta odpowiedź na sytuację „uciekaj” liczy się jako przegapiona.</li>"
        "<li>Każdy artykuł dostał 3 próby. Liczy się większość; „zmienia zdanie” pokazuje, jak często próby się różnią.</li>"
        "<li>Porównanie z Luną idzie na tych samych artykułach; artykuły o jednym zdarzeniu liczą się razem, nie osobno.</li>"
        "<li>Ograniczenie: artykuły dobrano według ocen, które wystawił wcześniej model produkcyjny (głównie Haiku). "
        "Wszystkie jego 9–10 są w teście, ale z artykułów ocenionych przez niego nisko tylko ok. 25. Sytuacja „uciekaj”, "
        "którą produkcja oceniła nisko, jest więc w teście rzadka – kolumny „produkcja 1–4 / 5–6” pokazują ją osobno.</li></ul>"
    )
    out.append("</main></body></html>")
    return "".join(out)


async def model_prices(specs: list[str]) -> dict:
    """Catalogue prices per run spec (``vendor/model@host+reasoning`` → the bare model's price)."""
    ids = {spec: spec.removesuffix("+reasoning").partition("@")[0] for spec in specs}
    catalogue = await fetch_model_catalogue(model_ids=frozenset(ids.values()))
    return {
        spec: {
            "input": float(catalogue[i].pricing.prompt) * 1e6,
            "cached_input": float(catalogue[i].pricing.input_cache_read or catalogue[i].pricing.prompt) * 1e6,
            "output": float(catalogue[i].pricing.completion) * 1e6,
        }
        for spec, i in ids.items()
        if i in catalogue
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", help="Run folder with score.json")
    parser.add_argument("--volume", default="data/eval/suite/volume.json")
    parser.add_argument("--monthly-cap", type=float, default=10.0)
    parser.add_argument("--labels", help="JSON map model id -> display name")
    parser.add_argument("--output")
    args = parser.parse_args()
    run_dir = Path(args.run)
    score = json.loads((run_dir / "score.json").read_text(encoding="utf-8"))
    snapshot = json.loads(Path(args.volume).read_text(encoding="utf-8"))
    prices_per_model = asyncio.run(model_prices(list(score["models"])))
    prices = price_table(score["models"], score["baseline"], snapshot, prices_per_model, args.monthly_cap)
    (run_dir / "price.json").write_text(json.dumps(prices, indent=1), encoding="utf-8")
    labels = json.loads(Path(args.labels).read_text(encoding="utf-8")) if args.labels else {}
    output = Path(args.output) if args.output else run_dir / "report.html"
    output.write_text(build_html(score, prices, labels), encoding="utf-8")
    print(f"Saved {output}")


if __name__ == "__main__":
    main()
