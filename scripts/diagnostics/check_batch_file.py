#!/usr/bin/env python3
"""Check batch JSONL file format."""
import json
import os
from shared.database.database import get_session
from shared.models.models import BatchJob

with get_session() as session:
    job = session.query(BatchJob).filter(
        BatchJob.job_type == 'daily_entity_extract'
    ).order_by(BatchJob.created_at.desc()).first()

    if not job:
        print("No daily_entity_extract jobs found")
        exit(1)

    print(f"Batch Job ID: {job.id}")
    print(f"Input file: {job.input_file_path}")
    print(f"Batch size: {job.batch_size}")
    print()

    # Check if file exists
    if not os.path.exists(job.input_file_path):
        print(f"ERROR: File not found at {job.input_file_path}")
        exit(1)

    # Check file size
    file_size_mb = os.path.getsize(job.input_file_path) / (1024 * 1024)
    print(f"File size: {file_size_mb:.2f} MB")

    # Validate JSONL format
    print("\nValidating JSONL format...")
    with open(job.input_file_path, 'r', encoding='utf-8') as f:
        for i, line in enumerate(f):
            if i >= 3:  # Check first 3 lines
                break
            try:
                data = json.loads(line)
                print(f"\nLine {i+1}: [OK] Valid JSON")
                print(f"  custom_id: {data.get('custom_id', 'MISSING')[:50]}...")
                print(f"  method: {data.get('method', 'MISSING')}")
                print(f"  url: {data.get('url', 'MISSING')}")

                # Check body structure
                body = data.get('body', {})
                if 'messages' not in body:
                    print("  ERROR: Missing 'messages' in body")
                else:
                    print(f"  messages: {len(body['messages'])} messages")

                if 'model' not in body:
                    print("  ERROR: Missing 'model' in body")
                else:
                    print(f"  model: {body['model']}")

            except json.JSONDecodeError as e:
                print(f"\nLine {i+1}: [ERROR] INVALID JSON")
                print(f"  Error: {e}")
                print(f"  Content: {line[:100]}...")

    print("\nDone.")
