"""
Embed Documents Missing Embeddings

This script finds documents in the database that don't have embeddings
and generates embeddings for them using direct embedding (no Celery required).

Usage:
    # Find and embed all missing documents
    python services/pipeline/embeddings/embed_missing_documents.py

    # Dry run (check what would be embedded without actually doing it)
    python services/pipeline/embeddings/embed_missing_documents.py --dry-run

    # Specify batch size
    python services/pipeline/embeddings/embed_missing_documents.py --batch-size 100

    # Show status only
    python services/pipeline/embeddings/embed_missing_documents.py --status
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime

# Add project root to path
script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent.parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text
from shared.database.database import get_session, get_engine
from shared.models.models import Document
from services.pipeline.ingestion.dsr import embed_documents_direct


def find_missing_embeddings(collection_name='chunk_embeddings'):
    """
    Find documents that don't have embeddings in pgvector.

    Args:
        collection_name: The LangChain collection to check against

    Returns:
        List of doc_ids missing embeddings
    """
    print(f"\n{'='*80}")
    print("Finding Documents Missing Embeddings")
    print(f"{'='*80}")
    print(f"Collection: {collection_name}")

    engine = get_engine()

    with engine.connect() as conn:
        # Find documents without embeddings that have distilled_text
        result = conn.execute(text("""
            SELECT
                d.doc_id,
                d.title,
                d.date,
                d.initiating_country,
                d.recipient_country,
                LENGTH(d.distilled_text) as text_length
            FROM documents d
            WHERE d.doc_id NOT IN (
                SELECT DISTINCT cmetadata->>'doc_id'
                FROM langchain_pg_embedding
                WHERE cmetadata->>'doc_id' IS NOT NULL
                AND collection_id = (
                    SELECT uuid FROM langchain_pg_collection WHERE name = :collection_name
                )
            )
            AND d.distilled_text IS NOT NULL
            AND d.distilled_text != ''
            ORDER BY d.date DESC
        """), {"collection_name": collection_name})

        missing_docs = result.fetchall()

    print(f"\nFound {len(missing_docs)} documents without embeddings")

    if missing_docs:
        print(f"\nSample of missing documents (first 10):")
        print(f"{'Doc ID':<30} {'Date':<12} {'Title':<50} {'Text Len':<10}")
        print("-" * 102)

        for doc in missing_docs[:10]:
            doc_id = doc[0][:28] + "..." if len(doc[0]) > 30 else doc[0]
            title = doc[1][:48] + "..." if doc[1] and len(doc[1]) > 50 else (doc[1] or "N/A")
            date = str(doc[2]) if doc[2] else "N/A"
            text_len = str(doc[5]) if doc[5] else "0"
            print(f"{doc_id:<30} {date:<12} {title:<50} {text_len:<10}")

        if len(missing_docs) > 10:
            print(f"... and {len(missing_docs) - 10} more")

    # Return just the doc_ids
    return [row[0] for row in missing_docs]


def get_embedding_statistics(collection_name='chunk_embeddings'):
    """
    Get statistics about embeddings in the database.

    Args:
        collection_name: The LangChain collection to check
    """
    print(f"\n{'='*80}")
    print("Embedding Statistics")
    print(f"{'='*80}")

    engine = get_engine()

    with engine.connect() as conn:
        # Total documents
        total_docs = conn.execute(text("""
            SELECT COUNT(*)
            FROM documents
            WHERE distilled_text IS NOT NULL
            AND distilled_text != ''
        """)).scalar()

        # Total embedded documents
        embedded_docs = conn.execute(text("""
            SELECT COUNT(DISTINCT cmetadata->>'doc_id')
            FROM langchain_pg_embedding
            WHERE cmetadata->>'doc_id' IS NOT NULL
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

    missing_docs = total_docs - embedded_docs
    completion_pct = (embedded_docs / total_docs * 100) if total_docs > 0 else 0

    print(f"Collection: {collection_name}")
    print(f"Total documents with text: {total_docs:,}")
    print(f"Documents with embeddings: {embedded_docs:,}")
    print(f"Documents missing embeddings: {missing_docs:,}")
    print(f"Total embedding records: {total_embeddings:,}")
    print(f"Completion: {completion_pct:.1f}%")
    print(f"{'='*80}\n")


def main():
    parser = argparse.ArgumentParser(
        description='Find and embed documents missing embeddings',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Find and embed all missing documents
  python services/pipeline/embeddings/embed_missing_documents.py

  # Show status only
  python services/pipeline/embeddings/embed_missing_documents.py --status

  # Dry run (no actual embedding)
  python services/pipeline/embeddings/embed_missing_documents.py --dry-run

  # Specify batch size
  python services/pipeline/embeddings/embed_missing_documents.py --batch-size 100
        """
    )

    parser.add_argument(
        '--collection',
        default='chunk_embeddings',
        help='LangChain collection name to check (default: chunk_embeddings)'
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=50,
        help='Number of documents to process per batch (default: 50)'
    )
    parser.add_argument(
        '--status',
        action='store_true',
        help='Show embedding statistics and exit'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Find missing documents but don\'t embed them'
    )
    parser.add_argument(
        '--limit',
        type=int,
        help='Limit number of documents to embed (for testing)'
    )

    args = parser.parse_args()

    # Show statistics
    get_embedding_statistics(args.collection)

    if args.status:
        sys.exit(0)

    # Find missing embeddings
    missing_doc_ids = find_missing_embeddings(args.collection)

    if not missing_doc_ids:
        print("\n✅ All documents have embeddings!")
        sys.exit(0)

    # Apply limit if specified
    if args.limit:
        print(f"\n⚠️  Limiting to {args.limit} documents")
        missing_doc_ids = missing_doc_ids[:args.limit]

    # Dry run
    if args.dry_run:
        print(f"\n[DRY RUN] Would embed {len(missing_doc_ids)} documents")
        sys.exit(0)

    # Confirm before proceeding
    print(f"\n{'='*80}")
    print(f"Ready to embed {len(missing_doc_ids)} documents")
    print(f"Batch size: {args.batch_size}")
    print(f"Collection: {args.collection}")
    print(f"{'='*80}")

    response = input("\nProceed with embedding? [y/N]: ").strip().lower()
    if response != 'y':
        print("Cancelled.")
        sys.exit(0)

    # Embed documents
    print(f"\n🚀 Starting direct embedding process...")
    start_time = datetime.now()

    try:
        embed_documents_direct(missing_doc_ids, batch_size=args.batch_size)

        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        print(f"\n{'='*80}")
        print("Embedding Complete!")
        print(f"{'='*80}")
        print(f"Documents embedded: {len(missing_doc_ids)}")
        print(f"Duration: {duration:.2f} seconds")
        print(f"Average: {duration/len(missing_doc_ids):.2f} seconds per document")
        print(f"{'='*80}\n")

        # Show updated statistics
        get_embedding_statistics(args.collection)

    except Exception as e:
        print(f"\n✗ Error during embedding: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
