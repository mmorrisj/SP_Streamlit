#!/usr/bin/env python3
"""List all batch jobs."""
from shared.database.database import get_session
from shared.models.models import BatchJob

with get_session() as session:
    jobs = session.query(BatchJob).filter(
        BatchJob.job_type == 'daily_entity_extract'
    ).order_by(BatchJob.created_at.desc()).all()

    print(f"Found {len(jobs)} daily_entity_extract batch jobs:\n")

    for i, job in enumerate(jobs, 1):
        file_size = 0
        try:
            import os
            if os.path.exists(job.input_file_path):
                file_size = os.path.getsize(job.input_file_path) / (1024 * 1024)
        except:
            pass

        print(f"{i}. Batch Job ID: {job.id}")
        print(f"   Status: {job.status}")
        print(f"   Country: {job.initiating_country}")
        print(f"   Batch size: {job.batch_size} requests")
        print(f"   File size: {file_size:.2f} MB")
        print(f"   Created: {job.created_at}")
        print(f"   Input file: {job.input_file_path}")
        print()
