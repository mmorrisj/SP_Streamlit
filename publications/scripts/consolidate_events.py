"""
Hierarchical Event Consolidation Pipeline

Consolidates daily event extractions into:
- Weekly summaries (groups events by ISO week)
- Monthly summaries (groups weekly events by month)
- Overall summary (final rollup across all months)

Input: publications/events/{Country}/daily/{YYYY-MM-DD}_events.json
Output:
  - publications/events/{Country}/weekly/{YYYY-W##}_events.json
  - publications/events/{Country}/monthly/{YYYY-MM}_events.json
  - publications/events/{Country}/overall_{start}_{end}_events.json

Features:
- LLM-based multi-day event detection and consolidation
- Entity consolidation (persons, organizations, companies, locations)
- Materiality score aggregation (max score across instances)
- Full source doc_id tracking with ATOM search URLs
- Citation chains for traceability

Usage:
    # Consolidate China events for June-December 2025
    python consolidate_events.py \
        --country China \
        --start-date 2025-06-01 \
        --end-date 2026-01-01

    # Weekly only
    python consolidate_events.py \
        --country China \
        --start-date 2025-06-01 \
        --end-date 2026-01-01 \
        --weekly-only

    # Monthly only (requires weekly files)
    python consolidate_events.py \
        --country China \
        --start-date 2025-06-01 \
        --end-date 2026-01-01 \
        --monthly-only
"""

import os
import sys
import json
import argparse
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from pathlib import Path
from collections import defaultdict
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from shared.utils.utils import gai, Config


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def get_materiality_score(event: Dict[str, Any]) -> float:
    """
    Safely extract materiality score from event, handling both dict and float formats.

    Args:
        event: Event dictionary

    Returns:
        Materiality score as float (0.0 if not found)
    """
    materiality = event.get('materiality', 0)

    # Handle dict format: {"score": 8.5, "justification": "..."}
    if isinstance(materiality, dict):
        return materiality.get('score', 0.0)

    # Handle float format: 8.5
    if isinstance(materiality, (int, float)):
        return float(materiality)

    return 0.0


def get_date_range_text(event: Dict[str, Any]) -> str:
    """
    Safely extract date range from event, handling both dict and string formats.

    Args:
        event: Event dictionary

    Returns:
        Formatted date range string
    """
    date_range = event.get('date_range', {})

    # Handle dict format: {"first_mention": "2025-06-01", "last_mention": "2025-06-30"}
    if isinstance(date_range, dict):
        first = date_range.get('first_mention', '')
        last = date_range.get('last_mention', '')
        if first and last:
            return f"{first} to {last}"
        return first or last or 'Unknown'

    # Handle string format: "2025-06-01 to 2025-06-30"
    if isinstance(date_range, str):
        return date_range

    return 'Unknown'


def build_hyperlink(doc_ids: List[str]) -> str:
    """
    Constructs a hyperlink to ATOM search with given document IDs.

    Args:
        doc_ids: List of document IDs to include in search query

    Returns:
        Formatted ATOM search URL
    """
    if not doc_ids:
        return ""

    # Enclose each ID in double quotes and join with '+OR+'
    quoted_ids = [f'%22{doc_id}%22' for doc_id in doc_ids]
    ids_query = '+OR+'.join(quoted_ids)

    link = f"https://atom.opensource.gov/searches?ss=id%3A({ids_query})&go=1"
    return link


def aggregate_event_metadata(event_ids: List[str], event_lookup: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """
    Aggregate metadata from multiple events.

    Args:
        event_ids: List of event IDs to aggregate
        event_lookup: Dictionary mapping event IDs to event data

    Returns:
        Aggregated metadata including entities, doc_ids, recipients, date_range, materiality
    """
    # Collect all data
    all_doc_ids = []
    all_recipients = set()
    all_persons = []
    all_organizations = []
    all_companies = []
    all_locations = []
    max_materiality = 0.0
    materiality_justification = ""
    first_date = None
    last_date = None

    for event_id in event_ids:
        event = event_lookup.get(event_id)
        if not event:
            continue

        # Collect doc IDs
        doc_ids = event.get('source_doc_ids', [])
        all_doc_ids.extend(doc_ids)

        # Collect recipients
        recipients = event.get('recipients', [])
        all_recipients.update(recipients)

        # Collect entities
        entities = event.get('entities', {})
        all_persons.extend(entities.get('persons', []))
        all_organizations.extend(entities.get('organizations', []))
        all_companies.extend(entities.get('companies', []))
        all_locations.extend(entities.get('locations', []))

        # Track materiality (take highest)
        mat_score = get_materiality_score(event)
        if mat_score > max_materiality:
            max_materiality = mat_score
            mat = event.get('materiality', {})
            if isinstance(mat, dict):
                materiality_justification = mat.get('justification', '')

        # Track date range
        date_range = event.get('date_range', {})
        if isinstance(date_range, dict):
            event_first = date_range.get('first_mention', '')
            event_last = date_range.get('last_mention', '')

            if event_first and (not first_date or event_first < first_date):
                first_date = event_first
            if event_last and (not last_date or event_last > last_date):
                last_date = event_last

    # Deduplicate entities by unique keys
    def deduplicate_by_name(items, key='name'):
        seen = set()
        result = []
        for item in items:
            # Handle both dict format and string format
            if isinstance(item, dict):
                name = item.get(key, '').strip()
                if name and name not in seen:
                    seen.add(name)
                    result.append(item)
            elif isinstance(item, str):
                # Handle string format (e.g., plain location names)
                name = item.strip()
                if name and name not in seen:
                    seen.add(name)
                    # Convert string to dict format for consistency
                    result.append({key: name})
        return result

    return {
        "source_doc_ids": list(set(all_doc_ids)),  # Remove duplicates
        "recipients": sorted(list(all_recipients)),
        "entities": {
            "persons": deduplicate_by_name(all_persons),
            "organizations": deduplicate_by_name(all_organizations),
            "companies": deduplicate_by_name(all_companies),
            "locations": deduplicate_by_name(all_locations)
        },
        "materiality": {
            "score": max_materiality,
            "justification": materiality_justification or f"Highest materiality score across consolidated events."
        },
        "date_range": {
            "first_mention": first_date or "Unknown",
            "last_mention": last_date or "Unknown"
        }
    }


# ============================================================================
# WEEKLY CONSOLIDATION
# ============================================================================

WEEKLY_CONSOLIDATION_PROMPT = """You are analyzing daily event extractions for {country} during Week {week_num} ({week_start} to {week_end}).

Below are ALL unique events extracted from each day of this week. Each event has a unique ID for reference.

Your task is to identify which events represent the SAME real-world event occurring across multiple days, and consolidate them.

Daily Events:
{daily_events_text}

CRITICAL INSTRUCTIONS:
1. **Multi-day Event Detection**: Identify events that are the same event happening across multiple days
   - Same infrastructure project mentioned on different days (e.g., Day 1: announcement, Day 3: groundbreaking)
   - Ongoing diplomatic visits/meetings spanning multiple days
   - Continuing negotiations or discussions
   - Multi-day conferences or summits

2. **Consolidation Logic**:
   - For multi-day events: Create ONE consolidated event referencing all relevant event IDs
   - For single-day events: Create ONE event referencing that single ID
   - Write a new event_summary that reflects developments across all days
   - Choose the most descriptive event_name

3. **Required Output Format** - JSON array of objects, each with:
   - "event_name": Clear name for the consolidated event
   - "event_summary": Comprehensive summary covering all days (2-4 sentences)
   - "category": Primary category (Economic/Diplomacy/Social/Military)
   - "consolidated_event_ids": Array of event IDs being consolidated (e.g., ["2025-06-01_event_1", "2025-06-03_event_2"])

**Return ONLY a valid JSON array. The script will handle metadata aggregation (entities, doc_ids, dates, recipients, materiality).**

Example Output:
[
  {{
    "event_name": "China-Iraq Hospital Construction Project",
    "event_summary": "China announced and began construction of 16 hospitals across Baghdad and Iraqi provinces under a framework agreement, involving reputable global companies to enhance Iraq's healthcare infrastructure.",
    "category": "Social",
    "consolidated_event_ids": ["2025-06-25_event_1", "2025-06-27_event_2", "2025-06-30_event_1"]
  }},
  {{
    "event_name": "China-Egypt Economic Cooperation Initiatives",
    "event_summary": "Investment meetings and renewable energy discussions between China and Egypt throughout the week, establishing framework for bilateral economic cooperation.",
    "category": "Economic",
    "consolidated_event_ids": ["2025-06-23_event_1"]
  }}
]
"""


def get_week_number(date: datetime) -> tuple:
    """Get ISO week number and year for a date."""
    iso_calendar = date.isocalendar()
    return iso_calendar[0], iso_calendar[1]  # (year, week_number)


def group_daily_events_by_week(
    country: str,
    start_date: datetime,
    end_date: datetime,
    events_dir: str = "publications/events"
) -> Dict[str, List[Dict[str, Any]]]:
    """Group daily event files by ISO week."""

    weekly_groups = defaultdict(list)
    current_date = start_date

    while current_date <= end_date:
        # Read daily event file
        date_str = current_date.strftime("%Y-%m-%d")
        daily_file = Path(events_dir) / country / "daily" / f"{date_str}_events.json"

        if daily_file.exists():
            try:
                with open(daily_file, 'r', encoding='utf-8') as f:
                    daily_data = json.load(f)

                # Get week identifier
                year, week = get_week_number(current_date)
                week_key = f"{year}-W{week:02d}"

                # Add to weekly group
                weekly_groups[week_key].append({
                    "date": date_str,
                    "events": daily_data.get("events", [])
                })
            except Exception as e:
                print(f"  Warning: Error reading {daily_file}: {e}")

        current_date += timedelta(days=1)

    return dict(weekly_groups)


def consolidate_weekly_events(
    week_key: str,
    daily_events_list: List[Dict[str, Any]],
    country: str,
    config: Config
) -> Optional[Dict[str, Any]]:
    """Consolidate daily events into weekly summary using LLM with script-based metadata aggregation."""

    # Get week start/end dates
    year, week_num = week_key.split('-W')
    # ISO week date calculation
    jan4 = datetime(int(year), 1, 4)
    week_start = jan4 + timedelta(days=-jan4.weekday(), weeks=int(week_num)-1)
    week_end = week_start + timedelta(days=6)

    # Build event lookup with IDs
    event_lookup = {}
    daily_events_text = []

    for daily_data in daily_events_list:
        date = daily_data["date"]
        events = daily_data["events"]

        daily_events_text.append(f"\n**{date}** ({len(events)} events):")

        for i, event in enumerate(events, 1):
            # Create unique event ID
            event_id = f"{date}_event_{i}"
            event_lookup[event_id] = event

            # Format for LLM with ID
            text = f"  [ID: {event_id}] {event.get('event_name', 'Unnamed')}\n"
            text += f"      Summary: {event.get('event_summary', '')[:200]}...\n"
            text += f"      Materiality: {get_materiality_score(event)}\n"
            text += f"      Category: {event.get('category', 'Unknown')}\n"
            text += f"      Recipients: {', '.join(event.get('recipients', []))}\n"
            daily_events_text.append(text)

    events_text = "\n".join(daily_events_text)

    # Build prompt
    prompt = WEEKLY_CONSOLIDATION_PROMPT.format(
        country=country,
        week_num=week_key,
        week_start=week_start.strftime("%Y-%m-%d"),
        week_end=week_end.strftime("%Y-%m-%d"),
        daily_events_text=events_text
    )

    try:
        sys_prompt = "You are an expert geopolitical analyst specializing in event consolidation and temporal analysis. You identify when events mentioned on different days represent the same real-world occurrence."

        response = gai(
            sys_prompt=sys_prompt,
            user_prompt=prompt,
            model=config.aws['default_model']
        )

        # Parse JSON response
        if isinstance(response, list):
            llm_events = response
        elif isinstance(response, str):
            llm_events = json.loads(response.strip())
        else:
            print(f"  Unexpected response type: {type(response)}")
            return None

        # Enrich each event with aggregated metadata from source daily events
        enriched_events = []

        for llm_event in llm_events:
            event_ids = llm_event.get('consolidated_event_ids', [])

            # Aggregate metadata from source events
            metadata = aggregate_event_metadata(event_ids, event_lookup)

            # Build enriched event with LLM summary + script-aggregated metadata
            enriched_event = {
                "event_name": llm_event.get('event_name'),
                "event_summary": llm_event.get('event_summary'),
                "materiality": metadata['materiality'],
                "category": llm_event.get('category'),
                "recipients": metadata['recipients'],
                "date_range": metadata['date_range'],
                "entities": metadata['entities'],
                "source_doc_ids": metadata['source_doc_ids'],
                "daily_sources": [eid.split('_event_')[0] for eid in event_ids],  # Extract dates
                "consolidated_from": event_ids
            }

            enriched_events.append(enriched_event)

        print(f"  [OK] Consolidated {week_key}: {len(enriched_events)} weekly events from {len(daily_events_list)} days")

        return {
            "week": week_key,
            "week_start": week_start.strftime("%Y-%m-%d"),
            "week_end": week_end.strftime("%Y-%m-%d"),
            "country": country,
            "events": enriched_events,
            "days_included": [d["date"] for d in daily_events_list],
            "consolidated_at": datetime.now().isoformat()
        }

    except json.JSONDecodeError as e:
        print(f"  [ERROR] Error parsing LLM response for {week_key}: {e}")
        return None
    except Exception as e:
        print(f"  [ERROR] Error consolidating {week_key}: {e}")
        import traceback
        traceback.print_exc()
        return None


# ============================================================================
# MONTHLY CONSOLIDATION
# ============================================================================

MONTHLY_CONSOLIDATION_PROMPT = """You are analyzing weekly event consolidations for {country} during {month_name} {year}.

Below are ALL consolidated weekly events for this month. Each event has a unique ID for reference.

Your task is to identify which events represent the SAME real-world event occurring across multiple weeks, and consolidate them.

Weekly Events:
{weekly_events_text}

CRITICAL INSTRUCTIONS:
1. **Multi-week Event Detection**: Identify events spanning multiple weeks
   - Ongoing construction projects (e.g., same hospital/infrastructure mentioned in Week 1 and Week 3)
   - Multi-phase diplomatic initiatives (e.g., summit preparation → summit → follow-up)
   - Continuing negotiations or trade discussions
   - Extended cultural/economic programs

2. **Consolidation Logic**:
   - For multi-week events: Create ONE consolidated event referencing all relevant event IDs
   - For single-week events: Create ONE event referencing that single ID
   - Write a new event_summary that reflects the full month's developments
   - Choose the most descriptive event_name

3. **Required Output Format** - JSON array of objects, each with:
   - "event_name": Clear name for the consolidated event
   - "event_summary": Comprehensive summary covering all weeks (3-5 sentences)
   - "category": Primary category (Economic/Diplomacy/Social/Military)
   - "consolidated_event_ids": Array of event IDs being consolidated (e.g., ["W26_event_1", "W27_event_2"])

**Return ONLY a valid JSON array. The script will handle metadata aggregation (entities, doc_ids, dates, recipients).**

Example Output:
[
  {{
    "event_name": "China-Egypt Belt and Road Rail Project",
    "event_summary": "Multi-week initiative spanning planning, MoU signing, and construction assessment...",
    "category": "Economic",
    "consolidated_event_ids": ["W23_event_1", "W24_event_3", "W26_event_2"]
  }}
]
"""


def group_weekly_events_by_month(
    country: str,
    start_date: datetime,
    end_date: datetime,
    events_dir: str = "publications/events"
) -> Dict[str, List[Dict[str, Any]]]:
    """Group weekly event files by month."""

    monthly_groups = defaultdict(list)

    # Find all weekly files in date range
    weekly_dir = Path(events_dir) / country / "weekly"
    if not weekly_dir.exists():
        return {}

    for weekly_file in sorted(weekly_dir.glob("*_events.json")):
        try:
            with open(weekly_file, 'r', encoding='utf-8') as f:
                weekly_data = json.load(f)

            # Get month from week_start
            week_start = datetime.strptime(weekly_data["week_start"], "%Y-%m-%d")

            # Check if in range
            if start_date <= week_start <= end_date:
                month_key = week_start.strftime("%Y-%m")
                monthly_groups[month_key].append(weekly_data)

        except Exception as e:
            print(f"  Warning: Error reading {weekly_file}: {e}")

    return dict(monthly_groups)


def consolidate_monthly_events(
    month_key: str,
    weekly_events_list: List[Dict[str, Any]],
    country: str,
    config: Config
) -> Optional[Dict[str, Any]]:
    """Consolidate weekly events into monthly summary using LLM with script-based metadata aggregation."""

    year, month = month_key.split('-')
    month_name = datetime(int(year), int(month), 1).strftime("%B")

    # Build event lookup with IDs
    event_lookup = {}
    weekly_events_text = []

    for weekly_data in weekly_events_list:
        week = weekly_data["week"]
        events = weekly_data["events"]

        weekly_events_text.append(f"\n**{week}** ({weekly_data['week_start']} to {weekly_data['week_end']}) - {len(events)} events:")

        for i, event in enumerate(events, 1):
            # Create unique event ID
            event_id = f"{week}_event_{i}"
            event_lookup[event_id] = event

            # Format for LLM with ID
            text = f"  [ID: {event_id}] {event.get('event_name', 'Unnamed')}\n"
            text += f"      Summary: {event.get('event_summary', '')[:200]}...\n"
            text += f"      Materiality: {get_materiality_score(event)}\n"
            text += f"      Category: {event.get('category', 'Unknown')}\n"
            text += f"      Date range: {get_date_range_text(event)}\n"
            weekly_events_text.append(text)

    events_text = "\n".join(weekly_events_text)

    # Build prompt
    prompt = MONTHLY_CONSOLIDATION_PROMPT.format(
        country=country,
        month_name=month_name,
        year=year,
        weekly_events_text=events_text
    )

    try:
        sys_prompt = "You are an expert geopolitical analyst specializing in event consolidation and temporal analysis. You identify when events mentioned across different weeks represent the same real-world occurrence."

        response = gai(
            sys_prompt=sys_prompt,
            user_prompt=prompt,
            model=config.aws['default_model']
        )

        # Parse JSON response
        if isinstance(response, list):
            llm_events = response
        elif isinstance(response, str):
            llm_events = json.loads(response.strip())
        else:
            print(f"  Unexpected response type: {type(response)}")
            return None

        # Enrich each event with aggregated metadata from source weekly events
        enriched_events = []

        for llm_event in llm_events:
            event_ids = llm_event.get('consolidated_event_ids', [])

            # Aggregate metadata from source events
            metadata = aggregate_event_metadata(event_ids, event_lookup)

            # Build enriched event with LLM summary + script-aggregated metadata
            enriched_event = {
                "event_name": llm_event.get('event_name'),
                "event_summary": llm_event.get('event_summary'),
                "materiality": metadata['materiality'],
                "category": llm_event.get('category'),
                "recipients": metadata['recipients'],
                "date_range": metadata['date_range'],
                "entities": metadata['entities'],
                "source_doc_ids": metadata['source_doc_ids'],
                "weekly_sources": [eid.split('_event_')[0] for eid in event_ids],  # Extract week IDs
                "consolidated_from": event_ids
            }

            enriched_events.append(enriched_event)

        print(f"  [OK] Consolidated {month_key}: {len(enriched_events)} monthly events from {len(weekly_events_list)} weeks")

        return {
            "month": month_key,
            "month_name": month_name,
            "country": country,
            "events": enriched_events,
            "weeks_included": [w["week"] for w in weekly_events_list],
            "consolidated_at": datetime.now().isoformat()
        }

    except json.JSONDecodeError as e:
        print(f"  [ERROR] Error parsing LLM response for {month_key}: {e}")
        return None
    except Exception as e:
        print(f"  [ERROR] Error consolidating {month_key}: {e}")
        import traceback
        traceback.print_exc()
        return None


# ============================================================================
# OVERALL CONSOLIDATION
# ============================================================================

OVERALL_CONSOLIDATION_PROMPT = """You are analyzing monthly event consolidations for {country} from {start_date} to {end_date}.

Below are ALL consolidated monthly events for this period. Your task is to identify which events should be consolidated and provide summaries.

Monthly Events (with IDs):
{monthly_events_text}

CRITICAL INSTRUCTIONS:
1. **Cross-month Event Detection**: Identify major events spanning multiple months
   - Large infrastructure projects
   - Long-term diplomatic initiatives
   - Major trade/economic programs
   - Sustained military/security cooperation

2. **Consolidation Rules**:
   - For multi-month events: Group related event IDs together
   - Prioritize HIGH materiality events (score ≥ 7.0)
   - For single-month events: Keep as-is
   - Write comprehensive summaries capturing full timeline and key details
   - Quality over quantity: Aim for 10-20 major events maximum

3. **Your Output** (the script will handle metadata aggregation):
   - event_name: Concise, descriptive name (3-10 words)
   - event_summary: Comprehensive summary with key details, participants, outcomes
   - consolidated_event_ids: Array of event IDs from monthly events that belong to this consolidated event
   - category: Primary category (Diplomacy, Economic, Military, Social, Technology)

NOTE: You do NOT need to manually list entities, source_doc_ids, or recipients - the script will automatically aggregate these from the consolidated_event_ids you provide.

Return ONLY a JSON array:
[
  {{
    "event_name": "China-Iraq Infrastructure Development Partnership",
    "event_summary": "China expanded its Belt and Road Initiative in Iraq through multiple projects including the construction of 16 hospitals across Baghdad provinces, railway infrastructure development, and energy sector cooperation...",
    "consolidated_event_ids": ["2025-06_event_3", "2025-06_event_12"],
    "category": "Economic"
  }},
  {{
    "event_name": "China-Egypt Economic Expansion",
    "event_summary": "Chinese companies including Haier and Xiaomi significantly expanded manufacturing in Egypt, creating thousands of jobs...",
    "consolidated_event_ids": ["2025-06_event_8"],
    "category": "Economic"
  }}
]
"""


def consolidate_overall_events(
    monthly_events_list: List[Dict[str, Any]],
    country: str,
    start_date: datetime,
    end_date: datetime,
    config: Config
) -> Optional[Dict[str, Any]]:
    """Consolidate monthly events into overall summary using LLM."""

    # Build event lookup and format for LLM
    event_lookup = {}
    monthly_events_text = []

    for monthly_data in monthly_events_list:
        month = monthly_data["month"]
        month_name = monthly_data["month_name"]
        events = monthly_data["events"]

        monthly_events_text.append(f"\n**{month_name} {month}** - {len(events)} events:")
        for i, event in enumerate(events, 1):
            # Create unique event ID
            event_id = f"{month}_event_{i}"
            event_lookup[event_id] = event

            text = f"  [ID: {event_id}] {event.get('event_name', 'Unnamed')}\n"
            text += f"      Summary: {event.get('event_summary', '')[:400]}...\n"
            text += f"      Materiality: {get_materiality_score(event)}\n"
            text += f"      Category: {event.get('category', 'Unknown')}\n"
            text += f"      Recipients: {', '.join(event.get('recipients', []))}\n"
            text += f"      Date range: {get_date_range_text(event)}\n"

            # Include entity summary
            entities = event.get('entities', {})
            person_count = len(entities.get('persons', []))
            org_count = len(entities.get('organizations', []))
            company_count = len(entities.get('companies', []))
            location_count = len(entities.get('locations', []))
            text += f"      Entities: {person_count} persons, {org_count} orgs, {company_count} companies, {location_count} locations\n"

            # Show first few entities as examples
            if person_count > 0:
                persons = entities['persons'][:2]
                person_names = [p.get('name', 'Unknown') for p in persons]
                text += f"        Key persons: {', '.join(person_names)}\n"
            if company_count > 0:
                companies = entities['companies'][:2]
                company_names = [c.get('name', 'Unknown') for c in companies]
                text += f"        Key companies: {', '.join(company_names)}\n"

            text += f"      Source doc IDs: {event.get('source_doc_ids', [])[:5]}{'...' if len(event.get('source_doc_ids', [])) > 5 else ''}\n"
            monthly_events_text.append(text)

    events_text = "\n".join(monthly_events_text)

    # Build prompt
    prompt = OVERALL_CONSOLIDATION_PROMPT.format(
        country=country,
        start_date=start_date.strftime("%Y-%m-%d"),
        end_date=end_date.strftime("%Y-%m-%d"),
        monthly_events_text=events_text
    )

    try:
        sys_prompt = "You are an expert geopolitical analyst creating final strategic intelligence summaries. Focus on identifying which events should be consolidated and writing comprehensive summaries. The script will handle metadata aggregation."

        response = gai(
            sys_prompt=sys_prompt,
            user_prompt=prompt,
            model=config.aws['default_model']
        )

        # Parse JSON response
        if isinstance(response, list):
            llm_events = response
        elif isinstance(response, str):
            llm_events = json.loads(response.strip())
        else:
            print(f"  Unexpected response type: {type(response)}")
            return None

        # Enrich each event with aggregated metadata
        enriched_events = []
        for llm_event in llm_events:
            event_ids = llm_event.get('consolidated_event_ids', [])

            if not event_ids:
                print(f"  Warning: Event '{llm_event.get('event_name', 'Unknown')}' has no consolidated_event_ids, skipping")
                continue

            # Aggregate metadata from source events
            metadata = aggregate_event_metadata(event_ids, event_lookup)

            # Build enriched event
            enriched_event = {
                "event_name": llm_event.get('event_name', 'Unnamed Event'),
                "event_summary": llm_event.get('event_summary', ''),
                "materiality": metadata['materiality'],
                "category": llm_event.get('category', 'Unknown'),
                "recipients": metadata['recipients'],
                "date_range": metadata['date_range'],
                "entities": metadata['entities'],
                "source_doc_ids": metadata['source_doc_ids'],
                "consolidated_from": event_ids  # Track which events were merged
            }

            enriched_events.append(enriched_event)

        print(f"  [OK] Created overall summary: {len(enriched_events)} major events")
        print(f"    Total unique doc_ids: {sum(len(e['source_doc_ids']) for e in enriched_events)}")
        print(f"    Total entities: {sum(len(e['entities']['persons']) + len(e['entities']['organizations']) + len(e['entities']['companies']) + len(e['entities']['locations']) for e in enriched_events)}")

        return {
            "period": f"{start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}",
            "country": country,
            "events": enriched_events,
            "months_included": [m["month"] for m in monthly_events_list],
            "consolidated_at": datetime.now().isoformat()
        }

    except json.JSONDecodeError as e:
        print(f"  [ERROR] Error parsing LLM response for overall summary: {e}")
        return None
    except Exception as e:
        print(f"  [ERROR] Error creating overall summary: {e}")
        import traceback
        traceback.print_exc()
        return None


# ============================================================================
# MAIN PROCESSING PIPELINE
# ============================================================================

def process_consolidation(
    country: str,
    start_date: datetime,
    end_date: datetime,
    events_dir: str = "publications/events",
    config: Config = None,
    weekly_only: bool = False,
    monthly_only: bool = False,
    overall_only: bool = False,
    force: bool = False,
    force_monthly: bool = False,
    force_overall: bool = False
):
    """Process hierarchical event consolidation."""

    print(f"\n{'='*80}")
    print(f"Consolidating Events: {country}")
    print(f"Date range: {start_date.date()} to {end_date.date()}")
    print(f"Events directory: {events_dir}/{country}/")
    if force:
        print(f"Force mode: ALL LEVELS (will reprocess all existing files)")
    elif force_monthly or force_overall:
        force_levels = []
        if force_monthly:
            force_levels.append("monthly")
        if force_overall:
            force_levels.append("overall")
        print(f"Force mode: {', '.join(force_levels).upper()} (will reprocess {', '.join(force_levels)} files only)")
    print(f"{'='*80}\n")

    if config is None:
        config = Config.from_yaml('shared/config/config.yaml')

    # Weekly consolidation
    if not monthly_only and not overall_only:
        print("\n[WEEKLY CONSOLIDATION]")
        print("-" * 80)

        weekly_groups = group_daily_events_by_week(country, start_date, end_date, events_dir)

        if not weekly_groups:
            print("  X No daily event files found")
            return

        print(f"  Found {len(weekly_groups)} weeks to process")

        # Create weekly output directory
        weekly_dir = Path(events_dir) / country / "weekly"
        weekly_dir.mkdir(parents=True, exist_ok=True)

        weekly_results = []
        skipped_count = 0

        for week_key in sorted(weekly_groups.keys()):
            output_file = weekly_dir / f"{week_key}_events.json"

            # Check if already processed
            if output_file.exists() and not force:
                print(f"\n  >> Skipping {week_key} (already exists, use --force to reprocess)")
                skipped_count += 1
                continue

            print(f"\n  Processing {week_key}...")
            daily_events = weekly_groups[week_key]

            weekly_data = consolidate_weekly_events(week_key, daily_events, country, config)

            if weekly_data:
                # Add ATOM search URLs
                for event in weekly_data["events"]:
                    if "source_doc_ids" in event:
                        event["atom_search_url"] = build_hyperlink(event["source_doc_ids"])

                # Save weekly file
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(weekly_data, f, indent=2, ensure_ascii=False)

                weekly_results.append({
                    "week": week_key,
                    "events_count": len(weekly_data["events"]),
                    "days_covered": len(daily_events)
                })

        if skipped_count > 0:
            print(f"\n  >> Skipped {skipped_count} existing weeks")

        print(f"\n  [SUCCESS] Weekly consolidation complete: {len(weekly_results)} weeks processed")

        if weekly_only:
            return

    # Monthly consolidation
    if not overall_only:
        print("\n\n[MONTHLY CONSOLIDATION]")
        print("-" * 80)

        monthly_groups = group_weekly_events_by_month(country, start_date, end_date, events_dir)

        if not monthly_groups:
            print("  X No weekly event files found. Run weekly consolidation first.")
            return

        print(f"  Found {len(monthly_groups)} months to process")

        # Create monthly output directory
        monthly_dir = Path(events_dir) / country / "monthly"
        monthly_dir.mkdir(parents=True, exist_ok=True)

        monthly_results = []
        skipped_count = 0

        for month_key in sorted(monthly_groups.keys()):
            output_file = monthly_dir / f"{month_key}_events.json"

            # Check if already processed
            if output_file.exists() and not force and not force_monthly:
                print(f"\n  >> Skipping {month_key} (already exists, use --force or --force-monthly to reprocess)")
                skipped_count += 1
                continue

            print(f"\n  Processing {month_key}...")
            weekly_events = monthly_groups[month_key]

            monthly_data = consolidate_monthly_events(month_key, weekly_events, country, config)

            if monthly_data:
                # Add ATOM search URLs
                for event in monthly_data["events"]:
                    if "source_doc_ids" in event:
                        event["atom_search_url"] = build_hyperlink(event["source_doc_ids"])

                # Save monthly file
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(monthly_data, f, indent=2, ensure_ascii=False)

                monthly_results.append({
                    "month": month_key,
                    "events_count": len(monthly_data["events"]),
                    "weeks_covered": len(weekly_events)
                })

        if skipped_count > 0:
            print(f"\n  >> Skipped {skipped_count} existing months")

        print(f"\n  [SUCCESS] Monthly consolidation complete: {len(monthly_results)} months processed")

        if monthly_only:
            return

    # Overall consolidation
    print("\n\n[OVERALL CONSOLIDATION]")
    print("-" * 80)

    # Load all monthly files
    monthly_dir = Path(events_dir) / country / "monthly"
    if not monthly_dir.exists():
        print("  X No monthly event files found. Run monthly consolidation first.")
        return

    monthly_files = sorted(monthly_dir.glob("*_events.json"))
    monthly_events_list = []

    for monthly_file in monthly_files:
        try:
            with open(monthly_file, 'r', encoding='utf-8') as f:
                monthly_data = json.load(f)
                monthly_events_list.append(monthly_data)
        except Exception as e:
            print(f"  Warning: Error reading {monthly_file}: {e}")

    if not monthly_events_list:
        print("  X No monthly events loaded")
        return

    # Check if overall file already exists
    overall_dir = Path(events_dir) / country
    output_file = overall_dir / f"overall_{start_date.strftime('%Y-%m-%d')}_{end_date.strftime('%Y-%m-%d')}_events.json"

    if output_file.exists() and not force and not force_overall:
        print(f"\n  >> Skipping overall summary (already exists, use --force or --force-overall to reprocess)")
        print(f"  Existing file: {output_file}")
        print(f"\n{'='*80}")
        print("[SUCCESS] CONSOLIDATION COMPLETE (skipped existing overall summary)")
        print(f"{'='*80}\n")
        return

    print(f"  Processing overall summary from {len(monthly_events_list)} months...")

    overall_data = consolidate_overall_events(monthly_events_list, country, start_date, end_date, config)

    if overall_data:
        # Add ATOM search URLs
        for event in overall_data["events"]:
            if "source_doc_ids" in event:
                event["atom_search_url"] = build_hyperlink(event["source_doc_ids"])

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(overall_data, f, indent=2, ensure_ascii=False)

        print(f"\n  [SUCCESS] Overall consolidation complete: {len(overall_data['events'])} major events")
        print(f"  Output: {output_file}")

    print(f"\n{'='*80}")
    print("[SUCCESS] HIERARCHICAL CONSOLIDATION COMPLETE")
    print(f"{'='*80}\n")


# ============================================================================
# COMMAND LINE INTERFACE
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Consolidate daily event extractions into weekly, monthly, and overall summaries"
    )
    parser.add_argument(
        "--country",
        required=True,
        help="Country to process"
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
        "--events-dir",
        default="publications/events",
        help="Events directory (default: publications/events)"
    )
    parser.add_argument(
        "--weekly-only",
        action="store_true",
        help="Only process weekly consolidation"
    )
    parser.add_argument(
        "--monthly-only",
        action="store_true",
        help="Only process monthly consolidation (requires weekly files)"
    )
    parser.add_argument(
        "--overall-only",
        action="store_true",
        help="Only process overall consolidation (requires monthly files)"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force reprocessing of existing files at all levels (default: skip existing)"
    )
    parser.add_argument(
        "--force-monthly",
        action="store_true",
        help="Force reprocessing of monthly files only (leaves weekly unchanged)"
    )
    parser.add_argument(
        "--force-overall",
        action="store_true",
        help="Force reprocessing of overall file only (leaves weekly and monthly unchanged)"
    )

    args = parser.parse_args()

    # Parse dates
    try:
        start_date = datetime.strptime(args.start_date, "%Y-%m-%d")
        end_date = datetime.strptime(args.end_date, "%Y-%m-%d")
    except ValueError as e:
        print(f"Error parsing dates: {e}")
        sys.exit(1)

    # Load config
    config = Config.from_yaml('shared/config/config.yaml')

    # Process
    process_consolidation(
        args.country,
        start_date,
        end_date,
        args.events_dir,
        config,
        args.weekly_only,
        args.monthly_only,
        args.overall_only,
        args.force,
        args.force_monthly,
        args.force_overall
    )


if __name__ == "__main__":
    main()
