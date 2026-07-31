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
    JOB_TYPE_GENERATE_WEEKLY_SUMMARY,
    JOB_TYPE_GENERATE_MONTHLY_SUMMARY,
    JOB_TYPE_GENERATE_YEARLY_SUMMARY,
    JOB_TYPE_SCORE_SUMMARY_MATERIALITY,
    JOB_TYPE_GENERATE_ENTITY_DESCRIPTIONS,
    JOB_TYPE_GENERATE_BILATERAL_SUMMARIES,
    JOB_TYPE_CLASSIFY_ENTITY_RELATIONSHIPS,
    JOB_TYPE_EVENT_RENAME,
    JOB_TYPE_PROPOSITION_EXTRACT,
    get_batch_file_path,
    get_model_for_job_type,
    DEFAULT_TEMPERATURE,
    TEMPERATURE_BY_JOB_TYPE
)
from services.pipeline.batch.schemas import get_response_format_for_job_type
from services.pipeline.batch.batch_tracker import BatchJobTracker
from services.pipeline.batch.utils.custom_id import generate_custom_id
from services.pipeline.batch.utils.jsonl_utils import write_jsonl, split_jsonl_by_file_size, count_jsonl_lines
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

    sys_prompt = """You are an expert analyst scoring the strategic materiality of soft power events.

**YOUR TASK:**
Assign a materiality score from 1.0 to 10.0 measuring the strategic and material impact of this soft power event. Use the anchors below to calibrate your score precisely.

**Scoring Scale (use precise anchors):**

1.0-2.0: **Routine/Ceremonial** — No new commitments or outcomes
  - Anniversary celebrations, cultural festivals, flag-raising ceremonies
  - Speeches reaffirming existing positions with no new elements
  - Routine diplomatic courtesy visits with no agenda
  - Score 1.0: Pure ceremony. Score 2.0: Ceremony with minor symbolic gesture (gift exchange, joint statement)

2.5-3.5: **Symbolic with Signal Value** — No material commitment but sends a political message
  - First-ever meeting between leaders (symbolic opening, no deal)
  - Public solidarity statements during a crisis
  - Boycotts, expulsions, or recalls of ambassadors
  - Cultural events explicitly tied to a political agenda (propaganda screenings, ideological exhibitions)
  - Score 2.5: Weak signal. Score 3.5: Strong signal that shifts perceptions

4.0-5.0: **Framework/Intent** — Commitments exist but are non-binding or vague
  - MOUs without specific projects, timelines, or dollar amounts
  - "Working groups" or "joint committees" established
  - Trade talks initiated but no agreement reached
  - Scholarship programs or training exchanges (small scale, <100 people)
  - Score 4.0: Vague intent. Score 5.0: Named initiative with structure but no funding

5.5-6.5: **Concrete but Limited** — Specific, verifiable commitments at moderate scale
  - Signed agreements with named projects and timelines
  - Financial commitments under $100M
  - Military equipment deliveries or specific joint exercises with named assets
  - Visa agreements, direct flight routes, or trade facilitation measures
  - Humanitarian aid deliveries with specific quantities
  - Score 5.5: Single small deliverable. Score 6.5: Multiple deliverables or binding agreement

7.0-8.0: **Substantial** — Major commitments that alter bilateral dynamics
  - Financial commitments $100M-$1B
  - Infrastructure projects breaking ground (not just announced)
  - Free trade agreements or major tariff changes
  - Defense pacts, base access agreements, or major arms deals
  - Large-scale humanitarian operations (thousands of beneficiaries)
  - Score 7.0: Major single commitment. Score 8.0: Multiple major commitments or implemented (not just signed)

8.5-10.0: **Transformative** — Reshapes regional dynamics or creates lasting structural change
  - Financial commitments >$1B
  - Nuclear/energy megaprojects under construction
  - New international institutions or frameworks (BRICS expansion, SCO membership)
  - Peace agreements ending active conflicts
  - Permanent military basing or security guarantees
  - Score 8.5: Major structural shift. Score 10.0: Historic, once-in-a-decade event

**Additional Signals (adjust score ±0.5-1.0):**
- High article count (>20) suggests significant media/policy attention → adjust UP
- Multi-day coverage suggests sustained importance → adjust UP
- Multiple recipient countries involved → adjust UP
- Event is an update to a previously scored event (follow-on meeting) → adjust DOWN vs. original event
- Announcement only with no implementation evidence → adjust DOWN

**CRITICAL:** Use the full 1-10 range. Score based on the anchors above, not gut feeling. A cultural festival is a 1-2 regardless of which countries are involved. A $500M infrastructure project is a 7+ regardless of how few articles cover it. Let the substance drive the score.

Respond with ONLY the JSON object: {{"material_score": <number>, "justification": "<brief explanation>"}}"""

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


def load_events_needing_weekly_summaries(
    session,
    country: str,
    start_date: DateType,
    end_date: DateType
) -> List[Dict]:
    """
    Load events that need weekly summaries across a date range.

    Splits the date range into Monday-Sunday weeks, loads daily summaries
    for each week grouped by event, and returns events with ≥2 daily
    summaries that don't already have a weekly summary.

    Args:
        session: Database session
        country: Initiating country (required)
        start_date: Start date (inclusive)
        end_date: End date (inclusive)

    Returns:
        List of dicts, each representing one (event, week) pair ready for
        prompt generation.
    """
    from datetime import timedelta

    def get_week_ranges(sd, ed):
        """Split date range into Monday-Sunday weekly periods."""
        ranges = []
        current = sd - timedelta(days=sd.weekday())  # Align to Monday
        while current <= ed:
            week_end = min(current + timedelta(days=6), ed)
            if week_end >= sd:
                ranges.append((max(current, sd), week_end))
            current += timedelta(days=7)
        return ranges

    events_to_process = []
    week_ranges = get_week_ranges(start_date, end_date)

    for week_start, week_end in week_ranges:
        # Load daily summaries grouped by event_name (same SQL as generate_weekly_summaries.py)
        result = session.execute(text('''
            SELECT
                es.id,
                es.event_name,
                es.period_start,
                es.period_end,
                es.narrative_summary,
                ce.id as canonical_event_id
            FROM event_summaries es
            JOIN canonical_events ce ON es.event_name = ce.canonical_name
            WHERE es.initiating_country = :country
              AND es.period_type = 'DAILY'
              AND es.period_start >= :week_start
              AND es.period_end <= :week_end
              AND ce.master_event_id IS NULL
              AND es.status = 'ACTIVE'
            ORDER BY es.event_name, es.period_start
        '''), {
            'country': country,
            'week_start': week_start,
            'week_end': week_end
        }).fetchall()

        # Group by event_name
        events_map = {}
        for row in result:
            event_name = row[1]
            if event_name not in events_map:
                events_map[event_name] = {
                    'canonical_event_id': str(row[5]),
                    'summaries': []
                }
            events_map[event_name]['summaries'].append({
                'summary_id': row[0],
                'period_start': row[2],
                'period_end': row[3],
                'narrative_summary': row[4]
            })

        for event_name, event_data in events_map.items():
            daily_summaries = event_data['summaries']

            # Skip events with < 2 daily summaries
            if len(daily_summaries) < 2:
                continue

            # Check if weekly summary already exists
            existing = session.execute(text('''
                SELECT 1 FROM event_summaries
                WHERE period_type = 'WEEKLY'
                  AND period_start = :week_start
                  AND period_end = :week_end
                  AND initiating_country = :country
                  AND event_name = :event_name
                LIMIT 1
            '''), {
                'week_start': week_start,
                'week_end': week_end,
                'country': country,
                'event_name': event_name
            }).fetchone()

            if existing:
                continue

            # Format daily summaries for the prompt
            daily_text_parts = []
            daily_summary_ids = []
            for i, summary in enumerate(daily_summaries, 1):
                date_str = summary['period_start'].strftime('%Y-%m-%d')
                narrative = summary['narrative_summary']
                daily_text_parts.append(
                    f"**Day {i} ({date_str}):**\n"
                    f"Overview: {narrative.get('overview', 'N/A')}\n"
                    f"Outcomes: {narrative.get('outcomes', 'N/A')}"
                )
                daily_summary_ids.append(str(summary['summary_id']))

            events_to_process.append({
                'canonical_event_id': event_data['canonical_event_id'],
                'event_name': event_name,
                'country': country,
                'week_start_str': week_start.strftime('%Y-%m-%d'),
                'week_end_str': week_end.strftime('%Y-%m-%d'),
                'daily_summaries_formatted': "\n\n".join(daily_text_parts),
                'daily_summary_ids': daily_summary_ids,
                'num_daily_summaries': len(daily_summaries)
            })

    return events_to_process


def build_weekly_summary_prompt(event_data: Dict) -> Dict[str, List[Dict[str, str]]]:
    """
    Build prompt messages for weekly summary generation.

    Uses the WEEKLY_SUMMARY_PROMPT template from summary_prompts.py.

    Args:
        event_data: Dict with event_name, country, week_start_str,
                    week_end_str, daily_summaries_formatted

    Returns:
        Dictionary with 'messages' key containing list of message dicts
    """
    from services.pipeline.summaries.summary_prompts import WEEKLY_SUMMARY_PROMPT

    prompt = WEEKLY_SUMMARY_PROMPT.format(
        country=event_data['country'],
        week_start=event_data['week_start_str'],
        week_end=event_data['week_end_str'],
        event_name=event_data['event_name'],
        daily_summaries=event_data['daily_summaries_formatted']
    )

    sys_prompt = "You are an experienced journalist writing in Associated Press (AP) style. Synthesize daily summaries into weekly narratives."

    return {
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": prompt}
        ]
    }


def load_events_needing_monthly_summaries(
    session,
    country: str,
    start_date: DateType,
    end_date: DateType
) -> List[Dict]:
    """
    Load events that need monthly summaries across a date range.

    Splits the date range into calendar months, loads weekly summaries
    for each month grouped by event, and returns events with ≥2 weekly
    summaries that don't already have a monthly summary.

    Args:
        session: Database session
        country: Initiating country (required)
        start_date: Start date (inclusive)
        end_date: End date (inclusive)

    Returns:
        List of dicts, each representing one (event, month) pair ready for
        prompt generation.
    """
    from datetime import timedelta

    def get_month_ranges(sd, ed):
        """Split date range into calendar month periods."""
        ranges = []
        current = sd.replace(day=1)
        while current <= ed:
            if current.month == 12:
                next_month = current.replace(year=current.year + 1, month=1, day=1)
            else:
                next_month = current.replace(month=current.month + 1, day=1)
            month_end = min(next_month - timedelta(days=1), ed)
            if month_end >= sd:
                ranges.append((max(current, sd), month_end))
            current = next_month
        return ranges

    events_to_process = []
    month_ranges = get_month_ranges(start_date, end_date)

    for month_start, month_end in month_ranges:
        # Load weekly summaries grouped by event_name (same SQL as generate_monthly_summaries.py)
        result = session.execute(text('''
            SELECT
                es.id,
                es.event_name,
                es.period_start,
                es.period_end,
                es.narrative_summary,
                ce.id as canonical_event_id
            FROM event_summaries es
            JOIN canonical_events ce ON es.event_name = ce.canonical_name
            WHERE es.initiating_country = :country
              AND es.period_type = 'WEEKLY'
              AND es.period_start >= :month_start
              AND es.period_end <= :month_end
              AND ce.master_event_id IS NULL
              AND es.status = 'ACTIVE'
            ORDER BY es.event_name, es.period_start
        '''), {
            'country': country,
            'month_start': month_start,
            'month_end': month_end
        }).fetchall()

        # Group by event_name
        events_map = {}
        for row in result:
            event_name = row[1]
            if event_name not in events_map:
                events_map[event_name] = {
                    'canonical_event_id': str(row[5]),
                    'summaries': []
                }
            events_map[event_name]['summaries'].append({
                'summary_id': row[0],
                'period_start': row[2],
                'period_end': row[3],
                'narrative_summary': row[4]
            })

        for event_name, event_data in events_map.items():
            weekly_summaries = event_data['summaries']

            # Skip events with < 2 weekly summaries
            if len(weekly_summaries) < 2:
                continue

            # Check if monthly summary already exists
            existing = session.execute(text('''
                SELECT 1 FROM event_summaries
                WHERE period_type = 'MONTHLY'
                  AND period_start = :month_start
                  AND period_end = :month_end
                  AND initiating_country = :country
                  AND event_name = :event_name
                LIMIT 1
            '''), {
                'month_start': month_start,
                'month_end': month_end,
                'country': country,
                'event_name': event_name
            }).fetchone()

            if existing:
                continue

            # Format weekly summaries for the prompt
            weekly_text_parts = []
            weekly_summary_ids = []
            for i, summary in enumerate(weekly_summaries, 1):
                week_str = (f"{summary['period_start'].strftime('%Y-%m-%d')} to "
                            f"{summary['period_end'].strftime('%Y-%m-%d')}")
                narrative = summary['narrative_summary']
                weekly_text_parts.append(
                    f"**Week {i} ({week_str}):**\n"
                    f"Overview: {narrative.get('overview', 'N/A')}\n"
                    f"Outcomes: {narrative.get('outcomes', 'N/A')}\n"
                    f"Progression: {narrative.get('progression', 'N/A')}"
                )
                weekly_summary_ids.append(str(summary['summary_id']))

            events_to_process.append({
                'canonical_event_id': event_data['canonical_event_id'],
                'event_name': event_name,
                'country': country,
                'month_start_str': month_start.strftime('%Y-%m-%d'),
                'month_end_str': month_end.strftime('%Y-%m-%d'),
                'month_year': month_start.strftime('%B %Y'),
                'weekly_summaries_formatted': "\n\n".join(weekly_text_parts),
                'weekly_summary_ids': weekly_summary_ids,
                'num_weekly_summaries': len(weekly_summaries)
            })

    return events_to_process


def build_monthly_summary_prompt(event_data: Dict) -> Dict[str, List[Dict[str, str]]]:
    """
    Build prompt messages for monthly summary generation.

    Uses the MONTHLY_SUMMARY_PROMPT template from summary_prompts.py.

    Args:
        event_data: Dict with event_name, country, month_year,
                    weekly_summaries_formatted

    Returns:
        Dictionary with 'messages' key containing list of message dicts
    """
    from services.pipeline.summaries.summary_prompts import MONTHLY_SUMMARY_PROMPT

    prompt = MONTHLY_SUMMARY_PROMPT.format(
        country=event_data['country'],
        month_year=event_data['month_year'],
        event_name=event_data['event_name'],
        weekly_summaries=event_data['weekly_summaries_formatted']
    )

    sys_prompt = "You are an experienced journalist writing in Associated Press (AP) style. Synthesize weekly summaries into monthly narratives."

    return {
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": prompt}
        ]
    }


def load_events_needing_yearly_summaries(
    session,
    country: str,
    start_date: DateType,
    end_date: DateType
) -> List[Dict]:
    """
    Load events that need yearly summaries across a date range.

    Splits the date range into calendar years, loads monthly summaries
    for each year grouped by event, and returns events with ≥2 monthly
    summaries that don't already have a yearly summary.

    Mirrors load_events_needing_monthly_summaries one level up the
    period hierarchy (monthly → yearly instead of weekly → monthly).

    Args:
        session: Database session
        country: Initiating country (required)
        start_date: Start date (inclusive)
        end_date: End date (inclusive)

    Returns:
        List of dicts, each representing one (event, year) pair ready for
        prompt generation.
    """
    def get_year_ranges(sd, ed):
        """Split date range into calendar year periods."""
        ranges = []
        current = sd.replace(month=1, day=1)
        while current <= ed:
            year_end = min(current.replace(month=12, day=31), ed)
            if year_end >= sd:
                ranges.append((max(current, sd), year_end))
            current = current.replace(year=current.year + 1)
        return ranges

    events_to_process = []

    for year_start, year_end in get_year_ranges(start_date, end_date):
        # Load monthly summaries grouped by event_name (same SQL as generate_yearly_summaries.py)
        result = session.execute(text('''
            SELECT
                es.id,
                es.event_name,
                es.period_start,
                es.period_end,
                es.narrative_summary,
                ce.id as canonical_event_id
            FROM event_summaries es
            JOIN canonical_events ce ON es.event_name = ce.canonical_name
            WHERE es.initiating_country = :country
              AND es.period_type = 'MONTHLY'
              AND es.period_start >= :year_start
              AND es.period_end <= :year_end
              AND ce.master_event_id IS NULL
              AND es.status = 'ACTIVE'
            ORDER BY es.event_name, es.period_start
        '''), {
            'country': country,
            'year_start': year_start,
            'year_end': year_end
        }).fetchall()

        # Group by event_name
        events_map = {}
        for row in result:
            event_name = row[1]
            if event_name not in events_map:
                events_map[event_name] = {
                    'canonical_event_id': str(row[5]),
                    'summaries': []
                }
            events_map[event_name]['summaries'].append({
                'summary_id': row[0],
                'period_start': row[2],
                'period_end': row[3],
                'narrative_summary': row[4]
            })

        for event_name, event_data in events_map.items():
            monthly_summaries = event_data['summaries']

            # Skip events with < 2 monthly summaries
            if len(monthly_summaries) < 2:
                continue

            # Check if yearly summary already exists
            existing = session.execute(text('''
                SELECT 1 FROM event_summaries
                WHERE period_type = 'YEARLY'
                  AND period_start = :year_start
                  AND period_end = :year_end
                  AND initiating_country = :country
                  AND event_name = :event_name
                LIMIT 1
            '''), {
                'year_start': year_start,
                'year_end': year_end,
                'country': country,
                'event_name': event_name
            }).fetchone()

            if existing:
                continue

            # Format monthly summaries for the prompt (same layout as
            # generate_yearly_summaries.py)
            monthly_text_parts = []
            monthly_summary_ids = []
            for i, summary in enumerate(monthly_summaries, 1):
                month_str = summary['period_start'].strftime('%B %Y')
                narrative = summary['narrative_summary']
                monthly_text_parts.append(
                    f"**Month {i} ({month_str}):**\n"
                    f"Monthly Overview: {narrative.get('monthly_overview', 'N/A')}\n"
                    f"Key Outcomes: {narrative.get('key_outcomes', 'N/A')}\n"
                    f"Strategic Significance: {narrative.get('strategic_significance', 'N/A')}"
                )
                monthly_summary_ids.append(str(summary['summary_id']))

            events_to_process.append({
                'canonical_event_id': event_data['canonical_event_id'],
                'event_name': event_name,
                'country': country,
                'year_start_str': year_start.strftime('%Y-%m-%d'),
                'year_end_str': year_end.strftime('%Y-%m-%d'),
                'year': year_start.year,
                'monthly_summaries_formatted': "\n\n".join(monthly_text_parts),
                'monthly_summary_ids': monthly_summary_ids,
                'num_monthly_summaries': len(monthly_summaries)
            })

    return events_to_process


def build_yearly_summary_prompt(event_data: Dict) -> Dict[str, List[Dict[str, str]]]:
    """
    Build prompt messages for yearly summary generation.

    Uses the YEARLY_SUMMARY_PROMPT template from summary_prompts.py.

    Args:
        event_data: Dict with event_name, country, year,
                    monthly_summaries_formatted

    Returns:
        Dictionary with 'messages' key containing list of message dicts
    """
    from services.pipeline.summaries.summary_prompts import YEARLY_SUMMARY_PROMPT

    prompt = YEARLY_SUMMARY_PROMPT.format(
        country=event_data['country'],
        year=event_data['year'],
        event_name=event_data['event_name'],
        monthly_summaries=event_data['monthly_summaries_formatted']
    )

    sys_prompt = "You are an experienced journalist writing in Associated Press (AP) style. Synthesize monthly summaries into yearly strategic narratives."

    return {
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": prompt}
        ]
    }


def load_summaries_for_materiality_scoring(
    session,
    country: str,
    start_date: DateType,
    end_date: DateType,
    period_type: Optional[str] = None,
    rescore: bool = False
) -> List[Dict]:
    """
    Load event summaries that need materiality scoring.

    Args:
        session: Database session
        country: Initiating country
        start_date: Start date
        end_date: End date
        period_type: Optional filter (DAILY, WEEKLY, MONTHLY). None = all.
        rescore: If True, rescore all summaries. If False, only unscored.

    Returns:
        List of summary dictionaries
    """
    score_filter = "" if rescore else "AND es.material_score IS NULL"
    period_filter = "AND es.period_type = :period_type" if period_type else ""

    query = text(f"""
        SELECT
            es.id,
            es.event_name,
            es.initiating_country,
            es.period_type,
            es.period_start,
            es.period_end,
            es.narrative_summary,
            es.count_by_category,
            es.count_by_recipient,
            es.total_documents_across_sources
        FROM event_summaries es
        WHERE es.initiating_country = :country
          AND es.period_start >= :start_date
          AND es.period_end <= :end_date
          AND es.is_deleted = false
          {score_filter}
          {period_filter}
        ORDER BY es.period_start DESC, es.event_name
    """)

    params = {
        'country': country,
        'start_date': start_date,
        'end_date': end_date
    }
    if period_type:
        params['period_type'] = period_type

    result = session.execute(query, params).fetchall()

    summaries = []
    for row in result:
        summaries.append({
            'id': str(row[0]),
            'event_name': row[1],
            'initiating_country': row[2],
            'period_type': row[3],
            'period_start': row[4],
            'period_end': row[5],
            'narrative_summary': row[6] or {},
            'count_by_category': row[7] or {},
            'count_by_recipient': row[8] or {},
            'total_documents': row[9] or 0
        })

    return summaries


def build_summary_materiality_prompt(summary: Dict) -> Dict[str, List[Dict[str, str]]]:
    """
    Build prompt messages for materiality scoring of event summaries.

    Uses the MATERIALITY_SCORE_PROMPT from summary_prompts.py.

    Args:
        summary: Event summary dictionary from load_summaries_for_materiality_scoring

    Returns:
        Dictionary with 'messages' key containing list of message dicts
    """
    from services.pipeline.summaries.summary_prompts import MATERIALITY_SCORE_PROMPT

    narrative = summary['narrative_summary']

    # Extract narrative text based on period type
    if summary['period_type'] == 'DAILY':
        summary_text = f"{narrative.get('overview', '')}\n\n{narrative.get('outcomes', '')}"
    elif summary['period_type'] == 'WEEKLY':
        summary_text = f"{narrative.get('overview', '')}\n\n{narrative.get('outcomes', '')}\n\n{narrative.get('progression', '')}"
    else:  # MONTHLY
        summary_text = f"{narrative.get('monthly_overview', '')}\n\n{narrative.get('key_outcomes', '')}\n\n{narrative.get('strategic_significance', '')}"

    # Format categories and recipients
    categories = summary['count_by_category']
    if isinstance(categories, dict) and categories:
        categories_str = ', '.join(list(categories.keys())[:5])
    else:
        categories_str = 'None'

    recipients = summary['count_by_recipient']
    if isinstance(recipients, dict) and recipients:
        recipients_str = ', '.join(list(recipients.keys())[:5])
    else:
        recipients_str = 'None'

    period_start = summary['period_start']
    period_end = summary['period_end']
    period_start_str = period_start.strftime('%Y-%m-%d') if hasattr(period_start, 'strftime') else str(period_start)
    period_end_str = period_end.strftime('%Y-%m-%d') if hasattr(period_end, 'strftime') else str(period_end)

    prompt = MATERIALITY_SCORE_PROMPT.format(
        country=summary['initiating_country'],
        event_name=summary['event_name'],
        period_type=summary['period_type'],
        period_start=period_start_str,
        period_end=period_end_str,
        event_summary=summary_text.strip(),
        categories=categories_str,
        recipients=recipients_str,
        total_documents=summary['total_documents']
    )

    sys_prompt = "You are an expert analyst assessing the materiality of soft power events. You assign scores from 1-10 measuring concrete/substantive nature versus symbolic/rhetorical gestures."

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


def load_docs_for_proposition_extract(
    s3_prefix: str = "dsr_extracts/",
    s3_files: Optional[List[str]] = None,
    filename_contains: Optional[List[str]] = None,
    initiators: Optional[List[str]] = None,
    recipients: Optional[List[str]] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    body_csv: Optional[List[str]] = None,
    input_text: str = "body",
    limit: int = 10_000_000,
) -> List[Dict[str, Any]]:
    """Load eligible DSR docs from S3 for proposition extraction.

    Reuses the same filter + body-lookup logic as proposition_pilot's batch
    mode so the two paths produce identical input universes. Returns a list
    of dicts with everything needed downstream (both for the LLM prompt and
    for the post-processing record reconstruction).

    Args:
        s3_prefix: S3 prefix for DSR JSON files (default: dsr_extracts/).
        s3_files: Specific filenames within s3_prefix to process.
        filename_contains: Substring filter on filenames (case-insensitive,
            ANY match keeps the file). Cheap way to prune 90 files down.
        initiators / recipients: Country allowlists. None falls back to
            shared/config/config.yaml's influencers / recipients.
        start_date / end_date: YYYY-MM-DD strings.
        body_csv: List of CSV sources (local paths, directories, or
            s3://bucket/prefix/ URIs) supplying body text per ATOM ID.
            Required when input_text is body or both.
        input_text: "distilled" | "body". (No "both" for batch - one source
            per job.)
        limit: Max docs to include.

    Returns:
        List of dicts; each contains doc_id, doc_date, doc_title, country
        fields, event_name, source_s3_file, source_body_csv, distilled_text,
        body_text, and input_text_source (which one will be used for the LLM
        call). Docs missing the requested input_text are filtered out.
    """
    # Import lazily to avoid cycles: proposition_pilot imports from batch
    # config via shared modules, and we want this module to load even if
    # proposition_pilot's dotenv side-effects haven't run.
    from services.pipeline.analysis.proposition_pilot import (
        iter_eligible_docs,
        load_body_csv_index,
        load_country_lists_from_config,
    )

    if initiators is None and recipients is None:
        initiators, recipients = load_country_lists_from_config()
        print(f"[proposition_extract] Filters from config.yaml: "
              f"{len(initiators)} initiators, {len(recipients)} recipients")

    start_d = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else None
    end_d = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else None

    if input_text not in ("distilled", "body"):
        raise ValueError(f"input_text must be 'distilled' or 'body' (got {input_text!r})")

    print(f"[proposition_extract] Scanning S3 prefix={s3_prefix} "
          f"input_text={input_text} limit={limit}")
    docs = list(iter_eligible_docs(
        s3_prefix=s3_prefix,
        specific_files=s3_files,
        initiators=initiators,
        recipients=recipients,
        start_date=start_d,
        end_date=end_d,
        limit=limit,
        filename_contains=filename_contains,
    ))
    print(f"[proposition_extract] {len(docs)} eligible docs after filters")

    if input_text == "body":
        if not body_csv:
            raise ValueError("input_text='body' requires body_csv source(s)")
        print(f"[proposition_extract] Loading body text from CSV: {body_csv}")
        body_index = load_body_csv_index(body_csv)
        print(f"[proposition_extract] body index size: {len(body_index)}")
        matched = 0
        for d in docs:
            entry = body_index.get(d["doc_id"])
            if entry:
                d["body_text"], d["_body_csv"] = entry
                matched += 1
        print(f"[proposition_extract] body_text matched on {matched}/{len(docs)} docs")
        # Drop docs with no body match - they can't be processed in body mode
        before = len(docs)
        docs = [d for d in docs if d.get("body_text")]
        print(f"[proposition_extract] dropped {before - len(docs)} docs with no body match")
    else:
        # Distilled-only: drop docs with no distilled_text (rare; filter already
        # rejected most via no_distilled_text, this is a defensive second pass).
        before = len(docs)
        docs = [d for d in docs if d.get("distilled_text")]
        if before - len(docs):
            print(f"[proposition_extract] dropped {before - len(docs)} docs missing distilled_text")

    # Build the records the batch pipeline expects - one per doc.
    result: List[Dict[str, Any]] = []
    for d in docs:
        result.append({
            "doc_id": d["doc_id"],
            "doc_date": str(d.get("date")) if d.get("date") else None,
            "doc_title": d.get("title"),
            "doc_initiating_country": d.get("initiating_country"),
            "doc_recipient_country": d.get("recipient_country"),
            "doc_event_name": d.get("event_name"),
            "source_s3_file": d.get("_source_s3_file"),
            "source_body_csv": d.get("_body_csv"),
            "distilled_text": d.get("distilled_text"),
            "body_text": d.get("body_text"),
            "input_text_source": input_text,
        })
    return result


def build_proposition_extract_prompt(doc: Dict[str, Any]) -> Dict[str, List[Dict[str, str]]]:
    """Build the messages array for one proposition extraction request.

    Pairs the project's proposition_extraction_prompt (v0.5+) as the system
    message with a structured user message containing the doc metadata and
    the chosen input text (body or distilled).
    """
    from shared.utils.prompts_proposition import proposition_extraction_prompt

    src = doc.get("input_text_source", "distilled")
    text = doc.get("body_text") if src == "body" else doc.get("distilled_text")
    if not text:
        # Should not happen if load_docs_for_proposition_extract did its job.
        raise ValueError(f"No {src} text for doc {doc.get('doc_id')!r}")

    user_msg = (
        f"doc_id: {doc.get('doc_id')}\n"
        f"date: {doc.get('doc_date')}\n"
        f"title: {doc.get('doc_title')}\n"
        f"doc_initiating_country: {doc.get('doc_initiating_country')}\n"
        f"doc_recipient_country: {doc.get('doc_recipient_country')}\n"
        f"{src}:\n{text}"
    )
    return {
        "messages": [
            {"role": "system", "content": proposition_extraction_prompt},
            {"role": "user", "content": user_msg},
        ]
    }


# ---- Entity Description Generation ----

ENTITY_DESCRIPTION_SYS_PROMPT = (
    "You are an expert analyst specializing in international relations and soft power. "
    "Generate concise, factual entity profiles based on the provided data. "
    "Use AP (Associated Press) style. Be specific and concrete, avoid generic characterizations. "
    "Focus on what this entity actually does based on the document evidence provided."
)


def load_entities_for_description_generation(
    session, country: str, min_docs: int = 3, force: bool = False
) -> List[Dict]:
    """
    Load canonical entities needing LLM description generation.

    Args:
        session: Database session
        country: Initiating country
        min_docs: Minimum total_documents threshold
        force: If True, include entities that already have descriptions

    Returns:
        List of entity dicts with pre-loaded event names
    """
    filter_clause = ""
    if not force:
        filter_clause = "AND ce.entity_description IS NULL"

    rows = session.execute(text(f"""
        SELECT
            ce.id::text,
            ce.canonical_name,
            ce.entity_type,
            ce.primary_role,
            ce.initiating_country,
            ce.country_affiliations,
            ce.alternative_names,
            ce.primary_categories,
            ce.primary_recipients,
            ce.total_documents,
            ce.total_mention_days,
            ce.first_mention_date::text,
            ce.last_mention_date::text,
            ce.associated_events
        FROM canonical_entities ce
        WHERE ce.initiating_country = :country
          AND ce.master_entity_id IS NULL
          AND ce.total_documents >= :min_docs
          {filter_clause}
        ORDER BY ce.total_documents DESC
    """), {'country': country, 'min_docs': min_docs}).fetchall()

    if not rows:
        return []

    # Collect all event IDs to batch-load event names
    all_event_ids = set()
    for row in rows:
        if row[13]:  # associated_events
            for eid in row[13][:5]:
                all_event_ids.add(str(eid))

    # Batch-load event names
    event_name_map = {}
    if all_event_ids:
        event_rows = session.execute(text("""
            SELECT id::text, canonical_name FROM canonical_events
            WHERE id::text = ANY(:event_ids)
              AND master_event_id IS NULL
        """), {'event_ids': list(all_event_ids)}).fetchall()
        event_name_map = {r[0]: r[1] for r in event_rows}

    result = []
    for row in rows:
        event_names = []
        if row[13]:
            event_names = [event_name_map.get(str(eid), '') for eid in row[13][:5]]
            event_names = [n for n in event_names if n]

        result.append({
            'id': row[0],
            'canonical_name': row[1],
            'entity_type': str(row[2]) if row[2] else 'unknown',
            'primary_role': str(row[3]) if row[3] else None,
            'initiating_country': row[4],
            'country_affiliations': row[5] or [],
            'alternative_names': row[6] or [],
            'primary_categories': row[7],
            'primary_recipients': row[8],
            'total_documents': row[9],
            'total_mention_days': row[10],
            'first_mention_date': row[11],
            'last_mention_date': row[12],
            'event_names': event_names
        })

    return result


def build_entity_description_prompt(entity: Dict) -> Dict[str, List[Dict[str, str]]]:
    """
    Build prompt for entity description generation.

    Mirrors the prompt logic from generate_entity_descriptions.py.

    Args:
        entity: Entity dict from load_entities_for_description_generation

    Returns:
        Dict with 'messages' key containing system + user messages
    """
    import json as _json

    # Format categories
    categories_str = "N/A"
    cats = entity.get('primary_categories')
    if cats:
        if isinstance(cats, str):
            try:
                cats = _json.loads(cats)
            except (ValueError, TypeError):
                cats = {}
        if isinstance(cats, dict) and cats:
            sorted_cats = sorted(cats.items(), key=lambda x: x[1], reverse=True)[:5]
            categories_str = ", ".join(f"{k} ({v})" for k, v in sorted_cats)

    # Format recipients
    recipients_str = "N/A"
    recips = entity.get('primary_recipients')
    if recips:
        if isinstance(recips, str):
            try:
                recips = _json.loads(recips)
            except (ValueError, TypeError):
                recips = {}
        if isinstance(recips, dict) and recips:
            sorted_recips = sorted(recips.items(), key=lambda x: x[1], reverse=True)[:5]
            recipients_str = ", ".join(f"{k} ({v})" for k, v in sorted_recips)

    alt_names_str = ", ".join(entity.get('alternative_names', [])[:5]) or "None"
    affiliations_str = ", ".join(entity.get('country_affiliations', [])[:5]) or "None"
    events_str = ", ".join(entity.get('event_names', [])[:5]) or "None linked"

    user_prompt = f"""Generate a profile for this entity based on its activity in diplomatic/soft power documents.

Entity: {entity['canonical_name']}
Type: {entity['entity_type']}
Role: {entity.get('primary_role') or 'Unknown'}
Country context: {entity['initiating_country']}
Country affiliations: {affiliations_str}
Also known as: {alt_names_str}
Active period: {entity['first_mention_date']} to {entity['last_mention_date']} ({entity.get('total_mention_days', 0)} days)
Total documents: {entity['total_documents']}
Top categories: {categories_str}
Top recipient countries: {recipients_str}
Associated events: {events_str}

Return ONLY a JSON object with no additional text:
{{
    "entity_description": "2-3 sentence profile describing who/what this entity is and their role in soft power activities. Be specific about their actions and significance based on the data above.",
    "key_activities": {{
        "primary_function": "One sentence on primary function/role",
        "notable_actions": ["action1", "action2", "action3"],
        "key_relationships": ["relationship1", "relationship2"],
        "geographic_focus": ["country1", "country2"]
    }}
}}"""

    return {
        "messages": [
            {"role": "system", "content": ENTITY_DESCRIPTION_SYS_PROMPT},
            {"role": "user", "content": user_prompt}
        ]
    }


RELATIONSHIP_CLASSIFICATION_SYS_PROMPT = (
    "You are an expert analyst of international relations and soft power diplomacy. "
    "Classify the relationship between two entities based only on the document evidence provided. "
    "Write descriptions in AP (Associated Press) style. Be specific and concrete — name the actual "
    "agreements, meetings, titles, or actions observed. Never use vague filler phrases. "
    "If the evidence is insufficient to determine a specific relationship type, use 'co_occurrence'. "
    "Output valid JSON only."
)

RELATIONSHIP_TYPE_DEFINITIONS = """\
Valid relationship_type values (choose exactly one):
  works_with        - Colleagues operating at the same level (e.g., two ministers collaborating)
  employed_by       - Person works for / is a staff member of an organization
  leads             - Person heads, directs, or chairs an organization (CEO, minister, director)
  represents        - Person acts as envoy, spokesperson, or representative of an entity
  partnered_with    - Two organizations have a formal partnership, MOU, or joint initiative
  subsidiary_of     - Organization is a branch, division, or subsidiary of a parent organization
  located_in        - Organization or person is based in / headquartered in a location
  visited           - Person traveled to, attended an event in, or met counterparts in a location
  signed_agreement_with - Entities formally signed a treaty, contract, or agreement together
  co_occurrence     - Insufficient evidence to determine a specific relationship type"""


def load_relationships_for_classification(
    session, country: str, force: bool = False, min_cooccurrence: int = 2
) -> List[Dict]:
    """
    Load entity relationship pairs needing LLM classification.

    Args:
        session: Database session
        country: Initiating country
        force: If True, include already-classified rows (not just 'co_occurrence')
        min_cooccurrence: Minimum co-occurrence count

    Returns:
        List of relationship dicts with entity metadata and doc snippets
    """
    import json as _json

    type_filter = "" if force else "AND er.relationship_type = 'co_occurrence'"

    rows = session.execute(text(f"""
        SELECT
            er.id::text,
            er.entity_from_id::text,
            er.entity_to_id::text,
            er.co_occurrence_count,
            er.first_co_occurrence::text,
            er.last_co_occurrence::text,
            er.primary_categories,
            er.source_doc_ids,
            ef.canonical_name    AS from_name,
            ef.entity_type::text AS from_type,
            ef.primary_role::text AS from_role,
            ef.initiating_country AS from_country,
            et.canonical_name    AS to_name,
            et.entity_type::text AS to_type,
            et.primary_role::text AS to_role
        FROM entity_relationships er
        JOIN canonical_entities ef ON er.entity_from_id = ef.id
        JOIN canonical_entities et ON er.entity_to_id = et.id
        WHERE ef.initiating_country = :country
          AND ef.master_entity_id IS NULL
          AND et.master_entity_id IS NULL
          AND er.co_occurrence_count >= :min_coo
          {type_filter}
        ORDER BY er.co_occurrence_count DESC
    """), {'country': country, 'min_coo': min_cooccurrence}).fetchall()

    if not rows:
        return []

    # Batch-load doc snippets for all relationships
    # Collect a sample of doc_ids across all relationships (cap to avoid huge queries)
    all_doc_ids = set()
    rel_doc_ids_map = {}
    for row in rows:
        source_ids = row[7] or []
        sampled = source_ids[:10]
        rel_doc_ids_map[row[0]] = sampled
        all_doc_ids.update(sampled)

    doc_snippets_map = {}
    if all_doc_ids:
        doc_id_list = list(all_doc_ids)
        snippet_rows = session.execute(text("""
            SELECT doc_id, distilled_text FROM documents
            WHERE doc_id = ANY(:doc_ids)
              AND distilled_text IS NOT NULL
              AND distilled_text != ''
        """), {'doc_ids': doc_id_list}).fetchall()
        for doc_id, distilled in snippet_rows:
            if distilled:
                doc_snippets_map[doc_id] = distilled[:400]

    result = []
    for row in rows:
        cats = row[6] or {}
        if isinstance(cats, str):
            try:
                cats = _json.loads(cats)
            except (ValueError, TypeError):
                cats = {}
        if isinstance(cats, dict) and cats:
            sorted_cats = sorted(cats.items(), key=lambda x: x[1], reverse=True)[:5]
            categories_str = ", ".join(f"{k} ({v})" for k, v in sorted_cats)
        else:
            categories_str = "N/A"

        rel_id = row[0]
        doc_snippets = [
            doc_snippets_map[did]
            for did in rel_doc_ids_map.get(rel_id, [])
            if did in doc_snippets_map
        ][:5]

        result.append({
            'id': rel_id,
            'entity_from_id': row[1],
            'entity_to_id': row[2],
            'co_occurrence_count': row[3],
            'first_co_occurrence': row[4],
            'last_co_occurrence': row[5],
            'categories_str': categories_str,
            'from_name': row[8],
            'from_type': row[9],
            'from_role': row[10],
            'from_country': row[11],
            'to_name': row[12],
            'to_type': row[13],
            'to_role': row[14],
            'doc_snippets': doc_snippets,
        })

    return result


def build_relationship_classification_prompt(rel: Dict) -> Dict[str, List[Dict[str, str]]]:
    """
    Build prompt for entity relationship classification.

    Args:
        rel: Relationship dict from load_relationships_for_classification

    Returns:
        Dict with 'messages' key containing system + user messages
    """
    snippets = rel.get('doc_snippets', [])
    if snippets:
        snippet_lines = "\n".join(f"  {i+1}. {s[:400]}" for i, s in enumerate(snippets))
    else:
        snippet_lines = "  (no document excerpts available)"

    user_prompt = f"""Classify the relationship between these two entities using ONLY the document evidence below.

**Entity A**: {rel['from_name']}
  Type: {rel['from_type']} | Role: {rel.get('from_role') or 'Unknown'} | Country: {rel['from_country']}

**Entity B**: {rel['to_name']}
  Type: {rel['to_type']} | Role: {rel.get('to_role') or 'Unknown'}

**Co-occurrence statistics**:
  Shared documents: {rel['co_occurrence_count']}
  Date range: {rel['first_co_occurrence']} to {rel['last_co_occurrence']}
  Top categories: {rel['categories_str']}

**Document evidence** (excerpts where both entities appear):
{snippet_lines}

{RELATIONSHIP_TYPE_DEFINITIONS}

Based ONLY on the evidence above, return a JSON object:
{{
    "relationship_type": "<one of the valid types above>",
    "relationship_description": "2-3 sentences. Name specific actions, titles, agreements, or meetings from the evidence. No filler phrases."
}}"""

    return {
        "messages": [
            {"role": "system", "content": RELATIONSHIP_CLASSIFICATION_SYS_PROMPT},
            {"role": "user", "content": user_prompt}
        ]
    }


def load_country_pairs_for_bilateral_summaries(
    session, country: Optional[str], min_docs: int = 500,
    regenerate: bool = False, config=None
) -> List[Dict]:
    """
    Load country pairs needing bilateral relationship summaries.

    Gathers all data for each pair at prepare time and embeds it in the prompt.

    Args:
        session: Database session
        country: Filter by initiating country (optional)
        min_docs: Minimum documents threshold for a pair
        regenerate: If True, include pairs that already have summaries
        config: Config object for influencer/recipient filtering

    Returns:
        List of pair dicts with pre-computed prompt data
    """
    import uuid as _uuid
    from services.pipeline.summaries.generate_bilateral_summaries import (
        gather_bilateral_data,
        format_bilateral_data_for_prompt,
        BILATERAL_SUMMARY_PROMPT
    )

    # Build query for eligible country pairs
    if config:
        influencers = config.influencers if hasattr(config, 'influencers') else []
        recipients = config.recipients if hasattr(config, 'recipients') else []

        pair_query = text("""
            SELECT
                ic.initiating_country,
                rc.recipient_country,
                COUNT(DISTINCT d.doc_id) as doc_count
            FROM documents d
            JOIN initiating_countries ic ON d.doc_id = ic.doc_id
            JOIN recipient_countries rc ON d.doc_id = rc.doc_id
            WHERE (:init_country IS NULL OR ic.initiating_country = :init_country)
            AND ic.initiating_country = ANY(:influencers)
            AND rc.recipient_country = ANY(:recipients)
            AND ic.initiating_country <> rc.recipient_country
            GROUP BY ic.initiating_country, rc.recipient_country
            HAVING COUNT(DISTINCT d.doc_id) >= :min_docs
            ORDER BY doc_count DESC
        """)

        pairs = session.execute(pair_query, {
            'init_country': country,
            'min_docs': min_docs,
            'influencers': influencers,
            'recipients': recipients
        }).fetchall()
    else:
        pair_query = text("""
            SELECT
                ic.initiating_country,
                rc.recipient_country,
                COUNT(DISTINCT d.doc_id) as doc_count
            FROM documents d
            JOIN initiating_countries ic ON d.doc_id = ic.doc_id
            JOIN recipient_countries rc ON d.doc_id = rc.doc_id
            WHERE (:init_country IS NULL OR ic.initiating_country = :init_country)
            AND ic.initiating_country <> rc.recipient_country
            GROUP BY ic.initiating_country, rc.recipient_country
            HAVING COUNT(DISTINCT d.doc_id) >= :min_docs
            ORDER BY doc_count DESC
        """)

        pairs = session.execute(pair_query, {
            'init_country': country,
            'min_docs': min_docs
        }).fetchall()

    if not pairs:
        return []

    # Filter out pairs that already have summaries (unless regenerate)
    if not regenerate:
        existing = session.execute(text("""
            SELECT initiating_country, recipient_country
            FROM bilateral_relationship_summaries
            WHERE is_deleted = false
        """)).fetchall()
        existing_set = {(r[0], r[1]) for r in existing}
        pairs = [p for p in pairs if (p[0], p[1]) not in existing_set]

    if not pairs:
        return []

    result = []
    for init_c, recip_c, doc_count in pairs:
        # Gather bilateral data (7 SQL queries per pair)
        data = gather_bilateral_data(session, init_c, recip_c)

        if data['total_documents'] == 0:
            continue

        # Format data for prompt
        prompt_data = format_bilateral_data_for_prompt(data)

        # Generate deterministic UUID from country pair
        pair_uuid = str(_uuid.uuid5(_uuid.NAMESPACE_DNS, f"{init_c}_{recip_c}"))

        result.append({
            'id': pair_uuid,
            'initiating_country': init_c,
            'recipient_country': recip_c,
            'total_documents': data['total_documents'],
            'first_date': data['first_date'],
            'last_date': data['last_date'],
            'daily_events': data['daily_events'],
            'weekly_events': data['weekly_events'],
            'monthly_events': data['monthly_events'],
            'prompt_data': prompt_data
        })

    return result


BILATERAL_SUMMARY_SYS_PROMPT = "You are an expert analyst of international relations and soft power diplomacy. Output valid JSON only."


def build_bilateral_summary_prompt(pair_data: Dict) -> Dict[str, List[Dict[str, str]]]:
    """
    Build prompt for bilateral relationship summary generation.

    Uses BILATERAL_SUMMARY_PROMPT template from generate_bilateral_summaries.py.

    Args:
        pair_data: Dict from load_country_pairs_for_bilateral_summaries

    Returns:
        Dict with 'messages' key containing system + user messages
    """
    from services.pipeline.summaries.generate_bilateral_summaries import BILATERAL_SUMMARY_PROMPT

    first_date = pair_data['first_date']
    last_date = pair_data['last_date']
    if hasattr(first_date, 'strftime'):
        first_date = first_date.strftime('%Y-%m-%d')
    if hasattr(last_date, 'strftime'):
        last_date = last_date.strftime('%Y-%m-%d')

    total_events = pair_data['daily_events'] + pair_data['weekly_events'] + pair_data['monthly_events']

    user_prompt = BILATERAL_SUMMARY_PROMPT.format(
        initiating_country=pair_data['initiating_country'],
        recipient_country=pair_data['recipient_country'],
        first_date=first_date,
        last_date=last_date,
        total_docs=pair_data['total_documents'],
        total_events=total_events,
        daily_events=pair_data['daily_events'],
        weekly_events=pair_data['weekly_events'],
        monthly_events=pair_data['monthly_events'],
        **pair_data['prompt_data']
    )

    return {
        "messages": [
            {"role": "system", "content": BILATERAL_SUMMARY_SYS_PROMPT},
            {"role": "user", "content": user_prompt}
        ]
    }


def load_raw_events_for_rename(
    session,
    country: str = None,
    limit: int = None,
) -> List[Dict]:
    """
    Load raw_events that need more specific event names.

    Targets generic event names by joining with document distilled_text
    to give the LLM enough context to produce a specific name.

    Returns list of dicts with: doc_id, event_name, distilled_text,
    category, subcategory, initiating_country, recipient_country, projects
    """
    filters = []
    params = {}

    if country:
        filters.append("d.initiating_country ILIKE :country")
        params['country'] = f"%{country}%"

    limit_clause = f"LIMIT {limit}" if limit else ""

    # Only load events that haven't been renamed yet
    base_filter = "re.specific_event_name IS NULL"
    if filters:
        where_clause = "WHERE " + base_filter + " AND " + " AND ".join(filters)
    else:
        where_clause = "WHERE " + base_filter

    query = text(f"""
        SELECT
            re.doc_id,
            re.event_name,
            d.distilled_text,
            d.category,
            d.subcategory,
            d.initiating_country,
            d.recipient_country,
            d.project_name,
            d.date
        FROM raw_events re
        JOIN documents d ON re.doc_id = d.doc_id
        {where_clause}
        ORDER BY d.date ASC
        {limit_clause}
    """)

    rows = session.execute(query, params).fetchall()

    records = []
    for row in rows:
        records.append({
            'doc_id': row.doc_id,
            'event_name': row.event_name,
            'distilled_text': (row.distilled_text or '')[:1500],  # Cap for token budget
            'category': row.category or '',
            'subcategory': row.subcategory or '',
            'initiating_country': row.initiating_country or '',
            'recipient_country': row.recipient_country or '',
            'projects': row.project_name or '',
            'date': str(row.date) if row.date else '',
        })

    print(f"  Loaded {len(records)} raw events for rename")
    return records


def build_event_rename_prompt(record: Dict) -> Dict[str, List[Dict[str, str]]]:
    """
    Build prompt to rename a generic event name to a specific one.

    Uses distilled_text + metadata to produce a name that uniquely
    identifies THIS event vs other events involving the same country pair.
    """
    sys_prompt = """You are an expert analyst specializing in international relations and soft power events.

Your task is to produce a SPECIFIC event name from a document about a soft power interaction.

**THE PROBLEM:**
Generic event names like "Iran-Oman Bilateral Relations" or "China-Egypt Diplomatic Engagement" are useless for event tracking because dozens of unrelated events share the same vague label. When these get clustered, they create mega-blobs of thousands of unrelated documents.

**YOUR TASK:**
Read the document content and produce a specific event name that uniquely identifies THIS particular event, agreement, project, or initiative.

**RULES:**
1. The event name MUST reference the specific activity described (e.g., "signs port MOU", "launches Confucius Institute", "mediates nuclear talks")
2. Include key entities: named agreements, named projects, named summits, specific people when central
3. Include geographic specificity when it distinguishes the event (e.g., "Alexandria Port" not just "port")
4. The name should be specific enough that it could NOT describe a different event between the same two countries
5. Keep it under 100 characters
6. If the document describes a well-known named event (BRICS Summit, Belt and Road Forum, etc.), use the specific instance (e.g., "2024 BRICS Summit in Kazan" not just "BRICS Summit")

**GOOD event names:**
- "China-Egypt Suez Canal Economic Zone Phase 2 Expansion"
- "Oman Mediates Iran-US Nuclear Backchannel Talks, March 2025"
- "Turkey-Qatar Eagle Shield Joint Military Exercise 2024"
- "Iran Cultural Screening of 'Hezbollah is Alive' in Tehran"
- "China Funds $2B Alexandria Port Construction Project"
- "2024 Shanghai Cooperation Organization Summit in Astana"

**BAD event names (too generic — NEVER produce these):**
- "China-Egypt Bilateral Relations"
- "Iran Cultural Diplomacy"
- "Turkey-Qatar Military Cooperation"
- "China Economic Engagement with Egypt"
- "Diplomatic Meeting"
- "Trade Agreement"

If the document content is too vague to produce a specific name, do your best with available details and set confidence below 0.5."""

    user_prompt = f"""**Current event name:** {record['event_name']}
**Date:** {record['date']}
**Category:** {record['category']} / {record['subcategory']}
**Initiating country:** {record['initiating_country']}
**Recipient country:** {record['recipient_country']}
**Referenced projects:** {record['projects']}

**Document content:**
{record['distilled_text']}

Produce a specific event name for this document."""

    return {
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt}
        ]
    }


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
    temperature = TEMPERATURE_BY_JOB_TYPE.get(job_type, DEFAULT_TEMPERATURE)
    response_format = get_response_format_for_job_type(job_type)

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
                    "temperature": temperature,
                    "response_format": response_format
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
                    "temperature": temperature,
                    "response_format": response_format
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
                    "temperature": temperature,
                    "response_format": response_format
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
                    "temperature": temperature,
                    "response_format": response_format
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
                    "temperature": temperature,
                    "response_format": response_format
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
                    "temperature": temperature,
                    "response_format": response_format
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
                    "temperature": temperature,
                    "response_format": response_format
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
                    "temperature": temperature,
                    "response_format": response_format
                }
            })

    elif job_type == JOB_TYPE_GENERATE_WEEKLY_SUMMARY:
        # records is a list of (event, week) dicts needing weekly summaries
        for event_data in records:
            custom_id = generate_custom_id(
                job_type, event_data['canonical_event_id'],
                suffix=f"{event_data['week_start_str']}_{event_data['week_end_str']}"
            )
            prompt_data = build_weekly_summary_prompt(event_data)

            batch_requests.append({
                "custom_id": custom_id,
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": {
                    "model": model,
                    "messages": prompt_data["messages"],
                    "temperature": temperature,
                    "response_format": response_format
                }
            })

    elif job_type == JOB_TYPE_GENERATE_MONTHLY_SUMMARY:
        # records is a list of (event, month) dicts needing monthly summaries
        for event_data in records:
            custom_id = generate_custom_id(
                job_type, event_data['canonical_event_id'],
                suffix=f"{event_data['month_start_str']}_{event_data['month_end_str']}"
            )
            prompt_data = build_monthly_summary_prompt(event_data)

            batch_requests.append({
                "custom_id": custom_id,
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": {
                    "model": model,
                    "messages": prompt_data["messages"],
                    "temperature": temperature,
                    "response_format": response_format
                }
            })

    elif job_type == JOB_TYPE_GENERATE_YEARLY_SUMMARY:
        # records is a list of (event, year) dicts needing yearly summaries
        for event_data in records:
            custom_id = generate_custom_id(
                job_type, event_data['canonical_event_id'],
                suffix=f"{event_data['year_start_str']}_{event_data['year_end_str']}"
            )
            prompt_data = build_yearly_summary_prompt(event_data)

            batch_requests.append({
                "custom_id": custom_id,
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": {
                    "model": model,
                    "messages": prompt_data["messages"],
                    "temperature": temperature,
                    "response_format": response_format
                }
            })

    elif job_type == JOB_TYPE_SCORE_SUMMARY_MATERIALITY:
        # records is a list of event summaries needing materiality scoring
        for summary in records:
            custom_id = generate_custom_id(job_type, summary['id'])
            prompt_data = build_summary_materiality_prompt(summary)

            batch_requests.append({
                "custom_id": custom_id,
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": {
                    "model": model,
                    "messages": prompt_data["messages"],
                    "temperature": temperature,
                    "response_format": response_format
                }
            })

    elif job_type == JOB_TYPE_GENERATE_ENTITY_DESCRIPTIONS:
        for entity in records:
            custom_id = generate_custom_id(job_type, entity['id'])
            prompt_data = build_entity_description_prompt(entity)

            batch_requests.append({
                "custom_id": custom_id,
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": {
                    "model": model,
                    "messages": prompt_data["messages"],
                    "temperature": temperature,
                    "response_format": response_format
                }
            })

    elif job_type == JOB_TYPE_GENERATE_BILATERAL_SUMMARIES:
        for pair in records:
            custom_id = generate_custom_id(
                job_type, pair['id'],
                suffix=f"{pair['initiating_country']}--{pair['recipient_country']}"
            )
            prompt_data = build_bilateral_summary_prompt(pair)

            batch_requests.append({
                "custom_id": custom_id,
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": {
                    "model": model,
                    "messages": prompt_data["messages"],
                    "temperature": temperature,
                    "response_format": response_format
                }
            })

    elif job_type == JOB_TYPE_CLASSIFY_ENTITY_RELATIONSHIPS:
        for rel in records:
            custom_id = generate_custom_id(job_type, rel['id'])
            prompt_data = build_relationship_classification_prompt(rel)

            batch_requests.append({
                "custom_id": custom_id,
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": {
                    "model": model,
                    "messages": prompt_data["messages"],
                    "temperature": temperature,
                    "response_format": response_format
                }
            })

    elif job_type == JOB_TYPE_EVENT_RENAME:
        # records is a list of raw event dicts needing specific names
        # raw_events has composite PK (doc_id, event_name), so one doc_id can
        # appear multiple times. Use a hash of event_name as suffix for uniqueness.
        import hashlib
        for record in records:
            name_hash = hashlib.md5(record['event_name'].encode()).hexdigest()[:8]
            custom_id = generate_custom_id(job_type, record['doc_id'], suffix=name_hash)
            prompt_data = build_event_rename_prompt(record)

            batch_requests.append({
                "custom_id": custom_id,
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": {
                    "model": model,
                    "messages": prompt_data["messages"],
                    "temperature": temperature,
                    "response_format": response_format
                }
            })

    elif job_type == JOB_TYPE_PROPOSITION_EXTRACT:
        # records is a list of doc dicts from load_docs_for_proposition_extract
        for doc in records:
            custom_id = generate_custom_id(job_type, doc['doc_id'])
            prompt_data = build_proposition_extract_prompt(doc)

            batch_requests.append({
                "custom_id": custom_id,
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": {
                    "model": model,
                    "messages": prompt_data["messages"],
                    "temperature": temperature,
                    "response_format": response_format
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
                               JOB_TYPE_CANONICAL_ENTITY_DECONFLICT, JOB_TYPE_GENERATE_DAILY_SUMMARY,
                               JOB_TYPE_GENERATE_WEEKLY_SUMMARY, JOB_TYPE_GENERATE_MONTHLY_SUMMARY,
                               JOB_TYPE_GENERATE_YEARLY_SUMMARY,
                               JOB_TYPE_SCORE_SUMMARY_MATERIALITY,
                               JOB_TYPE_GENERATE_ENTITY_DESCRIPTIONS,
                               JOB_TYPE_GENERATE_BILATERAL_SUMMARIES,
                               JOB_TYPE_CLASSIFY_ENTITY_RELATIONSHIPS,
                               JOB_TYPE_EVENT_RENAME,
                               JOB_TYPE_PROPOSITION_EXTRACT],
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

    # Summary materiality scoring specific
    parser.add_argument('--period-type', type=str, default=None,
                       choices=['DAILY', 'WEEKLY', 'MONTHLY'],
                       help='Period type filter for summary materiality scoring (default: all)')

    # Output configuration
    # Proposition extraction specific
    parser.add_argument('--s3-prefix', type=str, default='dsr_extracts/',
                        help='[proposition_extract] S3 prefix for DSR JSON files')
    parser.add_argument('--s3-files', nargs='+',
                        help='[proposition_extract] Specific DSR filenames within --s3-prefix')
    parser.add_argument('--filename-contains', nargs='+', default=None,
                        help='[proposition_extract] Substring filter on DSR filenames before download')
    parser.add_argument('--initiators', type=str,
                        help='[proposition_extract] Comma-separated initiator allowlist (defaults to config influencers)')
    parser.add_argument('--recipients', type=str,
                        help='[proposition_extract] Comma-separated recipient allowlist (defaults to config recipients)')
    parser.add_argument('--body-csv', nargs='+', default=None,
                        help='[proposition_extract] ATOM CSV source(s): file, directory, or s3://bucket/prefix/')
    parser.add_argument('--input-text', choices=['distilled', 'body'], default='body',
                        help='[proposition_extract] Which text to feed the LLM (default: body)')
    parser.add_argument('--limit', type=int, default=10_000_000,
                        help='[proposition_extract] Cap on docs to include')

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

        elif args.job_type == JOB_TYPE_GENERATE_WEEKLY_SUMMARY:
            if not args.country:
                print("Error: --country is required for generate_weekly_summary")
                return
            if not start_date or not end_date:
                print("Error: --start-date and --end-date are required for generate_weekly_summary")
                return
            records = load_events_needing_weekly_summaries(
                session,
                args.country,
                start_date,
                end_date
            )
            print(f"Found {len(records)} (event, week) pairs needing weekly summaries")

        elif args.job_type == JOB_TYPE_GENERATE_MONTHLY_SUMMARY:
            if not args.country:
                print("Error: --country is required for generate_monthly_summary")
                return
            if not start_date or not end_date:
                print("Error: --start-date and --end-date are required for generate_monthly_summary")
                return
            records = load_events_needing_monthly_summaries(
                session,
                args.country,
                start_date,
                end_date
            )
            print(f"Found {len(records)} (event, month) pairs needing monthly summaries")

        elif args.job_type == JOB_TYPE_GENERATE_YEARLY_SUMMARY:
            if not args.country:
                print("Error: --country is required for generate_yearly_summary")
                return
            if not start_date or not end_date:
                print("Error: --start-date and --end-date are required for generate_yearly_summary")
                return
            records = load_events_needing_yearly_summaries(
                session,
                args.country,
                start_date,
                end_date
            )
            print(f"Found {len(records)} (event, year) pairs needing yearly summaries")

        elif args.job_type == JOB_TYPE_SCORE_SUMMARY_MATERIALITY:
            if not args.country:
                print("Error: --country is required for score_summary_materiality")
                return
            if not start_date or not end_date:
                print("Error: --start-date and --end-date are required for score_summary_materiality")
                return
            records = load_summaries_for_materiality_scoring(
                session,
                args.country,
                start_date,
                end_date,
                period_type=args.period_type,
                rescore=args.rescore
            )
            period_label = args.period_type or "ALL"
            print(f"Found {len(records)} event summaries needing materiality scoring ({period_label})")

        elif args.job_type == JOB_TYPE_GENERATE_ENTITY_DESCRIPTIONS:
            if not args.country:
                print("Error: --country is required for generate_entity_descriptions")
                return
            records = load_entities_for_description_generation(
                session,
                args.country,
                min_docs=args.min_articles,
                force=args.force
            )
            mode = "all (force)" if args.force else "missing only"
            print(f"Found {len(records)} entities needing descriptions ({mode})")

        elif args.job_type == JOB_TYPE_GENERATE_BILATERAL_SUMMARIES:
            from shared.utils.utils import Config
            config = Config.from_yaml('shared/config/config.yaml')
            min_docs = args.min_articles if args.min_articles != 3 else 500
            records = load_country_pairs_for_bilateral_summaries(
                session,
                args.country,
                min_docs=min_docs,
                regenerate=args.rescore,
                config=config
            )
            mode = "all (regenerate)" if args.rescore else "new pairs only"
            print(f"Found {len(records)} country pairs needing bilateral summaries ({mode}, min_docs={min_docs})")

        elif args.job_type == JOB_TYPE_CLASSIFY_ENTITY_RELATIONSHIPS:
            if not args.country:
                print("Error: --country is required for classify_entity_relationships")
                return
            min_coo = args.min_articles if args.min_articles != 3 else 2
            records = load_relationships_for_classification(
                session,
                args.country,
                force=args.force,
                min_cooccurrence=min_coo
            )
            mode = "all (force)" if args.force else "unclassified only"
            print(f"Found {len(records)} entity relationships to classify ({mode}, min_cooccurrence={min_coo})")

        elif args.job_type == JOB_TYPE_EVENT_RENAME:
            records = load_raw_events_for_rename(
                session,
                args.country,
                limit=args.min_articles if args.min_articles != 3 else None,
            )
            print(f"Found {len(records)} raw events for rename")

        elif args.job_type == JOB_TYPE_PROPOSITION_EXTRACT:
            # S3-driven loader; no DB query. session arg is unused for this path.
            initiators = [c.strip() for c in args.initiators.split(",")] if args.initiators else None
            recipients = [c.strip() for c in args.recipients.split(",")] if args.recipients else None
            records = load_docs_for_proposition_extract(
                s3_prefix=args.s3_prefix,
                s3_files=args.s3_files,
                filename_contains=args.filename_contains,
                initiators=initiators,
                recipients=recipients,
                start_date=args.start_date,
                end_date=args.end_date,
                body_csv=args.body_csv,
                input_text=args.input_text,
                limit=args.limit,
            )
            print(f"Found {len(records)} docs for proposition extraction")

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
                # score_summary_materiality runs once per period type over the
                # same (country, date) window — qualify the filename or the
                # DAILY/WEEKLY/MONTHLY preps overwrite each other's input
                # JSONL and every submission uploads the last-written one.
                if args.job_type == JOB_TYPE_SCORE_SUMMARY_MATERIALITY and args.period_type:
                    base_output_file = base_output_file.replace(
                        '_input.jsonl', f'_{args.period_type}_input.jsonl')
                # Add batch number suffix if multiple batches
                if num_chunks > 1:
                    output_file = base_output_file.replace('.jsonl', f'_batch{chunk_idx}.jsonl')
                else:
                    output_file = base_output_file

            # Write JSONL file
            print(f"Writing JSONL file to: {output_file}")
            write_jsonl(output_file, batch_requests)

            # For proposition_extract, also write a sidecar metadata JSON so
            # the post-process step can reconstruct per-doc output records
            # (source_body_csv, doc_title, countries, etc.) without re-fetching
            # from S3. The sidecar is keyed by doc_id and lives next to the
            # input JSONL with suffix _metadata.json.
            if args.job_type == JOB_TYPE_PROPOSITION_EXTRACT:
                import json as _json
                sidecar_path = output_file.replace('.jsonl', '_metadata.json')
                sidecar: Dict[str, Dict[str, Any]] = {}
                for doc in chunk:
                    sidecar[doc['doc_id']] = {
                        'doc_date': doc.get('doc_date'),
                        'doc_title': doc.get('doc_title'),
                        'doc_initiating_country': doc.get('doc_initiating_country'),
                        'doc_recipient_country': doc.get('doc_recipient_country'),
                        'doc_event_name': doc.get('doc_event_name'),
                        'source_s3_file': doc.get('source_s3_file'),
                        'source_body_csv': doc.get('source_body_csv'),
                        'input_text_source': doc.get('input_text_source'),
                    }
                with open(sidecar_path, 'w') as _f:
                    _json.dump(sidecar, _f, indent=2, default=str, ensure_ascii=False)
                print(f"Writing proposition metadata sidecar to: {sidecar_path}")

            import os as _os
            file_size_mb = _os.path.getsize(output_file) / (1024 * 1024)
            print(f"  Wrote {len(batch_requests)} requests to {output_file} ({file_size_mb:.2f} MB)")

            # Auto-split if file exceeds upload size limit
            from services.pipeline.batch.batch_config import MAX_UPLOAD_FILE_SIZE_MB
            split_files = split_jsonl_by_file_size(output_file, max_size_mb=MAX_UPLOAD_FILE_SIZE_MB)

            if len(split_files) > 1:
                print(f"  File exceeded {MAX_UPLOAD_FILE_SIZE_MB} MB limit, split into {len(split_files)} parts")

            # Create batch_job record for each file (usually 1, more if split)
            for split_file in split_files:
                split_size = count_jsonl_lines(split_file)
                split_file_mb = _os.path.getsize(split_file) / (1024 * 1024)
                # Pro-rate cost estimate based on split size
                split_cost = cost_estimate['total_cost'] * (split_size / len(batch_requests)) if batch_requests else 0

                if len(split_files) > 1:
                    print(f"\n  Split file: {_os.path.basename(split_file)} ({split_size} requests, {split_file_mb:.2f} MB)")

                print("Creating batch_job database record...")
                with BatchJobTracker(session) as tracker:
                    batch_job = tracker.create_batch_job(
                        job_type=args.job_type,
                        batch_size=split_size,
                        initiating_country=args.country,
                        date_range_start=start_date,
                        date_range_end=end_date,
                        input_file_path=split_file,
                        estimated_cost=split_cost,
                        created_by='batch_prepare.py'
                    )

                    print(f"  Created batch_job record: {batch_job.id}")
                    print(f"  Status: {batch_job.status}")
                    print(f"  Batch size: {batch_job.batch_size}")
                    print(f"  Estimated cost: ${batch_job.estimated_cost:.4f}")

                    created_batch_jobs.append({
                        'id': batch_job.id,
                        'file': split_file,
                        'size': split_size,
                        'cost': split_cost
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
