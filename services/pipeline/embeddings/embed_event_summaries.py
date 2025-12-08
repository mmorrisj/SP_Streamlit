"""
Embed Event Summaries (Daily, Weekly, Monthly)

This script embeds event summaries from the event_summaries table into pgvector.
Each period type (DAILY, WEEKLY, MONTHLY) has its own collection.

Usage:
    # Embed all missing summaries
    python services/pipeline/embeddings/embed_event_summaries.py

    # Embed only daily summaries
    python services/pipeline/embeddings/embed_event_summaries.py --period daily

    # Check status only
    python services/pipeline/embeddings/embed_event_summaries.py --status

    # Dry run
    python services/pipeline/embeddings/embed_event_summaries.py --dry-run

    # Specify batch size
    python services/pipeline/embeddings/embed_event_summaries.py --batch-size 50
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Optional

# Configure stdout encoding for Unicode support on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# Add project root to path
script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent.parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text
from shared.database.database import get_session, get_engine
from shared.models.models import EventSummary, PeriodType
from services.pipeline.embeddings import embedding_vectorstore


def get_collection_name(period_type: str) -> str:
    """Get the collection name for a period type."""
    return f"{period_type.lower()}_event_embeddings"


def find_missing_embeddings(period_type: Optional[str] = None):
    """
    Find event summaries that don't have embeddings.

    Args:
        period_type: Filter by period type (DAILY, WEEKLY, MONTHLY) or None for all

    Returns:
        Dict mapping period_type to list of summary IDs
    """
    print(f"\n{'='*80}")
    print("Finding Event Summaries Missing Embeddings")
    print(f"{'='*80}")

    engine = get_engine()
    missing_by_period = {}

    # Determine which periods to check
    if period_type:
        periods = [period_type.upper()]
    else:
        periods = ['DAILY', 'WEEKLY', 'MONTHLY']

    with engine.connect() as conn:
        for period in periods:
            collection_name = get_collection_name(period)

            # Find summaries without embeddings
            result = conn.execute(text("""
                SELECT
                    es.id,
                    es.event_name,
                    es.initiating_country,
                    es.period_start,
                    es.period_end,
                    LENGTH(COALESCE(es.event_name, '') || ' ' || COALESCE(es.material_justification, '')) as text_length
                FROM event_summaries es
                WHERE es.period_type = :period_type
                AND es.id::text NOT IN (
                    SELECT DISTINCT cmetadata->>'summary_id'
                    FROM langchain_pg_embedding
                    WHERE cmetadata->>'summary_id' IS NOT NULL
                    AND collection_id = (
                        SELECT uuid FROM langchain_pg_collection WHERE name = :collection_name
                    )
                )
                ORDER BY es.period_start DESC
            """), {"period_type": period, "collection_name": collection_name})

            missing_summaries = result.fetchall()

            if missing_summaries:
                missing_by_period[period] = missing_summaries

                print(f"\n{period} Summaries:")
                print(f"  Missing embeddings: {len(missing_summaries)}")
                print(f"  Sample (first 5):")
                print(f"  {'Event Name':<50} {'Country':<20} {'Period':<25}")
                print(f"  {'-'*95}")

                for summary in missing_summaries[:5]:
                    event_name = summary[1][:48] + "..." if len(summary[1]) > 50 else summary[1]
                    country = summary[2][:18] + "..." if len(summary[2]) > 20 else summary[2]
                    period_str = f"{summary[3]} to {summary[4]}"
                    print(f"  {event_name:<50} {country:<20} {period_str:<25}")

                if len(missing_summaries) > 5:
                    print(f"  ... and {len(missing_summaries) - 5} more")

    return missing_by_period


def get_embedding_statistics(period_type: Optional[str] = None):
    """
    Get statistics about event summary embeddings.

    Args:
        period_type: Filter by period type or None for all
    """
    print(f"\n{'='*80}")
    print("Event Summary Embedding Statistics")
    print(f"{'='*80}")

    engine = get_engine()

    # Determine which periods to check
    if period_type:
        periods = [period_type.upper()]
    else:
        periods = ['DAILY', 'WEEKLY', 'MONTHLY']

    with engine.connect() as conn:
        for period in periods:
            collection_name = get_collection_name(period)

            # Total summaries
            total_summaries = conn.execute(text("""
                SELECT COUNT(*)
                FROM event_summaries
                WHERE period_type = :period_type
            """), {"period_type": period}).scalar()

            # Embedded summaries
            embedded_summaries = conn.execute(text("""
                SELECT COUNT(DISTINCT cmetadata->>'summary_id')
                FROM langchain_pg_embedding
                WHERE cmetadata->>'summary_id' IS NOT NULL
                AND collection_id = (
                    SELECT uuid FROM langchain_pg_collection WHERE name = :collection_name
                )
            """), {"collection_name": collection_name}).scalar()

            # Total embedding records
            total_embeddings = conn.execute(text("""
                SELECT COUNT(*)
                FROM langchain_pg_embedding
                WHERE collection_id = (
                    SELECT uuid FROM langchain_pg_collection WHERE name = :collection_name
                )
            """), {"collection_name": collection_name}).scalar()

            missing = total_summaries - (embedded_summaries or 0)
            completion_pct = ((embedded_summaries or 0) / total_summaries * 100) if total_summaries > 0 else 0

            print(f"\n{period} Event Summaries:")
            print(f"  Collection: {collection_name}")
            print(f"  Total summaries: {total_summaries:,}")
            print(f"  Summaries with embeddings: {embedded_summaries or 0:,}")
            print(f"  Missing embeddings: {missing:,}")
            print(f"  Total embedding records: {total_embeddings:,}")
            print(f"  Completion: {completion_pct:.1f}%")

    print(f"{'='*80}\n")


def embed_event_summaries(summary_ids: List[str], period_type: str, batch_size: int = 50):
    """
    Embed event summaries into pgvector.

    Args:
        summary_ids: List of summary IDs to embed
        period_type: Period type (DAILY, WEEKLY, MONTHLY)
        batch_size: Number of summaries to process per batch
    """
    print(f"\nEmbedding {len(summary_ids)} {period_type} event summaries...")

    # Get the appropriate vector store
    if period_type == 'DAILY':
        vector_store = embedding_vectorstore.daily_store
    elif period_type == 'WEEKLY':
        vector_store = embedding_vectorstore.weekly_store
    elif period_type == 'MONTHLY':
        vector_store = embedding_vectorstore.monthly_store
    else:
        raise ValueError(f"Unknown period type: {period_type}")

    embedded_count = 0

    with get_session() as session:
        # Process in batches
        for i in range(0, len(summary_ids), batch_size):
            batch_ids = summary_ids[i:i+batch_size]

            # Fetch summaries
            summaries = session.query(EventSummary).filter(
                EventSummary.id.in_(batch_ids)
            ).all()

            if not summaries:
                continue

            # Prepare texts and metadata
            batch_texts = []
            batch_metadatas = []
            batch_embedding_ids = []

            for summary in summaries:
                # Combine all text fields
                text_parts = []
                if summary.event_name:
                    text_parts.append(f"Event: {summary.event_name}")

                # Extract text from narrative_summary JSONB
                if summary.narrative_summary:
                    if isinstance(summary.narrative_summary, dict):
                        # Extract all text values from the JSON structure
                        for key, value in summary.narrative_summary.items():
                            if isinstance(value, str) and value.strip():
                                text_parts.append(f"{key}: {value}")
                            elif isinstance(value, list):
                                for item in value:
                                    if isinstance(item, str) and item.strip():
                                        text_parts.append(item)

                # Add material justification if present
                if hasattr(summary, 'material_justification') and summary.material_justification:
                    text_parts.append(f"Justification: {summary.material_justification}")

                combined_text = "\n".join(text_parts)

                if not combined_text.strip():
                    continue  # Skip empty summaries

                batch_texts.append(combined_text)
                batch_metadatas.append({
                    'summary_id': str(summary.id),
                    'period_type': summary.period_type.value,
                    'event_name': summary.event_name,
                    'initiating_country': summary.initiating_country,
                    'period_start': str(summary.period_start),
                    'period_end': str(summary.period_end),
                    'source': 'event_summary'
                })
                batch_embedding_ids.append(f"event_summary_{summary.id}_{len(batch_texts)}")

            # Embed the batch
            if batch_texts:
                try:
                    vector_store.add_texts(
                        texts=batch_texts,
                        metadatas=batch_metadatas,
                        ids=batch_embedding_ids
                    )
                    embedded_count += len(batch_texts)
                    print(f"[OK] Embedded batch {(i//batch_size)+1}: {len(batch_texts)} summaries")
                except Exception as e:
                    print(f"[ERROR] Error embedding batch {(i//batch_size)+1}: {e}")

    print(f"[COMPLETE] Embedded {embedded_count} {period_type} event summaries")
    return embedded_count


def main():
    parser = argparse.ArgumentParser(
        description='Embed event summaries (daily, weekly, monthly) into pgvector',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Embed all missing event summaries
  python services/pipeline/embeddings/embed_event_summaries.py

  # Embed only daily summaries
  python services/pipeline/embeddings/embed_event_summaries.py --period daily

  # Show status only
  python services/pipeline/embeddings/embed_event_summaries.py --status

  # Dry run (no actual embedding)
  python services/pipeline/embeddings/embed_event_summaries.py --dry-run
        """
    )

    parser.add_argument(
        '--period',
        choices=['daily', 'weekly', 'monthly'],
        help='Embed only summaries of this period type'
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=50,
        help='Number of summaries to process per batch (default: 50)'
    )
    parser.add_argument(
        '--status',
        action='store_true',
        help='Show embedding statistics and exit'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Find missing summaries but don\'t embed them'
    )
    parser.add_argument(
        '--yes', '-y',
        action='store_true',
        help='Skip confirmation prompt and proceed automatically'
    )

    args = parser.parse_args()

    # Show statistics
    get_embedding_statistics(args.period)

    if args.status:
        sys.exit(0)

    # Find missing embeddings
    missing_by_period = find_missing_embeddings(args.period)

    if not missing_by_period:
        print("\nAll event summaries have embeddings!")
        sys.exit(0)

    # Calculate total
    total_missing = sum(len(summaries) for summaries in missing_by_period.values())

    if args.dry_run:
        print(f"\n[DRY RUN] Would embed {total_missing} event summaries")
        sys.exit(0)

    # Confirm before proceeding
    print(f"\n{'='*80}")
    print(f"Ready to embed {total_missing} event summaries")
    print(f"Batch size: {args.batch_size}")
    for period, summaries in missing_by_period.items():
        print(f"  {period}: {len(summaries)} summaries")
    print(f"{'='*80}")

    if not args.yes:
        response = input("\nProceed with embedding? [y/N]: ").strip().lower()
        if response != 'y':
            print("Cancelled.")
            sys.exit(0)
    else:
        print("\nProceeding automatically (--yes flag provided)...")

    # Embed summaries by period
    print(f"\nStarting event summary embedding process...")
    start_time = datetime.now()

    try:
        total_embedded = 0
        for period, summaries in missing_by_period.items():
            summary_ids = [str(s[0]) for s in summaries]  # Extract IDs from result tuples
            embedded = embed_event_summaries(summary_ids, period, args.batch_size)
            total_embedded += embedded

        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        print(f"\n{'='*80}")
        print("Embedding Complete!")
        print(f"{'='*80}")
        print(f"Event summaries embedded: {total_embedded}")
        print(f"Duration: {duration:.2f} seconds")
        if total_embedded > 0:
            print(f"Average: {duration/total_embedded:.2f} seconds per summary")
        print(f"{'='*80}\n")

        # Show updated statistics
        get_embedding_statistics(args.period)

    except Exception as e:
        print(f"\n[ERROR] Error during embedding: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
