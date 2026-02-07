"""
Document-Based Hierarchical Summary Generator with Source Attribution

Generates hierarchical summaries directly from documents (bypasses event pipeline).
Perfect for quick publications when event data isn't ready.

CRITICAL FEATURE: Full source attribution with citation chains
- Every fact in summaries is cited with numbered references
- Citations link all the way back to original source documents
- Analysts can validate every claim by following the citation chain

Hierarchical Rollup:
    Documents → Daily Summaries (cites [1], [2], etc. for specific docs)
    Daily Summaries → Weekly Summaries (cites [Day 1], [Day 2], etc.)
    Weekly Summaries → Monthly Summaries (cites [Week 1], [Week 2], etc.)
    Monthly Summaries → Overall Summary (cites [Month 1], [Month 2], etc.)

Citation Chain Structure:
    Overall Summary [Month 1] → Monthly Summary [Week 2] → Weekly Summary [Day 3] → Daily Summary [5] → Document doc_id
    This allows complete traceability from any claim to its source documents.

Outputs:
    - JSON files at each level with 'citations' arrays for validation
    - Each citation includes doc_id, headline, source, URL, excerpt
    - Optional database storage for tracking

Usage:
    # Generate all levels for China (all recipients) June-December 2025
    python generate_document_based_summaries.py \
        --influencer China \
        --start-date 2025-06-01 \
        --end-date 2025-12-31 \
        --output-dir ./publications

    # Generate bilateral summaries (China → Egypt only)
    python generate_document_based_summaries.py \
        --influencer China \
        --recipient Egypt \
        --start-date 2025-06-01 \
        --end-date 2025-12-31 \
        --output-dir ./publications

    # Generate only daily summaries
    python generate_document_based_summaries.py \
        --influencer China \
        --start-date 2025-06-01 \
        --end-date 2025-12-31 \
        --daily-only

    # Dry run to see what would be generated
    python generate_document_based_summaries.py \
        --influencer China \
        --recipient Egypt \
        --start-date 2025-06-01 \
        --end-date 2025-12-31 \
        --dry-run

JSON Output Structure:
    {
        "summary": "Text with citations [1], [2], [Day 1], [Week 2], or [Month 1]",
        "citations": [
            {
                "citation_number": 1,
                "doc_id": "abc123",
                "headline": "...",
                "source_name": "...",
                "source_url": "...",
                "excerpt": "..."
            }
        ],
        "metrics": {...},
        ...
    }
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional
from collections import defaultdict
from sqlalchemy import text

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from shared.database.database import get_session
from shared.models.models import Document
from shared.utils.utils import gai, Config


def parse_date(date_str: str) -> date:
    """Parse date string in YYYY-MM-DD format."""
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(f"Invalid date format: {date_str}. Use YYYY-MM-DD")


def get_documents_for_day(
    session,
    influencer: str,
    target_date: date,
    recipient: Optional[str] = None,
    valid_recipients: Optional[List[str]] = None
) -> List[Dict]:
    """
    Get all documents for a specific influencer (and optionally recipient) on a date.

    Args:
        session: Database session
        influencer: Initiating country (e.g., "China", "Russia")
        target_date: Date to query
        recipient: Optional recipient country filter (e.g., "Egypt", "Kenya")
        valid_recipients: List of valid recipient countries from config.yaml (used when recipient is None)

    Returns:
        List of dicts with document metadata
    """
    if recipient:
        # Bilateral: Filter by both influencer and specific recipient
        query = text("""
            SELECT DISTINCT
                d.doc_id,
                d.date,
                d.title,
                d.distilled_text,
                d.source_name,
                NULL as source_url,
                CAST(d.salience AS FLOAT) as salience,
                (SELECT array_agg(DISTINCT c.category)
                 FROM categories c
                 WHERE c.doc_id = d.doc_id) as categories,
                (SELECT array_agg(DISTINCT rc.recipient_country)
                 FROM recipient_countries rc
                 WHERE rc.doc_id = d.doc_id) as recipients
            FROM documents d
            JOIN initiating_countries ic ON ic.doc_id = d.doc_id
            JOIN recipient_countries rc ON rc.doc_id = d.doc_id
            WHERE ic.initiating_country = :influencer
              AND rc.recipient_country = :recipient
              AND d.date = :target_date
            ORDER BY CAST(d.salience AS FLOAT) DESC
        """)

        results = session.execute(query, {
            'influencer': influencer,
            'recipient': recipient,
            'target_date': target_date
        }).fetchall()
    else:
        # All valid recipients: Filter by influencer and recipients in config.yaml
        if not valid_recipients:
            raise ValueError("valid_recipients must be provided when recipient is None")

        # Build parameterized query for IN clause
        recipient_params = {f'recipient_{i}': rec for i, rec in enumerate(valid_recipients)}
        recipient_placeholders = ', '.join([f':recipient_{i}' for i in range(len(valid_recipients))])

        query = text(f"""
            SELECT DISTINCT
                d.doc_id,
                d.date,
                d.title,
                d.distilled_text,
                d.source_name,
                NULL as source_url,
                CAST(d.salience AS FLOAT) as salience,
                (SELECT array_agg(DISTINCT c.category)
                 FROM categories c
                 WHERE c.doc_id = d.doc_id) as categories,
                (SELECT array_agg(DISTINCT rc.recipient_country)
                 FROM recipient_countries rc
                 WHERE rc.doc_id = d.doc_id) as recipients
            FROM documents d
            JOIN initiating_countries ic ON ic.doc_id = d.doc_id
            JOIN recipient_countries rc ON rc.doc_id = d.doc_id
            WHERE ic.initiating_country = :influencer
              AND rc.recipient_country IN ({recipient_placeholders})
              AND d.date = :target_date
            ORDER BY CAST(d.salience AS FLOAT) DESC
        """)

        params = {
            'influencer': influencer,
            'target_date': target_date,
            **recipient_params
        }
        results = session.execute(query, params).fetchall()

    return [
        {
            'doc_id': row[0],
            'date': row[1].isoformat() if row[1] else None,
            'title': row[2],
            'distilled_text': row[3],
            'source_name': row[4],
            'source_url': row[5],  # Will be None
            'salience': row[6],
            'categories': row[7] or [],
            'recipients': row[8] or []
        }
        for row in results
    ]


def chunk_documents_by_similarity(docs: List[Dict], max_chunk_size: int = 50) -> List[List[Dict]]:
    """
    Chunk documents into groups, keeping similar documents together.

    Strategy:
    1. Sort by (recipient_country, category, salience)
    2. Group sequentially into chunks of max_chunk_size

    This ensures documents about the same event/topic stay together.

    Args:
        docs: List of document dicts
        max_chunk_size: Maximum documents per chunk

    Returns:
        List of document chunks
    """
    if len(docs) <= max_chunk_size:
        return [docs]

    # Sort by: primary recipient, primary category, then salience (descending)
    def sort_key(doc):
        primary_recipient = doc['recipients'][0] if doc['recipients'] else "ZZZ"
        primary_category = doc['categories'][0] if doc['categories'] else "ZZZ"
        salience = doc['salience'] if doc['salience'] else 0
        return (primary_recipient, primary_category, -salience)

    sorted_docs = sorted(docs, key=sort_key)

    # Chunk sequentially
    chunks = []
    for i in range(0, len(sorted_docs), max_chunk_size):
        chunks.append(sorted_docs[i:i + max_chunk_size])

    return chunks


def generate_daily_summary(
    session,
    influencer: str,
    target_date: date,
    model: str = "gpt-4o-mini",
    max_docs_per_chunk: int = 100,
    recipient: Optional[str] = None,
    valid_recipients: Optional[List[str]] = None
) -> Optional[Dict]:
    """
    Generate LLM summary for a single day's documents with source attribution.

    For days with many documents, uses chunking with map-reduce:
    1. Chunk documents by similarity (keeps related docs together)
    2. Generate sub-summaries for each chunk
    3. Combine sub-summaries into final daily summary

    Args:
        session: Database session
        influencer: Initiating country
        target_date: Date to summarize
        model: LLM model to use
        max_docs_per_chunk: Max docs before chunking
        recipient: Optional recipient country for bilateral analysis
        valid_recipients: List of valid recipient countries from config.yaml (required when recipient is None)

    Returns:
        Dict with summary data, citations mapping, or None if no documents
    """
    docs = get_documents_for_day(session, influencer, target_date, recipient, valid_recipients)

    if not docs:
        return None

    # Chunk if too many documents
    if len(docs) > max_docs_per_chunk:
        return generate_daily_summary_chunked(docs, influencer, target_date, model, max_docs_per_chunk, recipient)

    # Standard single-pass generation
    return generate_daily_summary_single(docs, influencer, target_date, model, recipient)


def generate_daily_summary_chunked(
    docs: List[Dict],
    influencer: str,
    target_date: date,
    model: str = "gpt-4o-mini",
    max_docs_per_chunk: int = 100,
    recipient: Optional[str] = None
) -> Dict:
    """
    Generate daily summary for large document sets using map-reduce.

    Map phase: Generate sub-summaries for each chunk
    Reduce phase: Combine sub-summaries into final summary

    Preserves full citation chain from final summary → chunk summaries → documents.
    """
    print(f"\n    ⚠️  Large document set ({len(docs)} docs) - using chunked processing")

    # Chunk documents by similarity
    chunks = chunk_documents_by_similarity(docs, max_docs_per_chunk)
    print(f"    📦 Split into {len(chunks)} chunks")

    # MAP PHASE: Generate sub-summaries for each chunk
    chunk_summaries = []
    all_citations = []
    citation_offset = 0

    for chunk_idx, chunk in enumerate(chunks, 1):
        print(f"    Processing chunk {chunk_idx}/{len(chunks)} ({len(chunk)} docs)...", end='', flush=True)

        # Generate summary for this chunk with local citation numbers
        chunk_summary_dict = generate_daily_summary_single(chunk, influencer, target_date, model, recipient)

        # Check if LLM call failed
        if chunk_summary_dict is None:
            print(" ❌ LLM call failed, skipping chunk")
            continue

        # Renumber citations to be globally unique across all chunks
        for citation in chunk_summary_dict['citations']:
            citation['citation_number'] = citation_offset + citation['citation_number']

        citation_offset += len(chunk)

        chunk_summaries.append(chunk_summary_dict['summary'])
        all_citations.extend(chunk_summary_dict['citations'])
        print(" ✅")

    # Check if all chunks failed
    if not chunk_summaries:
        print(f"    ❌ All chunks failed - unable to generate summary for {target_date}")
        return None

    # REDUCE PHASE: Combine chunk summaries into final daily summary
    print(f"    🔄 Combining {len(chunk_summaries)} chunk summaries...")

    relationship_desc = f"{influencer} → {recipient}" if recipient else influencer

    reduce_system_prompt = """You are a foreign policy analyst combining multiple sub-summaries into a cohesive daily summary.

Generate a unified summary organized by:
1. Key Themes (what types of activities were prominent)
2. Notable Activities (specific actions, grouped by category)
3. Geographic Focus (which recipient countries were most mentioned)
4. Overall Assessment (1-2 sentences on strategic significance)

IMPORTANT: The sub-summaries already contain citations [N]. Preserve these citations in your combined summary.

Be factual, concise, and analytical. Focus on patterns and significance across all sub-summaries."""

    # Build sub-summaries text outside the f-string to avoid backslash issues
    sub_summaries_text = '---'.join(f"\n\nSub-summary {i+1}:\n{summary}" for i, summary in enumerate(chunk_summaries))

    reduce_user_prompt = f"""Relationship: {relationship_desc}
Date: {target_date.isoformat()}
Total Documents: {len(docs)}
Sub-summaries: {len(chunk_summaries)}

SUB-SUMMARIES TO COMBINE:
{sub_summaries_text}

Combine these sub-summaries into a single cohesive daily summary. Preserve all citations."""

    try:
        combined_summary = gai(reduce_system_prompt, reduce_user_prompt, model=model)

        # Calculate aggregate metrics
        categories = defaultdict(int)
        recipients_count = defaultdict(int)
        sources = defaultdict(int)

        for doc in docs:
            for cat in doc['categories']:
                categories[cat] += 1
            for rec in doc['recipients']:
                recipients_count[rec] += 1
            if doc['source_name']:
                sources[doc['source_name']] += 1

        result = {
            'date': target_date.isoformat(),
            'influencer': influencer,
            'summary': combined_summary,
            'citations': all_citations,  # Full citation list from all chunks
            'metrics': {
                'total_documents': len(docs),
                'categories': dict(categories),
                'recipients': dict(recipients_count),
                'sources': dict(sources),
                'avg_salience': sum(d['salience'] for d in docs if d['salience']) / len(docs),
                'chunks_processed': len(chunks)  # Added to show chunking was used
            },
            'doc_ids': [d['doc_id'] for d in docs],
            'generated_at': datetime.utcnow().isoformat()
        }

        if recipient:
            result['recipient'] = recipient

        return result

    except Exception as e:
        print(f"    ❌ Error in reduce phase for {target_date}: {e}")
        return None


def generate_daily_summary_single(
    docs: List[Dict],
    influencer: str,
    target_date: date,
    model: str = "gpt-4o-mini",
    recipient: Optional[str] = None
) -> Dict:
    """
    Generate daily summary from a single batch of documents (non-chunked).

    If there's only one document, uses the distilled_text directly instead of calling LLM.
    """

    # OPTIMIZATION: If only one document, skip LLM and use distilled_text directly
    if len(docs) == 1:
        doc = docs[0]
        summary_text = f"{doc['distilled_text'] or doc['title']} [1]"

        # Build single citation
        citations = [{
            'citation_number': 1,
            'doc_id': doc['doc_id'],
            'headline': doc['title'],
            'source_name': doc['source_name'],
            'source_url': doc['source_url'],
            'published_date': doc['date'],
            'salience': doc['salience'],
            'categories': doc['categories'],
            'recipients': doc['recipients'],
            'excerpt': doc['distilled_text'][:500] if doc['distilled_text'] else ""
        }]

        # Calculate metrics
        categories = defaultdict(int)
        recipients_count = defaultdict(int)
        sources = defaultdict(int)

        for cat in doc['categories']:
            categories[cat] += 1
        for rec in doc['recipients']:
            recipients_count[rec] += 1
        if doc['source_name']:
            sources[doc['source_name']] += 1

        result = {
            'date': target_date.isoformat(),
            'influencer': influencer,
            'summary': summary_text,
            'citations': citations,
            'metrics': {
                'total_documents': 1,
                'categories': dict(categories),
                'recipients': dict(recipients_count),
                'sources': dict(sources),
                'avg_salience': doc['salience'] or 0
            },
            'doc_ids': [doc['doc_id']],
            'generated_at': datetime.utcnow().isoformat()
        }

        if recipient:
            result['recipient'] = recipient

        return result

    # Multiple documents: Build context from documents with numbered references
    doc_context = []
    for i, doc in enumerate(docs, 1):
        categories_str = ", ".join(doc['categories']) if doc['categories'] else "None"
        recipients_str = ", ".join(doc['recipients']) if doc['recipients'] else "None"
        doc_context.append(
            f"[{i}] {doc['title']}\n"
            f"    Source: {doc['source_name']}\n"
            f"    Categories: {categories_str}\n"
            f"    Recipients: {recipients_str}\n"
            f"    Salience: {doc['salience']}/100\n"
            f"    Excerpt: {doc['distilled_text'][:400] if doc['distilled_text'] else 'N/A'}..."
        )

    context_text = "\n\n".join(doc_context)

    relationship_desc = f"{influencer} → {recipient}" if recipient else influencer

    # LLM prompt for daily summary WITH CITATIONS
    system_prompt = """You are a foreign policy analyst creating daily activity summaries.

CRITICAL: You must cite your sources using numbered references [1], [2], etc. that correspond to the document numbers provided.

OUTPUT FORMAT (PLAIN TEXT PARAGRAPHS ONLY):
Write 3-4 concise paragraphs covering:
- Paragraph 1: Main themes and prominent types of activities
- Paragraph 2: Specific notable activities grouped by category
- Paragraph 3: Geographic focus and recipient countries involved
- Paragraph 4: Brief strategic significance (1-2 sentences)

CITATION REQUIREMENTS:
- After EVERY factual claim, add a citation like [1] or [1,2] for multiple sources
- Use the document numbers from the provided list
- Multiple claims from the same document still need citations
- Be precise about which document supports which claim

IMPORTANT:
- Do NOT use markdown formatting (no **, ##, bullets, numbered lists, or section headers)
- Do NOT include labels like "Key Themes:" or "Notable Activities:"
- Write ONLY plain text paragraphs separated by blank lines
- Report directly on activities without meta-commentary about "soft power"
- Focus on what happened, not on categorizing it"""

    user_prompt = f"""Relationship: {relationship_desc}
Date: {target_date.isoformat()}
Documents: {len(docs)}

DOCUMENTS (use these numbers for citations):
{context_text}

Generate a structured daily summary with proper citations following the format above."""

    try:
        summary_text = gai(system_prompt, user_prompt, model=model)

        # Calculate metrics
        categories = defaultdict(int)
        recipients_count = defaultdict(int)
        sources = defaultdict(int)

        for doc in docs:
            for cat in doc['categories']:
                categories[cat] += 1
            for rec in doc['recipients']:
                recipients_count[rec] += 1
            if doc['source_name']:
                sources[doc['source_name']] += 1

        # Build citation reference list
        citations = []
        for i, doc in enumerate(docs, 1):
            citations.append({
                'citation_number': i,
                'doc_id': doc['doc_id'],
                'headline': doc['title'],
                'source_name': doc['source_name'],
                'source_url': doc['source_url'],
                'published_date': doc['date'],
                'salience': doc['salience'],
                'categories': doc['categories'],
                'recipients': doc['recipients'],
                'excerpt': doc['distilled_text'][:500] if doc['distilled_text'] else ""
            })

        result = {
            'date': target_date.isoformat(),
            'influencer': influencer,
            'summary': summary_text,
            'citations': citations,  # NEW: Full citation details for validation
            'metrics': {
                'total_documents': len(docs),
                'categories': dict(categories),
                'recipients': dict(recipients_count),
                'sources': dict(sources),
                'avg_salience': sum(d['salience'] for d in docs if d['salience']) / len(docs)
            },
            'doc_ids': [d['doc_id'] for d in docs],
            'generated_at': datetime.utcnow().isoformat()
        }

        if recipient:
            result['recipient'] = recipient

        return result

    except Exception as e:
        print(f"  ⚠️  Error generating summary for {target_date}: {e}")
        return None


def generate_weekly_summary(
    daily_summaries: List[Dict],
    week_start: date,
    week_end: date,
    influencer: str,
    model: str = "gpt-4o-mini",
    recipient: Optional[str] = None
) -> Dict:
    """
    Generate LLM summary from daily summaries for a week with source attribution.

    Args:
        daily_summaries: List of daily summary dicts (with citations)
        week_start: Start date of week
        week_end: End date of week
        influencer: Initiating country
        model: LLM model to use
        recipient: Optional recipient country for bilateral analysis

    Returns:
        Dict with weekly summary data and citation chain
    """
    if not daily_summaries:
        result = {
            'period_start': week_start.isoformat(),
            'period_end': week_end.isoformat(),
            'influencer': influencer,
            'summary': "No activities recorded for this week.",
            'citations': [],
            'metrics': {
                'total_documents': 0,
                'categories': {},
                'recipients': {},
                'sources': {}
            },
            'daily_dates': [],
            'generated_at': datetime.utcnow().isoformat()
        }
        if recipient:
            result['recipient'] = recipient
        return result

    # Build context from daily summaries with numbered references
    daily_context = []
    for i, daily in enumerate(daily_summaries, 1):
        daily_context.append(
            f"[Day {i}] {daily['date']}\n"
            f"Documents: {daily['metrics']['total_documents']}\n"
            f"Summary: {daily['summary']}\n"
        )

    context_text = "\n---\n".join(daily_context)

    relationship_desc = f"{influencer} → {recipient}" if recipient else influencer

    # LLM prompt for weekly rollup WITH CITATIONS
    system_prompt = """You are a foreign policy analyst creating weekly activity summaries from daily reports.

CRITICAL: You must cite your sources using numbered day references [Day 1], [Day 2], etc. that correspond to the daily summaries provided.

OUTPUT FORMAT (PLAIN TEXT PARAGRAPHS ONLY):
Write 4-5 concise paragraphs covering:
- Paragraph 1: Major sustained themes and patterns across the week
- Paragraph 2-3: Key developments and significant activities by category
- Paragraph 4: Geographic engagement patterns and trends
- Paragraph 5: Strategic significance and implications

CITATION REQUIREMENTS:
- After EVERY factual claim, add a citation like [Day 1] or [Day 1,2] for multiple days
- Use the day numbers from the provided daily summaries
- Be precise about which day's activities support which claim

IMPORTANT:
- Do NOT use markdown formatting (no **, ##, bullets, numbered lists, or section headers)
- Do NOT include labels like "Major Themes:" or "Key Developments:"
- Write ONLY plain text paragraphs separated by blank lines
- Report directly on activities without meta-commentary about "soft power"
- Identify patterns, escalations, and strategic shifts. Be analytical."""

    user_prompt = f"""Relationship: {relationship_desc}
Week: {week_start.isoformat()} to {week_end.isoformat()}
Days with Activity: {len(daily_summaries)}

DAILY SUMMARIES (use Day numbers for citations):
{context_text}

Generate a comprehensive weekly summary with proper citations synthesizing these daily reports."""

    try:
        summary_text = gai(system_prompt, user_prompt, model=model)

        # Aggregate metrics
        total_docs = sum(d['metrics']['total_documents'] for d in daily_summaries)
        categories = defaultdict(int)
        recipients_count = defaultdict(int)
        sources = defaultdict(int)

        for daily in daily_summaries:
            for cat, count in daily['metrics']['categories'].items():
                categories[cat] += count
            for rec, count in daily['metrics']['recipients'].items():
                recipients_count[rec] += count
            for src, count in daily['metrics']['sources'].items():
                sources[src] += count

        # Build citation reference list (links to daily summaries which link to docs)
        citations = []
        for i, daily in enumerate(daily_summaries, 1):
            citations.append({
                'citation_number': f"Day {i}",
                'date': daily['date'],
                'summary_excerpt': daily['summary'][:200] + "...",
                'total_documents': daily['metrics']['total_documents'],
                'doc_ids': daily['doc_ids'],
                'daily_citations': daily.get('citations', [])  # Include daily citations for drill-down
            })

        result = {
            'period_start': week_start.isoformat(),
            'period_end': week_end.isoformat(),
            'influencer': influencer,
            'summary': summary_text,
            'citations': citations,  # NEW: Citation chain to daily summaries and docs
            'metrics': {
                'total_documents': total_docs,
                'categories': dict(categories),
                'recipients': dict(recipients_count),
                'sources': dict(sources),
                'days_with_activity': len(daily_summaries)
            },
            'daily_dates': [d['date'] for d in daily_summaries],
            'generated_at': datetime.utcnow().isoformat()
        }

        if recipient:
            result['recipient'] = recipient

        return result

    except Exception as e:
        print(f"  ⚠️  Error generating weekly summary: {e}")
        return None


def generate_monthly_summary(
    weekly_summaries: List[Dict],
    month_start: date,
    month_end: date,
    influencer: str,
    model: str = "gpt-4o",
    recipient: Optional[str] = None
) -> Dict:
    """
    Generate LLM summary from weekly summaries for a month with source attribution.
    Uses GPT-4 for higher quality monthly analysis.
    """
    if not weekly_summaries:
        result = {
            'period_start': month_start.isoformat(),
            'period_end': month_end.isoformat(),
            'influencer': influencer,
            'summary': "No activities recorded for this month.",
            'citations': [],
            'metrics': {
                'total_documents': 0,
                'categories': {},
                'recipients': {},
                'sources': {}
            },
            'weeks_covered': 0,
            'generated_at': datetime.utcnow().isoformat()
        }
        if recipient:
            result['recipient'] = recipient
        return result

    # Build context from weekly summaries with numbered references
    weekly_context = []
    for i, weekly in enumerate(weekly_summaries, 1):
        weekly_context.append(
            f"[Week {i}] ({weekly['period_start']} to {weekly['period_end']})\n"
            f"Documents: {weekly['metrics']['total_documents']}\n"
            f"Summary: {weekly['summary']}\n"
        )

    context_text = "\n---\n".join(weekly_context)

    relationship_desc = f"{influencer} → {recipient}" if recipient else influencer

    # LLM prompt for monthly rollup WITH CITATIONS
    system_prompt = """You are a senior foreign policy analyst creating monthly strategic assessments.

CRITICAL: You must cite your sources using numbered week references [Week 1], [Week 2], etc. that correspond to the weekly summaries provided.

OUTPUT FORMAT (PLAIN TEXT PARAGRAPHS ONLY):
Write 5-6 comprehensive paragraphs covering:
- Paragraph 1-2: Strategic overview including major themes and patterns
- Paragraph 3: Key initiatives and significant activities by category
- Paragraph 4: Geographic engagement patterns by recipient country/region
- Paragraph 5: Outcome assessment including achievements and setbacks
- Paragraph 6: Notable trends and shifts in approach

CITATION REQUIREMENTS:
- After EVERY factual claim, add a citation like [Week 1] or [Week 1,2] for multiple weeks
- Use the week numbers from the provided weekly summaries
- Be precise about which week's activities support which claim

IMPORTANT:
- Do NOT use markdown formatting (no **, ##, bullets, numbered lists, or section headers)
- Do NOT include labels like "Strategic Overview:" or "Key Initiatives:"
- Write ONLY plain text paragraphs separated by blank lines
- Report directly on activities and developments without meta-commentary
- Provide strategic-level analysis with specific examples. Identify causality and strategic intent."""

    user_prompt = f"""Relationship: {relationship_desc}
Month: {month_start.strftime('%B %Y')}
Period: {month_start.isoformat()} to {month_end.isoformat()}
Weeks Covered: {len(weekly_summaries)}

WEEKLY SUMMARIES (use Week numbers for citations):
{context_text}

Generate a comprehensive monthly strategic assessment with proper citations synthesizing these weekly reports."""

    try:
        summary_text = gai(system_prompt, user_prompt, model=model)

        # Aggregate metrics
        total_docs = sum(w['metrics']['total_documents'] for w in weekly_summaries)
        categories = defaultdict(int)
        recipients_count = defaultdict(int)
        sources = defaultdict(int)

        for weekly in weekly_summaries:
            for cat, count in weekly['metrics']['categories'].items():
                categories[cat] += count
            for rec, count in weekly['metrics']['recipients'].items():
                recipients_count[rec] += count
            for src, count in weekly['metrics']['sources'].items():
                sources[src] += count

        # Build citation reference list (links to weekly summaries which link to daily which link to docs)
        citations = []
        for i, weekly in enumerate(weekly_summaries, 1):
            citations.append({
                'citation_number': f"Week {i}",
                'period_start': weekly['period_start'],
                'period_end': weekly['period_end'],
                'summary_excerpt': weekly['summary'][:200] + "...",
                'total_documents': weekly['metrics']['total_documents'],
                'daily_dates': weekly.get('daily_dates', []),
                'weekly_citations': weekly.get('citations', [])  # Include weekly citations for drill-down
            })

        result = {
            'period_start': month_start.isoformat(),
            'period_end': month_end.isoformat(),
            'influencer': influencer,
            'summary': summary_text,
            'citations': citations,  # NEW: Citation chain to weekly → daily → docs
            'metrics': {
                'total_documents': total_docs,
                'categories': dict(categories),
                'recipients': dict(recipients_count),
                'sources': dict(sources),
                'weeks_covered': len(weekly_summaries)
            },
            'generated_at': datetime.utcnow().isoformat()
        }

        if recipient:
            result['recipient'] = recipient

        return result

    except Exception as e:
        print(f"  ⚠️  Error generating monthly summary: {e}")
        return None


def generate_overall_summary(
    monthly_summaries: List[Dict],
    start_date: date,
    end_date: date,
    influencer: str,
    model: str = "gpt-4o",
    recipient: Optional[str] = None
) -> Dict:
    """
    Generate final overall summary from monthly summaries with source attribution.
    Uses GPT-4 for highest quality final analysis.
    """
    # Build context from monthly summaries with numbered references
    monthly_context = []
    for i, monthly in enumerate(monthly_summaries, 1):
        month_name = datetime.fromisoformat(monthly['period_start']).strftime('%B %Y')
        monthly_context.append(
            f"[Month {i}] {month_name}:\n"
            f"Documents: {monthly['metrics']['total_documents']}\n"
            f"Summary: {monthly['summary']}\n"
        )

    context_text = "\n---\n".join(monthly_context)

    relationship_desc = f"{influencer} → {recipient}" if recipient else influencer

    # LLM prompt for overall summary WITH CITATIONS
    system_prompt = """You are a senior foreign policy strategist creating a comprehensive assessment of diplomatic and international activities.

CRITICAL: You must cite your sources using numbered month references [Month 1], [Month 2], etc. that correspond to the monthly summaries provided.

OUTPUT FORMAT (PLAIN TEXT PARAGRAPHS ORGANIZED BY CATEGORY):
Structure your summary as follows:

FIRST SECTION (1-2 paragraphs): Executive summary of overall strategy and results across all categories.

THEN ORGANIZE BY CATEGORY - Only include categories with actual activity. For each active category, write 1-2 focused paragraphs:

If Economic activities exist: Write about economic initiatives, trade, infrastructure, financial engagement. Avoid content already covered in other categories.

If Diplomacy activities exist: Write about diplomatic initiatives, agreements, multilateral engagement, conflict resolution. Avoid content already covered in other categories.

If Social activities exist: Write about cultural, educational, media, religious, and diaspora engagement. Avoid content already covered in other categories.

If Military activities exist: Write about military sales, training, joint exercises, security cooperation. Avoid content already covered in other categories.

FINAL SECTION (1-2 paragraphs): Strategic outcomes and forward indicators across all categories.

DEDUPLICATION RULES:
- When activities span multiple categories, assign them to the MOST relevant category only
- Do not repeat the same activity or initiative in multiple category sections
- If an activity could fit multiple categories, include it where it has the strongest alignment
- Each category section should contain ONLY content uniquely relevant to that category

CITATION REQUIREMENTS:
- After EVERY factual claim, add a citation like [Month 1] or [Month 1,2] for multiple months
- Use the month numbers from the provided monthly summaries
- Be precise about which month's activities support which claim

IMPORTANT:
- Do NOT use markdown formatting (no **, ##, bullets, numbered lists, or section headers)
- Do NOT include category labels like "Economic:" or "Diplomacy:" - just write the content
- Separate sections with blank lines
- Report directly on activities and developments without meta-commentary
- Provide executive-level strategic analysis with specific evidence"""

    user_prompt = f"""Relationship: {relationship_desc}
Period: {start_date.isoformat()} to {end_date.isoformat()} ({len(monthly_summaries)} months)

MONTHLY SUMMARIES (use Month numbers for citations):
{context_text}

Generate a comprehensive strategic assessment of the soft power activities with proper citations across this period."""

    try:
        summary_text = gai(system_prompt, user_prompt, model=model)

        # Aggregate metrics
        total_docs = sum(m['metrics']['total_documents'] for m in monthly_summaries)
        categories = defaultdict(int)
        recipients_count = defaultdict(int)
        sources = defaultdict(int)

        for monthly in monthly_summaries:
            for cat, count in monthly['metrics']['categories'].items():
                categories[cat] += count
            for rec, count in monthly['metrics']['recipients'].items():
                recipients_count[rec] += count
            for src, count in monthly['metrics']['sources'].items():
                sources[src] += count

        # Build citation reference list (full chain: overall → monthly → weekly → daily → docs)
        citations = []
        for i, monthly in enumerate(monthly_summaries, 1):
            month_name = datetime.fromisoformat(monthly['period_start']).strftime('%B %Y')
            citations.append({
                'citation_number': f"Month {i}",
                'month_name': month_name,
                'period_start': monthly['period_start'],
                'period_end': monthly['period_end'],
                'summary_excerpt': monthly['summary'][:200] + "...",
                'total_documents': monthly['metrics']['total_documents'],
                'weeks_covered': monthly['metrics'].get('weeks_covered', 0),
                'monthly_citations': monthly.get('citations', [])  # Include monthly citations for drill-down
            })

        result = {
            'period_start': start_date.isoformat(),
            'period_end': end_date.isoformat(),
            'influencer': influencer,
            'summary': summary_text,
            'citations': citations,  # NEW: Full citation chain overall → monthly → weekly → daily → docs
            'metrics': {
                'total_documents': total_docs,
                'categories': dict(sorted(categories.items(), key=lambda x: x[1], reverse=True)),
                'recipients': dict(sorted(recipients_count.items(), key=lambda x: x[1], reverse=True)),
                'sources': dict(sorted(sources.items(), key=lambda x: x[1], reverse=True)),
                'months_covered': len(monthly_summaries)
            },
            'generated_at': datetime.utcnow().isoformat()
        }

        if recipient:
            result['recipient'] = recipient

        return result

    except Exception as e:
        print(f"  ⚠️  Error generating overall summary: {e}")
        return None


def save_json(data: Dict, filepath: Path, quiet: bool = False):
    """Save data to JSON file with pretty formatting."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    if not quiet:
        print(f"  ✅ Saved: {filepath}")


def load_json(filepath: Path) -> Optional[Dict]:
    """Load data from JSON file."""
    if not filepath.exists():
        return None
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


def get_existing_daily_summaries(output_dir: Path, start_date: date, end_date: date) -> Dict[str, Dict]:
    """
    Load existing daily summaries from JSON files.

    Returns:
        Dict mapping date strings (YYYY-MM-DD) to summary dicts
    """
    daily_dir = output_dir / 'daily'
    if not daily_dir.exists():
        return {}

    existing = {}
    current_date = start_date
    while current_date <= end_date:
        date_str = current_date.isoformat()
        filepath = daily_dir / f"{date_str}.json"
        if filepath.exists():
            summary = load_json(filepath)
            if summary:
                existing[date_str] = summary
        current_date += timedelta(days=1)

    return existing


def load_daily_summaries_from_json(output_dir: Path, start_date: date, end_date: date) -> List[Dict]:
    """
    Load ALL daily summaries from JSON files for the date range.
    This is the ground truth for weekly generation.

    Returns:
        List of daily summary dicts, sorted by date
    """
    existing = get_existing_daily_summaries(output_dir, start_date, end_date)
    return [existing[d] for d in sorted(existing.keys())]


def load_weekly_summaries_from_json(output_dir: Path) -> List[Dict]:
    """
    Load ALL weekly summaries from JSON files.
    This is the ground truth for monthly generation.

    Returns:
        List of weekly summary dicts, sorted by period_start
    """
    weekly_dir = output_dir / 'weekly'
    if not weekly_dir.exists():
        return []

    summaries = []
    for filepath in sorted(weekly_dir.glob('*.json')):
        summary = load_json(filepath)
        if summary:
            summaries.append(summary)

    return sorted(summaries, key=lambda x: x['period_start'])


def load_monthly_summaries_from_json(output_dir: Path) -> List[Dict]:
    """
    Load ALL monthly summaries from JSON files.
    This is the ground truth for overall generation.

    Returns:
        List of monthly summary dicts, sorted by period_start
    """
    monthly_dir = output_dir / 'monthly'
    if not monthly_dir.exists():
        return []

    summaries = []
    for filepath in sorted(monthly_dir.glob('*.json')):
        summary = load_json(filepath)
        if summary:
            summaries.append(summary)

    return sorted(summaries, key=lambda x: x['period_start'])


def generate_bilateral_monthly_summary(
    session,
    influencer: str,
    recipient: str,
    month_start: date,
    month_end: date,
    category: Optional[str] = None,
    model: str = "gpt-4o-mini",
    valid_recipients: Optional[List[str]] = None,
    doc_threshold: int = 100
) -> Optional[Dict]:
    """
    Generate monthly summary for a specific bilateral relationship, optionally filtered by category.

    Uses ADAPTIVE HIERARCHICAL APPROACH:
    - If category-filtered data >= doc_threshold: Uses existing daily summaries (scalable)
    - If category-filtered data < doc_threshold: Uses documents directly (better quality for sparse data)

    Args:
        session: Database session
        influencer: Initiating country
        recipient: Recipient country
        month_start: Start of month
        month_end: End of month
        category: Optional category filter (Economic, Diplomacy, Social, Military)
        model: LLM model to use
        valid_recipients: List of valid recipient countries from config.yaml
        doc_threshold: Document count threshold for hierarchical vs document approach (default: 100)

    Returns:
        Dict with monthly bilateral summary or None if no documents
    """
    # STEP 1: Try loading existing daily summaries from JSON files (hierarchical approach)
    base_output_dir = Path('publications') / influencer / recipient / 'daily'

    use_hierarchical = False
    filtered_dailies = []
    total_docs_in_category = 0

    if base_output_dir.exists() and category:
        # Load daily summaries for this month
        existing_dailies = get_existing_daily_summaries(
            base_output_dir.parent,
            month_start,
            month_end
        )

        # Filter daily summaries by category (check if category appears in metrics)
        for date_str, daily in existing_dailies.items():
            category_count = daily.get('metrics', {}).get('categories', {}).get(category, 0)
            if category_count > 0:
                filtered_dailies.append(daily)
                total_docs_in_category += category_count

        # ADAPTIVE DECISION: Use hierarchical if we have enough data
        if total_docs_in_category >= doc_threshold:
            use_hierarchical = True
            print(f"  📊 Using hierarchical approach: {len(filtered_dailies)} daily summaries, {total_docs_in_category} documents in {category}")

    # STEP 2A: HIERARCHICAL APPROACH - Build from filtered daily summaries
    if use_hierarchical:
        # Build context from daily summaries filtered by category
        daily_contexts = []
        all_citations = []
        citation_counter = 1

        for daily in filtered_dailies:
            date_obj = datetime.fromisoformat(daily['date'])
            date_formatted = date_obj.strftime('%B %d, %Y')

            # Filter citations to only those with the target category
            category_citations = [
                c for c in daily.get('citations', [])
                if category in c.get('categories', [])
            ]

            # Build mini-summary of this day's category-specific activity
            daily_contexts.append(
                f"[Day {citation_counter}] {date_formatted}\n"
                f"    {category} Documents: {len(category_citations)}\n"
                f"    Summary Excerpt: {daily['summary'][:400]}...\n"
            )

            # Track citations for full traceability
            for cit in category_citations[:20]:  # Limit citations per day
                all_citations.append({
                    'citation_number': citation_counter,
                    'date': daily['date'],
                    'doc_id': cit.get('doc_id'),
                    'headline': cit.get('headline'),
                    'source_name': cit.get('source_name'),
                    'source_url': cit.get('source_url'),
                    'published_date': cit.get('published_date'),
                    'salience': cit.get('salience'),
                    'categories': cit.get('categories', []),
                    'recipients': cit.get('recipients', []),
                    'excerpt': cit.get('excerpt', '')[:500]
                })
                citation_counter += 1

        context_text = "\n\n".join(daily_contexts)
        docs = []  # Not needed for hierarchical approach

    # STEP 2B: DOCUMENT APPROACH - Get documents directly (fallback for sparse data)
    else:
        # Get all documents for this bilateral relationship in this month
        docs = []
        current_date = month_start
        while current_date <= month_end:
            day_docs = get_documents_for_day(
                session, influencer, current_date, recipient, valid_recipients
            )
            docs.extend(day_docs)
            current_date += timedelta(days=1)

        # Filter by category if specified
        if category:
            docs = [doc for doc in docs if category in doc.get('categories', [])]

        if not docs:
            return None

        # Now we have the actual document count
        if base_output_dir.exists() and total_docs_in_category > 0:
            print(f"  📄 Using document approach: {len(docs)} documents (below threshold of {doc_threshold})")
        else:
            print(f"  📄 Using document approach: {len(docs)} documents (no daily summaries available)")

        # Build context from documents
        doc_context = []
        for i, doc in enumerate(docs[:100], 1):  # Limit to top 100 docs
            categories_str = ", ".join(doc['categories']) if doc['categories'] else "None"
            doc_context.append(
                f"[{i}] {doc['title']}\n"
                f"    Date: {doc['date']}\n"
                f"    Categories: {categories_str}\n"
                f"    Salience: {doc['salience']}/100\n"
                f"    Excerpt: {doc['distilled_text'][:300] if doc['distilled_text'] else 'N/A'}..."
            )

        context_text = "\n\n".join(doc_context)
        all_citations = None  # Will be built from docs later

    # Adjust prompt based on category filter
    if category:
        scope_description = f"{category} activities"
        system_prompt = f"""You are a senior foreign policy analyst creating bilateral relationship assessments focused on {category} activities.

CRITICAL: You must cite your sources using numbered references [1], [2], etc. that correspond to the document numbers provided.

OUTPUT FORMAT (PLAIN TEXT PARAGRAPHS ONLY):
Write 3-4 focused paragraphs covering:
- Paragraph 1: Overview of {category} engagement between these countries this month
- Paragraph 2: Specific {category} initiatives, agreements, or activities
- Paragraph 3: Strategic significance and trajectory of {category} cooperation
- Paragraph 4: Notable trends or future outlook (if any)

CITATION REQUIREMENTS:
- After EVERY factual claim, add a citation like [1] or [1,2] for multiple sources
- Use the document numbers from the provided list
- Be precise about which document supports which claim

IMPORTANT:
- Do NOT use markdown formatting (no **, ##, bullets, numbered lists, or section headers)
- Do NOT include labels like "Overview:" or "Key Initiatives:"
- Write ONLY plain text paragraphs separated by blank lines
- Report directly on activities and developments without meta-commentary
- Focus exclusively on {category}-related engagement"""
    else:
        scope_description = "all activities"
        system_prompt = """You are a senior foreign policy analyst creating bilateral relationship assessments.

CRITICAL: You must cite your sources using numbered references [1], [2], etc. that correspond to the document numbers provided.

OUTPUT FORMAT (PLAIN TEXT PARAGRAPHS ONLY):
Write 4-5 comprehensive paragraphs covering:
- Paragraph 1: Overview of bilateral activities and engagement level this month
- Paragraph 2-3: Key initiatives and activities by category (Economic, Diplomacy, Social, Military)
- Paragraph 4: Strategic significance and trajectory of the relationship
- Paragraph 5: Notable trends or shifts (if any)

CITATION REQUIREMENTS:
- After EVERY factual claim, add a citation like [1] or [1,2] for multiple sources
- Use the document numbers from the provided list
- Be precise about which document supports which claim

IMPORTANT:
- Do NOT use markdown formatting (no **, ##, bullets, numbered lists, or section headers)
- Do NOT include labels like "Overview:" or "Key Initiatives:"
- Write ONLY plain text paragraphs separated by blank lines
- Report directly on activities and developments without meta-commentary
- Provide strategic-level analysis with specific examples"""

    # Build user prompt based on approach
    category_filter_text = f" ({category} only)" if category else ""

    if use_hierarchical:
        source_description = "DAILY SUMMARIES"
        total_count = total_docs_in_category
    else:
        source_description = "DOCUMENTS"
        total_count = len(docs)

    user_prompt = f"""Bilateral Relationship: {influencer} → {recipient}{category_filter_text}
Month: {month_start.strftime('%B %Y')}
Period: {month_start.isoformat()} to {month_end.isoformat()}
Total Documents: {total_count}

{source_description} (use these numbers for citations):
{context_text}

Generate a comprehensive bilateral monthly summary with proper citations."""

    try:
        summary_text = gai(system_prompt, user_prompt, model=model)

        # Calculate metrics and build citations based on approach
        categories = defaultdict(int)
        sources = defaultdict(int)
        citations = []

        if use_hierarchical:
            # Use pre-built citations from filtered daily summaries
            citations = all_citations

            # Calculate metrics from filtered dailies
            for daily in filtered_dailies:
                for cat, count in daily.get('metrics', {}).get('categories', {}).items():
                    if not category or cat == category:
                        categories[cat] += count
                for src, count in daily.get('metrics', {}).get('sources', {}).items():
                    sources[src] += count

            total_docs = total_docs_in_category
        else:
            # Build from documents
            for doc in docs:
                for cat in doc['categories']:
                    categories[cat] += 1
                if doc['source_name']:
                    sources[doc['source_name']] += 1

            # Build citations from documents
            for i, doc in enumerate(docs[:100], 1):
                citations.append({
                    'citation_number': i,
                    'doc_id': doc['doc_id'],
                    'headline': doc['title'],
                    'source_name': doc['source_name'],
                    'source_url': doc['source_url'],
                    'published_date': doc['date'],
                    'salience': doc['salience'],
                    'categories': doc['categories'],
                    'recipients': doc['recipients'],
                    'excerpt': doc['distilled_text'][:500] if doc['distilled_text'] else ""
                })

            total_docs = len(docs)

        result = {
            'period_start': month_start.isoformat(),
            'period_end': month_end.isoformat(),
            'month_name': month_start.strftime('%B %Y'),
            'influencer': influencer,
            'recipient': recipient,
            'summary': summary_text,
            'citations': citations,
            'metrics': {
                'total_documents': total_docs,
                'categories': dict(sorted(categories.items(), key=lambda x: x[1], reverse=True)),
                'sources': dict(sorted(sources.items(), key=lambda x: x[1], reverse=True))
            },
            'generated_at': datetime.utcnow().isoformat()
        }

        # Add doc_ids if available (from document approach)
        if docs:
            result['doc_ids'] = [d['doc_id'] for d in docs]

        # Add approach metadata for transparency
        result['generation_approach'] = 'hierarchical' if use_hierarchical else 'document'

        if category:
            result['category'] = category

        return result

    except Exception as e:
        print(f"  ⚠️  Error generating bilateral summary for {influencer} → {recipient} ({category or 'all'}): {e}")
        return None


def generate_bilateral_overall_summary(
    bilateral_monthly_summaries: List[Dict],
    start_date: date,
    end_date: date,
    influencer: str,
    model: str = "gpt-4o"
) -> Dict:
    """
    Generate overall summary across all bilateral relationships.

    Synthesizes monthly summaries from different recipient countries to provide
    a comprehensive view of the influencer's bilateral engagement strategy.
    """
    # Group by recipient
    by_recipient = defaultdict(list)
    for summary in bilateral_monthly_summaries:
        by_recipient[summary['recipient']].append(summary)

    # Build context organized by recipient
    recipient_contexts = []
    for recipient, summaries in sorted(by_recipient.items()):
        total_docs = sum(s['metrics']['total_documents'] for s in summaries)
        monthly_summaries_text = "\n".join([
            f"  {s['month_name']}: {s['summary'][:300]}..."
            for s in summaries
        ])

        recipient_contexts.append(
            f"RECIPIENT: {recipient}\n"
            f"Total Documents: {total_docs}\n"
            f"Months with Activity: {len(summaries)}\n"
            f"Monthly Summaries:\n{monthly_summaries_text}"
        )

    context_text = "\n\n---\n\n".join(recipient_contexts)

    # LLM prompt for cross-bilateral synthesis
    system_prompt = """You are a senior foreign policy strategist creating a comprehensive assessment of bilateral engagement strategy.

You are analyzing engagement across MULTIPLE recipient countries to identify patterns, priorities, and strategic approaches.

OUTPUT FORMAT (PLAIN TEXT PARAGRAPHS ORGANIZED BY CATEGORY):
Structure your summary as follows:

FIRST SECTION (1-2 paragraphs): Executive summary of overall bilateral engagement strategy and geographic priorities.

THEN ORGANIZE BY CATEGORY - Only include categories with significant activity. For each active category, write 1-2 focused paragraphs:

If Economic activities exist: Write about bilateral economic engagement patterns, trade initiatives, infrastructure projects across different recipients. Avoid content already covered in other categories.

If Diplomacy activities exist: Write about diplomatic engagement patterns, bilateral agreements, state visits across different recipients. Avoid content already covered in other categories.

If Social activities exist: Write about cultural and educational exchange patterns, media engagement across different recipients. Avoid content already covered in other categories.

If Military activities exist: Write about defense cooperation patterns, military sales, training programs across different recipients. Avoid content already covered in other categories.

FINAL SECTION (1-2 paragraphs): Strategic assessment of bilateral engagement approach, regional patterns, and implications.

DEDUPLICATION RULES:
- When activities span multiple categories, assign them to the MOST relevant category only
- Do not repeat the same activity or initiative in multiple category sections
- Focus on patterns across bilateral relationships, not individual relationships
- Each category section should contain ONLY content uniquely relevant to that category

IMPORTANT:
- Do NOT use markdown formatting (no **, ##, bullets, numbered lists, or section headers)
- Do NOT include category labels like "Economic:" or "Diplomacy:" - just write the content
- Separate sections with blank lines
- Report directly on activities and patterns without meta-commentary
- Identify which recipient countries receive the most attention in each category
- Highlight regional or strategic groupings of recipients"""

    user_prompt = f"""Influencer: {influencer}
Period: {start_date.isoformat()} to {end_date.isoformat()}
Recipient Countries: {len(by_recipient)}
Total Bilateral Summaries: {len(bilateral_monthly_summaries)}

BILATERAL SUMMARIES BY RECIPIENT:
{context_text}

Generate a comprehensive cross-bilateral strategic assessment synthesizing these bilateral relationships."""

    try:
        summary_text = gai(system_prompt, user_prompt, model=model)

        # Aggregate metrics across all bilateral relationships
        total_docs = sum(s['metrics']['total_documents'] for s in bilateral_monthly_summaries)
        categories = defaultdict(int)
        sources = defaultdict(int)
        recipients_docs = defaultdict(int)

        for summary in bilateral_monthly_summaries:
            for cat, count in summary['metrics']['categories'].items():
                categories[cat] += count
            for src, count in summary['metrics']['sources'].items():
                sources[src] += count
            recipients_docs[summary['recipient']] += summary['metrics']['total_documents']

        return {
            'period_start': start_date.isoformat(),
            'period_end': end_date.isoformat(),
            'influencer': influencer,
            'summary': summary_text,
            'metrics': {
                'total_documents': total_docs,
                'total_recipients': len(by_recipient),
                'categories': dict(sorted(categories.items(), key=lambda x: x[1], reverse=True)),
                'recipients': dict(sorted(recipients_docs.items(), key=lambda x: x[1], reverse=True)),
                'sources': dict(sorted(sources.items(), key=lambda x: x[1], reverse=True)),
                'months_covered': len(set(s['month_name'] for s in bilateral_monthly_summaries))
            },
            'recipient_breakdown': {
                recipient: {
                    'total_documents': sum(s['metrics']['total_documents'] for s in summaries),
                    'months_with_activity': len(summaries)
                }
                for recipient, summaries in by_recipient.items()
            },
            'generated_at': datetime.utcnow().isoformat()
        }

    except Exception as e:
        print(f"  ⚠️  Error generating bilateral overall summary: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(
        description="Generate hierarchical summaries from documents for bilateral relationships",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument('--influencer', required=True, help='Influencer country to analyze (initiating country)')
    parser.add_argument('--recipient', help='Optional recipient country for bilateral analysis (omit for all recipients)')
    parser.add_argument('--start-date', required=True, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', required=True, help='End date (YYYY-MM-DD)')
    parser.add_argument('--output-dir', default='./publications', help='Output directory for JSON files')
    parser.add_argument('--daily-only', action='store_true', help='Generate only daily summaries')
    parser.add_argument('--bilateral-only', action='store_true', help='Generate only bilateral summaries (monthly per recipient + overall)')
    parser.add_argument('--from-weekly', action='store_true', help='Skip daily generation, start from weekly (reads daily JSON)')
    parser.add_argument('--from-monthly', action='store_true', help='Skip daily/weekly, start from monthly (reads weekly JSON)')
    parser.add_argument('--from-overall', action='store_true', help='Skip all, generate only overall (reads monthly JSON)')
    parser.add_argument('--force', action='store_true', help='Force regeneration of all summaries (ignore existing)')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be generated without generating')
    parser.add_argument('--model-daily', default='gpt-4o-mini', help='Model for daily summaries (default: gpt-4o-mini)')
    parser.add_argument('--model-monthly', default='gpt-4o', help='Model for monthly+ summaries (default: gpt-4o)')

    args = parser.parse_args()

    # Load config for validation
    # Go up to project root: publications/scripts/ -> publications/ -> app/
    config_path = Path(__file__).parent.parent.parent / 'shared' / 'config' / 'config.yaml'
    config = Config.from_yaml(config_path)

    # Validate influencer
    valid_influencers = getattr(config, 'influencers', [])
    if args.influencer not in valid_influencers:
        print(f"Error: Invalid influencer '{args.influencer}'")
        print(f"Valid influencers: {', '.join(valid_influencers)}")
        sys.exit(1)

    # Load valid recipients from config
    valid_recipients = getattr(config, 'recipients', [])

    # Validate recipient if specified
    if args.recipient:
        if args.recipient not in valid_recipients:
            print(f"Error: Invalid recipient '{args.recipient}'")
            print(f"Valid recipients: {', '.join(valid_recipients)}")
            sys.exit(1)

    # Parse dates
    try:
        start_date = parse_date(args.start_date)
        end_date = parse_date(args.end_date)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    if start_date > end_date:
        print("Error: start-date must be before or equal to end-date")
        sys.exit(1)

    # Build output directory path (nested by influencer and optionally recipient)
    base_output_dir = Path(args.output_dir)
    if args.recipient:
        # Bilateral: output_dir/influencer/recipient/
        output_dir = base_output_dir / args.influencer / args.recipient
        relationship_desc = f"{args.influencer} → {args.recipient}"
    else:
        # All recipients: output_dir/influencer/
        output_dir = base_output_dir / args.influencer
        relationship_desc = f"{args.influencer} (all recipients)"

    print("=" * 100)
    print("DOCUMENT-BASED HIERARCHICAL SUMMARY GENERATOR")
    print("=" * 100)
    print(f"Relationship: {relationship_desc}")
    print(f"Period: {start_date} to {end_date}")
    print(f"Output: {output_dir}")
    print(f"Dry Run: {args.dry_run}")
    print(f"Force: {args.force}")
    print("=" * 100)
    print()

    with get_session() as session:
        # STEP 1: Generate Daily Summaries
        if not args.from_weekly and not args.from_monthly and not args.from_overall and not args.bilateral_only:
            print("STEP 1: Generating Daily Summaries")
            print("-" * 100)

            # Check for existing summaries (unless --force)
            existing_daily = {}
            if not args.force and not args.dry_run:
                existing_daily = get_existing_daily_summaries(output_dir, start_date, end_date)
                if existing_daily:
                    print(f"📁 Found {len(existing_daily)} existing daily summaries")
                    latest_date = max(existing_daily.keys())
                    print(f"📅 Latest: {latest_date}")
                    print(f"🔄 Resuming from next day...")
                    print()

            generated_count = 0
            skipped_count = 0
            current_date = start_date

            while current_date <= end_date:
                date_str = current_date.isoformat()

                # Skip if already exists (unless --force)
                if not args.force and date_str in existing_daily:
                    if skipped_count == 0:  # Only print first skip
                        print(f"  {current_date}: ⏭️  Exists (use --force to regenerate)")
                    skipped_count += 1
                    current_date += timedelta(days=1)
                    continue

                if args.dry_run:
                    # Just check for documents
                    docs = get_documents_for_day(
                        session, args.influencer, current_date,
                        args.recipient, valid_recipients
                    )
                    if docs:
                        print(f"  {current_date}: {len(docs)} documents (would generate summary)")
                    else:
                        print(f"  {current_date}: 0 documents (skip)")
                else:
                    print(f"  {current_date}: ", end='', flush=True)
                    summary = generate_daily_summary(
                        session, args.influencer, current_date,
                        model=args.model_daily,
                        recipient=args.recipient,
                        valid_recipients=valid_recipients
                    )
                    if summary:
                        save_json(summary, output_dir / 'daily' / f"{date_str}.json")
                        print(f"{summary['metrics']['total_documents']} documents")
                        generated_count += 1
                    else:
                        print("No documents")

                current_date += timedelta(days=1)

            if skipped_count > 1:  # If we skipped more than just the first
                print(f"  ... (skipped {skipped_count} existing summaries)")

            print(f"\n✅ Generated {generated_count} new daily summaries")
            if skipped_count > 0:
                print(f"⏭️  Skipped {skipped_count} existing summaries")
            print()

            if args.daily_only or args.dry_run:
                print("Stopping after daily summaries (--daily-only or --dry-run)")
                return
        else:
            print("STEP 1: Skipping daily generation (using existing JSON)")
            print("-" * 100)

        # STEP 2: Generate Weekly Summaries (from JSON)
        if not args.from_monthly and not args.from_overall and not args.bilateral_only:
            print("STEP 2: Generating Weekly Summaries")
            print("-" * 100)

            # Load daily summaries from JSON (ground truth)
            print(f"📁 Loading daily summaries from {output_dir / 'daily'}...")
            all_daily_summaries = load_daily_summaries_from_json(output_dir, start_date, end_date)

            if not all_daily_summaries:
                print("❌ No daily summaries found. Run without --from-weekly first.")
                return

            print(f"✅ Loaded {len(all_daily_summaries)} daily summaries")
            print()

            weekly_summaries = []
            week_start = start_date - timedelta(days=start_date.weekday())  # Start from Monday

            while week_start <= end_date:
                week_end = week_start + timedelta(days=6)

                # Get daily summaries for this week from loaded JSON
                week_dailies = [
                    d for d in all_daily_summaries
                    if week_start <= datetime.fromisoformat(d['date']).date() <= week_end
                ]

                if week_dailies:
                    print(f"  Week {week_start} to {week_end}: ", end='', flush=True)
                    summary = generate_weekly_summary(
                        week_dailies, week_start, week_end, args.influencer,
                        model=args.model_daily,
                        recipient=args.recipient
                    )
                    if summary:
                        weekly_summaries.append(summary)
                        save_json(summary, output_dir / 'weekly' / f"{week_start.isoformat()}_to_{week_end.isoformat()}.json")
                        print(f"{len(week_dailies)} days")

                week_start += timedelta(days=7)

            print(f"\n✅ Generated {len(weekly_summaries)} weekly summaries")
            print()
        else:
            print("STEP 2: Skipping weekly generation (using existing JSON)")
            print("-" * 100)

        # STEP 3: Generate Monthly Summaries (from JSON)
        if not args.from_overall and not args.bilateral_only:
            print("STEP 3: Generating Monthly Summaries")
            print("-" * 100)

            # Load weekly summaries from JSON (ground truth)
            print(f"📁 Loading weekly summaries from {output_dir / 'weekly'}...")
            all_weekly_summaries = load_weekly_summaries_from_json(output_dir)

            if not all_weekly_summaries:
                print("❌ No weekly summaries found. Run without --from-monthly first.")
                return

            print(f"✅ Loaded {len(all_weekly_summaries)} weekly summaries")
            print()

            monthly_summaries = []
            current_month = start_date.replace(day=1)

            while current_month <= end_date:
                # Get last day of month
                if current_month.month == 12:
                    next_month = current_month.replace(year=current_month.year + 1, month=1)
                else:
                    next_month = current_month.replace(month=current_month.month + 1)

                month_end = next_month - timedelta(days=1)

                # Get weekly summaries for this month from loaded JSON
                month_weeklies = [
                    w for w in all_weekly_summaries
                    if current_month <= datetime.fromisoformat(w['period_start']).date() <= month_end
                ]

                if month_weeklies:
                    print(f"  {current_month.strftime('%B %Y')}: ", end='', flush=True)
                    summary = generate_monthly_summary(
                        month_weeklies, current_month, month_end, args.influencer,
                        model=args.model_monthly,
                        recipient=args.recipient
                    )
                    if summary:
                        monthly_summaries.append(summary)
                        save_json(summary, output_dir / 'monthly' / f"{current_month.strftime('%Y-%m')}.json")
                        print(f"{len(month_weeklies)} weeks")

                # Move to next month
                current_month = next_month

            print(f"\n✅ Generated {len(monthly_summaries)} monthly summaries")
            print()
        else:
            print("STEP 3: Skipping monthly generation (using existing JSON)")
            print("-" * 100)

        # STEP 4: Generate Overall Summary (from JSON)
        if not args.bilateral_only:
            print("STEP 4: Generating Overall Summary")
            print("-" * 100)

            # Load monthly summaries from JSON (ground truth)
            print(f"📁 Loading monthly summaries from {output_dir / 'monthly'}...")
            all_monthly_summaries = load_monthly_summaries_from_json(output_dir)

            if not all_monthly_summaries:
                print("❌ No monthly summaries found. Run without --from-overall first.")
                return

            print(f"✅ Loaded {len(all_monthly_summaries)} monthly summaries")
            print()

            print(f"  Period {start_date} to {end_date}: ", end='', flush=True)
            overall = generate_overall_summary(
                all_monthly_summaries, start_date, end_date, args.influencer,
                model=args.model_monthly,
                recipient=args.recipient
            )
            if overall:
                save_json(overall, output_dir / f"overall_{start_date.isoformat()}_to_{end_date.isoformat()}.json")
                print(f"{len(all_monthly_summaries)} months")
                print()
                print("✅ Generated overall summary")

            print()
        else:
            print("STEP 4: Skipping overall summary generation (--bilateral-only)")
            print("-" * 100)
            print()

        # STEP 5: Generate Bilateral Summaries (if --bilateral-only or no recipient specified)
        if args.bilateral_only or (not args.recipient and not args.daily_only):
            print("=" * 100)
            print("STEP 5: Generating Bilateral Summaries by Category")
            print("=" * 100)

            # Only generate bilateral summaries when analyzing all recipients
            if args.recipient:
                print("⏭️  Skipping bilateral generation (recipient filter specified)")
            else:
                bilateral_output_dir = base_output_dir / args.influencer / "bilateral"

                # Categories to analyze
                categories = ['Economic', 'Diplomacy', 'Social', 'Military']

                # Get all recipients from config
                print(f"Recipients to analyze: {', '.join(valid_recipients)}")
                print()

                all_bilateral_summaries = []

                # Iterate through each month in the date range
                current_month = date(start_date.year, start_date.month, 1)

                while current_month <= end_date:
                    # Get last day of month
                    if current_month.month == 12:
                        next_month = date(current_month.year + 1, 1, 1)
                    else:
                        next_month = date(current_month.year, current_month.month + 1, 1)
                    month_end = next_month - timedelta(days=1)

                    # Don't go past end_date
                    if month_end > end_date:
                        month_end = end_date

                    month_str = current_month.strftime('%Y-%m')
                    print(f"\n📅 Processing {current_month.strftime('%B %Y')}")
                    print("-" * 80)

                    # For each recipient country
                    for recipient in valid_recipients:
                        print(f"  {args.influencer} → {recipient}:")

                        # Generate category-specific summaries
                        for category in categories:
                            filename = f"{recipient}-{category}_{month_str}.json"
                            filepath = bilateral_output_dir / filename

                            # Skip if exists and not forcing
                            if filepath.exists() and not args.force:
                                print(f"    • {category}: ⏭️  Exists")
                                continue

                            summary = generate_bilateral_monthly_summary(
                                session, args.influencer, recipient,
                                current_month, month_end,
                                category=category,
                                model=args.model_daily,
                                valid_recipients=valid_recipients
                            )

                            if summary:
                                save_json(summary, filepath, quiet=True)
                                all_bilateral_summaries.append(summary)
                                print(f"    • {category}: ✅ {summary['metrics']['total_documents']} docs")
                            else:
                                print(f"    • {category}: ⏭️  No docs")

                        # Generate combined summary (all categories)
                        combined_filename = f"{recipient}_{month_str}.json"
                        combined_filepath = bilateral_output_dir / combined_filename

                        if combined_filepath.exists() and not args.force:
                            print(f"    • All Categories: ⏭️  Exists")
                        else:
                            combined_summary = generate_bilateral_monthly_summary(
                                session, args.influencer, recipient,
                                current_month, month_end,
                                category=None,  # All categories
                                model=args.model_daily,
                                valid_recipients=valid_recipients
                            )

                            if combined_summary:
                                save_json(combined_summary, combined_filepath, quiet=True)
                                print(f"    • All Categories: ✅ {combined_summary['metrics']['total_documents']} docs")
                            else:
                                print(f"    • All Categories: ⏭️  No docs")

                    # Move to next month
                    current_month = next_month

                print()
                print("=" * 100)
                print("Generating Bilateral Overall Rollup (across all recipients)")
                print("=" * 100)

                # Generate overall rollup across all bilateral relationships
                if all_bilateral_summaries:
                    overall_bilateral = generate_bilateral_overall_summary(
                        all_bilateral_summaries,
                        start_date, end_date, args.influencer,
                        model=args.model_monthly
                    )

                    if overall_bilateral:
                        overall_filename = f"overall_{start_date.isoformat()}_to_{end_date.isoformat()}.json"
                        save_json(overall_bilateral, bilateral_output_dir / overall_filename)
                        print(f"✅ Generated bilateral overall rollup ({overall_bilateral['metrics']['total_recipients']} recipients)")
                else:
                    print("⚠️  No bilateral summaries to roll up")

                print()

        print("=" * 100)
        print("SUMMARY COMPLETE")
        print("=" * 100)

        # Count existing files for final summary
        daily_count = len(list((output_dir / 'daily').glob('*.json'))) if (output_dir / 'daily').exists() else 0
        weekly_count = len(list((output_dir / 'weekly').glob('*.json'))) if (output_dir / 'weekly').exists() else 0
        monthly_count = len(list((output_dir / 'monthly').glob('*.json'))) if (output_dir / 'monthly').exists() else 0
        overall_count = 1 if (output_dir / f"overall_{start_date.isoformat()}_to_{end_date.isoformat()}.json").exists() else 0
        bilateral_count = len(list((base_output_dir / args.influencer / 'bilateral').glob('*.json'))) if (base_output_dir / args.influencer / 'bilateral').exists() else 0

        print(f"Daily summaries: {daily_count}")
        print(f"Weekly summaries: {weekly_count}")
        print(f"Monthly summaries: {monthly_count}")
        print(f"Overall summary: {overall_count}")
        print(f"Bilateral summaries: {bilateral_count}")
        print()
        print(f"Output directory: {output_dir.absolute()}")


if __name__ == "__main__":
    main()
