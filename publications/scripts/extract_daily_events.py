"""
Extract Daily Events with Materiality Assessment

Processes existing daily publication JSON files to extract:
- Unique events (no duplicates)
- Materiality scores (0.0-10.0, measuring concrete vs symbolic nature)
- Brief event summaries
- Key entities involved (persons, organizations, companies, locations)

Input: publications/{Country}/daily/{YYYY-MM-DD}.json
Output: publications/events/{Country}/daily/{YYYY-MM-DD}_events.json
"""

import os
import sys
import json
import argparse
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from shared.utils.utils import gai, Config


# ============================================================================
# LLM PROMPT FOR DAILY EVENT EXTRACTION
# ============================================================================

DAILY_EVENT_EXTRACTION_PROMPT = """You are analyzing diplomatic documents from {country} for {date}.

Summary:
{summary_text}

Document citations:
{citations_detail}

Your task is to extract UNIQUE events from this day's documents.

For each unique event, provide:

1. **Event name** (concise, 3-8 words)
2. **Event summary** (2-3 sentences describing what happened)
3. **Materiality assessment**:
   - **Score (0.0-10.0)**: Rate how concrete/tangible vs symbolic this event is
     - 9.0-10.0: Highly material (signed agreements, construction projects, financial commitments, troop deployments)
     - 7.0-8.9: Substantial (MoUs with implementation plans, trade deals with figures, joint ventures)
     - 5.0-6.9: Moderate (high-level visits with deliverables, working groups established)
     - 3.0-4.9: Limited (statements of intent, dialogue mechanisms, cultural exchanges)
     - 0.0-2.9: Symbolic (rhetoric, expressions of friendship, vague commitments)
   - **Justification**: Brief explanation of the materiality score
4. **Category**: Primary category (Diplomacy, Economic, Military, Social, Technology)
5. **Recipients**: Countries or entities involved
6. **Key entities**:
   - Persons (name, role, country)
   - Organizations (name, type)
   - Companies (name, sector)
   - Locations (name, type)
7. **Source doc_ids**: Document IDs that mention this event

CRITICAL:
- Extract UNIQUE events only - if multiple documents cover the same event, list it ONCE
- Use salience information from citations to prioritize
- Materiality measures CONCRETE ACTION, not importance or media coverage
- Track all entities mentioned in connection with each event
- If there are no events (only routine news), return empty array

Return ONLY a JSON array of events:
[
  {{
    "event_name": "China-Iraq Nuclear Training Reactor Agreement",
    "event_summary": "China's Atomic Energy Company signed a contract with Iraq to build Iraq's first subcritical nuclear training reactor at the Al-Tuwaitha complex. This educational project aims to develop skills in nuclear physics and peaceful nuclear technologies for Iraqi students and researchers.",
    "materiality": {{
      "score": 8.5,
      "justification": "High materiality due to signed contract, specific infrastructure project (reactor construction), defined location (Al-Tuwaitha), and concrete deliverable (training reactor). Not 10.0 because it's a training reactor (educational) rather than operational facility."
    }},
    "category": "Social",
    "recipients": ["Iraq"],
    "entities": {{
      "persons": [
        {{"name": "Naeem Al-Aboudi", "role": "Minister of Higher Education / Head of Atomic Energy Commission", "country": "Iraq"}}
      ],
      "organizations": [
        {{"name": "China Atomic Energy Company", "type": "State-owned Enterprise"}},
        {{"name": "Iraqi Atomic Energy Commission", "type": "Government Agency"}}
      ],
      "companies": [],
      "locations": [
        {{"name": "Al-Tuwaitha Complex", "type": "Nuclear facility", "country": "Iraq"}}
      ]
    }},
    "source_doc_ids": ["bf4075d1-1929-45d7-8723-cf20a15268a9"]
  }}
]
"""


# ============================================================================
# HYPERLINK UTILITIES
# ============================================================================

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


# ============================================================================
# FILE READING AND PROCESSING
# ============================================================================

def read_daily_json(country: str, date: datetime, publications_dir: str = "publications") -> Optional[Dict[str, Any]]:
    """Read a daily JSON file for a specific country and date."""
    date_str = date.strftime("%Y-%m-%d")
    file_path = Path(publications_dir) / country / "daily" / f"{date_str}.json"

    if not file_path.exists():
        return None

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"  Error reading {file_path}: {e}")
        return None


def extract_daily_events(
    daily_json: Dict[str, Any],
    config: Config
) -> Optional[List[Dict[str, Any]]]:
    """Extract events from a daily JSON file using LLM with materiality assessment."""

    date = daily_json.get('date', 'Unknown')
    country = daily_json.get('influencer', 'Unknown')
    summary_text = daily_json.get('summary', '')

    # Format document citations for LLM
    citations_detail = []
    for citation in daily_json.get('citations', []):
        detail = f"[{citation.get('citation_number', '?')}] {citation.get('headline', 'No title')}\n"
        detail += f"  Source: {citation.get('source_name', 'Unknown')}, Date: {citation.get('published_date', 'Unknown')}\n"

        if citation.get('salience'):
            detail += f"  Salience: {citation['salience']}\n"

        detail += f"  Categories: {', '.join(citation.get('categories', []))}\n"
        detail += f"  Recipients: {', '.join(citation.get('recipients', []))}\n"
        detail += f"  Doc ID: {citation.get('doc_id', 'Unknown')}\n"

        excerpt = citation.get('excerpt', '')
        if excerpt:
            detail += f"  Excerpt: {excerpt[:400]}...\n"

        citations_detail.append(detail)

    citations_text = "\n".join(citations_detail)

    # Build prompt
    prompt = DAILY_EVENT_EXTRACTION_PROMPT.format(
        country=country,
        date=date,
        summary_text=summary_text,
        citations_detail=citations_text
    )

    try:
        sys_prompt = "You are an expert geopolitical analyst specializing in materiality assessment. You distinguish between concrete, tangible developments and symbolic rhetoric. Extract unique events with precise materiality scoring and comprehensive entity tracking."

        # Uses default source="proxy" which routes through FastAPI /material_query
        # The proxy handles Azure→OpenAI fallback based on ENV variable
        response = gai(
            sys_prompt=sys_prompt,
            user_prompt=prompt,
            model=config.aws['default_model']
        )

        # Parse JSON response
        if isinstance(response, list):
            events = response
        elif isinstance(response, str):
            events = json.loads(response.strip())
        else:
            print(f"  Unexpected response type: {type(response)}")
            return None

        print(f"  ✓ Extracted {len(events)} unique events (Date: {date})")

        # Log materiality scores
        if events:
            scores = [e.get('materiality', {}).get('score', 0) for e in events]
            avg_score = sum(scores) / len(scores) if scores else 0
            print(f"    Materiality scores: {min(scores):.1f}-{max(scores):.1f} (avg: {avg_score:.1f})")

        return events

    except json.JSONDecodeError as e:
        print(f"  ✗ Error parsing LLM response for {date}: {e}")
        return None
    except Exception as e:
        print(f"  ✗ Error calling LLM for {date}: {e}")
        return None


def process_date_range(
    country: str,
    start_date: datetime,
    end_date: datetime,
    publications_dir: str = "publications",
    output_dir: str = "publications/events",
    config: Config = None,
    force: bool = False
):
    """
    Process all daily files in a date range for a country.

    Args:
        force: If True, reprocess dates that already have output files (default: False)
    """

    print(f"\n{'='*80}")
    print(f"Extracting Daily Events: {country}")
    print(f"Date range: {start_date.date()} to {end_date.date()}")
    print(f"Input: {publications_dir}/{country}/daily/")
    print(f"Output: {output_dir}/{country}/daily/")
    if force:
        print(f"Mode: FORCE - will reprocess existing files")
    else:
        print(f"Mode: Skip existing files (use --force to reprocess)")
    print(f"{'='*80}\n")

    if config is None:
        # Resolve config path relative to script location
        config_path = Path(__file__).parent.parent.parent / 'shared' / 'config' / 'config.yaml'
        config = Config.from_yaml(config_path)

    # Create output directory
    country_output_dir = Path(output_dir) / country / "daily"
    country_output_dir.mkdir(parents=True, exist_ok=True)

    # Process each date
    current_date = start_date
    results = []
    total_events = 0
    files_processed = 0
    files_skipped = 0

    while current_date <= end_date:
        # Check if output file already exists (unless force=True)
        date_str = current_date.strftime("%Y-%m-%d")
        output_file = country_output_dir / f"{date_str}_events.json"

        if not force and output_file.exists():
            print(f"  ⊗ Skipping {current_date.date()} (already exists)")
            files_skipped += 1
            current_date += timedelta(days=1)
            continue

        # Read daily JSON
        daily_json = read_daily_json(country, current_date, publications_dir)

        if not daily_json:
            print(f"  ⊘ No file for {current_date.date()}")
            current_date += timedelta(days=1)
            continue

        # Extract events
        print(f"Processing {current_date.date()}...")
        events = extract_daily_events(daily_json, config)

        if events is not None:
            # Add ATOM search hyperlink to each event
            for event in events:
                if "source_doc_ids" in event:
                    event["atom_search_url"] = build_hyperlink(event["source_doc_ids"])

            # Save individual daily file
            date_str = current_date.strftime("%Y-%m-%d")
            output_file = country_output_dir / f"{date_str}_events.json"

            output_data = {
                "date": date_str,
                "country": country,
                "events": events,
                "source_file": f"{country}/daily/{date_str}.json",
                "extracted_at": datetime.now().isoformat()
            }

            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, indent=2, ensure_ascii=False)

            files_processed += 1
            total_events += len(events)

            results.append({
                "date": date_str,
                "events_count": len(events),
                "output_file": str(output_file.name)
            })

        current_date += timedelta(days=1)

    # Save processing summary
    summary = {
        "country": country,
        "date_range": {
            "start": start_date.strftime("%Y-%m-%d"),
            "end": end_date.strftime("%Y-%m-%d")
        },
        "processing": {
            "files_processed": files_processed,
            "files_skipped": files_skipped,
            "total_events_extracted": total_events,
            "avg_events_per_day": round(total_events / files_processed, 2) if files_processed > 0 else 0
        },
        "daily_results": results,
        "processed_at": datetime.now().isoformat()
    }

    summary_file = country_output_dir / f"extraction_summary_{start_date.strftime('%Y-%m')}_{end_date.strftime('%Y-%m')}.json"
    with open(summary_file, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*80}")
    print(f"✅ Processing Complete!")
    print(f"  Files processed: {files_processed}")
    print(f"  Files skipped: {files_skipped}")
    print(f"  Total events extracted: {total_events}")
    print(f"  Average events/day: {summary['processing']['avg_events_per_day']}")
    print(f"  Summary: {summary_file}")
    print(f"{'='*80}\n")


# ============================================================================
# COMMAND LINE INTERFACE
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Extract daily events with materiality assessment from publication JSON files"
    )
    parser.add_argument(
        "--country",
        required=True,
        help="Initiating country to process"
    )
    parser.add_argument(
        "--start-date",
        required=True,
        help="Start date (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--end-date",
        required=True,
        help="End date (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--publications-dir",
        default="publications",
        help="Directory containing daily JSON files (default: publications)"
    )
    parser.add_argument(
        "--output-dir",
        default="publications/events",
        help="Output directory for event JSON files (default: publications/events)"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force reprocessing of dates that already have output files (default: skip existing)"
    )

    args = parser.parse_args()

    # Parse dates
    try:
        start_date = datetime.strptime(args.start_date, "%Y-%m-%d")
        end_date = datetime.strptime(args.end_date, "%Y-%m-%d")
    except ValueError as e:
        print(f"Error parsing dates: {e}")
        sys.exit(1)

    # Load config (resolve path relative to script location)
    config_path = Path(__file__).parent.parent.parent / 'shared' / 'config' / 'config.yaml'
    config = Config.from_yaml(config_path)

    # Process
    process_date_range(
        args.country,
        start_date,
        end_date,
        args.publications_dir,
        args.output_dir,
        config,
        force=args.force
    )


if __name__ == "__main__":
    main()
