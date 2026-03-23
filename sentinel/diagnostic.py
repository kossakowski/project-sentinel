"""Diagnostic HTML report generator for pipeline auditing.

Generates a self-contained HTML file showing every article the pipeline
fetched and what happened to it (duplicate, keyword-filtered, classified).
"""

import html
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime

from sentinel.models import Article, ClassificationResult

logger = logging.getLogger("sentinel.diagnostic")


@dataclass
class DiagnosticArticle:
    """One article's journey through the pipeline."""

    article: Article
    stage: str  # "duplicate", "filtered", "classified"
    keyword_match: dict | None = None
    classification: ClassificationResult | None = None


@dataclass
class DiagnosticData:
    """All data collected during a diagnostic pipeline cycle."""

    cycle_start: datetime
    duration_seconds: float
    total_fetched: int
    total_unique: int
    total_relevant: int
    total_classified: int
    items: list[DiagnosticArticle] = field(default_factory=list)


def _esc(text: str) -> str:
    """Shorthand for HTML escaping."""
    return html.escape(text, quote=True)


def _build_rows(items: list[DiagnosticArticle]) -> str:
    """Build HTML table rows from diagnostic items."""
    # Sort: classified first (military before non-military), then filtered, then duplicate
    def sort_key(item: DiagnosticArticle):
        stage_order = {"classified": 0, "filtered": 1, "duplicate": 2}
        military = 0
        if item.classification and item.classification.is_military_event:
            military = -1  # military events first
        return (
            stage_order.get(item.stage, 99),
            military,
            item.article.source_type,
            item.article.source_name,
        )

    sorted_items = sorted(items, key=sort_key)

    rows = []
    for i, item in enumerate(sorted_items, 1):
        a = item.article
        title_display = a.title[:120]
        if len(a.title) > 120:
            title_display += "..."
        summary_snippet = (a.summary or "")[:200].strip()
        if len(a.summary or "") > 200:
            summary_snippet += "..."

        # Status badge
        if item.stage == "duplicate":
            badge = '<span class="badge dup">Duplicate</span>'
            row_class = "row-dup"
        elif item.stage == "filtered":
            badge = '<span class="badge filtered">No Match</span>'
            row_class = "row-filtered"
        elif item.classification and item.classification.is_military_event:
            urgency = item.classification.urgency_score
            badge = f'<span class="badge military">Military ({urgency}/10)</span>'
            row_class = "row-military"
        elif item.classification:
            badge = f'<span class="badge safe">Not Military</span>'
            row_class = "row-safe"
        else:
            badge = '<span class="badge classified">Passed Filter</span>'
            row_class = "row-safe"

        # Details column
        details_parts = []
        if item.keyword_match:
            level = item.keyword_match.get("level", "?")
            matched = item.keyword_match.get("matched_keywords", [])
            kw_text = ", ".join(matched[:6])
            if len(matched) > 6:
                kw_text += f" (+{len(matched) - 6})"
            details_parts.append(
                f'<span class="kw-tag kw-{level}">{level}</span> {_esc(kw_text)}'
            )
        if item.classification:
            c = item.classification
            details_parts.append(f"Type: {_esc(c.event_type)}")
            details_parts.append(f"Confidence: {c.confidence:.0%}")
            if c.affected_countries:
                details_parts.append(
                    f"Countries: {_esc(', '.join(c.affected_countries))}"
                )
            if c.aggressor and c.aggressor != "none":
                details_parts.append(f"Aggressor: {_esc(c.aggressor)}")
            if c.summary_pl:
                details_parts.append(
                    f'<div class="summary-pl">{_esc(c.summary_pl[:150])}</div>'
                )

        details_html = "<br>".join(details_parts) if details_parts else "&mdash;"

        pub_time = ""
        if a.published_at:
            pub_time = a.published_at.strftime("%H:%M")

        source_type_label = a.source_type.replace("_", " ").title()

        row = f"""<tr class="{row_class}">
<td class="num">{i}</td>
<td><span class="src-type src-{_esc(a.source_type)}">{_esc(source_type_label)}</span>
<span class="src-name">{_esc(a.source_name)}</span></td>
<td class="lang">{_esc(a.language.upper())}</td>
<td class="title-cell">
<a href="{_esc(a.source_url)}" target="_blank" rel="noopener">{_esc(title_display)}</a>
{f'<div class="snippet">{_esc(summary_snippet)}</div>' if summary_snippet else ''}
</td>
<td class="time">{pub_time}</td>
<td>{badge}</td>
<td class="details">{details_html}</td>
</tr>"""
        rows.append(row)

    return "\n".join(rows)


def generate_html(data: DiagnosticData, output_path: str) -> str:
    """Generate a diagnostic HTML report.

    Returns the absolute path to the generated file.
    """
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    # Counts by stage
    n_dup = sum(1 for it in data.items if it.stage == "duplicate")
    n_filt = sum(1 for it in data.items if it.stage == "filtered")
    n_cls = sum(1 for it in data.items if it.stage == "classified")
    n_mil = sum(
        1
        for it in data.items
        if it.stage == "classified"
        and it.classification
        and it.classification.is_military_event
    )

    report_time = data.cycle_start.strftime("%Y-%m-%d %H:%M:%S UTC")
    rows_html = _build_rows(data.items)

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sentinel Diagnostic &mdash; {_esc(report_time)}</title>
<style>
:root {{
  --navy: #1a1a2e;
  --navy-light: #16213e;
  --accent: #e94560;
  --green: #28a745;
  --blue: #007bff;
  --amber: #ffc107;
  --gray: #6c757d;
  --bg: #f4f6f9;
  --card-bg: #ffffff;
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
    "Helvetica Neue", Arial, sans-serif;
  background: var(--bg);
  color: #333;
  line-height: 1.5;
}}

/* Header */
.header {{
  background: linear-gradient(135deg, var(--navy), var(--navy-light));
  color: #fff;
  padding: 1.5rem 2rem;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 0.5rem;
}}
.header h1 {{
  font-size: 1.4rem;
  font-weight: 700;
  letter-spacing: 0.5px;
}}
.header h1 span {{ color: var(--accent); }}
.header .meta {{
  font-size: 0.85rem;
  color: #a0aec0;
}}

/* Stats bar */
.stats {{
  display: flex;
  gap: 0;
  background: var(--card-bg);
  border-bottom: 2px solid #e2e8f0;
  flex-wrap: wrap;
}}
.stat {{
  flex: 1;
  min-width: 120px;
  padding: 1rem 1.25rem;
  text-align: center;
  border-right: 1px solid #e2e8f0;
  position: relative;
}}
.stat:last-child {{ border-right: none; }}
.stat .num {{
  font-size: 2rem;
  font-weight: 800;
  color: var(--navy);
}}
.stat .label {{
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: var(--gray);
  margin-top: 0.15rem;
}}
.stat .sub {{
  font-size: 0.75rem;
  color: #aaa;
}}
.stat.accent .num {{ color: var(--accent); }}
.stat.green .num {{ color: var(--green); }}
.stat.blue .num {{ color: var(--blue); }}

/* Funnel arrow between stats */
.stat::after {{
  content: "\\203A";
  position: absolute;
  right: -8px;
  top: 50%;
  transform: translateY(-50%);
  font-size: 1.4rem;
  color: #cbd5e0;
  z-index: 1;
}}
.stat:last-child::after {{ content: none; }}

/* Table container */
.table-wrap {{
  padding: 1rem 1.5rem 2rem;
  overflow-x: auto;
}}
.table-header {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.75rem;
  flex-wrap: wrap;
  gap: 0.5rem;
}}
.table-header h2 {{
  font-size: 1.1rem;
  color: var(--navy);
}}
.legend {{
  display: flex;
  gap: 0.75rem;
  font-size: 0.75rem;
  flex-wrap: wrap;
}}
.legend-item {{
  display: flex;
  align-items: center;
  gap: 4px;
}}
.legend-dot {{
  width: 10px;
  height: 10px;
  border-radius: 50%;
  display: inline-block;
}}
.legend-dot.mil {{ background: var(--accent); }}
.legend-dot.safe {{ background: var(--blue); }}
.legend-dot.filt {{ background: var(--amber); }}
.legend-dot.dup {{ background: #ccc; }}

table {{
  width: 100%;
  border-collapse: collapse;
  background: var(--card-bg);
  border-radius: 8px;
  overflow: hidden;
  box-shadow: 0 1px 4px rgba(0,0,0,0.06);
  font-size: 0.84rem;
}}
thead th {{
  background: var(--navy);
  color: #fff;
  padding: 0.65rem 0.75rem;
  text-align: left;
  font-weight: 600;
  font-size: 0.78rem;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  white-space: nowrap;
}}
tbody td {{
  padding: 0.55rem 0.75rem;
  border-bottom: 1px solid #edf2f7;
  vertical-align: top;
}}
tbody tr:hover {{ background: #f7fafc; }}

/* Row status indicators — left border */
tr.row-military {{ border-left: 3px solid var(--accent); }}
tr.row-safe {{ border-left: 3px solid var(--blue); }}
tr.row-filtered {{ border-left: 3px solid var(--amber); }}
tr.row-dup {{ border-left: 3px solid #ddd; }}
tr.row-dup td {{ color: #999; }}

td.num {{ color: #aaa; font-size: 0.78rem; white-space: nowrap; }}
td.lang {{ text-align: center; font-weight: 600; font-size: 0.78rem; }}
td.time {{ white-space: nowrap; color: #666; }}
td.details {{ font-size: 0.78rem; max-width: 320px; }}

.title-cell {{ max-width: 420px; }}
.title-cell a {{
  color: var(--navy);
  text-decoration: none;
  font-weight: 500;
}}
.title-cell a:hover {{ color: var(--accent); text-decoration: underline; }}
.snippet {{
  margin-top: 3px;
  font-size: 0.76rem;
  color: #888;
  line-height: 1.35;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}}

/* Source badges */
.src-type {{
  display: inline-block;
  font-size: 0.65rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  padding: 1px 6px;
  border-radius: 3px;
  margin-bottom: 2px;
}}
.src-rss {{ background: #e8f5e9; color: #2e7d32; }}
.src-google_news {{ background: #e3f2fd; color: #1565c0; }}
.src-gdelt {{ background: #fce4ec; color: #c62828; }}
.src-telegram {{ background: #e8eaf6; color: #283593; }}
.src-test {{ background: #f3e5f5; color: #6a1b9a; }}
.src-name {{ display: block; font-size: 0.78rem; color: #555; }}

/* Status badges */
.badge {{
  display: inline-block;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 0.72rem;
  font-weight: 700;
  white-space: nowrap;
}}
.badge.dup {{ background: #e0e0e0; color: #757575; }}
.badge.filtered {{ background: #fff3cd; color: #856404; }}
.badge.safe {{ background: #cce5ff; color: #004085; }}
.badge.military {{ background: #f8d7da; color: #721c24; }}
.badge.classified {{ background: #d4edda; color: #155724; }}

/* Keyword tags */
.kw-tag {{
  display: inline-block;
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 0.68rem;
  font-weight: 700;
  text-transform: uppercase;
  margin-right: 4px;
}}
.kw-critical {{ background: #f8d7da; color: #721c24; }}
.kw-high {{ background: #fff3cd; color: #856404; }}

.summary-pl {{
  margin-top: 4px;
  font-style: italic;
  color: #666;
  font-size: 0.76rem;
}}

/* Filter bar */
.filter-bar {{
  display: flex;
  gap: 0.5rem;
  margin-bottom: 1rem;
  flex-wrap: wrap;
}}
.filter-btn {{
  padding: 0.35rem 0.9rem;
  border: 1px solid #ddd;
  border-radius: 16px;
  background: #fff;
  cursor: pointer;
  font-size: 0.78rem;
  transition: all 0.15s;
}}
.filter-btn:hover {{ border-color: var(--navy); }}
.filter-btn.active {{ background: var(--navy); color: #fff; border-color: var(--navy); }}
.filter-btn .count {{ color: #999; margin-left: 3px; }}
.filter-btn.active .count {{ color: #a0aec0; }}

/* Footer */
.footer {{
  text-align: center;
  padding: 1.5rem;
  font-size: 0.75rem;
  color: #aaa;
}}

@media (max-width: 768px) {{
  .header {{ padding: 1rem; }}
  .table-wrap {{ padding: 0.5rem; }}
  .stat {{ padding: 0.75rem 0.5rem; }}
  .stat .num {{ font-size: 1.4rem; }}
}}
</style>
</head>
<body>

<div class="header">
  <h1>PROJECT <span>SENTINEL</span> &mdash; Diagnostic Report</h1>
  <div class="meta">
    Generated: {_esc(report_time)} &bull; Duration: {data.duration_seconds:.1f}s
  </div>
</div>

<div class="stats">
  <div class="stat">
    <div class="num">{data.total_fetched}</div>
    <div class="label">Fetched</div>
  </div>
  <div class="stat">
    <div class="num">{data.total_unique}</div>
    <div class="label">Unique</div>
    <div class="sub">&minus;{n_dup} duplicates</div>
  </div>
  <div class="stat blue">
    <div class="num">{data.total_relevant}</div>
    <div class="label">Keyword Match</div>
    <div class="sub">&minus;{n_filt} no match</div>
  </div>
  <div class="stat green">
    <div class="num">{data.total_classified}</div>
    <div class="label">Classified</div>
  </div>
  <div class="stat {'accent' if n_mil > 0 else ''}">
    <div class="num">{n_mil}</div>
    <div class="label">Military Events</div>
  </div>
</div>

<div class="table-wrap">
  <div class="table-header">
    <h2>All Articles ({len(data.items)})</h2>
    <div class="legend">
      <span class="legend-item"><span class="legend-dot mil"></span> Military</span>
      <span class="legend-item"><span class="legend-dot safe"></span> Classified (safe)</span>
      <span class="legend-item"><span class="legend-dot filt"></span> No keyword match</span>
      <span class="legend-item"><span class="legend-dot dup"></span> Duplicate</span>
    </div>
  </div>

  <div class="filter-bar">
    <button class="filter-btn active" onclick="filterRows('all')">
      All <span class="count">({len(data.items)})</span>
    </button>
    <button class="filter-btn" onclick="filterRows('row-military')">
      Military <span class="count">({n_mil})</span>
    </button>
    <button class="filter-btn" onclick="filterRows('row-safe')">
      Classified <span class="count">({n_cls - n_mil})</span>
    </button>
    <button class="filter-btn" onclick="filterRows('row-filtered')">
      Filtered <span class="count">({n_filt})</span>
    </button>
    <button class="filter-btn" onclick="filterRows('row-dup')">
      Duplicates <span class="count">({n_dup})</span>
    </button>
  </div>

  <table>
    <thead>
      <tr>
        <th>#</th>
        <th>Source</th>
        <th>Lang</th>
        <th>Title</th>
        <th>Time</th>
        <th>Status</th>
        <th>Details</th>
      </tr>
    </thead>
    <tbody>
{rows_html}
    </tbody>
  </table>
</div>

<div class="footer">
  Project Sentinel Diagnostic Report &bull; Generated automatically &bull; {_esc(report_time)}
</div>

<script>
function filterRows(cls) {{
  const rows = document.querySelectorAll('tbody tr');
  const buttons = document.querySelectorAll('.filter-btn');
  buttons.forEach(b => b.classList.remove('active'));
  event.target.closest('.filter-btn').classList.add('active');
  rows.forEach(row => {{
    if (cls === 'all') {{
      row.style.display = '';
    }} else {{
      row.style.display = row.classList.contains(cls) ? '' : 'none';
    }}
  }});
}}
</script>
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(page)

    abs_path = os.path.abspath(output_path)
    logger.info("Diagnostic report written to %s", abs_path)
    return abs_path
