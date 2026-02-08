"""
Report Validation Service

Validates that LLM-generated narratives in reports are properly supported by their cited sources.
Uses a second LLM pass to fact-check claims against source documents.
"""

import re
import json
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Generator
from datetime import datetime

from shared.database.database import get_session
from shared.models.models import Document
from shared.utils.utils import gai


class ValidationStatus(Enum):
    GREEN = "green"    # All claims verified, sources accurate
    YELLOW = "yellow"  # Some sourcing concerns but generally supported
    RED = "red"        # Major claims unsupported or sources inaccurate
    PENDING = "pending"


@dataclass
class ClaimValidation:
    """Validation result for an individual claim."""
    claim_text: str
    cited_sources: List[int]
    is_supported: bool
    confidence: float
    issues: List[str] = field(default_factory=list)


@dataclass
class SectionValidation:
    """Validation result for a section (event, category, or entity)."""
    section_type: str  # "overall_summary", "category", "event", "entity"
    section_id: str    # e.g., "category:Economic", "event:Economic:0"
    status: str        # ValidationStatus value
    claims_validated: int
    uncited_claims: int
    issues: List[str] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "section_type": self.section_type,
            "section_id": self.section_id,
            "status": self.status,
            "claims_validated": self.claims_validated,
            "uncited_claims": self.uncited_claims,
            "issues": self.issues,
            "summary": self.summary
        }


def extract_citations(text: str) -> List[int]:
    """
    Extract citation numbers from text like [1], [2], [1,2,3], [1, 2].

    Args:
        text: Narrative text containing inline citations

    Returns:
        List of unique citation numbers found
    """
    if not text:
        return []

    citations = set()

    # Match patterns like [1], [2], [1,2,3], [1, 2, 3]
    pattern = r'\[(\d+(?:\s*,\s*\d+)*)\]'
    matches = re.findall(pattern, text)

    for match in matches:
        # Split on comma and extract individual numbers
        nums = re.findall(r'\d+', match)
        citations.update(int(n) for n in nums)

    return sorted(citations)


def extract_claims(text: str) -> List[Dict[str, Any]]:
    """
    Split narrative text into individual claims with their citations.

    Args:
        text: Narrative text to split into claims

    Returns:
        List of dicts with 'claim' text and 'citations' list
    """
    if not text:
        return []

    claims = []

    # Split on sentence boundaries (. ! ?)
    # But keep citations attached to their preceding sentence
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        # Extract citations from this sentence
        citations = extract_citations(sentence)

        # Remove citation markers to get clean claim text
        clean_claim = re.sub(r'\s*\[\d+(?:\s*,\s*\d+)*\]', '', sentence).strip()

        if clean_claim:
            claims.append({
                'claim': clean_claim,
                'citations': citations
            })

    return claims


def get_source_content(session, doc_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """
    Fetch document content for the given doc_ids.

    Args:
        session: Database session
        doc_ids: List of document IDs to fetch

    Returns:
        Dict mapping doc_id to document content and metadata
    """
    if not doc_ids:
        return {}

    docs = session.query(Document).filter(Document.doc_id.in_(doc_ids)).all()

    result = {}
    for doc in docs:
        result[doc.doc_id] = {
            'doc_id': doc.doc_id,
            'title': doc.title,
            'source_name': doc.source_name,
            'date': str(doc.date) if doc.date else None,
            'content': doc.distilled_text or '',
            'category': doc.category,
            'initiating_country': doc.initiating_country,
            'recipient_country': doc.recipient_country
        }

    return result


def validate_claim_against_sources(
    claim: str,
    sources: List[Dict[str, Any]],
    model: str = "gpt-4o-mini"
) -> ClaimValidation:
    """
    Use LLM to verify if a claim is supported by the provided source documents.

    Args:
        claim: The factual claim to verify
        sources: List of source documents with content
        model: LLM model to use

    Returns:
        ClaimValidation result
    """
    if not sources:
        return ClaimValidation(
            claim_text=claim,
            cited_sources=[],
            is_supported=False,
            confidence=0.0,
            issues=["No source documents provided for verification"]
        )

    # Build source context
    source_lines = []
    citation_nums = []
    for src in sources:
        cnum = src.get('citation_number', 0)
        citation_nums.append(cnum)
        content_snippet = (src.get('content') or '')[:1500]
        source_lines.append(
            f"[{cnum}] {src.get('headline', src.get('title', 'Untitled'))} — "
            f"{src.get('source_name', 'Unknown')}, {src.get('date', src.get('published_date', 'n.d.'))}\n"
            f"Content: {content_snippet}"
        )

    sources_text = "\n\n".join(source_lines)

    sys_prompt = """You are a fact-checker evaluating whether claims are supported by source documents.

Your task: Determine if the CLAIM is supported by the SOURCE DOCUMENTS.

Respond with JSON only:
{
  "is_supported": true/false,
  "confidence": 0.0-1.0,
  "issues": ["list of specific concerns if any"]
}

Rules:
- A claim is "supported" if the essential facts are present in the sources
- Minor wording differences are acceptable
- Flag if the claim makes inferences not directly stated in sources
- Flag if the claim contradicts information in sources
- Flag if the cited source doesn't contain relevant information for this claim
- Confidence should reflect how well the sources support the claim:
  - 0.9-1.0: Direct quote or very close paraphrase
  - 0.7-0.9: Facts clearly present, minor interpretation
  - 0.5-0.7: Partial support, some facts present
  - 0.0-0.5: Weak or no support"""

    user_prompt = f"""CLAIM: "{claim}"

SOURCE DOCUMENTS:
{sources_text}

Evaluate whether this claim is supported by the sources."""

    try:
        response = gai(sys_prompt, user_prompt, model=model)

        if isinstance(response, dict):
            return ClaimValidation(
                claim_text=claim,
                cited_sources=citation_nums,
                is_supported=response.get('is_supported', False),
                confidence=float(response.get('confidence', 0.0)),
                issues=response.get('issues', [])
            )

        # Try to parse string response
        if isinstance(response, str):
            response_str = response.strip()
            if response_str.startswith("```json"):
                response_str = response_str[7:]
            if response_str.endswith("```"):
                response_str = response_str[:-3]

            parsed = json.loads(response_str.strip())
            return ClaimValidation(
                claim_text=claim,
                cited_sources=citation_nums,
                is_supported=parsed.get('is_supported', False),
                confidence=float(parsed.get('confidence', 0.0)),
                issues=parsed.get('issues', [])
            )

    except Exception as e:
        return ClaimValidation(
            claim_text=claim,
            cited_sources=citation_nums,
            is_supported=False,
            confidence=0.0,
            issues=[f"Validation error: {str(e)}"]
        )

    return ClaimValidation(
        claim_text=claim,
        cited_sources=citation_nums,
        is_supported=False,
        confidence=0.0,
        issues=["Could not parse validation response"]
    )


def determine_status(
    claims: List[ClaimValidation],
    uncited_claims: List[str],
    section_type: str = "event"
) -> ValidationStatus:
    """
    Determine overall validation status based on claim results.

    Args:
        claims: List of validated claims
        uncited_claims: List of claims without citations
        section_type: Type of section (affects thresholds)

    Returns:
        ValidationStatus enum value
    """
    if not claims and not uncited_claims:
        return ValidationStatus.GREEN

    # Get thresholds based on section type
    if section_type == "entity":
        min_confidence = 0.6
        allow_uncited_ratio = 0.5
        yellow_threshold = 2
        red_threshold = 3
    else:
        min_confidence = 0.75
        allow_uncited_ratio = 0.1
        yellow_threshold = 1
        red_threshold = 2

    # Count issues
    unsupported_count = sum(1 for c in claims if not c.is_supported)
    low_confidence_count = sum(1 for c in claims if c.confidence < min_confidence)
    total_claims = len(claims) + len(uncited_claims)
    uncited_ratio = len(uncited_claims) / total_claims if total_claims > 0 else 0

    # Determine status
    if unsupported_count >= red_threshold or uncited_ratio > 0.5:
        return ValidationStatus.RED

    if unsupported_count >= yellow_threshold or uncited_ratio > allow_uncited_ratio or low_confidence_count >= 2:
        return ValidationStatus.YELLOW

    return ValidationStatus.GREEN


def validate_section(
    text: str,
    citations_data: List[Dict[str, Any]],
    section_type: str,
    section_id: str,
    model: str = "gpt-4o-mini"
) -> SectionValidation:
    """
    Validate a single section of the report.

    Args:
        text: The narrative text to validate
        citations_data: List of citation objects with doc metadata
        section_type: Type of section (overall_summary, category, event, entity)
        section_id: Unique identifier for the section
        model: LLM model to use

    Returns:
        SectionValidation result
    """
    if not text:
        return SectionValidation(
            section_type=section_type,
            section_id=section_id,
            status=ValidationStatus.GREEN.value,
            claims_validated=0,
            uncited_claims=0,
            summary="No content to validate"
        )

    # Build citation number to doc mapping
    citation_map = {}
    for cit in citations_data:
        cnum = cit.get('citation_number')
        if cnum:
            citation_map[cnum] = cit

    # Extract claims from text
    claims = extract_claims(text)

    validated_claims = []
    uncited_claims = []
    all_issues = []

    # Get document content for validation
    with get_session() as session:
        all_doc_ids = [c.get('doc_id') for c in citations_data if c.get('doc_id')]
        doc_contents = get_source_content(session, all_doc_ids)

    for claim_data in claims:
        claim_text = claim_data['claim']
        cited_nums = claim_data['citations']

        if not cited_nums:
            uncited_claims.append(claim_text)
            continue

        # Build source list for this claim
        sources = []
        for cnum in cited_nums:
            if cnum in citation_map:
                cit = citation_map[cnum]
                doc_id = cit.get('doc_id')
                source_entry = {
                    'citation_number': cnum,
                    'headline': cit.get('headline'),
                    'source_name': cit.get('source_name'),
                    'published_date': cit.get('published_date'),
                    'content': doc_contents.get(doc_id, {}).get('content', '')
                }
                sources.append(source_entry)

        if sources:
            validation = validate_claim_against_sources(claim_text, sources, model)
            validated_claims.append(validation)
            all_issues.extend(validation.issues)
        else:
            uncited_claims.append(claim_text)

    # Determine overall status
    status = determine_status(validated_claims, uncited_claims, section_type)

    # Build summary
    supported_count = sum(1 for c in validated_claims if c.is_supported)
    summary_parts = []
    if validated_claims:
        summary_parts.append(f"{supported_count}/{len(validated_claims)} claims supported")
    if uncited_claims:
        summary_parts.append(f"{len(uncited_claims)} uncited claims")
    if all_issues:
        summary_parts.append(f"{len(all_issues)} issues found")

    return SectionValidation(
        section_type=section_type,
        section_id=section_id,
        status=status.value,
        claims_validated=len(validated_claims),
        uncited_claims=len(uncited_claims),
        issues=all_issues[:5],  # Limit to top 5 issues
        summary="; ".join(summary_parts) if summary_parts else "Validated"
    )


def validate_report_stream(
    report: Dict[str, Any],
    model: str = "gpt-4o-mini"
) -> Generator[Dict[str, Any], None, None]:
    """
    Validate a completed report, yielding SSE events for each section.

    Args:
        report: The complete report JSON
        model: LLM model to use for validation

    Yields:
        SSE event dicts with 'type' and 'payload'
    """
    # Build flat list of all citations for lookup
    all_citations = []
    citations_by_event = report.get('citations_by_event', [])
    for cat_group in citations_by_event:
        for evt in cat_group.get('events', []):
            all_citations.extend(evt.get('citations', []))

    # Count total sections
    categories = report.get('categories', [])
    entities = report.get('entities', [])

    total_sections = 1  # overall_summary
    total_sections += len(categories)  # category narratives
    for cat in categories:
        total_sections += len(cat.get('events', []))  # event narratives
    for entity_group in entities:
        total_sections += len(entity_group.get('entities', []))  # entity summaries

    yield {
        'type': 'validation_start',
        'payload': {'total_sections': total_sections}
    }

    overall_statuses = []

    # 1. Validate overall summary
    overall_summary = report.get('overall_summary', '')
    if overall_summary:
        result = validate_section(
            overall_summary,
            all_citations,
            'overall_summary',
            'overall_summary',
            model
        )
        overall_statuses.append(result.status)
        yield {
            'type': 'section_validated',
            'payload': result.to_dict()
        }

    # 2. Validate category narratives
    for cat in categories:
        cat_name = cat.get('category', '')
        narrative = cat.get('narrative', '')

        # Get citations for this category
        cat_citations = []
        for cat_group in citations_by_event:
            if cat_group.get('category') == cat_name:
                for evt in cat_group.get('events', []):
                    cat_citations.extend(evt.get('citations', []))

        if narrative:
            result = validate_section(
                narrative,
                cat_citations,
                'category',
                f'category:{cat_name}',
                model
            )
            overall_statuses.append(result.status)
            yield {
                'type': 'section_validated',
                'payload': result.to_dict()
            }

        # 3. Validate event narratives within category
        for idx, event in enumerate(cat.get('events', [])):
            overview = event.get('overview', '')
            outcomes = event.get('outcomes', '')
            combined_text = f"{overview} {outcomes}".strip()

            # Get citations for this event
            event_citations = []
            event_name = event.get('event_name', '')
            for cat_group in citations_by_event:
                if cat_group.get('category') == cat_name:
                    for evt in cat_group.get('events', []):
                        if evt.get('event_name') == event_name:
                            event_citations = evt.get('citations', [])
                            break

            if combined_text:
                result = validate_section(
                    combined_text,
                    event_citations,
                    'event',
                    f'event:{cat_name}:{idx}',
                    model
                )
                overall_statuses.append(result.status)
                yield {
                    'type': 'section_validated',
                    'payload': result.to_dict()
                }

    # 4. Validate entity summaries
    for entity_group in entities:
        entity_type = entity_group.get('entity_type', '')
        for entity in entity_group.get('entities', []):
            entity_name = entity.get('name', '')
            summary = entity.get('summary', '')

            # Get citations for this entity
            citation_nums = entity.get('citation_numbers', [])
            entity_citations = [c for c in all_citations if c.get('citation_number') in citation_nums]

            if summary:
                result = validate_section(
                    summary,
                    entity_citations,
                    'entity',
                    f'entity:{entity_type}:{entity_name}',
                    model
                )
                overall_statuses.append(result.status)
                yield {
                    'type': 'section_validated',
                    'payload': result.to_dict()
                }

    # Determine overall status
    if ValidationStatus.RED.value in overall_statuses:
        overall_status = ValidationStatus.RED.value
    elif ValidationStatus.YELLOW.value in overall_statuses:
        overall_status = ValidationStatus.YELLOW.value
    else:
        overall_status = ValidationStatus.GREEN.value

    yield {
        'type': 'validation_complete',
        'payload': {
            'overall_status': overall_status,
            'validated_at': datetime.utcnow().isoformat()
        }
    }


def validate_report(
    report: Dict[str, Any],
    model: str = "gpt-4o-mini"
) -> Dict[str, Any]:
    """
    Synchronous validation of entire report.

    Args:
        report: The complete report JSON
        model: LLM model to use

    Returns:
        Validation results dict
    """
    sections = {}
    overall_status = ValidationStatus.GREEN.value

    for event in validate_report_stream(report, model):
        if event['type'] == 'section_validated':
            payload = event['payload']
            sections[payload['section_id']] = payload
        elif event['type'] == 'validation_complete':
            overall_status = event['payload']['overall_status']

    return {
        'status': overall_status,
        'validated_at': datetime.utcnow().isoformat(),
        'model_used': model,
        'sections': sections
    }
