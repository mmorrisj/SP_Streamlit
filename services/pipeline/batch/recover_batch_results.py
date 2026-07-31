#!/usr/bin/env python3
"""
Recover batch results from OpenAI API when local tracking records are lost.

Lists recent batches from OpenAI, downloads completed results, and feeds
them into the standard result processing pipeline.

Usage:
    python recover_batch_results.py --job-type cluster_deconflict
    python recover_batch_results.py --job-type cluster_deconflict --dry-run
    python recover_batch_results.py --job-type cluster_deconflict --limit 200
"""
import argparse
import json
import os
import sys
from pathlib import Path
from datetime import datetime

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from openai import OpenAI


def main():
    parser = argparse.ArgumentParser(description="Recover batch results from OpenAI API")
    parser.add_argument('--job-type', required=True, help='Job type to filter by (matched against metadata)')
    parser.add_argument('--output-dir', default='services/pipeline/batch/batches',
                       help='Directory to save downloaded results')
    parser.add_argument('--limit', type=int, default=100, help='Max batches to list from OpenAI (max 100)')
    parser.add_argument('--days', type=int, default=1, help='Look back N days for completed batches (default: 1 = today only)')
    parser.add_argument('--dry-run', action='store_true', help='List batches without downloading')
    args = parser.parse_args()

    # Load .env if available
    env_path = project_root / '.env'
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, _, value = line.partition('=')
                    key = key.strip()
                    value = value.strip().strip("'\"")
                    if key and value:
                        os.environ.setdefault(key, value)

    # Initialize OpenAI client
    api_key = os.getenv('OPENAI_PROJ_API') or os.getenv('OPENAI_API_KEY')
    if not api_key:
        print("Error: Set OPENAI_PROJ_API or OPENAI_API_KEY environment variable")
        sys.exit(1)

    client = OpenAI(api_key=api_key)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    from datetime import date, timedelta
    cutoff_date = (date.today() - timedelta(days=args.days - 1)).isoformat()
    print(f"Listing batches from OpenAI (since {cutoff_date})...")
    completed = []
    after = None
    while True:
        kwargs = {'limit': 100}
        if after:
            kwargs['after'] = after
        batches = client.batches.list(**kwargs)
        if not batches.data:
            break
        found_old = False
        for batch in batches.data:
            created = datetime.fromtimestamp(batch.created_at)
            if created.date().isoformat() < cutoff_date:
                found_old = True
                break
            if batch.status == 'completed' and batch.output_file_id:
                completed.append(batch)
        if found_old:
            break
        after = batches.data[-1].id

    print(f"Found {len(completed)} completed batches with output files")

    if not completed:
        print("Nothing to recover.")
        return

    # Filter to likely matches by checking the first result's custom_id
    matched = []
    for batch in completed:
        # Check if this batch belongs to our job type by peeking at metadata
        # or by the endpoint (all use /v1/chat/completions so we check output)
        matched.append(batch)

    print(f"\nWill download {len(matched)} batches")
    if args.dry_run:
        for b in matched:
            created = datetime.fromtimestamp(b.created_at).strftime('%Y-%m-%d %H:%M')
            counts = b.request_counts
            print(f"  {b.id} | {created} | {counts.completed}/{counts.total} requests | {b.status}")
        return

    downloaded = 0
    skipped = 0
    for i, batch in enumerate(matched, 1):
        output_path = output_dir / f"recovered_{batch.id}_output.jsonl"

        if output_path.exists():
            skipped += 1
            continue

        created = datetime.fromtimestamp(batch.created_at).strftime('%Y-%m-%d %H:%M')
        counts = batch.request_counts
        print(f"  [{i}/{len(matched)}] {batch.id} | {created} | {counts.completed} requests")

        try:
            content = client.files.content(batch.output_file_id)
            output_path.write_text(content.text, encoding='utf-8')
            downloaded += 1
            print(f"    -> {output_path}")
        except Exception as e:
            print(f"    ERROR: {e}")

    print(f"\nDownloaded: {downloaded}, Skipped (already exists): {skipped}")

    # Now check which files contain our job type
    print(f"\nFiltering for job_type='{args.job_type}'...")
    job_type_files = []
    for f in output_dir.glob("recovered_*_output.jsonl"):
        with open(f, 'r', encoding='utf-8') as fh:
            first_line = fh.readline().strip()
            if first_line:
                try:
                    data = json.loads(first_line)
                    custom_id = data.get('custom_id', '')
                    if custom_id.startswith(args.job_type):
                        job_type_files.append(f)
                except json.JSONDecodeError:
                    pass

    print(f"Found {len(job_type_files)} files matching job_type='{args.job_type}'")

    if not job_type_files:
        print("No matching files found. The batches may use a different job_type prefix.")
        return

    # Verify record IDs exist in current database
    from shared.database.database import get_session
    from shared.models.models import EventCluster, CanonicalEvent
    from services.pipeline.batch.utils.custom_id import parse_custom_id

    # Pick the right model to validate against based on job type
    CLUSTER_TYPES = {'cluster_deconflict'}
    CANONICAL_TYPES = {'canonical_deconflict', 'score_materiality', 'entity_extract',
                       'generate_daily_summary', 'generate_weekly_summary',
                       'generate_monthly_summary', 'generate_yearly_summary'}
    SKIP_VALIDATION_TYPES = {'event_rename', 'daily_entity_extract',
                              'generate_entity_descriptions', 'generate_bilateral_summaries',
                              'classify_entity_relationships', 'score_summary_materiality'}

    if args.job_type in CLUSTER_TYPES:
        validate_model = EventCluster
        model_label = 'cluster'
    elif args.job_type in CANONICAL_TYPES:
        validate_model = CanonicalEvent
        model_label = 'canonical event'
    else:
        validate_model = None
        model_label = 'record'

    valid_files = []
    with get_session() as session:
        for f in job_type_files:
            if validate_model is None:
                # Skip validation for job types that don't use cluster/canonical IDs
                valid_files.append(f)
                continue
            with open(f, 'r', encoding='utf-8') as fh:
                first_line = fh.readline().strip()
                if first_line:
                    data = json.loads(first_line)
                    custom_id = data.get('custom_id', '')
                    parsed = parse_custom_id(custom_id)
                    record = session.get(validate_model, parsed['record_id'])
                    if record:
                        valid_files.append(f)
                    else:
                        print(f"  SKIP {f.name}: {model_label} IDs don't match current DB (old run)")

    print(f"\n{len(valid_files)} files have valid {model_label} IDs (current DB)")

    if not valid_files:
        print(f"No recoverable files — all reference old {model_label} IDs.")
        return

    # Process each valid file using the appropriate handler
    from services.pipeline.batch.batch_process_results import (
        process_cluster_result, process_canonical_result, process_event_rename_result,
        process_materiality_score_result,
        process_summary_materiality_result,
        process_daily_summary_result, process_weekly_summary_result,
        process_monthly_summary_result, process_yearly_summary_result
    )
    from services.pipeline.events.llm_deconflict_clusters import LLMClusterDeconfliction

    total_processed = 0
    total_errors = 0

    with get_session() as session:
        deconfliction_processor = None
        if args.job_type == 'cluster_deconflict':
            deconfliction_processor = LLMClusterDeconfliction(dry_run=False, verbose=False)

        for fi, filepath in enumerate(valid_files, 1):
            print(f"\n[{fi}/{len(valid_files)}] Processing {filepath.name}...")

            with open(filepath, 'r', encoding='utf-8') as fh:
                lines = fh.readlines()

            file_processed = 0
            file_errors = 0

            for line in lines:
                line = line.strip()
                if not line:
                    continue

                try:
                    result = json.loads(line)
                    custom_id = result.get('custom_id', '')
                    response = result.get('response', {})

                    if response.get('status_code') != 200:
                        file_errors += 1
                        continue

                    content = response['body']['choices'][0]['message']['content']
                    llm_response = json.loads(content)

                    parsed = parse_custom_id(custom_id)
                    record_id = parsed['record_id']

                    # Normalize field names
                    if 'reasoning' in llm_response and 'explanation' not in llm_response:
                        llm_response['explanation'] = llm_response['reasoning']

                    savepoint = session.begin_nested()
                    try:
                        if args.job_type == 'cluster_deconflict':
                            stats = process_cluster_result(
                                session, record_id, llm_response,
                                deconfliction_processor, verbose=False
                            )
                        elif args.job_type == 'canonical_deconflict':
                            stats = process_canonical_result(
                                session, record_id, llm_response, verbose=False
                            )
                        elif args.job_type == 'score_materiality':
                            stats = process_materiality_score_result(
                                session, record_id, llm_response, verbose=False
                            )
                        elif args.job_type == 'score_summary_materiality':
                            stats = process_summary_materiality_result(
                                session, record_id, llm_response, verbose=False
                            )
                        elif args.job_type == 'event_rename':
                            stats = process_event_rename_result(
                                session, record_id, llm_response, verbose=False
                            )
                        elif args.job_type == 'generate_daily_summary':
                            suffix = parsed.get('suffix')
                            if not suffix:
                                file_errors += 1
                                continue
                            stats = process_daily_summary_result(
                                session, record_id, llm_response,
                                date_str=suffix, verbose=False
                            )
                        elif args.job_type == 'generate_weekly_summary':
                            suffix = parsed.get('suffix')
                            if not suffix:
                                file_errors += 1
                                continue
                            stats = process_weekly_summary_result(
                                session, record_id, llm_response,
                                week_str=suffix, verbose=False
                            )
                        elif args.job_type == 'generate_monthly_summary':
                            suffix = parsed.get('suffix')
                            if not suffix:
                                file_errors += 1
                                continue
                            stats = process_monthly_summary_result(
                                session, record_id, llm_response,
                                month_str=suffix, verbose=False
                            )
                        elif args.job_type == 'generate_yearly_summary':
                            suffix = parsed.get('suffix')
                            if not suffix:
                                file_errors += 1
                                continue
                            stats = process_yearly_summary_result(
                                session, record_id, llm_response,
                                year_str=suffix, verbose=False
                            )
                        else:
                            print(f"    Unsupported job type: {args.job_type}")
                            savepoint.rollback()
                            file_errors += 1
                            continue

                        savepoint.commit()
                        file_processed += 1
                    except Exception as e:
                        savepoint.rollback()
                        file_errors += 1
                        print(f"    Error processing {custom_id}: {e}")

                except (json.JSONDecodeError, KeyError, ValueError) as e:
                    file_errors += 1

                if file_processed > 0 and file_processed % 100 == 0:
                    session.commit()
                    print(f"    [CHECKPOINT] {file_processed} processed")

            session.commit()
            total_processed += file_processed
            total_errors += file_errors
            print(f"  Done: {file_processed} processed, {file_errors} errors")

    print(f"\n{'='*60}")
    print(f"RECOVERY COMPLETE")
    print(f"Total processed: {total_processed}")
    print(f"Total errors: {total_errors}")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()
