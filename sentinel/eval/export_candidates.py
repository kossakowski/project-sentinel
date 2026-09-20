"""Read-only production article sampling for local benchmark preparation."""

import argparse
import json
import shlex
import subprocess
from datetime import UTC, datetime
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-production", action="store_true", required=True)
    parser.add_argument("--output", default="data/eval/production-candidates.json")
    args = parser.parse_args()
    query = """
    WITH ranked AS (
      SELECT a.id,a.source_name,a.source_url,a.source_type,a.title,a.summary,
             a.language,a.published_at,a.fetched_at,
             row_number() OVER (
               PARTITION BY a.language, CASE WHEN c.urgency_score>=5 THEN 1 ELSE 0 END
               ORDER BY a.fetched_at DESC
             ) AS sample_rank
      FROM articles a JOIN classifications c ON c.article_id=a.id
      WHERE a.fetched_at >= '2026-09-13' AND a.fetched_at < '2026-09-17'
    ) SELECT id,source_name,source_url,source_type,title,summary,language,published_at,fetched_at
      FROM ranked WHERE sample_rank<=25 ORDER BY fetched_at;
    """
    command = "sudo sqlite3 -readonly -json /var/lib/sentinel/sentinel.db " + shlex.quote(query)
    result = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=12", "-p", "2222", "deploy@178.104.76.254", command],
        check=True,
        capture_output=True,
        text=True,
    )
    articles = json.loads(result.stdout)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "exported_at": datetime.now(UTC).isoformat(),
                "selection": "latest up to 25 per source-language and prior score tier; not random",
                "warning": "Scores used only for sampling; no historical labels are exported.",
                "articles": articles,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Saved {len(articles)} source records to {output}")


if __name__ == "__main__":
    main()
