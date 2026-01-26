"""
Improved LLM Deconfliction with Better Resume and Parallelization Support

Enhancements over original:
1. Automatic resume (no --resume flag needed)
2. Progress file tracking (.llm_progress.json)
3. Shows which group it's currently processing
4. Can be parallelized by running multiple instances with --chunk parameter
5. Graceful interrupt handling (Ctrl+C)

Usage:
    # Basic usage (auto-resumes from last checkpoint)
    python llm_deconflict_canonical_events_parallel.py --country China

    # Process specific chunk for parallelization (0-indexed)
    python llm_deconflict_canonical_events_parallel.py --country China --chunk 0 --total-chunks 4
    python llm_deconflict_canonical_events_parallel.py --country China --chunk 1 --total-chunks 4
    python llm_deconflict_canonical_events_parallel.py --country China --chunk 2 --total-chunks 4
    python llm_deconflict_canonical_events_parallel.py --country China --chunk 3 --total-chunks 4

    # Smaller batch size for more frequent commits
    python llm_deconflict_canonical_events_parallel.py --country China --batch-size 5

    # Skip already processed groups automatically
    python llm_deconflict_canonical_events_parallel.py --country China --skip-validated
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import argparse
import json
import signal
from datetime import datetime
from typing import List, Dict
from collections import defaultdict
from sqlalchemy import text

from shared.database.database import get_session
from shared.utils.utils import gai


# Global flag for graceful shutdown
interrupted = False

def signal_handler(sig, frame):
    global interrupted
    print("\n\n⚠️  Interrupt received - will stop after current group")
    interrupted = True

signal.signal(signal.SIGINT, signal_handler)


def load_progress(country: str) -> Dict:
    """Load progress from file."""
    progress_file = Path(f".llm_progress_{country}.json")
    if progress_file.exists():
        with open(progress_file, 'r') as f:
            return json.load(f)
    return {'processed_groups': [], 'last_updated': None}


def save_progress(country: str, processed_groups: List[str], stats: Dict):
    """Save progress to file."""
    progress_file = Path(f".llm_progress_{country}.json")
    progress = {
        'processed_groups': processed_groups,
        'last_updated': datetime.now().isoformat(),
        'stats': stats
    }
    with open(progress_file, 'w') as f:
        json.dump(progress, f, indent=2)


def get_event_groups(session, country: str = None, skip_validated: bool = True) -> Dict[str, List[Dict]]:
    """
    Load all event groups that need LLM review.

    Returns dict mapping master_event_id -> list of child events
    """
    # Load child events
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

    # Skip groups where master is already validated
    if skip_validated:
        query += """
            AND ce.master_event_id IN (
                SELECT id FROM canonical_events
                WHERE master_event_id IS NULL
                AND (llm_validated = FALSE OR llm_validated IS NULL)
            )
        """

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

    # Load master events
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

    if skip_validated:
        master_query += " AND (ce.llm_validated = FALSE OR ce.llm_validated IS NULL)"

    master_query += """
        GROUP BY ce.id, ce.canonical_name, ce.initiating_country, ce.alternative_names
    """

    master_result = session.execute(text(master_query), params).fetchall()

    for row in master_result:
        master_id = str(row[0])
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


def llm_review_group(events: List[Dict]) -> Dict:
    """Use LLM to review event group."""
    event_names = [e['canonical_name'] for e in events]
    names_list = "\n".join([f"{i+1}. {name} ({events[i]['total_articles']} articles, {events[i]['days_mentioned']} days)"
                           for i, name in enumerate(event_names)])

    sys_prompt = """You are an expert at analyzing event names to determine if they represent the same real-world event.

Return ONLY valid JSON with this exact structure:
{
  "same_event": true/false,
  "best_canonical_name": "Event Name",
  "reasoning": "Brief explanation",
  "should_split": false
}"""

    user_prompt = f"""Event group ({events[0]['initiating_country']}):
{names_list}

Do these represent the SAME event? Pick the BEST name.
Return JSON only."""

    response = gai(sys_prompt, user_prompt, model="gpt-4o-mini")

    try:
        # Parse JSON response
        json_str = response.strip()
        if json_str.startswith("```json"):
            json_str = json_str[7:]
        if json_str.endswith("```"):
            json_str = json_str[:-3]
        json_str = json_str.strip()

        review = json.loads(json_str)
        return review
    except Exception as e:
        print(f"    ⚠️  Error parsing LLM response: {e}")
        return {
            'same_event': True,
            'best_canonical_name': events[0]['canonical_name'],
            'reasoning': 'Parse error - keeping original',
            'should_split': False
        }


def process_groups(
    country: str,
    batch_size: int = 10,
    chunk: int = None,
    total_chunks: int = None,
    skip_validated: bool = True,
    dry_run: bool = False
):
    """Process event groups with resume capability."""

    # Load progress
    progress = load_progress(country)
    processed_master_ids = set(progress.get('processed_groups', []))

    print(f"\n{'='*80}")
    print(f"LLM DECONFLICTION: {country}")
    print(f"{'='*80}")
    print(f"Batch size: {batch_size}")
    print(f"Skip validated: {skip_validated}")
    print(f"Dry run: {dry_run}")
    if chunk is not None:
        print(f"Processing chunk: {chunk+1}/{total_chunks}")
    print(f"Previously processed: {len(processed_master_ids)} groups")
    print(f"{'='*80}\n")

    stats = progress.get('stats', {
        'validated': 0,
        'renamed': 0,
        'split': 0,
        'skipped': 0
    })

    with get_session() as session:
        # Load groups
        print("Loading event groups...")
        all_groups = get_event_groups(session, country, skip_validated)
        group_list = list(all_groups.items())

        # Apply chunking if specified
        if chunk is not None and total_chunks:
            chunk_size = len(group_list) // total_chunks + (1 if len(group_list) % total_chunks else 0)
            start_idx = chunk * chunk_size
            end_idx = min(start_idx + chunk_size, len(group_list))
            group_list = group_list[start_idx:end_idx]
            print(f"Chunk {chunk+1}: Processing groups {start_idx+1} to {end_idx} (of {len(all_groups)})")

        # Filter out already processed
        group_list = [(mid, events) for mid, events in group_list if mid not in processed_master_ids]

        print(f"Groups to process: {len(group_list)}\n")

        if len(group_list) == 0:
            print("✅ All groups already processed!")
            return

        groups_since_commit = 0

        for i, (master_id, group_events) in enumerate(group_list, 1):
            if interrupted:
                print("\n⚠️  Stopping gracefully...")
                break

            print(f"\n[{i}/{len(group_list)}] Processing group {master_id}")
            print(f"  Master: {group_events[0]['canonical_name'][:80]}")
            print(f"  Children: {len(group_events)-1} events")

            # LLM review
            review = llm_review_group(group_events)

            print(f"  Decision: same_event={review['same_event']}")
            if review.get('best_canonical_name'):
                print(f"  Best name: {review['best_canonical_name'][:80]}")
            print(f"  Reasoning: {review.get('reasoning', '')[:100]}")

            if not dry_run:
                # Mark master as validated
                session.execute(
                    text("""UPDATE canonical_events
                           SET llm_validated = TRUE,
                               llm_validated_at = NOW()
                           WHERE id = :master_id"""),
                    {'master_id': master_id}
                )

            stats['validated'] += 1
            processed_master_ids.add(master_id)
            groups_since_commit += 1

            # Commit every batch_size groups
            if not dry_run and groups_since_commit >= batch_size:
                session.commit()
                save_progress(country, list(processed_master_ids), stats)
                print(f"  ✅ CHECKPOINT: Saved progress ({i}/{len(group_list)} groups)")
                groups_since_commit = 0

        # Final commit
        if not dry_run and groups_since_commit > 0:
            session.commit()
            save_progress(country, list(processed_master_ids), stats)
            print(f"\n✅ FINAL COMMIT: Saved progress")

    print(f"\n{'='*80}")
    print("PROCESSING COMPLETE")
    print(f"{'='*80}")
    print(f"Validated: {stats['validated']}")
    print(f"Renamed: {stats['renamed']}")
    print(f"Split: {stats['split']}")
    print(f"Skipped: {stats['skipped']}")
    print(f"{'='*80}\n")


def main():
    parser = argparse.ArgumentParser(
        description='LLM deconfliction with improved resume and parallelization'
    )
    parser.add_argument('--country', required=True, help='Country to process')
    parser.add_argument('--batch-size', type=int, default=10, help='Commit every N groups (default: 10)')
    parser.add_argument('--chunk', type=int, help='Chunk number (0-indexed) for parallelization')
    parser.add_argument('--total-chunks', type=int, help='Total number of chunks for parallelization')
    parser.add_argument('--skip-validated', action='store_true', default=True, help='Skip validated groups (default: True)')
    parser.add_argument('--no-skip-validated', action='store_false', dest='skip_validated', help='Process all groups')
    parser.add_argument('--dry-run', action='store_true', help='Dry run mode')
    parser.add_argument('--clear-progress', action='store_true', help='Clear progress file and start fresh')

    args = parser.parse_args()

    if args.clear_progress:
        progress_file = Path(f".llm_progress_{args.country}.json")
        if progress_file.exists():
            progress_file.unlink()
            print(f"✅ Cleared progress file for {args.country}")
            return

    if (args.chunk is not None) != (args.total_chunks is not None):
        print("Error: --chunk and --total-chunks must be used together")
        return

    process_groups(
        country=args.country,
        batch_size=args.batch_size,
        chunk=args.chunk,
        total_chunks=args.total_chunks,
        skip_validated=args.skip_validated,
        dry_run=args.dry_run
    )


if __name__ == '__main__':
    main()
