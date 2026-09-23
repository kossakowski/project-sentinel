"""Build the eval-suite item pool from production (read-only) and synthetic fixtures.

Production is only read: one ``sqlite3 -readonly`` query over SSH as ``deploy@``.
Previous model scores are used to stratify the sample and are stored for later
analysis, but the labelling page never shows them.
"""

import argparse
import asyncio
import hashlib
import json
import random
import shlex
import subprocess
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

import yaml

SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=12", "-p", "2222", "deploy@178.104.76.254"]
PROD_DB = "/var/lib/sentinel/sentinel.db"
DEFAULT_OUTPUT = "data/eval/suite/items.json"
SYNTHETIC = "tests/fixtures/eval_suite_synthetic.yaml"
HOLDOUT = "tests/fixtures/model_comparison_v2_holdout.yaml"
# Items per production-urgency stratum. None means "take all".
QUOTAS = {"9-10": None, "7-8": 60, "5-6": 35, "1-4": 25}
MAX_CHAINS = 12
CHAIN_LENGTH = 6
DEV_SHARE = 0.4

ARTICLES_SQL = """
SELECT a.id, a.source_name, a.source_url, a.source_type, a.title, a.summary, a.language,
       a.published_at, a.fetched_at, a.title_normalized,
       c.urgency_score AS prod_urgency, c.affected_countries AS prod_countries,
       c.model_used AS prod_model, c.is_military_event AS prod_military
FROM articles a JOIN classifications c ON c.article_id = a.id
ORDER BY a.fetched_at
"""
EVENTS_SQL = "SELECT id, article_ids FROM events WHERE last_updated_at >= '2026-08-24'"


def prod_query(sql: str) -> list[dict]:
    command = f"sqlite3 -readonly -json {PROD_DB} " + shlex.quote(" ".join(sql.split()))
    result = subprocess.run([*SSH, command], check=True, capture_output=True, text=True)
    return json.loads(result.stdout or "[]")


def stratum(urgency: int) -> str:
    if urgency >= 9:
        return "9-10"
    if urgency >= 7:
        return "7-8"
    if urgency >= 5:
        return "5-6"
    return "1-4"


def _countries(raw) -> set[str]:
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        return set()
    return {c for c in value or [] if isinstance(c, str) and c not in {"", "unknown"}}


class _Union:
    def __init__(self, keys):
        self.parent = {k: k for k in keys}

    def find(self, key):
        while self.parent[key] != key:
            self.parent[key] = self.parent[self.parent[key]]
            key = self.parent[key]
        return key

    def join(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def dedupe(rows: list[dict]) -> list[dict]:
    """Keep the earliest article per normalized title (syndicated copies are one item)."""
    seen, kept = set(), []
    for row in sorted(rows, key=lambda r: r["fetched_at"]):
        key = row["title_normalized"].strip()
        if key and key not in seen:
            seen.add(key)
            kept.append(row)
    return kept


def cluster(rows: list[dict], events: list[dict]) -> dict[str, str]:
    """Group articles that could describe one incident, so pools never split an incident.

    Joins articles on the same UTC day that share a production event, or (for urgency
    >= 5) share a concrete country. Links never cross days: multi-day events would
    otherwise chain a busy week of distinct incidents into one cluster, leaving the
    locked pool with a single incident's critical articles.
    """
    ids = {r["id"] for r in rows}
    day = {r["id"]: r["fetched_at"][:10] for r in rows}
    union = _Union(ids)
    for event in events:
        members = [a for a in json.loads(event["article_ids"] or "[]") if a in ids]
        for i, first in enumerate(members):
            for other in members[i + 1 :]:
                if day[first] == day[other]:
                    union.join(first, other)
    by_day = defaultdict(list)
    for row in rows:
        if row["prod_urgency"] >= 5 and _countries(row["prod_countries"]):
            by_day[row["fetched_at"][:10]].append(row)
    for day_rows in by_day.values():
        for i, row in enumerate(day_rows):
            for other in day_rows[i + 1 :]:
                if _countries(row["prod_countries"]) & _countries(other["prod_countries"]):
                    union.join(row["id"], other["id"])
    return {r["id"]: "c-" + union.find(r["id"])[:8] for r in rows}


def pick_singles(rows: list[dict], rng: random.Random) -> list[dict]:
    by_stratum = defaultdict(list)
    for row in rows:
        by_stratum[stratum(row["prod_urgency"])].append(row)
    chosen = []
    for name, quota in QUOTAS.items():
        pool = by_stratum[name]
        if quota is None or len(pool) <= quota:
            chosen.extend(pool)
            continue
        # Round-robin across languages so the rarer Ukrainian items are not crowded out.
        by_lang = defaultdict(list)
        for row in pool:
            by_lang[row["language"]].append(row)
        for items in by_lang.values():
            rng.shuffle(items)
        picked = []
        while len(picked) < quota:
            for lang in sorted(by_lang):
                if by_lang[lang] and len(picked) < quota:
                    picked.append(by_lang[lang].pop())
        chosen.extend(picked)
    return chosen


def pick_chains(rows: list[dict], clusters: dict[str, str]) -> list[list[dict]]:
    """Real incident chains: busy clusters with a critical-tier article and several sources."""
    members = defaultdict(list)
    for row in rows:
        members[clusters[row["id"]]].append(row)
    candidates = [
        sorted(group, key=lambda r: r["fetched_at"])
        for group in members.values()
        if len(group) >= 4
        and max(r["prod_urgency"] for r in group) >= 7
        and len({r["source_name"] for r in group}) >= 2
    ]
    candidates.sort(key=lambda g: (-max(r["prod_urgency"] for r in g), -len(g), g[0]["fetched_at"]))
    chains = []
    for group in candidates[:MAX_CHAINS]:
        if len(group) <= CHAIN_LENGTH:
            chains.append(group)
            continue
        step = (len(group) - 1) / (CHAIN_LENGTH - 1)
        chains.append([group[round(i * step)] for i in range(CHAIN_LENGTH)])
    return chains


def assign_pools(items: list[dict], rng: random.Random, dev_share: float = DEV_SHARE) -> None:
    """Assign whole clusters to dev/locked, per stratum, so no incident leaks across pools."""
    groups = defaultdict(list)
    for item in items:
        groups[item["cluster_id"]].append(item)
    by_key = defaultdict(list)
    for cluster_id, group in groups.items():
        top = max((g["prod"]["urgency"] for g in group if g.get("prod")), default=0)
        key = (group[0]["origin"], stratum(top) if top else "synthetic")
        by_key[key].append(cluster_id)
    for key in sorted(by_key):
        cluster_ids = sorted(by_key[key])
        rng.shuffle(cluster_ids)
        total = sum(len(groups[c]) for c in cluster_ids)
        dev = 0
        for cluster_id in cluster_ids:
            pool = "dev" if dev < dev_share * total else "locked"
            dev += len(groups[cluster_id]) if pool == "dev" else 0
            for item in groups[cluster_id]:
                item["pool"] = pool


def production_item(row: dict, cluster_id: str, chain: tuple[str, int] | None) -> dict:
    return {
        "id": "real-" + row["id"][:12],
        "origin": "production",
        "article_id": row["id"],
        "cluster_id": cluster_id,
        "chain_id": chain[0] if chain else None,
        "chain_pos": chain[1] if chain else None,
        "article": {k: row[k] for k in ("source_name", "source_url", "source_type", "title", "language")}
        | {"summary": row["summary"] or "", "published_at": row["published_at"], "fetched_at": row["fetched_at"]},
        "input": {"stored_summary": row["summary"] or "", "enrichment": "pending", "fetched": False},
        "prod": {
            "urgency": row["prod_urgency"],
            "countries": sorted(_countries(row["prod_countries"])),
            "model": row["prod_model"],
            "military": bool(row["prod_military"]),
        },
    }


def synthetic_items() -> list[dict]:
    items = []
    for raw in yaml.safe_load(Path(SYNTHETIC).read_text(encoding="utf-8"))["items"]:
        items.append(
            {
                "id": raw["id"],
                "origin": "synthetic",
                "cluster_id": "c-" + raw["id"],
                "chain_id": None,
                "chain_pos": None,
                "article": dict(raw["article"]),
                "input": {"stored_summary": raw["article"]["summary"], "enrichment": "synthetic", "fetched": False},
                "target": raw["target"],
            }
        )
    cases = yaml.safe_load(Path(HOLDOUT).read_text(encoding="utf-8"))["cases"]
    order = defaultdict(list)
    for case in sorted(cases, key=lambda c: c["article"]["fetched_at"]):
        order[case["sequence_id"]].append(case["id"])
    for case in cases:
        position = order[case["sequence_id"]].index(case["id"])
        items.append(
            {
                "id": case["id"],
                "origin": "holdout",
                "cluster_id": "c-" + case["sequence_id"],
                "chain_id": case["sequence_id"],
                "chain_pos": position,
                "article": dict(case["article"]),
                "input": {"stored_summary": case["article"]["summary"], "enrichment": "synthetic", "fetched": False},
            }
        )
    return items


async def enrich(items: list[dict], config_path: str, cache_path: Path) -> None:
    """Re-create production enrichment: fetch the body for headline-only items and freeze it.

    Production does this in memory and never stores the result, so the stored summary
    is the pre-enrichment text. The LLM vagueness gate is skipped (heuristic gate only).
    Fetched bodies are cached per article, so a rebuild never changes labelled text;
    failures are retried with a pause because Google News decoding is rate limited.
    """
    from sentinel.eval.compare_models import make_article, make_config
    from sentinel.processing.enricher import ArticleEnricher

    enricher = ArticleEnricher(make_config(config_path))
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    semaphore = asyncio.Semaphore(3)

    async def one(item):
        article = make_article({"id": item["id"], "article": item["article"]})
        if not enricher.is_garbage_summary(article):
            item["input"]["enrichment"] = "none"
            return
        item["input"]["enrichment"] = "heuristic"
        key = item["article_id"]
        if key not in cache:
            body = None
            for attempt in range(3):
                async with semaphore:
                    body = await enricher._fetch_body(article)
                if body:
                    break
                await asyncio.sleep(2 * (attempt + 1))
            cache[key] = body
        if cache[key]:
            item["article"]["summary"] = cache[key]
            item["input"]["fetched"] = True

    try:
        await asyncio.gather(*(one(i) for i in items if i["origin"] == "production"))
    finally:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")


def build(seed: int, config_path: str, cache_path: Path) -> dict:
    rng = random.Random(seed)
    rows = dedupe(prod_query(ARTICLES_SQL))
    events = prod_query(EVENTS_SQL)
    clusters = cluster(rows, events)
    chains = pick_chains(rows, clusters)
    chain_of = {}
    for number, chain in enumerate(chains, 1):
        for position, row in enumerate(chain):
            chain_of[row["id"]] = (f"chain-{number:02d}", position)
    singles = pick_singles([r for r in rows if r["id"] not in chain_of], rng)
    chosen = singles + [row for chain in chains for row in chain]
    items = [production_item(r, clusters[r["id"]], chain_of.get(r["id"])) for r in chosen]
    items += synthetic_items()
    asyncio.run(enrich(items, config_path, cache_path))
    assign_pools(items, rng)
    return {
        "version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "seed": seed,
        "quotas": QUOTAS,
        "counts": {
            "items": len(items),
            "origin": dict(Counter(i["origin"] for i in items)),
            "pool": dict(Counter(i["pool"] for i in items)),
            "stratum": dict(Counter(stratum(i["prod"]["urgency"]) for i in items if i.get("prod"))),
            "chains": len(chains),
            "enrichment": dict(Counter(f"{i['input']['enrichment']}:{i['input']['fetched']}" for i in items)),
        },
        "items": items,
    }


def items_hash(items: list[dict]) -> str:
    frozen = [{k: i[k] for k in ("id", "article", "chain_id", "chain_pos", "pool")} for i in items]
    return hashlib.sha256(json.dumps(frozen, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-production", action="store_true", required=True)
    parser.add_argument("--seed", type=int, default=20260923)
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--enrichment-cache", default="data/eval/suite/enrichment-cache.json")
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        raise SystemExit(f"{output} exists; the item pool is frozen once built. Use a new --output.")
    data = build(args.seed, args.config, Path(args.enrichment_cache))
    data["items_sha256"] = items_hash(data["items"])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"output": str(output), "sha256": data["items_sha256"], **data["counts"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
