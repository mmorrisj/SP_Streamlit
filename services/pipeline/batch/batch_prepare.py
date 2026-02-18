"""
Stage 1: Prepare JSONL input files for OpenAI Batch API.

Queries unprocessed records from the database and generates JSONL files
in OpenAI Batch API format. Creates batch_job records for tracking.

Usage:
    # Cluster deconfliction
    python batch_prepare.py \\
        --job-type cluster_deconflict \\
        --country China \\
        --start-date 2024-08-01 \\
        --end-date 2024-08-31

    # Canonical event deconfliction
    python batch_prepare.py \\
        --job-type canonical_deconflict \\
        --country China \\
        --all-unprocessed

    # Entity extraction
    python batch_prepare.py \\
        --job-type entity_extract \\
        --country China \\
        --min-articles 3

    # Materiality scoring
    python batch_prepare.py \\
        --job-type score_materiality \\
        --country China \\
        --min-articles 3 \\
        --min-days 1

    # Dry run (preview without creating files)
    python batch_prepare.py \\
        --job-type cluster_deconflict \\
        --country China \\
        --dry-run
"""
import argparse
import sys
from pathlib import Path
from datetime import datetime, date as DateType
from typing import List, Dict, Any, Optional

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text
from shared.database.database import get_session
from shared.models.models import (
    EventCluster, Document, InitiatingCountry, RecipientCountry,
    RawEntity, EntityCluster, EntityTypeEnum
)
from services.pipeline.batch.batch_config import (
    JOB_TYPE_CLUSTER_DECONFLICT,
    JOB_TYPE_CANONICAL_DECONFLICT,
    JOB_TYPE_ENTITY_EXTRACT,
    JOB_TYPE_SCORE_MATERIALITY,
    JOB_TYPE_DAILY_ENTITY_EXTRACT,
    JOB_TYPE_ENTITY_DECONFLICT,
    JOB_TYPE_CANONICAL_ENTITY_DECONFLICT,
    JOB_TYPE_GENERATE_DAILY_SUMMARY,
    get_batch_file_path,
    get_model_for_job_type,
    DEFAULT_TEMPERATURE
)
from services.pipeline.batch.batch_tracker import BatchJobTracker
from services.pipeline.batch.utils.custom_id import generate_custom_id
from services.pipeline.batch.utils.jsonl_utils import write_jsonl
from services.pipeline.batch.utils.cost_estimator import calculate_message_tokens


def build_cluster_deconflict_prompt(cluster: EventCluster) -> Dict[str, List[Dict[str, str]]]:
    """
    Build prompt messages for cluster deconfliction.

    Extracts exact prompt template from llm_deconflict_clusters.py:llm_review_cluster()

    Args:
        cluster: EventCluster object

    Returns:
        Dictionary with 'messages' key containing list of message dicts
    """
    unique_names = list(set(cluster.event_names))
    names_list = "\\n".join([f"{i+1}. {name}" for i, name in enumerate(unique_names)])

    sys_prompt = """You are an expert at tracking events across their lifecycle in news coverage.

**CRITICAL UNDERSTANDING:**
Events evolve through stages over time. Your task is to group event names that refer to the SAME underlying event, EVEN IF they are at different stages.

**Event Lifecycle Stages:**
- ANNOUNCEMENT: "China announces Belt and Road Forum"
- PREPARATION: "China preparing for Belt and Road Forum"
- EXECUTION: "Belt and Road Forum begins in Beijing"
- CONTINUATION: "Belt and Road Forum continues with trade deals"
- AFTERMATH: "Belt and Road Forum concludes with 50 agreements"

**Your Task:**
Analyze the following list of event names that were clustered together. Identify which event names refer to the SAME underlying event across different stages, and which are DISTINCT events.

**Context:**
- These events all occurred on the same date
- They are all initiated by the same country
- The clustering algorithm grouped them based on semantic similarity
- The algorithm often groups topically related but DISTINCT events together

**Examples:**

✅ SAME EVENT - Group Together (same event at different stages):
- "China announces South-South Cooperation Forum"
- "Preparations underway for South-South Cooperation Forum"
- "South-South Cooperation Forum opens in Beijing"
- "South-South Cooperation Forum concludes with cooperation agreements"
→ All refer to same forum at different lifecycle stages

✅ SAME EVENT - Group Together (same event, different wording):
- "President Xi visits Egypt for bilateral talks"
- "Xi Jinping state visit to Egypt"
- "China-Egypt summit during Xi's Cairo visit"
→ All refer to same visit

✅ SAME EVENT - Group Together (same event, different aspects):
- "Beijing Declaration", "Beijing Agreement", "Beijing Summit Agreement"
→ All refer to same agreement
- "Arbaeen Pilgrimage", "Arbaeen Pilgrimage Support", "Arbaeen Healthcare Services"
→ All aspects of same pilgrimage event

❌ DIFFERENT EVENTS - Keep Separate (different instances):
- "First China-Arab States Cooperation Forum"
- "Second China-Arab States Cooperation Forum"
→ Different instances of the same type of event

❌ DIFFERENT EVENTS - Keep Separate (different topics with same partner):
- "China signs trade deal with Egypt"
- "China signs defense cooperation with Egypt"
→ Different agreements, even with same country

❌ DIFFERENT EVENTS - Keep Separate (same type, different partners):
- "China signs trade deal with Egypt"
- "China signs trade deal with UAE"
→ Different countries = different events

❌ DIFFERENT EVENTS - Keep Separate (topically related but distinct):
- "Belt and Road Initiative", "Beijing Declaration", "25-year Cooperation Plan"
→ Three separate diplomatic initiatives
- "Humanitarian Aid to Gaza", "Ceasefire Negotiations", "UN Security Council Meeting"
→ Related to same conflict but three distinct events

**Your Goal:**
- Group event names that refer to the SAME core event (even at different stages)
- Keep DISTINCT events in separate groups
- Err on the side of grouping if it's the same core event evolving over time"""

    user_prompt = f"""Event names from cluster (cluster_id={cluster.cluster_id}, size={cluster.cluster_size}):
{names_list}

**ANALYZE USING CHAIN-OF-THOUGHT:**

**STEP 1 - IDENTIFY CORE EVENTS:**
For each event name, extract the core event:
- What is the main activity? (summit, visit, agreement, project, announcement, etc.)
- Who are the key actors? (countries, organizations, leaders)
- What is the context? (location, initiative, purpose)

**STEP 2 - MATCH ACROSS STAGES:**
Group events that share the same core, even if they differ in:
- Stage indicators: "announces", "preparing", "begins", "ongoing", "concludes", "resulted in"
- Temporal markers: "upcoming", "scheduled", "started", "continuing", "ended"
- Outcome language: "will", "plans to", "is", "has", "completed"

**STEP 3 - DISTINGUISH TRULY DIFFERENT EVENTS:**
Keep events SEPARATE if they are:
- Different instances: "First meeting" vs "Second meeting"
- Different topics: "Trade agreement" vs "Defense cooperation" (both with same country)
- Different entities: "China-Egypt summit" vs "China-UAE summit"
- Different projects: "Port project in Egypt" vs "Railway project in Egypt"

**STEP 4 - VALIDATION:**
For each potential group, verify:
- If tracking this event's lifecycle, would all these headlines fit the same timeline?
- Could these be different news sources reporting the SAME event at different stages?
- Or are these genuinely DIFFERENT events (even if similar)?

---

**OUTPUT (JSON format):**
{{
    "reasoning": "Brief overview of your grouping strategy (2-3 sentences)",
    "same_event": true/false,  // true if ALL names refer to ONE event, false if multiple distinct events
    "groups": [[1,2,3], [4,5], [6]],  // group numbers by which events belong together
    "stages_identified": ["announcement", "execution", "aftermath"],  // lifecycle stages present (if applicable)
    "confidence": 0.95  // 0.0-1.0 confidence in your grouping
}}

**Examples:**
- If all {len(unique_names)} names refer to ONE event: {{"reasoning": "...", "same_event": true, "groups": [[{','.join(str(i+1) for i in range(len(unique_names)))}]], "stages_identified": ["execution"], "confidence": 0.95}}
- If there are TWO distinct events: {{"reasoning": "...", "same_event": false, "groups": [[1,2], [3,4,5]], "stages_identified": [], "confidence": 0.90}}
- If there are THREE distinct events: {{"reasoning": "...", "same_event": false, "groups": [[1,2], [3], [4,5,6]], "stages_identified": [], "confidence": 0.85}}

**IMPORTANT:**
- Every number from 1 to {len(unique_names)} must appear in exactly one group
- Create as many groups as there are distinct real-world events
- Group events that are the SAME core event at different lifecycle stages
- Only keep events separate if you're confident they're truly distinct events (confidence >= 0.80)"""

    return {
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt}
        ]
    }


def build_canonical_deconflict_prompt(events: List[Dict]) -> Dict[str, List[Dict[str, str]]]:
    """
    Build prompt messages for canonical event deconfliction.

    Extracts exact prompt template from llm_deconflict_canonical_events.py:llm_review_group()

    Args:
        events: List of event dictionaries with canonical_name, total_articles, days_mentioned

    Returns:
        Dictionary with 'messages' key containing list of message dicts
    """
    event_names = [e['canonical_name'] for e in events]
    names_list = "\\n".join([f"{i+1}. {name} ({events[i]['total_articles']} articles, {events[i]['days_mentioned']} days)"
                           for i, name in enumerate(event_names)])

    sys_prompt = """You are an expert at analyzing event names to determine if they represent the same real-world event.

**Your Task:**
1. Determine if all event names refer to the SAME underlying event (even if phrased differently or at different stages)
2. If they are the same event, pick the BEST canonical name
3. If they are different events that were incorrectly grouped, identify how to split them

**Guidelines for "Same Event":**
✅ Same core event, different stages:
- "Belt and Road Forum announced" vs "Belt and Road Forum begins" vs "Belt and Road Forum concludes"

✅ Same event, different phrasing:
- "China-Egypt Summit" vs "Xi Jinping visits Egypt" vs "Egypt-China bilateral meeting"

✅ Same event, different aspects:
- "Beijing Declaration" vs "Beijing Agreement" vs "Beijing Summit Declaration"

❌ Different events (should split):
- "First China-Arab Forum" vs "Second China-Arab Forum" (different instances)
- "Trade agreement with Egypt" vs "Defense agreement with Egypt" (different topics)
- "China-Egypt summit" vs "China-UAE summit" (different countries)

**Guidelines for Picking Best Name:**
1. Prefer specific over generic: "Belt and Road Forum 2024" > "International Forum"
2. Prefer complete over abbreviated: "One Belt One Road Initiative" > "BRI"
3. Prefer neutral over outcome-focused: "Ceasefire Negotiations" > "Successful Ceasefire Deal"
4. Prefer standard terminology over journalistic: "Presidential Visit" > "Historic Presidential Trip"
5. Consider article count - higher coverage often indicates more accurate naming"""

    user_prompt = f"""Event group to analyze:
{names_list}

**Country:** {events[0].get('initiating_country', 'Unknown')}
**Group size:** {len(events)} events

**Analyze:**
1. Do all these event names refer to the SAME real-world event?
2. If yes, which name is the best canonical name?
3. If no, how should this group be split?

**Output JSON format:**
{{
    "same_event": true/false,
    "best_canonical_name": "The best name from the list (if same_event=true)",
    "reasoning": "2-3 sentence explanation of your decision",
    "should_split": true/false,
    "split_groups": [
        {{"indices": [1,2], "canonical_name": "Best name for this subgroup"}},
        {{"indices": [3,4,5], "canonical_name": "Best name for this subgroup"}}
    ]  // If should_split=true, provide subgroups with their best canonical names
}}

**Examples:**

Example 1 - Same event:
{{
    "same_event": true,
    "best_canonical_name": "Belt and Road Initiative",
    "reasoning": "All names refer to the same Chinese infrastructure initiative, just with different phrasings (BRI, One Belt One Road). The full name 'Belt and Road Initiative' is most widely recognized and specific.",
    "should_split": false,
    "split_groups": []
}}

Example 2 - Should split:
{{
    "same_event": false,
    "best_canonical_name": null,
    "reasoning": "This group contains two distinct events: a trade agreement (names 1,2,3) and a separate defense cooperation agreement (names 4,5). They should be split even though both involve the same countries.",
    "should_split": true,
    "split_groups": [
        {{"indices": [1,2,3], "canonical_name": "China-Egypt Trade Agreement"}},
        {{"indices": [4,5], "canonical_name": "China-Egypt Defense Cooperation Agreement"}}
    ]
}}

Now analyze the event group above and return your assessment as JSON."""

    return {
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt}
        ]
    }


def build_entity_extract_prompt(event: Dict) -> Dict[str, List[Dict[str, str]]]:
    """
    Build prompt messages for entity extraction from canonical events.

    Extracts exact prompt template from extract_canonical_event_entities.py

    Args:
        event: Canonical event dictionary

    Returns:
        Dictionary with 'messages' key containing list of message dicts
    """
    # Format recipients
    recipients = event.get('primary_recipients', {})
    if isinstance(recipients, dict):
        recipients_list = [f"{k} ({v} docs)" for k, v in sorted(recipients.items(), key=lambda x: -x[1])[:5]]
        recipients_str = ', '.join(recipients_list) if recipients_list else 'None'
    else:
        recipients_str = 'None'

    # Format categories
    categories = event.get('primary_categories', {})
    if isinstance(categories, dict):
        categories_list = [f"{k} ({v} docs)" for k, v in sorted(categories.items(), key=lambda x: -x[1])[:5]]
        categories_str = ', '.join(categories_list) if categories_list else 'None'
    else:
        categories_str = 'None'

    # Format key facts
    key_facts = event.get('key_facts', {})
    if isinstance(key_facts, dict) and key_facts:
        facts_list = []
        for key, value in list(key_facts.items())[:10]:
            if isinstance(value, list):
                facts_list.append(f"- {key}: {', '.join(str(v) for v in value[:3])}")
            else:
                facts_list.append(f"- {key}: {value}")
        key_facts_str = '\\n'.join(facts_list) if facts_list else 'None available'
    else:
        key_facts_str = 'None available'

    sys_prompt = """You are analyzing a consolidated soft power event to extract ALL named entities.

Your task is to extract ALL named entities mentioned in this event.

Extract the following entity types:

1. **PERSONS** - Names of individuals mentioned
   - Include their role/title (e.g., "Foreign Minister", "CEO", "President")
   - Include country affiliation
   - Context: What is their role in this event?

2. **ORGANIZATIONS** - Government agencies, NGOs, international bodies, institutions
   - Include type (e.g., "Government Agency", "NGO", "International Organization")
   - Include country of origin
   - Role: What is their function in this event?

3. **COMPANIES** - Businesses, corporations, state-owned enterprises
   - Include sector (e.g., "Technology", "Energy", "Construction", "Finance")
   - Include country of origin
   - Role: What are they doing in this event?

4. **LOCATIONS** - Cities, venues, facilities, infrastructure projects
   - Include type (e.g., "City", "Venue", "Facility", "Infrastructure Project")
   - Include country
   - Significance: Why is this location important to the event?

CRITICAL GUIDELINES:
- Extract ONLY entities explicitly mentioned in the description and key facts
- Use the most complete name form (e.g., "Wang Yi" not just "Minister Wang")
- Use official names for organizations and companies
- Include context that shows HOW the entity is involved in the event
- If the event doesn't mention any entities of a type, return an empty array

Return ONLY a valid JSON object with this structure:
{{
  "persons": [
    {{
      "entity_name": "Wang Yi",
      "role": "Chinese Foreign Minister",
      "country_affiliation": "China",
      "context_snippet": "Led negotiations for the bilateral agreement"
    }}
  ],
  "organizations": [
    {{
      "entity_name": "Iraqi Ministry of Foreign Affairs",
      "type": "Government Agency",
      "country_affiliation": "Iraq",
      "context_snippet": "Signed the cooperation framework"
    }}
  ],
  "companies": [
    {{
      "entity_name": "China State Construction Engineering Corporation",
      "sector": "Construction",
      "country_affiliation": "China",
      "context_snippet": "Awarded contract for infrastructure project"
    }}
  ],
  "locations": [
    {{
      "entity_name": "Baghdad",
      "type": "City",
      "country_affiliation": "Iraq",
      "context_snippet": "Venue for summit meetings"
    }}
  ]
}}

Respond with ONLY the JSON object."""

    user_prompt = f"""Event: {event['canonical_name']}
Initiating Country: {event['initiating_country']}
Recipient Countries: {recipients_str}
Categories: {categories_str}
Date Range: {event['first_mention_date']} to {event['last_mention_date']}
Total Articles: {event.get('total_articles', 0)}

Event Description:
{event.get('consolidated_description', 'No description available')}

Key Facts:
{key_facts_str}

Extract ALL named entities from this event."""

    return {
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt}
        ]
    }


def build_score_materiality_prompt(event: Dict) -> Dict[str, List[Dict[str, str]]]:
    """
    Build prompt messages for materiality scoring of canonical events.

    Extracts exact prompt template from score_canonical_event_materiality.py

    Args:
        event: Canonical event dictionary

    Returns:
        Dictionary with 'messages' key containing list of message dicts
    """
    # Format categories
    categories = event.get('primary_categories', {})
    if isinstance(categories, dict):
        categories_list = [f"{k} ({v} docs)" for k, v in sorted(categories.items(), key=lambda x: -x[1])[:5]]
        categories_str = ', '.join(categories_list) if categories_list else 'None'
    else:
        categories_str = 'None'

    # Format recipients
    recipients = event.get('primary_recipients', {})
    if isinstance(recipients, dict):
        recipients_list = [f"{k} ({v} docs)" for k, v in sorted(recipients.items(), key=lambda x: -x[1])[:5]]
        recipients_str = ', '.join(recipients_list) if recipients_list else 'None'
    else:
        recipients_str = 'None'

    # Format key facts
    key_facts = event.get('key_facts', {})
    if isinstance(key_facts, dict) and key_facts:
        facts_list = []
        for key, value in list(key_facts.items())[:10]:
            if isinstance(value, list):
                facts_list.append(f"- {key}: {', '.join(str(v) for v in value[:3])}")
            else:
                facts_list.append(f"- {key}: {value}")
        key_facts_str = '\\n'.join(facts_list) if facts_list else 'None available'
    else:
        key_facts_str = 'None available'

    sys_prompt = """You are an expert analyst assessing the material impact of soft power events.

**YOUR TASK:**
Assign a materiality score from 1.0 to 10.0 measuring the concrete/substantive nature of this event.

**Scoring Scale:**
- 1-3: Symbolic/rhetorical (statements, cultural events with no material commitments)
- 4-6: Mixed symbolic and material (agreements with unclear implementation, capacity building)
- 7-10: Highly material (concrete infrastructure, specific financial commitments, tangible deliverables)

**Consider:**
- Concrete commitments vs. symbolic gestures
- Specific financial amounts vs. vague promises
- Tangible deliverables vs. aspirational statements
- Implementation status vs. announcements only

**Output JSON format:**
{{
    "material_score": 7.5,
    "justification": "Brief explanation of the score"
}}

**Example 1 - Score 2.5:**
Event: Cultural Festival Participation
Description: Country representatives attended international cultural festival, delivered speeches on cultural cooperation.
Justification: "Purely symbolic participation with no concrete commitments or tangible outcomes beyond statements."

**Example 2 - Score 6.0:**
Event: Renewable Energy Cooperation Agreement
Description: Two countries signed MOU on renewable energy cooperation, established working group for future projects.
Justification: "Agreement shows intent but lacks specific projects, timelines, or financial commitments. Mixed symbolic/material."

**Example 3 - Score 9.0:**
Event: Nuclear Power Plant Construction
Description: Construction began on nuclear power plant with $25B confirmed financing, four reactors with 4,800 MW capacity, completion scheduled by 2030.
Justification: "Major infrastructure project with specific financial commitment ($25B), confirmed construction phase, and tangible deliverables (4,800 MW capacity)."

Respond with ONLY the JSON object."""

    user_prompt = f"""**Event:** {event['canonical_name']}
**Country:** {event['initiating_country']}
**Time Period:** {event['first_mention_date']} to {event['last_mention_date']} ({event.get('total_mention_days', 0)} days mentioned)
**Total Articles:** {event.get('total_articles', 0)}
**Primary Categories:** {categories_str}
**Primary Recipients:** {recipients_str}

**Event Description:**
{event.get('consolidated_description', 'No description available')}

**Key Facts:**
{key_facts_str}

Assign a materiality score (1.0-10.0) to this event."""

    return {
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt}
        ]
    }


def load_canonical_events_for_entity_extraction(
    session,
    country: Optional[str],
    min_articles: int = 1,
    force: bool = False
) -> List[Dict]:
    """
    Load canonical events that need entity extraction.

    Args:
        session: Database session
        country: Filter by country (optional)
        min_articles: Minimum articles threshold
        force: If True, reprocess all events

    Returns:
        List of canonical event dictionaries
    """
    entity_filter = "" if force else "AND (ce.entities_mentioned IS NULL OR ce.entities_mentioned = '{}'::jsonb)"

    query_text = f"""
        SELECT
            ce.id,
            ce.canonical_name,
            ce.initiating_country,
            ce.first_mention_date,
            ce.last_mention_date,
            ce.total_mention_days,
            ce.total_articles,
            ce.consolidated_description,
            ce.key_facts,
            ce.primary_categories,
            ce.primary_recipients
        FROM canonical_events ce
        WHERE ce.master_event_id IS NULL
          AND ce.total_articles >= :min_articles
          {entity_filter}
    """

    params = {'min_articles': min_articles}
    if country:
        query_text += " AND ce.initiating_country = :country"
        params['country'] = country

    query_text += " ORDER BY ce.total_articles DESC NULLS LAST"

    result = session.execute(text(query_text), params).fetchall()

    events = []
    for row in result:
        events.append({
            'id': str(row[0]),
            'canonical_name': row[1],
            'initiating_country': row[2],
            'first_mention_date': str(row[3]) if row[3] else 'N/A',
            'last_mention_date': str(row[4]) if row[4] else 'N/A',
            'total_mention_days': row[5] or 0,
            'total_articles': row[6] or 0,
            'consolidated_description': row[7] or '',
            'key_facts': row[8] or {},
            'primary_categories': row[9] or {},
            'primary_recipients': row[10] or {}
        })

    return events


def load_canonical_events_for_materiality_scoring(
    session,
    country: Optional[str],
    min_articles: int = 1,
    min_days: int = 1,
    rescore: bool = False
) -> List[Dict]:
    """
    Load canonical events that need materiality scoring.

    Args:
        session: Database session
        country: Filter by country (optional)
        min_articles: Minimum articles threshold
        min_days: Minimum days mentioned threshold
        rescore: If True, rescore all events

    Returns:
        List of canonical event dictionaries
    """
    score_filter = "" if rescore else "AND ce.material_score IS NULL"

    query_text = f"""
        SELECT
            ce.id,
            ce.canonical_name,
            ce.initiating_country,
            ce.first_mention_date,
            ce.last_mention_date,
            ce.total_mention_days,
            ce.total_articles,
            ce.consolidated_description,
            ce.key_facts,
            ce.primary_categories,
            ce.primary_recipients
        FROM canonical_events ce
        WHERE ce.master_event_id IS NULL
          AND ce.total_mention_days >= :min_days
          AND ce.total_articles >= :min_articles
          {score_filter}
    """

    params = {'min_days': min_days, 'min_articles': min_articles}
    if country:
        query_text += " AND ce.initiating_country = :country"
        params['country'] = country

    query_text += " ORDER BY ce.total_articles DESC NULLS LAST"

    result = session.execute(text(query_text), params).fetchall()

    events = []
    for row in result:
        events.append({
            'id': str(row[0]),
            'canonical_name': row[1],
            'initiating_country': row[2],
            'first_mention_date': str(row[3]) if row[3] else 'N/A',
            'last_mention_date': str(row[4]) if row[4] else 'N/A',
            'total_mention_days': row[5] or 0,
            'total_articles': row[6] or 0,
            'consolidated_description': row[7] or '',
            'key_facts': row[8] or {},
            'primary_categories': row[9] or {},
            'primary_recipients': row[10] or {}
        })

    return events


def load_unprocessed_clusters(
    session,
    country: Optional[str],
    start_date: Optional[DateType],
    end_date: Optional[DateType]
) -> List[EventCluster]:
    """
    Load unprocessed event clusters from database.

    Args:
        session: Database session
        country: Filter by country (optional)
        start_date: Filter by start date (optional)
        end_date: Filter by end date (optional)

    Returns:
        List of EventCluster objects where llm_deconflicted=False
    """
    query = session.query(EventCluster).filter(
        EventCluster.llm_deconflicted == False,
        EventCluster.is_noise == False
    )

    if country:
        query = query.filter(EventCluster.initiating_country == country)
    if start_date:
        query = query.filter(EventCluster.cluster_date >= start_date)
    if end_date:
        query = query.filter(EventCluster.cluster_date <= end_date)

    # Only process clusters with multiple unique event names
    clusters = query.all()
    filtered_clusters = [c for c in clusters if len(set(c.event_names)) > 1]

    return filtered_clusters


def load_unprocessed_canonical_events(
    session,
    country: Optional[str]
) -> Dict[str, List[Dict]]:
    """
    Load unprocessed canonical event groups from database.

    Args:
        session: Database session
        country: Filter by country (optional)

    Returns:
        Dictionary mapping master_event_id to list of event dicts
    """
    from sqlalchemy import text
    from collections import defaultdict

    # Include both master events and their children in each group
    # so that a master with 1 child correctly forms a group of 2
    query = """
        SELECT
            ce.id,
            ce.canonical_name,
            ce.initiating_country,
            ce.group_id,
            COALESCE(SUM(dem.article_count), 0) as total_articles,
            COUNT(DISTINCT dem.mention_date) as days_mentioned
        FROM (
            -- Children: events assigned to a master
            SELECT id, canonical_name, initiating_country,
                   master_event_id as group_id
            FROM canonical_events
            WHERE master_event_id IS NOT NULL
              AND master_event_id IN (
                  SELECT id FROM canonical_events
                  WHERE master_event_id IS NULL
                  AND (llm_validated = FALSE OR llm_validated IS NULL)
              )

            UNION ALL

            -- Masters: events that have at least one child
            SELECT id, canonical_name, initiating_country,
                   id as group_id
            FROM canonical_events
            WHERE master_event_id IS NULL
              AND (llm_validated = FALSE OR llm_validated IS NULL)
              AND id IN (
                  SELECT DISTINCT master_event_id FROM canonical_events
                  WHERE master_event_id IS NOT NULL
              )
        ) ce
        LEFT JOIN daily_event_mentions dem ON ce.id = dem.canonical_event_id
    """

    params = {}
    if country:
        query += " WHERE ce.initiating_country = :country"
        params['country'] = country

    query += """
        GROUP BY ce.id, ce.canonical_name, ce.initiating_country, ce.group_id
        ORDER BY ce.group_id, total_articles DESC
    """

    result = session.execute(text(query), params).fetchall()

    groups = defaultdict(list)
    for row in result:
        group_id = str(row[3])
        groups[group_id].append({
            'id': row[0],
            'canonical_name': row[1],
            'initiating_country': row[2],
            'master_event_id': row[3],
            'total_articles': row[4],
            'days_mentioned': row[5]
        })

    # Filter groups with 2+ events (master + at least 1 child)
    filtered_groups = {k: v for k, v in groups.items() if len(v) > 1}

    return filtered_groups


def load_unprocessed_entity_clusters(
    session,
    country: Optional[str],
    start_date: Optional[DateType] = None,
    end_date: Optional[DateType] = None
) -> List[EntityCluster]:
    """
    Load unprocessed entity clusters that need LLM deconfliction.

    Only returns clusters with multiple unique entity names (single-name
    clusters are auto-resolved without LLM).

    Args:
        session: Database session
        country: Filter by country (optional)
        start_date: Filter by start date (optional)
        end_date: Filter by end date (optional)

    Returns:
        List of EntityCluster objects where llm_deconflicted=False
    """
    query = session.query(EntityCluster).filter(
        EntityCluster.llm_deconflicted == False,
        EntityCluster.is_noise == False
    )

    if country:
        query = query.filter(EntityCluster.initiating_country == country)
    if start_date:
        query = query.filter(EntityCluster.cluster_date >= start_date)
    if end_date:
        query = query.filter(EntityCluster.cluster_date <= end_date)

    clusters = query.order_by(
        EntityCluster.initiating_country,
        EntityCluster.cluster_date,
        EntityCluster.entity_type,
        EntityCluster.batch_number
    ).all()

    # Only include clusters with multiple unique entity names
    filtered = [c for c in clusters if len(set(c.entity_names)) > 1]

    return filtered


def build_entity_deconflict_prompt(cluster: EntityCluster) -> Dict[str, List[Dict[str, str]]]:
    """
    Build prompt messages for entity cluster deconfliction.

    Adapted from llm_deconflict_entity_clusters.py:llm_review_cluster()

    Args:
        cluster: EntityCluster object

    Returns:
        Dictionary with 'messages' key containing list of message dicts
    """
    unique_names = list(set(cluster.entity_names))
    names_list = "\\n".join([f"{i+1}. {name}" for i, name in enumerate(unique_names)])
    entity_type_label = cluster.entity_type.value.upper()

    # Build entity-type-specific guidelines
    guidelines = ""
    if cluster.entity_type == EntityTypeEnum.PERSON:
        guidelines = """**PERSONS:**
- Same person: 'Wang Yi', 'Chinese FM Wang Yi', 'Foreign Minister Wang Yi', 'FM Wang'
- Same person: 'Xi Jinping', 'President Xi', 'Chinese President Xi Jinping'
- Different persons: 'Wang Yi' vs 'Wang Li' (different people with same surname)
- Different persons: 'President Xi' vs 'Premier Li' (different officials)"""
    elif cluster.entity_type == EntityTypeEnum.ORGANIZATION:
        guidelines = """**ORGANIZATIONS:**
- Same org: 'Ministry of Foreign Affairs', 'MFA', 'Chinese Foreign Ministry'
- Same org: 'Shanghai Cooperation Organization', 'SCO'
- Different orgs: 'Ministry of Foreign Affairs' vs 'Ministry of Defense' (different ministries)"""
    elif cluster.entity_type == EntityTypeEnum.COMPANY:
        guidelines = """**COMPANIES:**
- Same company: 'CNOOC', 'China National Offshore Oil Corporation'
- Same company: 'Huawei', 'Huawei Technologies Co.'
- Different companies: 'CNOOC' vs 'Sinopec' (different oil companies)"""
    elif cluster.entity_type == EntityTypeEnum.LOCATION:
        guidelines = """**LOCATIONS:**
- Same location: 'Beijing', 'China's capital', 'Beijing, China'
- Same location: 'Middle East', 'Middle Eastern region'
- Different locations: 'Beijing' vs 'Shanghai' (different cities)"""

    sys_prompt = f"""You are an expert at entity resolution and disambiguation for {entity_type_label} entities.

**CRITICAL UNDERSTANDING:**
Your task is to determine if the following entity names refer to the SAME real-world entity, or if they are DIFFERENT entities that were incorrectly clustered together.

**Context:**
- Entity type: {entity_type_label}
- These entities were mentioned on the same date
- They are all associated with the same country
- The clustering algorithm grouped them based on semantic similarity
- Names may vary due to: titles, abbreviations, alternative spellings, or contexts

{guidelines}

**Your Goal:**
- Group names that refer to the SAME real-world entity
- Keep DISTINCT entities in separate groups
- Choose the best canonical name (most complete, professional, commonly used)
- Identify the primary role/function of the entity
- Identify the primary country affiliation"""

    user_prompt = f"""Entity names from cluster (type={entity_type_label}, size={cluster.cluster_size}):
{names_list}

**ANALYZE USING CHAIN-OF-THOUGHT:**

**STEP 1 - IDENTIFY CORE ENTITY:**
For each name, extract:
- Who/what is this? (full name, title, abbreviation)
- What roles/titles are mentioned?
- What country affiliations are mentioned?

**STEP 2 - CHECK IF SAME ENTITY:**
Do these names refer to the SAME real-world {entity_type_label}?
- Look for: name variations, abbreviations, title differences
- Check for: same person/org with different titles/contexts
- Distinguish: truly different entities with similar names

**STEP 3 - PROVIDE DECISION:**
Return a JSON object with:
{{
  "same_entity": true/false,
  "explanation": "Brief reasoning for your decision",
  "canonical_name": "Best canonical name for this entity",
  "primary_role": "One of: government_official, diplomat, business_leader, cultural_figure, military_official, academic, media_figure, civil_society, implementing_organization, funding_organization, recipient_institution, infrastructure_project, venue, other",
  "country_affiliation": "Primary country affiliation",
  "groups": [[list of indices that belong to same entity], [another group if split]]
}}

**IMPORTANT:**
- If same_entity=true: all names go in one group, provide canonical_name
- If same_entity=false: split into multiple groups
- Groups use 1-based indices (1, 2, 3, etc.)

Return ONLY the JSON object, no additional text."""

    return {
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt}
        ]
    }


VALID_ENTITY_ROLES = [
    "government_official", "diplomat", "business_leader", "cultural_figure",
    "military_official", "academic", "media_figure", "civil_society",
    "implementing_organization", "funding_organization", "recipient_institution",
    "infrastructure_project", "venue", "other"
]


def build_canonical_entity_deconflict_prompt(entities: List[Dict]) -> Dict[str, List[Dict[str, str]]]:
    """
    Build prompt messages for canonical entity group deconfliction.

    Adapted from llm_deconflict_canonical_entities.py:llm_review_group()

    Args:
        entities: List of entity dicts with canonical_name, entity_type, primary_role,
                  country_affiliations, alternative_names, entity_description,
                  total_documents, days_mentioned

    Returns:
        Dictionary with 'messages' key containing list of message dicts
    """
    entity_lines = []
    for i, e in enumerate(entities):
        line = f"{i+1}. \"{e['canonical_name']}\""
        line += f" ({e['total_documents']} docs, {e['days_mentioned']} days)"
        if e.get('primary_role'):
            line += f" [role: {e['primary_role']}]"
        if e.get('country_affiliations'):
            affiliations = e['country_affiliations']
            if isinstance(affiliations, list):
                line += f" [affiliations: {', '.join(affiliations[:5])}]"
        if e.get('alternative_names'):
            alt_names = e['alternative_names']
            if isinstance(alt_names, list):
                line += f" [aliases: {', '.join(alt_names[:3])}]"
        if e.get('entity_description'):
            desc = str(e['entity_description'])[:100]
            line += f" [desc: {desc}]"
        entity_lines.append(line)

    names_list = "\\n".join(entity_lines)
    entity_type = entities[0].get('entity_type', 'unknown')

    sys_prompt = f"""You are an expert at analyzing entity names to determine if they represent the same real-world {entity_type}.

**Your Task:**
1. Determine if all entity names refer to the SAME real-world {entity_type} (even if spelled differently or using aliases)
2. If they are the same entity, pick the BEST canonical name
3. Pick the best primary_role from the allowed values
4. If they are different entities that were incorrectly grouped, identify how to split them

**Guidelines for "Same Entity":**
For PERSON type:
  - Same person, different name forms: "Xi Jinping" vs "President Xi" vs "Xi"
  - Same person, different transliterations: "Mohammed bin Salman" vs "MBS" vs "Muhammad bin Salman"
  - Different people with same/similar name: SPLIT these (e.g., "Wang Wei" the diplomat vs "Wang Wei" the artist)

For ORGANIZATION type:
  - Same org, different abbreviations: "United Nations" vs "UN"
  - Same org, different branches: Consider if they function as one entity or distinct units
  - Different orgs with similar names: SPLIT these

For COMPANY type:
  - Same company, different name forms: "Huawei Technologies" vs "Huawei"
  - Parent vs subsidiary: Generally SPLIT unless they're commonly referred to interchangeably

**Guidelines for Picking Best Name:**
1. Prefer full formal name over abbreviations: "Xi Jinping" > "Xi"
2. Prefer widely recognized form: "Huawei" > "Huawei Technologies Co., Ltd."
3. Prefer standard English transliteration for non-English names
4. Consider document count - higher coverage often indicates more standard naming

**Allowed primary_role values:**
{', '.join(VALID_ENTITY_ROLES)}"""

    user_prompt = f"""Entity group to analyze:
{names_list}

**Entity Type:** {entity_type}
**Country:** {entities[0].get('initiating_country', 'Unknown')}
**Group size:** {len(entities)} entities

**Analyze:**
1. Do all these entity names refer to the SAME real-world {entity_type}?
2. If yes, which name is the best canonical name?
3. What is the best primary_role for this entity?
4. If no, how should this group be split?

**Output JSON format:**
{{
    "same_entity": true/false,
    "best_canonical_name": "The best name from the list (if same_entity=true)",
    "best_primary_role": "one of the allowed role values",
    "reasoning": "2-3 sentence explanation of your decision",
    "should_split": true/false,
    "split_groups": [
        {{"indices": [1,2], "canonical_name": "Best name for subgroup", "primary_role": "role"}},
        {{"indices": [3,4,5], "canonical_name": "Best name for subgroup", "primary_role": "role"}}
    ]
}}

Now analyze the entity group above and return your assessment as JSON."""

    return {
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt}
        ]
    }


def load_unprocessed_canonical_entity_groups(
    session,
    country: Optional[str]
) -> Dict[str, List[Dict]]:
    """
    Load consolidated canonical entity groups needing LLM validation.

    Adapted from llm_deconflict_canonical_entities.py:load_entity_groups()

    Args:
        session: Database session
        country: Filter by country (optional)

    Returns:
        Dictionary mapping master_entity_id to list of entity dicts
    """
    from collections import defaultdict

    # Load child entities (those with master_entity_id set)
    query = """
        SELECT
            ce.id,
            ce.canonical_name,
            ce.initiating_country,
            ce.entity_type,
            ce.primary_role,
            ce.master_entity_id,
            ce.alternative_names,
            ce.country_affiliations,
            ce.entity_description,
            COALESCE(SUM(dem.document_count), 0) as total_documents,
            COUNT(DISTINCT dem.mention_date) as days_mentioned
        FROM canonical_entities ce
        LEFT JOIN daily_entity_mentions dem ON ce.id = dem.canonical_entity_id
        WHERE ce.master_entity_id IS NOT NULL
          AND ce.master_entity_id IN (
              SELECT id FROM canonical_entities
              WHERE master_entity_id IS NULL
              AND (llm_validated = FALSE OR llm_validated IS NULL)
          )
    """

    params = {}
    if country:
        query += " AND ce.initiating_country = :country"
        params['country'] = country

    query += """
        GROUP BY ce.id, ce.canonical_name, ce.initiating_country, ce.entity_type,
                 ce.primary_role, ce.master_entity_id, ce.alternative_names,
                 ce.country_affiliations, ce.entity_description
        ORDER BY ce.master_entity_id, total_documents DESC
    """

    result = session.execute(text(query), params).fetchall()

    groups = defaultdict(list)
    for row in result:
        master_id = str(row[5])
        groups[master_id].append({
            'id': str(row[0]),
            'canonical_name': row[1],
            'initiating_country': row[2],
            'entity_type': str(row[3]) if row[3] else None,
            'primary_role': str(row[4]) if row[4] else None,
            'master_entity_id': str(row[5]),
            'alternative_names': row[6] or [],
            'country_affiliations': row[7] or [],
            'entity_description': row[8],
            'total_documents': row[9],
            'days_mentioned': row[10]
        })

    # Also load master entities themselves
    master_query = """
        SELECT
            ce.id,
            ce.canonical_name,
            ce.initiating_country,
            ce.entity_type,
            ce.primary_role,
            ce.alternative_names,
            ce.country_affiliations,
            ce.entity_description,
            COALESCE(SUM(dem.document_count), 0) as total_documents,
            COUNT(DISTINCT dem.mention_date) as days_mentioned
        FROM canonical_entities ce
        LEFT JOIN daily_entity_mentions dem ON ce.id = dem.canonical_entity_id
        WHERE ce.master_entity_id IS NULL
          AND (ce.llm_validated = FALSE OR ce.llm_validated IS NULL)
          AND EXISTS (
              SELECT 1 FROM canonical_entities child
              WHERE child.master_entity_id = ce.id
          )
    """

    if country:
        master_query += " AND ce.initiating_country = :country"

    master_query += """
        GROUP BY ce.id, ce.canonical_name, ce.initiating_country, ce.entity_type,
                 ce.primary_role, ce.alternative_names, ce.country_affiliations,
                 ce.entity_description
    """

    master_result = session.execute(text(master_query), params).fetchall()

    for row in master_result:
        master_id = str(row[0])
        if master_id in groups:
            groups[master_id].insert(0, {
                'id': str(row[0]),
                'canonical_name': row[1],
                'initiating_country': row[2],
                'entity_type': str(row[3]) if row[3] else None,
                'primary_role': str(row[4]) if row[4] else None,
                'master_entity_id': None,
                'alternative_names': row[5] or [],
                'country_affiliations': row[6] or [],
                'entity_description': row[7],
                'total_documents': row[8],
                'days_mentioned': row[9]
            })

    # Filter groups with 2+ entities (single-entity groups don't need LLM)
    filtered_groups = {k: v for k, v in groups.items() if len(v) > 1}

    return filtered_groups


def load_events_needing_daily_summaries(
    session,
    country: str,
    start_date: DateType,
    end_date: DateType
) -> List[Dict]:
    """
    Load master events that need daily summaries across a date range.

    For each date in the range, queries active master events with ≥3 articles,
    checks for existing EventSummary records, and collects representative
    document samples for prompt generation.

    Args:
        session: Database session
        country: Initiating country (required)
        start_date: Start date (inclusive)
        end_date: End date (inclusive)

    Returns:
        List of dicts, each representing one (event, date) pair ready for
        prompt generation. Each dict contains:
        - master_id, date_str, canonical_name, country, article_count,
          categories, recipients, article_samples, doc_ids
    """
    from datetime import timedelta
    from sqlalchemy import select

    events_to_process = []
    current_date = start_date

    while current_date <= end_date:
        # Query active master events for this date (same CTE as generate_daily_summaries.py)
        query = text("""
            WITH master_events AS (
                SELECT
                    ce.id as master_id,
                    ce.canonical_name,
                    ce.primary_categories,
                    ce.primary_recipients
                FROM canonical_events ce
                WHERE ce.master_event_id IS NULL
                  AND ce.initiating_country = :country
                  AND ce.first_mention_date <= :date
                  AND ce.last_mention_date >= :date
            ),
            event_family AS (
                SELECT
                    me.master_id,
                    me.canonical_name,
                    me.primary_categories,
                    me.primary_recipients,
                    ce.id as canonical_event_id
                FROM master_events me
                LEFT JOIN canonical_events ce ON (
                    ce.master_event_id = me.master_id OR ce.id = me.master_id
                )
            ),
            daily_mentions AS (
                SELECT
                    dem.canonical_event_id,
                    dem.doc_ids
                FROM daily_event_mentions dem
                WHERE dem.mention_date = :date
            )
            SELECT
                ef.master_id,
                ef.canonical_name,
                ef.primary_categories,
                ef.primary_recipients,
                COALESCE(
                    array_agg(DISTINCT unnested_doc ORDER BY unnested_doc)
                    FILTER (WHERE unnested_doc IS NOT NULL),
                    ARRAY[]::text[]
                ) as doc_ids,
                COUNT(DISTINCT unnested_doc)
                FILTER (WHERE unnested_doc IS NOT NULL) as article_count
            FROM event_family ef
            LEFT JOIN daily_mentions dm ON dm.canonical_event_id = ef.canonical_event_id
            LEFT JOIN LATERAL unnest(dm.doc_ids) unnested_doc ON true
            GROUP BY ef.master_id, ef.canonical_name, ef.primary_categories, ef.primary_recipients
            HAVING COUNT(DISTINCT unnested_doc) FILTER (WHERE unnested_doc IS NOT NULL) >= 3
            ORDER BY article_count DESC
        """)

        result = session.execute(
            query, {"country": country, "date": current_date}
        ).fetchall()

        for row in result:
            master_id = row.master_id
            canonical_name = row.canonical_name
            doc_ids = list(row.doc_ids) if row.doc_ids else []

            # Check if summary already exists (use raw SQL to avoid model/DB column mismatch)
            existing_check = session.execute(text("""
                SELECT 1 FROM event_summaries
                WHERE period_type = :period_type
                  AND period_start = :period_start
                  AND period_end = :period_end
                  AND initiating_country = :country
                  AND event_name = :event_name
                LIMIT 1
            """), {
                'period_type': 'DAILY',
                'period_start': current_date,
                'period_end': current_date,
                'country': country,
                'event_name': canonical_name
            }).fetchone()

            if existing_check:
                continue

            if not doc_ids:
                continue

            # Select representative docs (5 most recent)
            stmt = (
                select(Document)
                .where(Document.doc_id.in_(doc_ids))
                .order_by(Document.date.desc())
                .limit(5)
            )
            representative_docs = list(session.execute(stmt).scalars().all())

            if not representative_docs:
                continue

            # Format article samples
            samples = []
            for i, doc in enumerate(representative_docs, 1):
                samples.append(f"[{i}] {doc.title}\n"
                               f"Source: {doc.source_name}\n"
                               f"Date: {doc.date.strftime('%B %d, %Y') if doc.date else 'Unknown'}\n"
                               f"Excerpt: {doc.distilled_text[:500] if doc.distilled_text else doc.title[:500] if doc.title else 'No text available'}...\n")
            article_samples = "\n".join(samples)

            # Extract categories and recipients
            categories = list(row.primary_categories.keys()) if row.primary_categories else []
            recipients = list(row.primary_recipients.keys()) if row.primary_recipients else []

            events_to_process.append({
                'master_id': str(master_id),
                'date_str': current_date.strftime('%Y-%m-%d'),
                'date_formatted': current_date.strftime('%B %d, %Y'),
                'canonical_name': canonical_name,
                'country': country,
                'article_count': row.article_count,
                'categories': categories,
                'recipients': recipients,
                'article_samples': article_samples,
                'doc_ids': doc_ids
            })

        current_date += timedelta(days=1)

    return events_to_process


def build_daily_summary_prompt(event_data: Dict) -> Dict[str, List[Dict[str, str]]]:
    """
    Build prompt messages for daily summary generation.

    Uses the DAILY_SUMMARY_PROMPT template from summary_prompts.py.

    Args:
        event_data: Dict with canonical_name, country, date_formatted,
                    article_count, article_samples, categories, recipients

    Returns:
        Dictionary with 'messages' key containing list of message dicts
    """
    from services.pipeline.summaries.summary_prompts import DAILY_SUMMARY_PROMPT

    prompt = DAILY_SUMMARY_PROMPT.format(
        country=event_data['country'],
        date=event_data['date_formatted'],
        event_name=event_data['canonical_name'],
        article_count=event_data['article_count'],
        article_samples=event_data['article_samples'],
        categories=', '.join(event_data['categories']),
        recipients=', '.join(event_data['recipients'])
    )

    sys_prompt = "You are an experienced journalist writing in Associated Press (AP) style. Follow the instructions exactly and output valid JSON only."

    return {
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": prompt}
        ]
    }


def build_daily_entity_extract_prompt(doc: Dict) -> Dict[str, List[Dict[str, str]]]:
    """
    Build prompt for extracting entities from a document.

    Extracts entities from extract_daily_entities.py prompt.

    Args:
        doc: Document dictionary with metadata

    Returns:
        OpenAI API messages format
    """
    sys_prompt = "You are an expert at named entity recognition, specializing in diplomatic and geopolitical documents. Extract entities with precise categorization and contextual information."

    user_prompt = f"""You are analyzing a diplomatic document to extract named entities.

Document Metadata:
- Date: {doc['date']}
- Initiating Country: {doc['initiating_country']}
- Recipient Countries: {doc['recipient_countries']}
- Categories: {doc['categories']}
- Source: {doc['source_name']}

Document Text:
{doc['distilled_text'][:4000]}

Your task is to extract ALL named entities mentioned in this document.

Extract the following entity types:

1. **PERSONS** - Names of individuals mentioned
   - Include their role/title (e.g., "Foreign Minister", "CEO", "President")
   - Include country affiliation (which country they represent/work for)
   - Context: What are they doing in this document? (1-2 sentences)

2. **ORGANIZATIONS** - Government agencies, NGOs, international bodies, institutions
   - Include type (e.g., "Government Agency", "NGO", "International Organization")
   - Include country of origin
   - Role: What is their function in this context?

3. **COMPANIES** - Businesses, corporations, state-owned enterprises
   - Include sector (e.g., "Technology", "Energy", "Construction", "Finance")
   - Include country of origin
   - Role: What are they doing in this document?

4. **LOCATIONS** - Cities, venues, facilities, infrastructure projects
   - Include type (e.g., "City", "Venue", "Facility", "Infrastructure Project")
   - Include country
   - Significance: Why is this location mentioned?

CRITICAL GUIDELINES:
- Extract ONLY entities explicitly mentioned in the text
- For persons: Use the most complete name form (e.g., "Wang Yi" not just "Minister Wang")
- For organizations: Use official names (e.g., "Chinese Ministry of Foreign Affairs" not "MFA")
- For companies: Include full legal names when available
- Include context snippets that show HOW the entity is involved
- If the document doesn't mention any entities of a type, return an empty array for that type

Return ONLY a valid JSON object with this structure:
{{
  "persons": [
    {{
      "entity_name": "Wang Yi",
      "role": "Chinese Foreign Minister",
      "country_affiliation": "China",
      "context_snippet": "Wang Yi met with his Iraqi counterpart to discuss bilateral cooperation"
    }}
  ],
  "organizations": [
    {{
      "entity_name": "Iraqi Atomic Energy Commission",
      "role": "Government agency overseeing nuclear programs",
      "country_affiliation": "Iraq",
      "context_snippet": "The Iraqi Atomic Energy Commission signed the framework agreement"
    }}
  ],
  "companies": [
    {{
      "entity_name": "China Atomic Energy Company",
      "role": "State-owned nuclear energy contractor",
      "country_affiliation": "China",
      "context_snippet": "China Atomic Energy Company signed a contract to build Iraq's first nuclear training reactor"
    }}
  ],
  "locations": [
    {{
      "entity_name": "Al-Tuwaitha Complex",
      "role": "Nuclear research facility",
      "country_affiliation": "Iraq",
      "context_snippet": "The reactor will be built at the Al-Tuwaitha Complex near Baghdad"
    }}
  ]
}}"""

    return {
        'messages': [
            {'role': 'system', 'content': sys_prompt},
            {'role': 'user', 'content': user_prompt}
        ]
    }


def load_documents_for_entity_extraction(
    session,
    country: str,
    start_date: Optional[str],
    end_date: Optional[str],
    force: bool = False
) -> List[Dict]:
    """
    Load documents needing entity extraction.

    Applies the same filtering logic as extract_daily_entities.py:
    - Filters by initiating country
    - Filters by valid recipient countries from config.yaml (excluding self-referential)
    - Filters by date range
    - Excludes documents already processed (unless force=True)

    Args:
        session: Database session
        country: Initiating country
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        force: Force reprocessing

    Returns:
        List of document dictionaries
    """
    from datetime import datetime
    from sqlalchemy import and_
    from shared.utils.utils import Config
    from pathlib import Path

    # Load config to get valid recipients (same as extract_daily_entities.py)
    config_path = Path(__file__).parent.parent.parent.parent / 'shared' / 'config' / 'config.yaml'
    config = Config.from_yaml(config_path)
    valid_recipients = [r for r in config.recipients if r != country]

    print(f"Filtering documents for {country} with {len(valid_recipients)} valid recipient countries")

    # Build date filters
    date_filters = []
    if start_date:
        date_filters.append(Document.date >= datetime.strptime(start_date, '%Y-%m-%d').date())
    if end_date:
        date_filters.append(Document.date <= datetime.strptime(end_date, '%Y-%m-%d').date())

    # Get documents already processed (if not force mode)
    processed_doc_ids = set()
    if not force:
        processed_docs = session.query(RawEntity.doc_id).distinct().all()
        processed_doc_ids = {doc_id for (doc_id,) in processed_docs}

    # Query documents with RecipientCountry join and filtering (same as extract_daily_entities.py)
    query = session.query(Document).join(
        InitiatingCountry,
        Document.doc_id == InitiatingCountry.doc_id
    ).join(
        RecipientCountry,
        Document.doc_id == RecipientCountry.doc_id
    ).filter(
        and_(
            InitiatingCountry.initiating_country == country,
            RecipientCountry.recipient_country.in_(valid_recipients),
            RecipientCountry.recipient_country != country,  # Exclude self-referential
            Document.distilled_text != None,
            Document.distilled_text != '',
            *date_filters
        )
    ).distinct()  # Distinct to avoid duplicates from multiple recipients

    # Exclude already processed
    if processed_doc_ids:
        query = query.filter(~Document.doc_id.in_(processed_doc_ids))

    documents = query.all()  # No limit - will be chunked later

    print(f"Found {len(documents)} documents needing entity extraction (filtered by valid recipients)")

    # Convert to dictionaries
    result = []
    for doc in documents:
        # Get metadata
        initiating_countries = [ic.initiating_country for ic in doc.initiating_countries]
        recipient_countries = [rc.recipient_country for rc in doc.recipient_countries]
        categories = [c.category for c in doc.categories]

        result.append({
            'doc_id': doc.doc_id,
            'date': doc.date.strftime("%Y-%m-%d") if doc.date else "Unknown",
            'initiating_country': ", ".join(initiating_countries) if initiating_countries else "Unknown",
            'recipient_countries': ", ".join(recipient_countries) if recipient_countries else "Unknown",
            'categories': ", ".join(categories) if categories else "Unknown",
            'source_name': doc.source_name or "Unknown",
            'distilled_text': doc.distilled_text[:4000]  # Limit for token management
        })

    return result


def generate_batch_requests(
    job_type: str,
    records: List[Any],
    model: str
) -> List[Dict[str, Any]]:
    """
    Generate batch API requests from database records.

    Args:
        job_type: Job type
        records: List of database records (EventCluster or event groups)
        model: Model name

    Returns:
        List of batch request dictionaries in OpenAI format
    """
    batch_requests = []

    if job_type == JOB_TYPE_CLUSTER_DECONFLICT:
        for cluster in records:
            custom_id = generate_custom_id(job_type, cluster.id)
            prompt_data = build_cluster_deconflict_prompt(cluster)

            batch_requests.append({
                "custom_id": custom_id,
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": {
                    "model": model,
                    "messages": prompt_data["messages"],
                    "temperature": DEFAULT_TEMPERATURE,
                    "response_format": {"type": "json_object"}
                }
            })

    elif job_type == JOB_TYPE_CANONICAL_DECONFLICT:
        # records is a dict mapping master_event_id to list of events
        for master_id, events in records.items():
            custom_id = generate_custom_id(job_type, events[0]['master_event_id'])
            prompt_data = build_canonical_deconflict_prompt(events)

            batch_requests.append({
                "custom_id": custom_id,
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": {
                    "model": model,
                    "messages": prompt_data["messages"],
                    "temperature": DEFAULT_TEMPERATURE,
                    "response_format": {"type": "json_object"}
                }
            })

    elif job_type == JOB_TYPE_ENTITY_EXTRACT:
        # records is a list of canonical events needing entity extraction
        for event in records:
            custom_id = generate_custom_id(job_type, event['id'])
            prompt_data = build_entity_extract_prompt(event)

            batch_requests.append({
                "custom_id": custom_id,
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": {
                    "model": model,
                    "messages": prompt_data["messages"],
                    "temperature": DEFAULT_TEMPERATURE,
                    "response_format": {"type": "json_object"}
                }
            })

    elif job_type == JOB_TYPE_SCORE_MATERIALITY:
        # records is a list of canonical events needing materiality scoring
        for event in records:
            custom_id = generate_custom_id(job_type, event['id'])
            prompt_data = build_score_materiality_prompt(event)

            batch_requests.append({
                "custom_id": custom_id,
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": {
                    "model": model,
                    "messages": prompt_data["messages"],
                    "temperature": DEFAULT_TEMPERATURE,
                    "response_format": {"type": "json_object"}
                }
            })

    elif job_type == JOB_TYPE_DAILY_ENTITY_EXTRACT:
        # records is a list of documents needing entity extraction
        for doc in records:
            custom_id = generate_custom_id(job_type, doc['doc_id'])
            prompt_data = build_daily_entity_extract_prompt(doc)

            batch_requests.append({
                "custom_id": custom_id,
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": {
                    "model": model,
                    "messages": prompt_data["messages"],
                    "temperature": DEFAULT_TEMPERATURE,
                    "response_format": {"type": "json_object"}
                }
            })

    elif job_type == JOB_TYPE_ENTITY_DECONFLICT:
        # records is a list of EntityCluster objects needing LLM deconfliction
        for cluster in records:
            custom_id = generate_custom_id(job_type, cluster.id)
            prompt_data = build_entity_deconflict_prompt(cluster)

            batch_requests.append({
                "custom_id": custom_id,
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": {
                    "model": model,
                    "messages": prompt_data["messages"],
                    "temperature": DEFAULT_TEMPERATURE,
                    "response_format": {"type": "json_object"}
                }
            })

    elif job_type == JOB_TYPE_CANONICAL_ENTITY_DECONFLICT:
        # records is a dict mapping master_entity_id to list of entity dicts
        for master_id, entities in records.items():
            custom_id = generate_custom_id(job_type, master_id)
            prompt_data = build_canonical_entity_deconflict_prompt(entities)

            batch_requests.append({
                "custom_id": custom_id,
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": {
                    "model": model,
                    "messages": prompt_data["messages"],
                    "temperature": DEFAULT_TEMPERATURE,
                    "response_format": {"type": "json_object"}
                }
            })

    elif job_type == JOB_TYPE_GENERATE_DAILY_SUMMARY:
        # records is a list of (event, date) dicts needing daily summaries
        for event_data in records:
            custom_id = generate_custom_id(
                job_type, event_data['master_id'],
                suffix=event_data['date_str']
            )
            prompt_data = build_daily_summary_prompt(event_data)

            batch_requests.append({
                "custom_id": custom_id,
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": {
                    "model": model,
                    "messages": prompt_data["messages"],
                    "temperature": DEFAULT_TEMPERATURE,
                    "response_format": {"type": "json_object"}
                }
            })

    return batch_requests


def chunk_records(records, chunk_size: int = 10000):
    """
    Split records into chunks for reliable batch uploads.

    Default chunk size of 10K keeps file sizes ~38MB for documents with large text.
    OpenAI's max is 50K but large files (>70MB) timeout during upload.

    Handles both list records and dict records (e.g., canonical_deconflict
    returns a dict mapping master_event_id to event lists).

    Args:
        records: List or Dict of records to chunk
        chunk_size: Maximum records per chunk (default: 10000)

    Returns:
        List of record chunks (same type as input)
    """
    if isinstance(records, dict):
        items = list(records.items())
        chunks = []
        for i in range(0, len(items), chunk_size):
            chunks.append(dict(items[i:i + chunk_size]))
        return chunks
    else:
        chunks = []
        for i in range(0, len(records), chunk_size):
            chunks.append(records[i:i + chunk_size])
        return chunks


def main():
    parser = argparse.ArgumentParser(
        description="Stage 1: Prepare JSONL input files for OpenAI Batch API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    # Job configuration
    parser.add_argument('--job-type', required=True,
                       choices=[JOB_TYPE_CLUSTER_DECONFLICT, JOB_TYPE_CANONICAL_DECONFLICT,
                               JOB_TYPE_ENTITY_EXTRACT, JOB_TYPE_SCORE_MATERIALITY,
                               JOB_TYPE_DAILY_ENTITY_EXTRACT, JOB_TYPE_ENTITY_DECONFLICT,
                               JOB_TYPE_CANONICAL_ENTITY_DECONFLICT, JOB_TYPE_GENERATE_DAILY_SUMMARY],
                       help='Type of batch job to prepare')
    parser.add_argument('--model', type=str,
                       help='OpenAI model to use (default: auto-detect from job type)')

    # Scope filters
    parser.add_argument('--country', type=str, help='Filter by initiating country')
    parser.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD)')
    parser.add_argument('--all-unprocessed', action='store_true',
                       help='Process all unprocessed records (ignores date filters)')

    # Entity extraction specific
    parser.add_argument('--min-articles', type=int, default=3,
                       help='Minimum articles for entity extraction/materiality scoring (default: 3)')
    parser.add_argument('--force', action='store_true',
                       help='Force entity extraction even if already processed')

    # Materiality scoring specific
    parser.add_argument('--min-days', type=int, default=1,
                       help='Minimum days for materiality scoring (default: 1)')
    parser.add_argument('--rescore', action='store_true',
                       help='Rescore events even if already scored')

    # Output configuration
    parser.add_argument('--output', type=str, help='Output JSONL file path (optional, auto-generated if not provided)')
    parser.add_argument('--dry-run', action='store_true', help='Preview without creating files or database records')
    parser.add_argument('--verbose', action='store_true', default=True, help='Verbose output')

    args = parser.parse_args()

    # Parse dates
    start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date() if args.start_date else None
    end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date() if args.end_date else None

    # Get model
    model = args.model or get_model_for_job_type(args.job_type)

    print("=" * 80)
    print("BATCH PREPARE - Stage 1: Generate JSONL Input File")
    print("=" * 80)
    print(f"Job type: {args.job_type}")
    print(f"Model: {model}")
    print(f"Country: {args.country or 'All'}")
    print(f"Date range: {start_date or 'All'} to {end_date or 'All'}")
    if args.dry_run:
        print("[DRY RUN MODE] No files or database records will be created")
    print("=" * 80)
    print()

    with get_session() as session:
        # Load unprocessed records
        print("Loading unprocessed records from database...")

        if args.job_type == JOB_TYPE_CLUSTER_DECONFLICT:
            records = load_unprocessed_clusters(session, args.country, start_date, end_date)
            print(f"Found {len(records)} unprocessed event clusters")

        elif args.job_type == JOB_TYPE_CANONICAL_DECONFLICT:
            records = load_unprocessed_canonical_events(session, args.country)
            print(f"Found {len(records)} unprocessed canonical event groups")

        elif args.job_type == JOB_TYPE_ENTITY_EXTRACT:
            records = load_canonical_events_for_entity_extraction(
                session,
                args.country,
                args.min_articles,
                args.force
            )
            print(f"Found {len(records)} canonical events needing entity extraction")

        elif args.job_type == JOB_TYPE_SCORE_MATERIALITY:
            records = load_canonical_events_for_materiality_scoring(
                session,
                args.country,
                args.min_articles,
                args.min_days,
                args.rescore
            )
            print(f"Found {len(records)} canonical events needing materiality scoring")

        elif args.job_type == JOB_TYPE_DAILY_ENTITY_EXTRACT:
            records = load_documents_for_entity_extraction(
                session,
                args.country,
                args.start_date,
                args.end_date,
                args.force
            )
            print(f"Found {len(records)} documents needing entity extraction")

        elif args.job_type == JOB_TYPE_ENTITY_DECONFLICT:
            records = load_unprocessed_entity_clusters(
                session,
                args.country,
                start_date,
                end_date
            )
            print(f"Found {len(records)} entity clusters needing LLM deconfliction")

        elif args.job_type == JOB_TYPE_CANONICAL_ENTITY_DECONFLICT:
            records = load_unprocessed_canonical_entity_groups(
                session,
                args.country
            )
            print(f"Found {len(records)} canonical entity groups needing LLM validation")

        elif args.job_type == JOB_TYPE_GENERATE_DAILY_SUMMARY:
            if not args.country:
                print("Error: --country is required for generate_daily_summary")
                return
            if not start_date or not end_date:
                print("Error: --start-date and --end-date are required for generate_daily_summary")
                return
            records = load_events_needing_daily_summaries(
                session,
                args.country,
                start_date,
                end_date
            )
            print(f"Found {len(records)} (event, date) pairs needing daily summaries")

        else:
            print(f"Error: Unsupported job type: {args.job_type}")
            return

        if len(records) == 0:
            print("No unprocessed records found. Exiting.")
            return

        # Chunk records for reliable uploads
        from services.pipeline.batch.batch_config import RECOMMENDED_BATCH_SIZE
        record_chunks = chunk_records(records, chunk_size=RECOMMENDED_BATCH_SIZE)
        num_chunks = len(record_chunks)

        print(f"\\nSplitting {len(records)} records into {num_chunks} batch(es) ({RECOMMENDED_BATCH_SIZE} per batch for reliable uploads)")

        if args.dry_run:
            print("\\n[DRY RUN] Would have created:")
            for i in range(num_chunks):
                print(f"  - Batch {i+1}: {len(record_chunks[i])} requests")
            print(f"  - {num_chunks} batch_jobs database record(s)")
            print("\\nExiting without creating files.")
            return

        # Process each chunk
        created_batch_jobs = []
        total_cost = 0.0
        from services.pipeline.batch.utils.cost_estimator import estimate_batch_cost

        for chunk_idx, chunk in enumerate(record_chunks, start=1):
            print(f"\\n{'='*80}")
            print(f"Processing Batch {chunk_idx}/{num_chunks}")
            print(f"{'='*80}")

            # Generate batch requests for this chunk
            print("Generating batch API requests...")
            batch_requests = generate_batch_requests(args.job_type, chunk, model)
            print(f"Generated {len(batch_requests)} batch requests")

            # Estimate cost
            print("Estimating costs...")
            total_input_tokens = sum(
                calculate_message_tokens(req['body']['messages'], model)
                for req in batch_requests
            )
            avg_input_tokens = total_input_tokens // len(batch_requests) if batch_requests else 0

            cost_estimate = estimate_batch_cost(len(batch_requests), avg_input_tokens, model=model)

            print(f"  Total requests: {len(batch_requests)}")
            print(f"  Avg input tokens: {avg_input_tokens}")
            print(f"  Estimated input cost: ${cost_estimate['input_cost']:.4f}")
            print(f"  Estimated output cost: ${cost_estimate['output_cost']:.4f}")
            print(f"  Estimated total cost: ${cost_estimate['total_cost']:.4f}")

            total_cost += cost_estimate['total_cost']

            # Generate output file path with batch suffix
            if args.output and num_chunks == 1:
                output_file = args.output
            else:
                base_output_file = get_batch_file_path(
                    args.job_type,
                    'input',
                    args.country,
                    str(start_date) if start_date else None,
                    str(end_date) if end_date else None
                )
                # Add batch number suffix if multiple batches
                if num_chunks > 1:
                    output_file = base_output_file.replace('.jsonl', f'_batch{chunk_idx}.jsonl')
                else:
                    output_file = base_output_file

            # Write JSONL file
            print(f"Writing JSONL file to: {output_file}")
            write_jsonl(output_file, batch_requests)
            print(f"✓ Wrote {len(batch_requests)} requests to {output_file}")

            # Create batch_job record
            print("Creating batch_job database record...")
            with BatchJobTracker(session) as tracker:
                batch_job = tracker.create_batch_job(
                    job_type=args.job_type,
                    batch_size=len(batch_requests),
                    initiating_country=args.country,
                    date_range_start=start_date,
                    date_range_end=end_date,
                    input_file_path=output_file,
                    estimated_cost=cost_estimate['total_cost'],
                    created_by='batch_prepare.py'
                )

                print(f"✓ Created batch_job record: {batch_job.id}")
                print(f"  Status: {batch_job.status}")
                print(f"  Batch size: {batch_job.batch_size}")
                print(f"  Estimated cost: ${batch_job.estimated_cost:.4f}")

                created_batch_jobs.append({
                    'id': batch_job.id,
                    'file': output_file,
                    'size': len(batch_requests),
                    'cost': cost_estimate['total_cost']
                })

        # Print summary
        print()
        print("=" * 80)
        print("BATCH PREPARE COMPLETE")
        print("=" * 80)
        print(f"Total batches created: {len(created_batch_jobs)}")
        print(f"Total records: {len(records)}")
        print(f"Total estimated cost: ${total_cost:.4f}")
        print()
        for i, job in enumerate(created_batch_jobs, start=1):
            print(f"Batch {i}:")
            print(f"  Batch Job ID: {job['id']}")
            print(f"  Input file: {job['file']}")
            print(f"  Records: {job['size']}")
            print(f"  Estimated cost: ${job['cost']:.4f}")
        print()
        print("Next step: Submit batch(es) to OpenAI")
        for job in created_batch_jobs:
            print(f"  python batch_submit.py --batch-job-id {job['id']}")
        print("=" * 80)


if __name__ == "__main__":
    main()
