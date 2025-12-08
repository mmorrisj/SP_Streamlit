"""
Stage 2B: LLM Validation of Canonical Event Consolidation

Part of the two-stage batch consolidation pipeline for event processing.

This script processes consolidated canonical event groups and uses an LLM to:
1. Validate that events in each group truly represent the same real-world event
2. Pick the best canonical name from the group
3. Split groups that were incorrectly merged by embedding similarity

PIPELINE CONTEXT:
  - Stage 1: Daily clustering (batch_cluster_events.py + llm_deconflict_clusters.py)
  - Stage 2A: consolidate_all_events.py - Groups events using embedding similarity
  - Stage 2B: THIS SCRIPT - LLM validates groupings, picks best names, splits if needed
  - Stage 2C: merge_canonical_events.py - Consolidates daily mentions

Processing Strategy:
1. Load all event groups (canonical events with same master_event_id)
2. For each group, send event names to LLM for review
3. LLM validates grouping and selects best canonical name
4. If group contains multiple distinct events, split into subgroups
5. Update database with LLM recommendations

Usage:
    # Process all consolidated event groups
    python llm_deconflict_canonical_events.py --all

    # Process specific country
    python llm_deconflict_canonical_events.py --country China

    # Process all influencers
    python llm_deconflict_canonical_events.py --influencers

    # Dry run
    python llm_deconflict_canonical_events.py --all --dry-run

See EVENT_PROCESSING_ARCHITECTURE.md for complete pipeline documentation.
"""

import argparse
import json
import yaml
from typing import List, Dict, Optional
from collections import defaultdict
from sqlalchemy import text

from shared.database.database import get_session
from shared.utils.utils import gai


def load_config(config_path: str = 'shared/config/config.yaml') -> dict:
    """Load configuration from config.yaml"""
    try:
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
            return {
                'influencers': config.get('influencers', ['China', 'Russia', 'Iran', 'Turkey', 'United States'])
            }
    except Exception as e:
        print(f"[WARNING] Could not load config.yaml: {e}")
        return {'influencers': ['China', 'Russia', 'Iran', 'Turkey', 'United States']}


def load_event_groups(
    session,
    country: Optional[str] = None
) -> Dict[str, List[Dict]]:
    """
    Load all consolidated event groups.

    Returns:
        Dict mapping master_event_id to list of events in that group
    """
    query = """
        SELECT
            ce.id,
            ce.canonical_name,
            ce.initiating_country,
            ce.master_event_id,
            ce.alternative_names,
            COALESCE(SUM(dem.article_count), 0) as total_articles,
            COUNT(DISTINCT dem.mention_date) as days_mentioned
        FROM canonical_events ce
        LEFT JOIN daily_event_mentions dem ON ce.id = dem.canonical_event_id
        WHERE ce.master_event_id IS NOT NULL
    """

    params = {}
    if country:
        query += " AND ce.initiating_country = :country"
        params['country'] = country

    query += """
        GROUP BY ce.id, ce.canonical_name, ce.initiating_country, ce.master_event_id, ce.alternative_names
        ORDER BY ce.master_event_id, total_articles DESC
    """

    result = session.execute(text(query), params).fetchall()

    # Group by master_event_id
    groups = defaultdict(list)
    for row in result:
        master_id = str(row[3])
        groups[master_id].append({
            'id': row[0],
            'canonical_name': row[1],
            'initiating_country': row[2],
            'master_event_id': row[3],
            'alternative_names': row[4] or [],
            'total_articles': row[5],
            'days_mentioned': row[6]
        })

    # Also load the master events themselves
    master_query = """
        SELECT
            ce.id,
            ce.canonical_name,
            ce.initiating_country,
            ce.alternative_names,
            COALESCE(SUM(dem.article_count), 0) as total_articles,
            COUNT(DISTINCT dem.mention_date) as days_mentioned
        FROM canonical_events ce
        LEFT JOIN daily_event_mentions dem ON ce.id = dem.canonical_event_id
        WHERE ce.master_event_id IS NULL
          AND EXISTS (
              SELECT 1 FROM canonical_events child
              WHERE child.master_event_id = ce.id
          )
    """

    if country:
        master_query += " AND ce.initiating_country = :country"

    master_query += """
        GROUP BY ce.id, ce.canonical_name, ce.initiating_country, ce.alternative_names
    """

    master_result = session.execute(text(master_query), params).fetchall()

    for row in master_result:
        master_id = str(row[0])
        # Add master event to its own group
        if master_id in groups:
            groups[master_id].insert(0, {
                'id': row[0],
                'canonical_name': row[1],
                'initiating_country': row[2],
                'master_event_id': None,
                'alternative_names': row[3] or [],
                'total_articles': row[4],
                'days_mentioned': row[5]
            })

    return groups


def llm_review_group(events: List[Dict], verbose: bool = True) -> Dict:
    """
    Use LLM to review an event group and select the best canonical name.

    Returns:
        Dict with:
        - same_event: bool (whether all events represent the same thing)
        - best_canonical_name: str (best name to use)
        - reasoning: str (explanation)
        - should_split: bool (whether group should be split)
        - split_groups: list of lists (if should_split=True)
    """
    # Build event names list
    event_names = [e['canonical_name'] for e in events]
    names_list = "\n".join([f"{i+1}. {name} ({events[i]['total_articles']} articles, {events[i]['days_mentioned']} days)"
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

**Country:** {events[0]['initiating_country']}
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

    try:
        if verbose:
            print(f"    [LLM] Reviewing {len(events)} events...")

        # Call LLM via FastAPI proxy
        response = gai(sys_prompt, user_prompt, model="gpt-4o-mini", use_proxy=True)

        # Parse JSON response
        if isinstance(response, dict):
            result = response
        else:
            # Try to extract JSON from response
            import re
            json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', response, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group(0))
            else:
                result = json.loads(response)

        # Validate response
        if 'same_event' not in result:
            raise ValueError(f"Invalid LLM response: missing 'same_event' field")

        return result

    except Exception as e:
        if verbose:
            print(f"    [WARNING] LLM review failed: {e}")

        # Return safe default - keep group as-is, use highest article count name
        return {
            'same_event': True,
            'best_canonical_name': events[0]['canonical_name'],
            'reasoning': f'LLM review failed: {str(e)}. Defaulting to highest article count.',
            'should_split': False,
            'split_groups': []
        }


def process_country(
    session,
    country: str,
    dry_run: bool = False,
    verbose: bool = True
) -> Dict[str, int]:
    """
    Process all event groups for a specific country.

    Returns:
        Statistics dict
    """
    if verbose:
        print(f"\n{'='*80}")
        print(f"LLM Deconfliction: {country}")
        print(f"{'='*80}")

    # Load event groups
    groups = load_event_groups(session, country)

    if len(groups) == 0:
        if verbose:
            print(f"  No consolidated event groups found")
        return {'groups': 0, 'validated': 0, 'split': 0, 'renamed': 0}

    if verbose:
        print(f"  Found {len(groups)} consolidated event groups")

    stats = {
        'groups': len(groups),
        'validated': 0,
        'split': 0,
        'renamed': 0
    }

    # Process each group
    for i, (master_id, group_events) in enumerate(groups.items(), 1):
        if verbose and i % 100 == 0:
            print(f"  Progress: {i}/{len(groups)} groups processed...")

        # Skip single-event groups
        if len(group_events) <= 1:
            continue

        # Get LLM review
        review = llm_review_group(group_events, verbose=False)

        if verbose:
            best_name_raw = review.get('best_canonical_name')
            safe_name = best_name_raw.encode('ascii', 'replace').decode('ascii') if best_name_raw else 'N/A'
            print(f"\n  Group {i}/{len(groups)}: {len(group_events)} events")
            print(f"    Current master: {group_events[0]['canonical_name'].encode('ascii', 'replace').decode('ascii')}")
            print(f"    LLM decision: same_event={review['same_event']}, should_split={review.get('should_split', False)}")
            if review['same_event'] and best_name_raw:
                print(f"    Best name: {safe_name}")
            print(f"    Reasoning: {review.get('reasoning', 'N/A')[:100]}...")

        # Handle splitting
        if review.get('should_split') and review.get('split_groups'):
            if verbose:
                print(f"    [SPLIT] Group should be split into {len(review['split_groups'])} subgroups")
            stats['split'] += 1

            if not dry_run:
                # Implement splitting logic
                for subgroup_idx, subgroup in enumerate(review['split_groups']):
                    indices = subgroup.get('indices', [])
                    new_canonical_name = subgroup.get('canonical_name')

                    if not indices or not new_canonical_name:
                        continue

                    # Get events in this subgroup (convert 1-indexed to 0-indexed)
                    subgroup_events = [group_events[i-1] for i in indices if 0 < i <= len(group_events)]

                    if len(subgroup_events) == 0:
                        continue

                    # Find or create the event with the canonical name
                    best_event = next((e for e in subgroup_events if e['canonical_name'] == new_canonical_name), None)

                    if not best_event:
                        # Use highest article count event as master, but we'll note the desired name
                        best_event = max(subgroup_events, key=lambda e: e['total_articles'])
                        if verbose:
                            print(f"      Subgroup {subgroup_idx+1}: Using '{best_event['canonical_name']}' as proxy for '{new_canonical_name}'")

                    # Set this event as the new master for this subgroup
                    new_master_id = best_event['id']

                    # Clear its master_event_id (make it a master)
                    session.execute(
                        text('UPDATE canonical_events SET master_event_id = NULL WHERE id = :new_master'),
                        {'new_master': new_master_id}
                    )

                    # Point all other events in this subgroup to the new master
                    for event in subgroup_events:
                        if event['id'] != new_master_id:
                            session.execute(
                                text('UPDATE canonical_events SET master_event_id = :new_master WHERE id = :child_id'),
                                {'new_master': new_master_id, 'child_id': event['id']}
                            )

                    if verbose:
                        print(f"      Created subgroup with master: {new_canonical_name}")

        # Handle renaming
        elif review['same_event'] and review.get('best_canonical_name'):
            best_name = review['best_canonical_name']
            current_master_name = group_events[0]['canonical_name']

            if best_name != current_master_name:
                if verbose:
                    print(f"    [RENAME] Master event name should change")
                stats['renamed'] += 1

                if not dry_run:
                    # Find the event with this name in the group
                    best_event = next((e for e in group_events if e['canonical_name'] == best_name), None)

                    if best_event and best_event['id'] != group_events[0]['id']:
                        # Swap master_event_id: make best_event the new master
                        old_master_id = group_events[0]['id']
                        new_master_id = best_event['id']

                        # Set old master to point to new master
                        session.execute(
                            text('UPDATE canonical_events SET master_event_id = :new_master WHERE id = :old_master'),
                            {'new_master': new_master_id, 'old_master': old_master_id}
                        )

                        # Update all other children to point to new master
                        session.execute(
                            text('UPDATE canonical_events SET master_event_id = :new_master WHERE master_event_id = :old_master'),
                            {'new_master': new_master_id, 'old_master': old_master_id}
                        )

                        # Set new master's master_event_id to NULL
                        session.execute(
                            text('UPDATE canonical_events SET master_event_id = NULL WHERE id = :new_master'),
                            {'new_master': new_master_id}
                        )

                        if verbose:
                            print(f"    [UPDATED] Swapped master event")

        stats['validated'] += 1

    # Commit if not dry run
    if not dry_run and (stats['renamed'] > 0 or stats['split'] > 0):
        session.commit()
        if verbose:
            print(f"\n  [COMMITTED] Renamed {stats['renamed']} groups")

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="LLM Deconfliction for Consolidated Canonical Events",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    # Country selection
    parser.add_argument('--country', type=str, help='Process specific country')
    parser.add_argument('--influencers', action='store_true', help='Process all influencer countries')
    parser.add_argument('--all', action='store_true', help='Process all countries')

    # Options
    parser.add_argument('--dry-run', action='store_true', help='Preview without saving to database')
    parser.add_argument('--verbose', action='store_true', default=True, help='Print detailed progress')

    args = parser.parse_args()

    # Get countries to process
    if args.influencers:
        config = load_config()
        countries = config['influencers']
    elif args.country:
        countries = [args.country]
    elif args.all:
        countries = None  # Process all
    else:
        print("[ERROR] Must specify --country, --influencers, or --all")
        return

    print("="*80)
    print("LLM DECONFLICTION FOR CONSOLIDATED CANONICAL EVENTS")
    print("="*80)
    if countries:
        print(f"Countries: {', '.join(countries)}")
    else:
        print("Countries: All")
    if args.dry_run:
        print("[DRY RUN MODE] No changes will be saved")
    print("="*80)

    overall_stats = {
        'total_groups': 0,
        'total_validated': 0,
        'total_split': 0,
        'total_renamed': 0
    }

    with get_session() as session:
        if countries is None:
            # Get all countries with consolidated events
            result = session.execute(text('''
                SELECT DISTINCT initiating_country
                FROM canonical_events
                WHERE master_event_id IS NOT NULL
                ORDER BY initiating_country
            ''')).fetchall()
            countries = [row[0] for row in result]

        for country in countries:
            stats = process_country(session, country, args.dry_run, args.verbose)
            overall_stats['total_groups'] += stats['groups']
            overall_stats['total_validated'] += stats['validated']
            overall_stats['total_split'] += stats['split']
            overall_stats['total_renamed'] += stats['renamed']

    print()
    print("="*80)
    print("SUMMARY")
    print("="*80)
    print(f"Total event groups: {overall_stats['total_groups']}")
    print(f"Groups validated: {overall_stats['total_validated']}")
    print(f"Groups split: {overall_stats['total_split']}")
    print(f"Groups renamed: {overall_stats['total_renamed']}")
    print("="*80)


if __name__ == "__main__":
    main()
