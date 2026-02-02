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

    # Dry run (preview without creating files)
    python batch_prepare.py \\
        --job-type cluster_deconflict \\
        --country China \\
        --dry-run
"""
import argparse
import json
import sys
from pathlib import Path
from datetime import datetime, date as DateType
from typing import List, Dict, Any, Optional
import yaml

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from shared.database.database import get_session
from shared.models.models import EventCluster, CanonicalEvent
from services.pipeline.batch.batch_config import (
    JOB_TYPE_CLUSTER_DECONFLICT,
    JOB_TYPE_CANONICAL_DECONFLICT,
    get_batch_file_path,
    get_model_for_job_type,
    DEFAULT_TEMPERATURE
)
from services.pipeline.batch.batch_tracker import BatchJobTracker
from services.pipeline.batch.utils.custom_id import generate_custom_id
from services.pipeline.batch.utils.jsonl_utils import write_jsonl
from services.pipeline.batch.utils.cost_estimator import estimate_batch_cost, calculate_message_tokens


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

    query = """
        SELECT
            ce.id,
            ce.canonical_name,
            ce.initiating_country,
            ce.master_event_id,
            COALESCE(SUM(dem.article_count), 0) as total_articles,
            COUNT(DISTINCT dem.mention_date) as days_mentioned
        FROM canonical_events ce
        LEFT JOIN daily_event_mentions dem ON ce.id = dem.canonical_event_id
        WHERE ce.master_event_id IS NOT NULL
          AND ce.master_event_id IN (
              SELECT id FROM canonical_events
              WHERE master_event_id IS NULL
              AND (llm_validated = FALSE OR llm_validated IS NULL)
          )
    """

    params = {}
    if country:
        query += " AND ce.initiating_country = :country"
        params['country'] = country

    query += """
        GROUP BY ce.id, ce.canonical_name, ce.initiating_country, ce.master_event_id
        ORDER BY ce.master_event_id, total_articles DESC
    """

    result = session.execute(text(query), params).fetchall()

    groups = defaultdict(list)
    for row in result:
        master_id = str(row[3])
        groups[master_id].append({
            'id': row[0],
            'canonical_name': row[1],
            'initiating_country': row[2],
            'master_event_id': row[3],
            'total_articles': row[4],
            'days_mentioned': row[5]
        })

    # Filter groups with 2+ events
    filtered_groups = {k: v for k, v in groups.items() if len(v) > 1}

    return filtered_groups


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

    return batch_requests


def main():
    parser = argparse.ArgumentParser(
        description="Stage 1: Prepare JSONL input files for OpenAI Batch API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    # Job configuration
    parser.add_argument('--job-type', required=True,
                       choices=[JOB_TYPE_CLUSTER_DECONFLICT, JOB_TYPE_CANONICAL_DECONFLICT],
                       help='Type of batch job to prepare')
    parser.add_argument('--model', type=str,
                       help='OpenAI model to use (default: auto-detect from job type)')

    # Scope filters
    parser.add_argument('--country', type=str, help='Filter by initiating country')
    parser.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD)')
    parser.add_argument('--all-unprocessed', action='store_true',
                       help='Process all unprocessed records (ignores date filters)')

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

        else:
            print(f"Error: Unsupported job type: {args.job_type}")
            return

        if len(records) == 0:
            print("No unprocessed records found. Exiting.")
            return

        # Generate batch requests
        print(f"\\nGenerating batch API requests...")
        batch_requests = generate_batch_requests(args.job_type, records, model)
        print(f"Generated {len(batch_requests)} batch requests")

        # Estimate cost
        print(f"\\nEstimating costs...")
        total_input_tokens = sum(
            calculate_message_tokens(req['body']['messages'], model)
            for req in batch_requests
        )
        avg_input_tokens = total_input_tokens // len(batch_requests) if batch_requests else 0

        from services.pipeline.batch.utils.cost_estimator import estimate_batch_cost
        cost_estimate = estimate_batch_cost(len(batch_requests), avg_input_tokens, model=model)

        print(f"  Total requests: {len(batch_requests)}")
        print(f"  Avg input tokens: {avg_input_tokens}")
        print(f"  Estimated input cost: ${cost_estimate['input_cost']:.4f}")
        print(f"  Estimated output cost: ${cost_estimate['output_cost']:.4f}")
        print(f"  Estimated total cost: ${cost_estimate['total_cost']:.4f}")
        print(f"  Cost per request: ${cost_estimate['per_request_cost']:.6f}")

        if args.dry_run:
            print("\\n[DRY RUN] Would have created:")
            print(f"  - JSONL file with {len(batch_requests)} requests")
            print(f"  - batch_jobs database record")
            print("\\nExiting without creating files.")
            return

        # Generate output file path
        if args.output:
            output_file = args.output
        else:
            output_file = get_batch_file_path(
                args.job_type,
                'input',
                args.country,
                str(start_date) if start_date else None,
                str(end_date) if end_date else None
            )

        # Write JSONL file
        print(f"\\nWriting JSONL file to: {output_file}")
        write_jsonl(output_file, batch_requests)
        print(f"✓ Wrote {len(batch_requests)} requests to {output_file}")

        # Create batch_job record
        print(f"\\nCreating batch_job database record...")
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
            print(f"  Status: {batch_job.status.value}")
            print(f"  Batch size: {batch_job.batch_size}")
            print(f"  Estimated cost: ${batch_job.estimated_cost:.4f}")

        print()
        print("=" * 80)
        print("BATCH PREPARE COMPLETE")
        print("=" * 80)
        print(f"Batch Job ID: {batch_job.id}")
        print(f"Input file: {output_file}")
        print(f"\\nNext step: Submit batch to OpenAI")
        print(f"  python batch_submit.py --batch-job-id {batch_job.id}")
        print("=" * 80)


if __name__ == "__main__":
    main()
