"""Freeze the full article text of every production eval item.

Uses the production extractor (``sentinel.processing.fulltext``). Results are cached per
article, so the labelled text never changes on a rerun; failures are retried with pauses
(Google News link decoding is rate limited). The text is stored beside the article
(``item["full_text"]``), outside the frozen-item hash, so the labelling queue stays valid.
Synthetic items have no page and get ``None``.
"""

import argparse
import asyncio
import json
from collections import Counter
from pathlib import Path

from sentinel.eval.compare_models import make_article
from sentinel.processing.fulltext import fetch_full_text

ITEMS = Path("data/eval/suite/items.json")
CACHE = Path("data/eval/suite/fulltext-cache.json")


async def snapshot(items: list[dict], cache: dict, attempts: int = 3, concurrency: int = 3) -> None:
    semaphore = asyncio.Semaphore(concurrency)

    async def one(item):
        key = item["article_id"]
        if key in cache and cache[key]["status"] == "ok":
            return
        article = make_article({"id": item["id"], "article": item["article"]})
        result = None
        for attempt in range(attempts):
            async with semaphore:
                result = await fetch_full_text(article)
            if result.ok or result.status.startswith("http_4"):
                break
            await asyncio.sleep(3 * (attempt + 1))
        cache[key] = {"url": result.url, "status": result.status, "text": result.text}

    await asyncio.gather(*(one(i) for i in items if i["origin"] == "production"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--items", default=str(ITEMS))
    parser.add_argument("--cache", default=str(CACHE))
    args = parser.parse_args()
    items_path, cache_path = Path(args.items), Path(args.cache)
    data = json.loads(items_path.read_text(encoding="utf-8"))
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    try:
        asyncio.run(snapshot(data["items"], cache))
    finally:
        cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    for item in data["items"]:
        entry = cache.get(item.get("article_id"))
        item["full_text"] = entry["text"] if entry else None
        item["full_text_status"] = entry["status"] if entry else "synthetic"
    items_path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(dict(Counter(i["full_text_status"] for i in data["items"]))))


if __name__ == "__main__":
    main()
