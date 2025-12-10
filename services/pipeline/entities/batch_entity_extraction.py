"""
Batch entity extraction with automatic incremental storage.

Processes documents in batches, saves results, and stores to database immediately
to prevent data loss on crashes. Automatically skips already-processed documents.

Usage:
    python services/pipeline/entities/batch_entity_extraction.py --country China --batch-size 500
    python services/pipeline/entities/batch_entity_extraction.py --country China --batch-size 1000 --start-batch 5
"""

import argparse
import logging
import subprocess
import sys
import os
from pathlib import Path
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def run_extraction_batch(
    country: str,
    batch_size: int,
    model: str = "gpt-4o-mini",
    parallel_workers: int = 1
) -> tuple[bool, str]:
    """
    Run entity extraction for one batch of documents.

    Args:
        country: Country to process
        batch_size: Number of documents per batch
        model: LLM model to use
        parallel_workers: Number of parallel workers (default 1 = sequential)

    Returns:
        Tuple of (success, output_file_path)
    """
    cmd = [
        sys.executable,
        "services/pipeline/entities/entity_extraction.py",
        "--country", country,
        "--limit", str(batch_size),
        "--model", model,
        "--parallel-workers", str(parallel_workers)
    ]

    try:
        logger.info(f"Running extraction batch: {batch_size} documents")

        # Set up environment with PYTHONPATH
        env = os.environ.copy()
        if 'PYTHONPATH' not in env:
            env['PYTHONPATH'] = os.getcwd()

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=21600,  # 6 hour timeout per batch
            env=env
        )

        if result.returncode != 0:
            logger.error(f"Extraction failed: {result.stderr}")
            return False, None

        # Parse output to find the JSON file path
        output_lines = result.stdout.split('\n')
        output_file = None
        for line in output_lines:
            if "Saved extractions to" in line or "Output file:" in line:
                # Extract file path from line
                parts = line.split(':')
                if len(parts) >= 2:
                    output_file = parts[-1].strip()
                    break

        if not output_file:
            # Try to find the most recent entity extraction file
            data_dir = Path("data/entity_extractions")
            if data_dir.exists():
                files = sorted(data_dir.glob(f"entity_extractions_{country}_*.json"),
                             key=lambda p: p.stat().st_mtime, reverse=True)
                if files:
                    output_file = str(files[0])

        return True, output_file

    except subprocess.TimeoutExpired:
        logger.error(f"Extraction batch timed out after 6 hours")
        return False, None
    except Exception as e:
        logger.error(f"Extraction error: {e}")
        return False, None


def store_extraction_batch(json_file: str) -> bool:
    """
    Store extracted entities from JSON file to database.

    Returns:
        bool: Success status
    """
    if not json_file or not Path(json_file).exists():
        logger.error(f"JSON file not found: {json_file}")
        return False

    cmd = [
        sys.executable,
        "services/pipeline/entities/store_entities.py",
        json_file
    ]

    try:
        logger.info(f"Storing extraction batch: {json_file}")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600  # 10 minute timeout for storage
        )

        if result.returncode != 0:
            logger.error(f"Storage failed: {result.stderr}")
            return False

        logger.info("Batch stored successfully")
        return True

    except subprocess.TimeoutExpired:
        logger.error(f"Storage batch timed out")
        return False
    except Exception as e:
        logger.error(f"Storage error: {e}")
        return False


def get_processing_status(country: str) -> dict:
    """
    Get current processing status from database.

    Returns:
        dict: Status with total, processed, remaining counts
    """
    cmd = [
        sys.executable,
        "-c",
        f"""
from shared.database.database import get_session
from shared.models.models import Document
from sqlalchemy import text

with get_session() as session:
    # Total documents
    total = session.query(Document).filter(
        Document.initiating_country == '{country}',
        Document.salience_bool == 'true',
        Document.distilled_text.isnot(None),
        Document.distilled_text != ''
    ).count()

    # Already processed
    processed = session.execute(text(
        \"\"\"SELECT COUNT(DISTINCT de.doc_id)
           FROM document_entities de
           JOIN documents d ON de.doc_id = d.doc_id
           WHERE d.initiating_country = '{country}'
        \"\"\"
    )).scalar()

    print(f"{{total}},{{processed}},{{total-processed}}")
"""
    ]

    try:
        # Set up environment with PYTHONPATH
        env = os.environ.copy()
        if 'PYTHONPATH' not in env:
            env['PYTHONPATH'] = os.getcwd()

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=env)
        if result.returncode == 0:
            total, processed, remaining = map(int, result.stdout.strip().split(','))
            return {
                "total": total,
                "processed": processed,
                "remaining": remaining
            }
    except Exception as e:
        logger.error(f"Error getting status: {e}")

    # Return None to signal error rather than misleading zeros
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Batch entity extraction with automatic incremental storage"
    )
    parser.add_argument("--country", type=str, required=True, help="Country to process")
    parser.add_argument("--batch-size", type=int, default=500, help="Documents per batch")
    parser.add_argument("--max-batches", type=int, help="Maximum number of batches to process")
    parser.add_argument("--model", type=str, default="gpt-4o-mini", help="LLM model to use")
    parser.add_argument("--parallel-workers", type=int, default=10,
                        help="Number of parallel workers (default: 10)")

    args = parser.parse_args()

    logger.info("="*60)
    logger.info(f"BATCH ENTITY EXTRACTION: {args.country}")
    logger.info(f"Batch size: {args.batch_size}")
    logger.info(f"Model: {args.model}")
    logger.info(f"Parallel workers: {args.parallel_workers}")
    logger.info("="*60)

    # Get initial status
    status = get_processing_status(args.country)
    if status is None:
        logger.error("Failed to get processing status - cannot continue")
        return

    logger.info(f"Initial status:")
    logger.info(f"  Total documents: {status['total']}")
    logger.info(f"  Already processed: {status['processed']}")
    logger.info(f"  Remaining: {status['remaining']}")

    if status['remaining'] == 0:
        logger.info("All documents already processed!")
        return

    # Calculate number of batches needed
    total_batches = (status['remaining'] + args.batch_size - 1) // args.batch_size
    if args.max_batches:
        total_batches = min(total_batches, args.max_batches)

    logger.info(f"Will process {total_batches} batches of up to {args.batch_size} documents each")
    logger.info("")

    # Process batches
    batches_completed = 0
    batches_failed = 0

    for batch_num in range(1, total_batches + 1):
        logger.info("="*60)
        logger.info(f"BATCH {batch_num}/{total_batches}")
        logger.info("="*60)

        # Check current status
        current_status = get_processing_status(args.country)
        if current_status is None:
            logger.warning("Could not get status, continuing with batch...")
        elif current_status['remaining'] == 0:
            logger.info("All documents processed!")
            break
        else:
            logger.info(f"Remaining documents: {current_status['remaining']}")

        # Run extraction
        success, output_file = run_extraction_batch(
            args.country,
            args.batch_size,
            args.model,
            args.parallel_workers
        )

        if not success:
            logger.error(f"Batch {batch_num} extraction failed")
            batches_failed += 1
            continue

        if not output_file:
            logger.warning(f"Batch {batch_num} produced no output file")
            continue

        # Store to database
        if store_extraction_batch(output_file):
            batches_completed += 1
            logger.info(f"Batch {batch_num} completed successfully")
        else:
            logger.error(f"Batch {batch_num} storage failed")
            batches_failed += 1

        logger.info("")

    # Final status
    final_status = get_processing_status(args.country)
    logger.info("="*60)
    logger.info("FINAL SUMMARY")
    logger.info("="*60)
    logger.info(f"Batches completed: {batches_completed}")
    logger.info(f"Batches failed: {batches_failed}")
    if final_status:
        logger.info(f"Documents processed: {final_status['processed']}")
        logger.info(f"Documents remaining: {final_status['remaining']}")
    else:
        logger.warning("Could not retrieve final status")
    logger.info("="*60)


if __name__ == "__main__":
    main()
