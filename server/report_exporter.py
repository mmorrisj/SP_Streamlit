"""
Word document exporter for Publication reports.
Converts report JSON data into a formatted .docx file with charts.
"""

import io
from datetime import datetime
from typing import Dict, List, Any

from docx import Document
from docx.shared import Pt, RGBColor, Inches, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.ticker import MaxNLocator
import numpy as np


# ── Colour palette ──────────────────────────────────────────────

CATEGORY_COLORS = {
    'Economic': RGBColor(0x25, 0x63, 0xEB),
    'Diplomacy': RGBColor(0x7C, 0x3A, 0xED),
    'Social': RGBColor(0x05, 0x96, 0x69),
    'Military': RGBColor(0xDC, 0x26, 0x26),
}

CATEGORY_HEX = {
    'Economic': '#2563eb',
    'Diplomacy': '#7c3aed',
    'Social': '#059669',
    'Military': '#dc2626',
}

ENTITY_TYPE_COLORS = {
    'PERSON': '#7c3aed',
    'ORGANIZATION': '#2563eb',
    'COMPANY': '#059669',
    'LOCATION': '#ea580c',
}

TREND_COLORS = ['#2563eb', '#7c3aed', '#059669', '#ea580c', '#dc2626']


# ── Chart helpers ───────────────────────────────────────────────

def _fig_to_bytes(fig) -> io.BytesIO:
    """Render a matplotlib figure to a PNG BytesIO buffer."""
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=150, bbox_inches='tight',
                facecolor='white', edgecolor='none')
    plt.close(fig)
    buf.seek(0)
    return buf


def _make_horizontal_bar(data: List[Dict], label_key: str, value_key: str,
                         color: str = '#4a6fa5', title: str = '',
                         max_items: int = 10) -> io.BytesIO:
    """Generic horizontal bar chart."""
    items = data[:max_items]
    if not items:
        return None

    labels = [d[label_key] for d in items][::-1]
    values = [d[value_key] for d in items][::-1]

    fig, ax = plt.subplots(figsize=(5.5, max(2, len(labels) * 0.35)))
    bars = ax.barh(labels, values, color=color, height=0.6)
    ax.set_xlabel('Count', fontsize=8)
    if title:
        ax.set_title(title, fontsize=10, fontweight='bold')
    ax.tick_params(axis='both', labelsize=8)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    # Add value labels
    for bar, val in zip(bars, values):
        ax.text(bar.get_width() + max(values) * 0.01, bar.get_y() + bar.get_height() / 2,
                str(val), va='center', fontsize=7)

    fig.tight_layout()
    return _fig_to_bytes(fig)


def _make_materiality_histogram(data: List[Dict]) -> io.BytesIO:
    """Materiality score distribution bar chart."""
    filtered = [d for d in data if d['count'] > 0]
    if not filtered:
        return None

    labels = [d['bin'] for d in filtered]
    values = [d['count'] for d in filtered]

    fig, ax = plt.subplots(figsize=(5.5, 2.5))
    ax.bar(labels, values, color='#4a6fa5', width=0.7)
    ax.set_xlabel('Materiality Score Range', fontsize=8)
    ax.set_ylabel('Event Count', fontsize=8)
    ax.set_title('Materiality Score Distribution', fontsize=10, fontweight='bold')
    ax.tick_params(axis='both', labelsize=7)
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    fig.tight_layout()
    return _fig_to_bytes(fig)


def _make_materiality_trends(trends: Dict[str, Any]) -> io.BytesIO:
    """Materiality trends line chart."""
    overall = trends.get('overall_series', [])
    if len(overall) < 2:
        return None

    fig, ax = plt.subplots(figsize=(6, 3))

    # Parse months
    overall_months = [datetime.strptime(p['month'], '%Y-%m-%d') for p in overall]
    overall_scores = [p['avg_score'] for p in overall]

    ax.plot(overall_months, overall_scores, color='#1a365d', linewidth=2.5,
            marker='o', markersize=4, label='Overall', zorder=5)

    # Per-recipient lines
    recipient_series = trends.get('recipient_series', {})
    for i, (recip, series) in enumerate(recipient_series.items()):
        months = [datetime.strptime(p['month'], '%Y-%m-%d') for p in series]
        scores = [p['avg_score'] for p in series]
        color = TREND_COLORS[i % len(TREND_COLORS)]
        ax.plot(months, scores, color=color, linewidth=1.5, linestyle='--',
                marker='s', markersize=3, label=recip)

    ax.set_ylim(0, 10)
    ax.set_ylabel('Avg Materiality Score', fontsize=8)
    ax.set_title('Materiality Trends Over Time', fontsize=10, fontweight='bold')
    ax.tick_params(axis='both', labelsize=7)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %y'))
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.legend(fontsize=7, loc='upper left', framealpha=0.9)
    ax.grid(True, alpha=0.3)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    fig.autofmt_xdate(rotation=30)
    fig.tight_layout()
    return _fig_to_bytes(fig)


# ── Hyperlink helper ────────────────────────────────────────────

def _add_hyperlink(paragraph, text: str, url: str,
                   font_size: int = 8, color_hex: str = '2563EB'):
    """Add a clickable hyperlink run to an existing paragraph."""
    part = paragraph.part
    r_id = part.relate_to(url, 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink', is_external=True)

    hyperlink = OxmlElement('w:hyperlink')
    hyperlink.set(qn('r:id'), r_id)

    new_run = OxmlElement('w:r')
    rPr = OxmlElement('w:rPr')

    # Font size (half-points)
    sz = OxmlElement('w:sz')
    sz.set(qn('w:val'), str(font_size * 2))
    rPr.append(sz)

    # Color
    c = OxmlElement('w:color')
    c.set(qn('w:val'), color_hex)
    rPr.append(c)

    # Underline
    u = OxmlElement('w:u')
    u.set(qn('w:val'), 'single')
    rPr.append(u)

    # Font name
    rFonts = OxmlElement('w:rFonts')
    rFonts.set(qn('w:ascii'), 'Calibri')
    rFonts.set(qn('w:hAnsi'), 'Calibri')
    rPr.append(rFonts)

    new_run.append(rPr)

    t = OxmlElement('w:t')
    t.text = text
    t.set(qn('xml:space'), 'preserve')
    new_run.append(t)

    hyperlink.append(new_run)
    paragraph._p.append(hyperlink)


# ── Style helpers ───────────────────────────────────────────────

def _set_font(run, name='Calibri', size=11, bold=False, italic=False,
              color: RGBColor = None):
    run.font.name = name
    run.font.size = Pt(size)
    run.bold = bold
    run.italic = italic
    if color:
        run.font.color.rgb = color


def _add_heading(doc: Document, text: str, level: int = 2,
                 color: RGBColor = None):
    heading = doc.add_heading(text, level=level)
    if color:
        for run in heading.runs:
            run.font.color.rgb = color
    return heading


# ── Main export function ────────────────────────────────────────

def export_report_to_docx(report_data: dict) -> io.BytesIO:
    """
    Convert a report JSON dict into a formatted .docx BytesIO buffer.
    """
    doc = Document()

    # Set default font
    style = doc.styles['Normal']
    style.font.name = 'Calibri'
    style.font.size = Pt(11)

    country = report_data.get('country', 'Report')
    period_start = report_data.get('period_start', '')
    period_end = report_data.get('period_end', '')
    recipient_filter = report_data.get('recipient_filter', 'All')

    # ── Title Page ──────────────────────────────────────────────

    # Add some spacing
    for _ in range(4):
        doc.add_paragraph()

    title_para = doc.add_paragraph()
    title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_run = title_para.add_run(report_data.get('title', f'{country} Report'))
    _set_font(title_run, size=24, bold=True, color=RGBColor(0x1A, 0x36, 0x5D))

    subtitle_para = doc.add_paragraph()
    subtitle_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub_run = subtitle_para.add_run(
        f"{_format_date(period_start)} — {_format_date(period_end)}"
    )
    _set_font(sub_run, size=14, color=RGBColor(0x64, 0x74, 0x8B))

    if recipient_filter and recipient_filter != 'All':
        recip_para = doc.add_paragraph()
        recip_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = recip_para.add_run(f"Recipient Focus: {recipient_filter}")
        _set_font(r, size=12, italic=True, color=RGBColor(0x64, 0x74, 0x8B))

    gen_para = doc.add_paragraph()
    gen_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    gen_run = gen_para.add_run(
        f"Generated: {_format_datetime(report_data.get('generated_at', ''))}"
    )
    _set_font(gen_run, size=9, color=RGBColor(0x94, 0xA3, 0xB8))

    doc.add_page_break()

    # ── Executive Summary ───────────────────────────────────────

    overall_summary = report_data.get('overall_summary')
    if overall_summary:
        _add_heading(doc, 'Executive Summary', level=1,
                     color=RGBColor(0x1A, 0x36, 0x5D))
        p = doc.add_paragraph(overall_summary)
        p.style.font.size = Pt(11)
        doc.add_paragraph()  # spacer

    # ── Metrics Charts ──────────────────────────────────────────

    metrics = report_data.get('metrics', {})

    _add_heading(doc, 'Metrics Overview', level=1,
                 color=RGBColor(0x1A, 0x36, 0x5D))

    # Summary stats
    stats_para = doc.add_paragraph()
    r = stats_para.add_run(
        f"Total Documents: {metrics.get('total_documents', 0):,}  |  "
        f"Total Events: {metrics.get('total_events', 0)}"
    )
    _set_font(r, size=10, bold=True, color=RGBColor(0x33, 0x33, 0x33))

    # Category distribution chart
    cat_dist = metrics.get('category_distribution', [])
    if cat_dist:
        buf = _make_horizontal_bar(cat_dist, 'category', 'count',
                                   color='#1a365d',
                                   title='Category Distribution')
        if buf:
            doc.add_picture(buf, width=Inches(5.5))

    # Materiality histogram
    mat_hist = metrics.get('materiality_histogram', [])
    if mat_hist:
        buf = _make_materiality_histogram(mat_hist)
        if buf:
            doc.add_picture(buf, width=Inches(5.5))

    # Recipient distribution
    recip_dist = metrics.get('recipient_distribution', [])
    if recip_dist:
        buf = _make_horizontal_bar(recip_dist, 'recipient', 'count',
                                   color='#059669',
                                   title='Top Recipient Countries')
        if buf:
            doc.add_picture(buf, width=Inches(5.5))

    # Materiality trends
    trends = report_data.get('materiality_trends', {})
    if trends and trends.get('overall_series'):
        buf = _make_materiality_trends(trends)
        if buf:
            doc.add_picture(buf, width=Inches(5.5))

            # Significant changes
            changes = trends.get('significant_changes', [])
            if changes:
                p = doc.add_paragraph()
                r = p.add_run('Significant Changes: ')
                _set_font(r, size=9, bold=True, color=RGBColor(0x33, 0x33, 0x33))
                for sc in changes:
                    arrow = '▲' if sc['direction'] == 'increase' else '▼'
                    sc_color = RGBColor(0xDC, 0x26, 0x26) if sc['direction'] == 'increase' else RGBColor(0x05, 0x96, 0x69)
                    r = p.add_run(
                        f"  {sc['recipient']}: {arrow} {abs(sc['delta']):.1f} "
                        f"({_format_date(sc['month'])})  "
                    )
                    _set_font(r, size=8, color=sc_color)

    doc.add_page_break()

    # ── Category Sections ───────────────────────────────────────

    categories = report_data.get('categories', [])
    for cat_data in categories:
        cat_name = cat_data['category']
        cat_color = CATEGORY_COLORS.get(cat_name, RGBColor(0x1A, 0x36, 0x5D))

        _add_heading(doc, cat_name, level=1, color=cat_color)

        # Category narrative
        narrative = cat_data.get('narrative')
        if narrative:
            p = doc.add_paragraph(narrative)
            for run in p.runs:
                _set_font(run, size=10)

        # Events
        for event in cat_data.get('events', []):
            # Event heading
            event_heading = doc.add_heading(level=3)
            r = event_heading.add_run(event['event_name'])
            r.font.size = Pt(12)
            r.font.color.rgb = RGBColor(0x33, 0x33, 0x33)

            # Event metadata line
            meta_para = doc.add_paragraph()
            meta_items = [
                f"Materiality: {event.get('materiality_score', 'N/A')}/10",
                f"Articles: {event.get('article_count', 0)}",
                f"{_format_date(event.get('first_mention_date'))} – {_format_date(event.get('last_mention_date'))}",
            ]
            r = meta_para.add_run('  |  '.join(meta_items))
            _set_font(r, size=8, italic=True, color=RGBColor(0x64, 0x74, 0x8B))

            # Overview
            overview = event.get('overview')
            if overview:
                p = doc.add_paragraph()
                r = p.add_run('Overview: ')
                _set_font(r, size=10, bold=True)
                r = p.add_run(overview)
                _set_font(r, size=10)

            # Outcomes
            outcomes = event.get('outcomes')
            if outcomes:
                p = doc.add_paragraph()
                r = p.add_run('Outcomes: ')
                _set_font(r, size=10, bold=True)
                r = p.add_run(outcomes)
                _set_font(r, size=10)

            # Materiality Assessment
            justification = event.get('material_justification')
            if justification:
                p = doc.add_paragraph()
                r = p.add_run('Materiality Assessment: ')
                _set_font(r, size=9, bold=True, color=RGBColor(0x66, 0x66, 0x66))
                r = p.add_run(justification)
                _set_font(r, size=9, italic=True, color=RGBColor(0x55, 0x55, 0x55))

            # Key Entities
            entities = event.get('key_entities', [])
            if entities:
                p = doc.add_paragraph()
                r = p.add_run('Key Entities: ')
                _set_font(r, size=9, bold=True, color=RGBColor(0x66, 0x66, 0x66))
                for i, ent in enumerate(entities):
                    ent_type = (ent.get('entity_type') or 'UNKNOWN').upper()
                    hex_color = ENTITY_TYPE_COLORS.get(ent_type, '#666666')
                    rgb = RGBColor(
                        int(hex_color[1:3], 16),
                        int(hex_color[3:5], 16),
                        int(hex_color[5:7], 16)
                    )
                    separator = ', ' if i < len(entities) - 1 else ''
                    r = p.add_run(f"{ent['name']} ({ent_type}){separator}")
                    _set_font(r, size=8, color=rgb)

            # Spacer
            doc.add_paragraph()

    # ── Key Entities Section ────────────────────────────────────

    entity_groups = report_data.get('entities', [])
    if entity_groups:
        doc.add_page_break()
        _add_heading(doc, 'Key Entities', level=1,
                     color=RGBColor(0x1A, 0x36, 0x5D))

        for group in entity_groups:
            _add_heading(doc, group.get('type_label', 'ENTITIES'), level=2,
                         color=RGBColor(0x47, 0x55, 0x69))

            for entity in group.get('entities', []):
                # Entity name and role
                p = doc.add_paragraph()
                r = p.add_run(entity['name'])
                _set_font(r, size=10, bold=True)
                role = entity.get('role', 'Unknown')
                if role and role not in ('Unknown', 'OTHER'):
                    display_role = role.replace('_', ' ').title()
                    r = p.add_run(f'  —  {display_role}')
                    _set_font(r, size=9, italic=True, color=RGBColor(0x64, 0x74, 0x8B))

                # Document count and mention days
                meta_parts = [
                    f"Documents: {entity.get('total_documents', 0)}",
                    f"Mention Days: {entity.get('total_mention_days', 0)}",
                ]
                meta_para = doc.add_paragraph()
                r = meta_para.add_run('  |  '.join(meta_parts))
                _set_font(r, size=8, color=RGBColor(0x94, 0xA3, 0xB8))

                # Categories and recipients
                categories = entity.get('primary_categories') or {}
                recipients = entity.get('primary_recipients') or {}
                if categories or recipients:
                    tags_para = doc.add_paragraph()
                    top_cats = sorted(categories.items(), key=lambda x: x[1], reverse=True)[:4]
                    for cat, count in top_cats:
                        r = tags_para.add_run(f'{cat} ({count})  ')
                        _set_font(r, size=8, color=RGBColor(0x25, 0x63, 0xEB))
                    top_recips = sorted(recipients.items(), key=lambda x: x[1], reverse=True)[:3]
                    for recip, count in top_recips:
                        r = tags_para.add_run(f'{recip} ({count})  ')
                        _set_font(r, size=8, color=RGBColor(0xEA, 0x58, 0x0C))

                # Summary
                summary = entity.get('summary')
                if summary:
                    p = doc.add_paragraph(summary)
                    for run in p.runs:
                        _set_font(run, size=9)

                doc.add_paragraph()  # spacer

    # ── Methodology ─────────────────────────────────────────────

    doc.add_page_break()
    _add_heading(doc, 'Methodology', level=1,
                 color=RGBColor(0x1A, 0x36, 0x5D))

    methodology_paras = [
        (
            "This report is produced through an automated analytical pipeline that ingests "
            "open-source media reporting from a curated set of international news sources. "
            "Documents are collected, classified by thematic category and geographic relevance, "
            "and stored in a structured database for systematic analysis."
        ),
        (
            "Key Event Selection.  "
            "Individual articles are clustered into canonical events using embedding-based "
            "similarity analysis combined with temporal proximity. Events appearing in at least "
            "two independent source documents within the reporting period are surfaced for "
            "inclusion. Events are ranked by materiality score and filtered to the most "
            "substantive developments per thematic category."
        ),
        (
            "Materiality Scoring.  "
            "Each event is assigned a materiality score on a 1\u201310 scale reflecting its "
            "assessed policy relevance. Scoring criteria include the scope of actors involved, "
            "the scale of commitments or outcomes documented, coverage breadth across independent "
            "sources, and the degree to which the event represents a departure from established "
            "patterns. Scores are generated through a combination of algorithmic assessment and "
            "language model analysis of source material."
        ),
        (
            "Validation.  "
            "All narrative content, source attributions, and materiality assessments in this "
            "report are subject to review by subject matter experts (SMEs). Inline citations "
            "link each factual claim to its originating source document to support verification "
            "and traceability."
        ),
    ]

    for para_text in methodology_paras:
        p = doc.add_paragraph()
        r = p.add_run(para_text)
        _set_font(r, size=10)
        p.paragraph_format.space_after = Pt(6)

    # ── End Notes / Citations ───────────────────────────────────

    citations_by_event = report_data.get('citations_by_event', [])
    if citations_by_event:
        doc.add_page_break()
        _add_heading(doc, 'End Notes', level=1,
                     color=RGBColor(0x1A, 0x36, 0x5D))

        citation_num = 0
        for group in citations_by_event:
            cat_name = group['category']
            cat_color = CATEGORY_COLORS.get(cat_name, RGBColor(0x1A, 0x36, 0x5D))
            _add_heading(doc, cat_name, level=2, color=cat_color)

            for event_cit in group.get('events', []):
                # Event sub-heading
                p = doc.add_paragraph()
                r = p.add_run(event_cit['event_name'])
                _set_font(r, size=10, bold=True)
                r = p.add_run(
                    f"  (Materiality: {event_cit.get('materiality_score', 'N/A')}/10, "
                    f"{event_cit.get('date_range', '')})"
                )
                _set_font(r, size=8, italic=True, color=RGBColor(0x64, 0x74, 0x8B))

                # Individual citations
                for cit in event_cit.get('citations', []):
                    num = cit.get('citation_number', '')
                    headline = cit.get('headline', 'Untitled')
                    source = cit.get('source_name', 'Unknown')
                    pub_date = _format_date(cit.get('published_date'))
                    hyperlink = cit.get('repo_hyperlink', '')

                    p = doc.add_paragraph()
                    r = p.add_run(f'[{num}] ')
                    _set_font(r, size=8, bold=True, color=RGBColor(0x25, 0x63, 0xEB))
                    r = p.add_run(f'{headline}')
                    _set_font(r, size=8, bold=True)
                    r = p.add_run(f'  — {source}, {pub_date}')
                    _set_font(r, size=8, color=RGBColor(0x64, 0x74, 0x8B))
                    if hyperlink:
                        r = p.add_run('  ')
                        _add_hyperlink(p, '[ATOM]', hyperlink)

    # ── Write to buffer ─────────────────────────────────────────

    output = io.BytesIO()
    doc.save(output)
    output.seek(0)
    return output


# ── Utility ─────────────────────────────────────────────────────

def _format_date(date_str: str | None) -> str:
    if not date_str:
        return ''
    try:
        dt = datetime.strptime(date_str[:10], '%Y-%m-%d')
        return dt.strftime('%b %d, %Y')
    except (ValueError, TypeError):
        return str(date_str)


def _format_datetime(dt_str: str | None) -> str:
    if not dt_str:
        return ''
    try:
        dt = datetime.fromisoformat(dt_str)
        return dt.strftime('%B %d, %Y at %I:%M %p')
    except (ValueError, TypeError):
        return str(dt_str)
