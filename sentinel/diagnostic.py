"""Diagnostic HTML report generator for pipeline auditing.

Generates a self-contained HTML file with one wide table showing every
article fetched and what happened to it at each pipeline stage:
Dedup -> Keyword Filter -> Classification -> Corroboration.
"""

import html
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime

from sentinel.models import Article, ClassificationResult, Event

logger = logging.getLogger("sentinel.diagnostic")


@dataclass
class DiagnosticArticle:
    """One article's full journey through the pipeline."""

    article: Article

    # Dedup stage
    dedup_passed: bool
    dedup_reason: str  # "" if passed, reason string if duplicate

    # Keyword filter stage (None values if stage not reached)
    keyword_info: dict | None = None  # {passed, critical, high, excluded_by}

    # Classification (None if stage not reached)
    classification: ClassificationResult | None = None

    # Corroboration (None if not grouped into an event)
    event: Event | None = None


@dataclass
class DiagnosticData:
    """All data collected during a diagnostic pipeline cycle."""

    cycle_start: datetime
    duration_seconds: float
    total_fetched: int
    total_unique: int
    total_relevant: int
    total_classified: int
    total_events: int
    items: list[DiagnosticArticle] = field(default_factory=list)


def _esc(text: str) -> str:
    return html.escape(text, quote=True)


def _sort_key(item: DiagnosticArticle):
    """Sort: military events first (by urgency desc), then classified safe,
    then keyword-matched, then filtered, then duplicates."""
    if item.classification and item.classification.is_military_event:
        return (0, -item.classification.urgency_score)
    if item.classification:
        return (1, -item.classification.urgency_score)
    if item.keyword_info and item.keyword_info.get("passed"):
        return (2, 0)
    if item.dedup_passed:
        return (3, 0)
    return (4, 0)


def _render_dedup_cell(item: DiagnosticArticle) -> str:
    if item.dedup_passed:
        return '<span class="pass">&#10003; Unique</span>'
    reason = _esc(item.dedup_reason) if item.dedup_reason else "Duplicate"
    return f'<span class="fail">&#10007; {reason}</span>'


def _render_keyword_cell(item: DiagnosticArticle) -> str:
    if item.keyword_info is None:
        return '<span class="skip">&mdash;</span>'

    kw = item.keyword_info
    parts = []

    if kw["critical"]:
        kws = ", ".join(kw["critical"][:4])
        extra = f" (+{len(kw['critical']) - 4})" if len(kw["critical"]) > 4 else ""
        parts.append(
            f'<span class="kw-badge kw-crit">CRITICAL</span> {_esc(kws)}{extra}'
        )
    if kw["high"]:
        kws = ", ".join(kw["high"][:4])
        extra = f" (+{len(kw['high']) - 4})" if len(kw["high"]) > 4 else ""
        parts.append(
            f'<span class="kw-badge kw-high">HIGH</span> {_esc(kws)}{extra}'
        )

    if kw.get("excluded_by"):
        exc = ", ".join(kw["excluded_by"][:3])
        parts.append(f'<span class="kw-badge kw-excl">EXCLUDED</span> {_esc(exc)}')

    if not parts:
        return '<span class="fail">&#10007; No match</span>'

    if kw["passed"]:
        prefix = '<span class="pass">&#10003;</span> '
    else:
        prefix = '<span class="fail">&#10007;</span> '

    return prefix + "<br>".join(parts)


def _render_classification_cell(item: DiagnosticArticle) -> str:
    if item.classification is None:
        if item.keyword_info and item.keyword_info.get("passed"):
            return '<span class="skip">API error</span>'
        return '<span class="skip">&mdash;</span>'

    c = item.classification
    lines = []

    if c.is_military_event:
        lines.append(
            f'<span class="cls-badge cls-mil">MILITARY</span> '
            f'<span class="urgency u{min(c.urgency_score, 10)}">{c.urgency_score}/10</span>'
        )
    else:
        lines.append(
            f'<span class="cls-badge cls-safe">NOT MILITARY</span> '
            f'<span class="urgency u{min(c.urgency_score, 10)}">{c.urgency_score}/10</span>'
        )

    lines.append(f"Type: {_esc(c.event_type)} &bull; Conf: {c.confidence:.0%}")

    if c.affected_countries:
        lines.append(f"Countries: {_esc(', '.join(c.affected_countries))}")
    if c.aggressor and c.aggressor != "none":
        lines.append(f"Aggressor: {_esc(c.aggressor)}")
    if c.summary_pl:
        summary = c.summary_pl[:120]
        if len(c.summary_pl) > 120:
            summary += "..."
        lines.append(f'<div class="cls-summary">{_esc(summary)}</div>')

    return "<br>".join(lines)


def _render_corroboration_cell(item: DiagnosticArticle) -> str:
    if item.event is None:
        if item.classification is None:
            return '<span class="skip">&mdash;</span>'
        c = item.classification
        if not c.is_military_event:
            return '<span class="skip">N/A (not military)</span>'
        if c.urgency_score < 5:
            return f'<span class="skip">N/A (urgency {c.urgency_score} &lt; 5)</span>'
        return '<span class="skip">No event match</span>'

    e = item.event
    corr_req = 2  # default
    lines = []

    status_map = {
        "phone_call": ("corr-call", "PHONE CALL"),
        "sms": ("corr-sms", "SMS"),
        "whatsapp": ("corr-wa", "WHATSAPP"),
        "pending": ("corr-pending", "PENDING"),
        "dry_run": ("corr-dry", "DRY RUN"),
    }
    cls, label = status_map.get(e.alert_status, ("corr-pending", e.alert_status.upper()))
    lines.append(f'<span class="corr-badge {cls}">{label}</span>')
    lines.append(f"Sources: {e.source_count}")
    lines.append(f"Type: {_esc(e.event_type)}")

    return "<br>".join(lines)


def _build_rows(items: list[DiagnosticArticle]) -> str:
    sorted_items = sorted(items, key=_sort_key)
    rows = []

    for i, item in enumerate(sorted_items, 1):
        a = item.article
        title_display = a.title[:100]
        if len(a.title) > 100:
            title_display += "..."
        summary_snippet = (a.summary or "")[:150].strip()
        if len(a.summary or "") > 150:
            summary_snippet += "..."

        # Row class for filtering
        if item.classification and item.classification.is_military_event:
            row_cls = "row-military"
        elif item.classification:
            row_cls = "row-classified"
        elif item.dedup_passed and item.keyword_info and item.keyword_info.get("passed"):
            row_cls = "row-matched"
        elif item.dedup_passed:
            row_cls = "row-filtered"
        else:
            row_cls = "row-dup"

        src_type = a.source_type.replace("_", " ").title()
        pub_time = a.published_at.strftime("%H:%M") if a.published_at else ""

        row = f"""<tr class="{row_cls}">
<td class="c-num">{i}</td>
<td class="c-src"><span class="src-type st-{_esc(a.source_type)}">{_esc(src_type)}</span>
<span class="src-name">{_esc(a.source_name)}</span></td>
<td class="c-title">
<a href="{_esc(a.source_url)}" target="_blank" rel="noopener">{_esc(title_display)}</a>
{f'<div class="snippet">{_esc(summary_snippet)}</div>' if summary_snippet else ''}
</td>
<td class="c-lang">{_esc(a.language.upper())}</td>
<td class="c-time">{pub_time}</td>
<td class="c-stage">{_render_dedup_cell(item)}</td>
<td class="c-stage">{_render_keyword_cell(item)}</td>
<td class="c-stage c-cls">{_render_classification_cell(item)}</td>
<td class="c-stage">{_render_corroboration_cell(item)}</td>
</tr>"""
        rows.append(row)

    return "\n".join(rows)


def generate_html(data: DiagnosticData, output_path: str) -> str:
    """Generate a diagnostic HTML report. Returns absolute path."""
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    n_dup = sum(1 for it in data.items if not it.dedup_passed)
    n_no_kw = sum(
        1
        for it in data.items
        if it.dedup_passed and it.keyword_info and not it.keyword_info.get("passed")
    )
    n_classified = data.total_classified
    n_mil = sum(
        1
        for it in data.items
        if it.classification and it.classification.is_military_event
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
  --accent: #e94560;
  --green: #28a745;
  --blue: #2196f3;
  --amber: #ff9800;
  --gray: #607d8b;
  --bg: #f4f6f9;
  --card: #fff;
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
  background: var(--bg); color: #333; font-size: 13px; line-height: 1.45;
}}

/* --- Header --- */
.header {{
  background: linear-gradient(135deg, var(--navy), #16213e);
  color: #fff; padding: 1.2rem 1.5rem;
  display: flex; align-items: center; justify-content: space-between;
  flex-wrap: wrap; gap: .4rem;
}}
.header h1 {{ font-size: 1.25rem; font-weight: 700; letter-spacing: .5px; }}
.header h1 span {{ color: var(--accent); }}
.header .meta {{ font-size: .8rem; color: #a0aec0; }}

/* --- Stats --- */
.stats {{
  display: flex; gap: 0; background: var(--card);
  border-bottom: 2px solid #e2e8f0; flex-wrap: wrap;
}}
.stat {{
  flex: 1; min-width: 100px; padding: .8rem 1rem; text-align: center;
  border-right: 1px solid #e2e8f0; position: relative;
}}
.stat:last-child {{ border-right: none; }}
.stat .n {{ font-size: 1.6rem; font-weight: 800; color: var(--navy); }}
.stat .l {{
  font-size: .65rem; text-transform: uppercase; letter-spacing: .8px;
  color: #888; margin-top: 2px;
}}
.stat .sub {{ font-size: .72rem; color: #aaa; }}
.stat.a .n {{ color: var(--accent); }}
.stat.g .n {{ color: var(--green); }}
.stat.b .n {{ color: var(--blue); }}
.stat::after {{
  content: "\\203A"; position: absolute; right: -7px; top: 50%;
  transform: translateY(-50%); font-size: 1.3rem; color: #cbd5e0; z-index: 1;
}}
.stat:last-child::after {{ content: none; }}

/* --- Controls --- */
.controls {{
  padding: .8rem 1.2rem; display: flex; gap: .5rem;
  flex-wrap: wrap; align-items: center;
}}
.fbtn {{
  padding: .3rem .75rem; border: 1px solid #ddd; border-radius: 14px;
  background: #fff; cursor: pointer; font-size: .75rem;
  transition: all .12s; font-family: inherit;
}}
.fbtn:hover {{ border-color: var(--navy); }}
.fbtn.on {{ background: var(--navy); color: #fff; border-color: var(--navy); }}
.fbtn .ct {{ color: #999; margin-left: 3px; }}
.fbtn.on .ct {{ color: #a0aec0; }}
.search-box {{
  margin-left: auto; padding: .35rem .7rem; border: 1px solid #ddd;
  border-radius: 14px; font-size: .78rem; width: 200px;
  font-family: inherit; outline: none;
}}
.search-box:focus {{ border-color: var(--blue); }}

/* --- Table --- */
.table-wrap {{ padding: .5rem 1rem 2rem; overflow-x: auto; }}
table {{
  width: 100%; border-collapse: collapse; background: var(--card);
  border-radius: 6px; overflow: hidden;
  box-shadow: 0 1px 3px rgba(0,0,0,.06); font-size: .8rem;
  min-width: 1200px;
}}

/* Column group headers */
thead tr.group-row th {{
  text-align: center; font-size: .7rem; letter-spacing: 1px;
  text-transform: uppercase; padding: .35rem .5rem; font-weight: 700;
}}
.gh-info {{ background: var(--navy); color: #fff; }}
.gh-dedup {{ background: var(--gray); color: #fff; }}
.gh-kw {{ background: var(--amber); color: #fff; }}
.gh-cls {{ background: var(--blue); color: #fff; }}
.gh-corr {{ background: var(--green); color: #fff; }}

thead tr.col-row th {{
  background: #2d2d44; color: #ccc; padding: .45rem .6rem;
  text-align: left; font-weight: 600; font-size: .72rem;
  white-space: nowrap; border-right: 1px solid #3a3a55;
}}
thead tr.col-row th:last-child {{ border-right: none; }}

tbody td {{
  padding: .45rem .6rem; border-bottom: 1px solid #edf2f7;
  vertical-align: top; border-right: 1px solid #f0f0f0;
}}
tbody td:last-child {{ border-right: none; }}
tbody tr:hover {{ background: #f7fafc; }}

/* Row status left border */
tr.row-military {{ border-left: 3px solid var(--accent); }}
tr.row-classified {{ border-left: 3px solid var(--blue); }}
tr.row-matched {{ border-left: 3px solid var(--green); }}
tr.row-filtered {{ border-left: 3px solid var(--amber); }}
tr.row-dup {{ border-left: 3px solid #ddd; }}
tr.row-dup td {{ color: #aaa; }}

/* Cell types */
.c-num {{ color: #aaa; font-size: .72rem; white-space: nowrap; text-align: right; width: 30px; }}
.c-src {{ width: 120px; }}
.c-title {{ min-width: 250px; max-width: 350px; }}
.c-lang {{ text-align: center; font-weight: 700; font-size: .72rem; width: 35px; }}
.c-time {{ white-space: nowrap; color: #666; width: 45px; }}
.c-stage {{ min-width: 140px; max-width: 260px; font-size: .76rem; }}
.c-cls {{ min-width: 200px; }}

/* Source badges */
.src-type {{
  display: inline-block; font-size: .6rem; font-weight: 700;
  text-transform: uppercase; letter-spacing: .4px;
  padding: 1px 5px; border-radius: 3px; margin-bottom: 1px;
}}
.st-rss {{ background: #e8f5e9; color: #2e7d32; }}
.st-google_news {{ background: #e3f2fd; color: #1565c0; }}
.st-gdelt {{ background: #fce4ec; color: #c62828; }}
.st-telegram {{ background: #e8eaf6; color: #283593; }}
.st-test {{ background: #f3e5f5; color: #6a1b9a; }}
.src-name {{ display: block; font-size: .74rem; color: #555; }}

/* Title & snippet */
.c-title a {{ color: var(--navy); text-decoration: none; font-weight: 500; }}
.c-title a:hover {{ color: var(--accent); text-decoration: underline; }}
.snippet {{
  margin-top: 2px; font-size: .7rem; color: #999; line-height: 1.3;
  display: -webkit-box; -webkit-line-clamp: 2;
  -webkit-box-orient: vertical; overflow: hidden;
}}

/* Status indicators */
.pass {{ color: var(--green); font-weight: 700; }}
.fail {{ color: #c0392b; font-weight: 600; }}
.skip {{ color: #bbb; font-style: italic; }}

/* Keyword badges */
.kw-badge {{
  display: inline-block; padding: 1px 4px; border-radius: 3px;
  font-size: .62rem; font-weight: 700; text-transform: uppercase;
  letter-spacing: .3px; margin-right: 3px; vertical-align: middle;
}}
.kw-crit {{ background: #f8d7da; color: #721c24; }}
.kw-high {{ background: #fff3cd; color: #856404; }}
.kw-excl {{ background: #fde2e2; color: #9b2c2c; }}

/* Classification badges */
.cls-badge {{
  display: inline-block; padding: 1px 5px; border-radius: 3px;
  font-size: .65rem; font-weight: 700; margin-right: 4px;
}}
.cls-mil {{ background: #f8d7da; color: #721c24; }}
.cls-safe {{ background: #cce5ff; color: #004085; }}
.cls-summary {{
  margin-top: 3px; font-style: italic; color: #666;
  font-size: .72rem; line-height: 1.3;
}}

/* Urgency scale */
.urgency {{ font-weight: 800; font-size: .78rem; }}
.u1, .u2 {{ color: #888; }}
.u3, .u4 {{ color: #b8860b; }}
.u5, .u6 {{ color: #e67e22; }}
.u7, .u8 {{ color: #e74c3c; }}
.u9, .u10 {{ color: #c0392b; font-size: .85rem; }}

/* Corroboration badges */
.corr-badge {{
  display: inline-block; padding: 1px 5px; border-radius: 3px;
  font-size: .62rem; font-weight: 700; margin-bottom: 2px;
}}
.corr-call {{ background: #f8d7da; color: #721c24; }}
.corr-sms {{ background: #fff3cd; color: #856404; }}
.corr-wa {{ background: #d4edda; color: #155724; }}
.corr-pending {{ background: #e2e8f0; color: #4a5568; }}
.corr-dry {{ background: #e8eaf6; color: #283593; }}

.footer {{
  text-align: center; padding: 1.2rem; font-size: .7rem; color: #aaa;
}}

@media (max-width: 768px) {{
  .header {{ padding: .8rem; }}
  .table-wrap {{ padding: .3rem; }}
}}
</style>
</head>
<body>

<div class="header">
  <h1>PROJECT <span>SENTINEL</span> &mdash; Diagnostic Report</h1>
  <div class="meta">
    {_esc(report_time)} &bull; Duration: {data.duration_seconds:.1f}s
  </div>
</div>

<div class="stats">
  <div class="stat">
    <div class="n">{data.total_fetched}</div>
    <div class="l">Fetched</div>
  </div>
  <div class="stat">
    <div class="n">{data.total_unique}</div>
    <div class="l">Unique</div>
    <div class="sub">&minus;{n_dup} duplicates</div>
  </div>
  <div class="stat b">
    <div class="n">{data.total_relevant}</div>
    <div class="l">Keyword Match</div>
    <div class="sub">&minus;{n_no_kw} filtered</div>
  </div>
  <div class="stat g">
    <div class="n">{n_classified}</div>
    <div class="l">Classified</div>
  </div>
  <div class="stat {'a' if n_mil > 0 else ''}">
    <div class="n">{n_mil}</div>
    <div class="l">Military Events</div>
  </div>
  <div class="stat">
    <div class="n">{data.total_events}</div>
    <div class="l">Events</div>
  </div>
</div>

<div class="controls">
  <button class="fbtn on" onclick="filterRows('all')">All <span class="ct">({len(data.items)})</span></button>
  <button class="fbtn" onclick="filterRows('row-military')">Military <span class="ct">({n_mil})</span></button>
  <button class="fbtn" onclick="filterRows('row-classified')">Classified <span class="ct">({n_classified - n_mil})</span></button>
  <button class="fbtn" onclick="filterRows('row-filtered')">Filtered <span class="ct">({n_no_kw})</span></button>
  <button class="fbtn" onclick="filterRows('row-dup')">Duplicates <span class="ct">({n_dup})</span></button>
  <input type="text" class="search-box" placeholder="Search titles..." oninput="searchRows(this.value)">
</div>

<div class="table-wrap">
<table>
  <thead>
    <tr class="group-row">
      <th class="gh-info" colspan="5">Article Info</th>
      <th class="gh-dedup">Dedup</th>
      <th class="gh-kw">Keywords</th>
      <th class="gh-cls">Classification</th>
      <th class="gh-corr">Corroboration</th>
    </tr>
    <tr class="col-row">
      <th>#</th>
      <th>Source</th>
      <th>Title</th>
      <th>Lang</th>
      <th>Time</th>
      <th>Result</th>
      <th>Match</th>
      <th>Haiku Verdict</th>
      <th>Event</th>
    </tr>
  </thead>
  <tbody>
{rows_html}
  </tbody>
</table>
</div>

<div class="footer">
  Project Sentinel Diagnostic &bull; {_esc(report_time)}
</div>

<script>
function filterRows(cls) {{
  document.querySelectorAll('tbody tr').forEach(r => {{
    r.style.display = (cls === 'all' || r.classList.contains(cls)) ? '' : 'none';
  }});
  document.querySelectorAll('.fbtn').forEach(b => b.classList.remove('on'));
  event.target.closest('.fbtn').classList.add('on');
}}
function searchRows(q) {{
  const lq = q.toLowerCase();
  document.querySelectorAll('tbody tr').forEach(r => {{
    r.style.display = (!lq || r.textContent.toLowerCase().includes(lq)) ? '' : 'none';
  }});
  if (!lq) document.querySelectorAll('.fbtn').forEach((b,i) => b.classList.toggle('on', i===0));
}}
</script>
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(page)

    abs_path = os.path.abspath(output_path)
    logger.info("Diagnostic report written to %s", abs_path)
    return abs_path
