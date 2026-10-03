"""Local blind-labelling page for the eval suite.

Shows only what the model saw (title, text, source, language, time). Never shows a
model score, production urgency, synthetic target or origin. Every answer is appended
to a JSONL file immediately, so a crash or closed tab loses nothing.

Run: .venv/bin/python -m sentinel.eval.suite.label_server   then open http://localhost:8774/
"""

import argparse
import http.server
import json
import random
import socketserver
from datetime import UTC, datetime
from pathlib import Path

PAGE = Path(__file__).with_name("label_page.html")
ITEMS = Path("data/eval/suite/items.json")
QUEUE = Path("data/eval/suite/queue.json")
LABELS = Path("data/eval/suite/labels.jsonl")
TRANSLATIONS = Path("data/eval/suite/translations.json")
RETEST_COUNT = 20
TIERS = {"FLEE": (9, 10), "WATCH": (7, 8), "NOTE": (5, 6), "NOISE": (1, 4)}
COUNTRIES = {"PL", "LT", "LV", "EE"}
# A second possible score may differ by at most this much; wider ranges would make
# almost every model answer count as correct.
MAX_ALT_GAP = 2


def build_queue(items: list[dict], seed: int, retest_count: int = RETEST_COUNT) -> list[dict]:
    """Shuffle labelling units (a chain stays together, in time order); add hidden repeats.

    Repeats are drawn from single production items in the first 60% of the queue and
    placed at random in the last 40%, so there is a long gap before they reappear. They
    are indistinguishable on screen.
    """
    rng = random.Random(seed)
    units: dict[str, list[dict]] = {}
    for item in items:
        units.setdefault(item["chain_id"] or item["id"], []).append(item)
    order = sorted(units)
    rng.shuffle(order)
    slots, unit_of = [], []
    for key in order:
        for item in sorted(units[key], key=lambda i: (i["chain_pos"] or 0, i["article"]["fetched_at"])):
            slots.append({"slot": "", "item_id": item["id"], "retest_of": None})
            unit_of.append(key)
    early = {s["item_id"] for s in slots[: int(len(slots) * 0.6)]}
    candidates = sorted(
        i["id"] for i in items if i["origin"] == "production" and not i["chain_id"] and i["id"] in early
    )
    repeats = rng.sample(candidates, min(retest_count, len(candidates)))
    # Hide repeats in the last 40%, only between labelling units (never inside a chain).
    tail_start = int(len(slots) * 0.6)
    boundaries = [p for p in range(tail_start, len(slots) + 1) if p == len(slots) or unit_of[p - 1] != unit_of[p]]
    chosen = []
    for item_id in repeats:
        # Never directly after its own original, and at most one repeat per boundary.
        options = [p for p in boundaries if p not in chosen and slots[p - 1]["item_id"] != item_id]
        if options:
            chosen.append(rng.choice(options))
    for position, item_id in sorted(zip(chosen, repeats, strict=False), reverse=True):
        slots.insert(position, {"slot": "", "item_id": item_id, "retest_of": item_id})
    for number, slot in enumerate(slots, 1):
        slot["slot"] = f"s{number:03d}"
    return slots


def public_view(item: dict, slot: dict, chain_earlier: list[dict], translation: dict | None = None) -> dict:
    """The only item data the page ever receives (plus a Polish translation and the full text)."""
    article = item["article"]
    return {
        "slot": slot["slot"],
        "title": article["title"],
        "summary": article["summary"],
        "source_name": article["source_name"],
        "source_type": article["source_type"],
        "language": article["language"],
        "published_at": article["published_at"],
        "in_chain": bool(item["chain_id"]) and slot["retest_of"] is None,
        "chain_earlier": chain_earlier,
        "translation": translation,
        # Full page text for the operator's judgment (the model sees only the summary).
        "full_text": item.get("full_text") if item.get("full_text_status") == "ok" else None,
    }


def validate_label(label: dict, slots: dict[str, dict]) -> dict:
    slot = slots.get(label.get("slot"))
    if slot is None:
        raise ValueError("unknown slot")
    tier = label.get("tier")
    if tier not in TIERS:
        raise ValueError("tier required")
    urgency = label.get("urgency")
    low, high = TIERS[tier]
    if type(urgency) is not int or not low <= urgency <= high:
        raise ValueError("urgency must lie inside the chosen tier")
    alternative = label.get("urgency_alt")
    if alternative is not None and (
        type(alternative) is not int or not 1 <= alternative <= 10 or abs(alternative - urgency) > MAX_ALT_GAP
    ):
        raise ValueError(f"alternative urgency must be 1-10 and within {MAX_ALT_GAP} of the main one")
    countries = label.get("countries", [])
    if not isinstance(countries, list) or not set(countries) <= COUNTRIES:
        raise ValueError("invalid countries")
    clean = {
        "slot": slot["slot"],
        "item_id": slot["item_id"],
        "retest_of": slot["retest_of"],
        "tier": tier,
        "urgency": urgency,
        "urgency_alt": alternative,
        "countries": sorted(set(countries)),
        "bad_input": bool(label.get("bad_input")),
        "note": str(label.get("note") or "")[:1000],
        "same_as": label.get("same_as"),
        "notify": label.get("notify"),
        "labelled_at": datetime.now(UTC).isoformat(),
    }
    if clean["same_as"] is not None and not isinstance(clean["same_as"], str):
        raise ValueError("invalid same_as")
    if clean["notify"] not in (None, True, False):
        raise ValueError("invalid notify")
    return clean


def latest_labels(path: Path) -> dict[str, dict]:
    """Last answer per slot wins (the page allows going back and correcting)."""
    labels = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                labels[row["slot"]] = row
    return labels


def page_labels(path: Path) -> dict[str, dict]:
    """Saved answers for the page, without item ids (they would reveal origin)."""
    hidden = {"item_id", "retest_of", "labelled_at"}
    return {slot: {k: v for k, v in row.items() if k not in hidden} for slot, row in latest_labels(path).items()}


class LabelStore:
    def __init__(
        self, items_path: Path, queue_path: Path, labels_path: Path, seed: int, translations_path: Path | None = None
    ):
        data = json.loads(items_path.read_text(encoding="utf-8"))
        self.translations = (
            json.loads(translations_path.read_text(encoding="utf-8"))
            if translations_path is not None and translations_path.exists()
            else {}
        )
        self.items = {i["id"]: i for i in data["items"]}
        if queue_path.exists():
            queue = json.loads(queue_path.read_text(encoding="utf-8"))
            if queue["items_sha256"] != data["items_sha256"]:
                raise SystemExit("queue.json was built for a different items.json; refusing to mix them")
            self.slots = queue["slots"]
        else:
            self.slots = build_queue(data["items"], seed)
            queue_path.write_text(
                json.dumps({"items_sha256": data["items_sha256"], "seed": seed, "slots": self.slots}, indent=1),
                encoding="utf-8",
            )
        self.by_slot = {s["slot"]: s for s in self.slots}
        self.labels_path = labels_path

    def view(self) -> list[dict]:
        first_slot = {}
        for slot in self.slots:
            if slot["retest_of"] is None:
                first_slot.setdefault(slot["item_id"], slot["slot"])
        views = []
        for slot in self.slots:
            item = self.items[slot["item_id"]]
            earlier = []
            if item["chain_id"] and slot["retest_of"] is None:
                earlier = [
                    {
                        "slot": first_slot[other["id"]],
                        "title": self.translations.get(other["id"], {}).get("title_pl") or other["article"]["title"],
                    }
                    for other in self.items.values()
                    if other["chain_id"] == item["chain_id"] and (other["chain_pos"] or 0) < (item["chain_pos"] or 0)
                ]
                earlier.sort(key=lambda e: e["slot"])
            views.append(public_view(item, slot, earlier, self.translations.get(item["id"])))
        return views

    def save(self, label: dict) -> dict:
        clean = validate_label(label, self.by_slot)
        item = self.items[clean["item_id"]]
        if clean["same_as"] is not None:
            target = self.by_slot.get(clean["same_as"])
            other = self.items.get(target["item_id"]) if target else None
            if (
                other is None
                or not item["chain_id"]
                or other["chain_id"] != item["chain_id"]
                or (other["chain_pos"] or 0) >= (item["chain_pos"] or 0)
            ):
                raise ValueError("same_as must name an earlier article of the same series")
        with self.labels_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(clean, ensure_ascii=False) + "\n")
            handle.flush()
        return clean


def make_handler(store: LabelStore):
    class Handler(http.server.BaseHTTPRequestHandler):
        def _send(self, code, body, ctype="application/json; charset=utf-8"):
            data = body.encode("utf-8") if isinstance(body, str) else body
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self._send(200, PAGE.read_text(encoding="utf-8"), "text/html; charset=utf-8")
            elif self.path == "/api/queue":
                self._send(200, json.dumps(store.view(), ensure_ascii=False))
            elif self.path == "/api/labels":
                self._send(200, json.dumps(page_labels(store.labels_path), ensure_ascii=False))
            else:
                self._send(404, '{"error": "not found"}')

        def do_POST(self):
            if self.path != "/api/label":
                self._send(404, '{"error": "not found"}')
                return
            # Only JSON bodies: a cross-site form or text POST cannot plant labels, because
            # a browser must first ask permission (preflight) for this content type.
            if not (self.headers.get("Content-Type") or "").startswith("application/json"):
                self._send(415, '{"error": "JSON only"}')
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                saved = store.save(json.loads(self.rfile.read(length)))
            except (ValueError, json.JSONDecodeError) as exc:
                self._send(400, json.dumps({"error": str(exc)}))
                return
            self._send(200, json.dumps({"ok": True, "slot": saved["slot"]}))

        def log_message(self, *args):
            pass

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8774)
    parser.add_argument("--seed", type=int, default=20260923)
    parser.add_argument("--items", default=str(ITEMS))
    parser.add_argument("--queue", default=str(QUEUE))
    parser.add_argument("--labels", default=str(LABELS))
    parser.add_argument("--translations", default=str(TRANSLATIONS))
    args = parser.parse_args()
    store = LabelStore(Path(args.items), Path(args.queue), Path(args.labels), args.seed, Path(args.translations))
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", args.port), make_handler(store)) as server:
        done = len(latest_labels(store.labels_path))
        print(f"Labelling page: http://localhost:{args.port}/  ({done}/{len(store.slots)} answered)", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
