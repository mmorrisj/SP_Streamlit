"""
Citation and hyperlink utilities for source-traceable summaries.

Provides functions to:
- Generate ATOM search hyperlinks from doc_ids
- Create formatted citations for documents
- Prepare reviewer versions with citations
"""

from typing import List, Dict, Tuple
from shared.database.database import get_session
from shared.models.models import Document
from sqlalchemy import select


def build_hyperlink(doc_ids: List[str]) -> str:
    """
    Constructs a hyperlink to ATOM search with given document IDs.

    Args:
        doc_ids: List of document IDs to include in search query

    Returns:
        Formatted ATOM search URL

    Example:
        >>> build_hyperlink(['doc123', 'doc456'])
        'https://atom.opensource.gov/searches?ss=id%3A(%22doc123%22+OR+%22doc456%22)&go=1'
    """
    if not doc_ids:
        return ""

    # Enclose each ID in double quotes and join with '+OR+'
    quoted_ids = [f'%22{doc_id}%22' for doc_id in doc_ids]
    ids_query = '+OR+'.join(quoted_ids)

    link = f"https://atom.opensource.gov/searches?ss=id%3A({ids_query})&go=1"
    return link


def get_citation_data(session, doc_id: str) -> Tuple[str, str, str, str]:
    """
    Retrieve citation metadata for a document.

    Args:
        session: SQLAlchemy session
        doc_id: Document ID

    Returns:
        Tuple of (source_name, doc_id, title, formatted_date)

    Example:
        >>> data = get_citation_data(session, 'doc123')
        >>> data
        ('Reuters', 'doc123', 'Iran Opens Border Crossings', '15 August 2024')
    """
    stmt = select(
        Document.source_name,
        Document.doc_id,
        Document.title,
        Document.date
    ).where(Document.doc_id == doc_id)

    result = session.execute(stmt).first()

    if not result:
        return ("Unknown Source", doc_id, "Title Not Available", "Date Unknown")

    source_name, doc_id, title, date = result

    # Format date as "DD Month YYYY"
    if date:
        formatted_date = date.strftime('%d %B %Y')
    else:
        formatted_date = "Date Unknown"

    return (
        source_name or "Unknown Source",
        doc_id,
        title or "Title Not Available",
        formatted_date
    )


def create_citation(citation_data: Tuple[str, str, str, str]) -> str:
    """
    Create formatted citation string from citation data.

    Args:
        citation_data: Tuple of (source_name, doc_id, title, formatted_date)

    Returns:
        Formatted citation string

    Example:
        >>> data = ('Reuters', 'doc123', 'Iran Opens Border Crossings', '15 August 2024')
        >>> create_citation(data)
        '[Reuters | ATOM ID: doc123 | Iran Opens Border Crossings | 15 August 2024]'
    """
    source_name, doc_id, title, formatted_date = citation_data
    citation = f'[{source_name} | ATOM ID: {doc_id} | {title} | {formatted_date}]'
    return citation


def get_citations_for_doc_ids(doc_ids: List[str]) -> List[Dict[str, str]]:
    """
    Get formatted citations for a list of document IDs.

    Args:
        doc_ids: List of document IDs

    Returns:
        List of citation dictionaries with 'doc_id' and 'citation' keys

    Example:
        >>> citations = get_citations_for_doc_ids(['doc123', 'doc456'])
        >>> citations[0]
        {
            'doc_id': 'doc123',
            'citation': '[Reuters | ATOM ID: doc123 | Iran Opens... | 15 August 2024]',
            'source_name': 'Reuters',
            'title': 'Iran Opens Border Crossings',
            'date': '15 August 2024'
        }
    """
    citations = []

    with get_session() as session:
        for doc_id in doc_ids:
            citation_data = get_citation_data(session, doc_id)
            citation_str = create_citation(citation_data)

            citations.append({
                'doc_id': doc_id,
                'citation': citation_str,
                'source_name': citation_data[0],
                'title': citation_data[2],
                'date': citation_data[3]
            })

    return citations


def format_reviewer_section(
    overview: str,
    outcomes: str,
    doc_ids: List[str],
    include_hyperlink: bool = True,
    include_citations: bool = True
) -> str:
    """
    Format a reviewer-friendly section with summary, hyperlink, and citations.

    Args:
        overview: Overview paragraph text
        outcomes: Outcomes paragraph text
        doc_ids: List of document IDs supporting this summary
        include_hyperlink: Whether to include ATOM search hyperlink
        include_citations: Whether to include full citation list

    Returns:
        Formatted markdown string for reviewer display

    Example output:
        **Overview:**
        Iran opened three border crossings...

        **Outcomes:**
        Iraqi officials thanked Iran...

        **Sources (89 articles):**
        🔗 [View in ATOM](https://atom.opensource.gov/searches?ss=...)

        **Citations:**
        - [Reuters | ATOM ID: doc123 | Iran Opens... | 15 August 2024]
        - [AP News | ATOM ID: doc456 | Border Crossing... | 15 August 2024]
        ...

        **Document IDs:**
        doc123, doc456, doc789, ...
    """
    sections = []

    # Overview
    sections.append("**Overview:**")
    sections.append(overview)
    sections.append("")

    # Outcomes
    sections.append("**Outcomes:**")
    sections.append(outcomes)
    sections.append("")

    # Sources header
    sections.append(f"**Sources ({len(doc_ids)} articles):**")

    # Hyperlink
    if include_hyperlink and doc_ids:
        hyperlink = build_hyperlink(doc_ids)
        sections.append(f"🔗 [View in ATOM]({hyperlink})")
        sections.append("")

    # Citations
    if include_citations and doc_ids:
        sections.append("**Citations:**")
        citations = get_citations_for_doc_ids(doc_ids)

        # Show first 10 citations, then summarize rest
        for citation in citations[:10]:
            sections.append(f"- {citation['citation']}")

        if len(citations) > 10:
            sections.append(f"- ... and {len(citations) - 10} more articles")

        sections.append("")

    # Document IDs list
    sections.append("**Document IDs:**")
    # Format as comma-separated list, with line breaks every 5 IDs for readability
    id_chunks = [doc_ids[i:i+5] for i in range(0, len(doc_ids), 5)]
    for chunk in id_chunks:
        sections.append(", ".join(chunk) + ("," if chunk != id_chunks[-1] else ""))

    return "\n".join(sections)


def prepare_summary_with_sources(
    event_summary_id: str,
    include_hyperlink: bool = True,
    include_citations: bool = True,
    citation_limit: int = 10
) -> Dict:
    """
    Prepare complete summary with sources for display or export.

    Args:
        event_summary_id: ID of EventSummary record
        include_hyperlink: Include ATOM search hyperlink
        include_citations: Include formatted citations
        citation_limit: Maximum number of citations to include

    Returns:
        Dictionary with summary data and formatted sources

    Example:
        >>> summary = prepare_summary_with_sources('uuid-123')
        >>> summary.keys()
        dict_keys(['event_name', 'overview', 'outcomes', 'source_link',
                   'citations', 'doc_ids', 'reviewer_markdown'])
    """
    from shared.models.models import EventSummary, EventSourceLink

    with get_session() as session:
        # Get summary
        summary = session.get(EventSummary, event_summary_id)
        if not summary:
            return None

        # Get all source doc_ids
        source_links = session.query(EventSourceLink).filter(
            EventSourceLink.event_summary_id == event_summary_id
        ).order_by(EventSourceLink.contribution_weight.desc()).all()

        doc_ids = [link.doc_id for link in source_links]

        # Get narrative content
        narrative = summary.narrative_summary or {}
        overview = narrative.get('overview', '')
        outcomes = narrative.get('outcomes', '')

        # Build hyperlink
        source_link = build_hyperlink(doc_ids) if include_hyperlink else None

        # Get citations
        citations = []
        if include_citations:
            citations = get_citations_for_doc_ids(doc_ids[:citation_limit])

        # Format reviewer markdown
        reviewer_markdown = format_reviewer_section(
            overview=overview,
            outcomes=outcomes,
            doc_ids=doc_ids,
            include_hyperlink=include_hyperlink,
            include_citations=include_citations
        )

        return {
            'event_name': summary.event_name,
            'initiating_country': summary.initiating_country,
            'period_type': summary.period_type.value,
            'period_start': str(summary.period_start),
            'period_end': str(summary.period_end),
            'overview': overview,
            'outcomes': outcomes,
            'source_link': source_link,
            'citations': citations,
            'doc_ids': doc_ids,
            'source_count': len(doc_ids),
            'reviewer_markdown': reviewer_markdown
        }
