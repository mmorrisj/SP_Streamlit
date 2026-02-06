#!/usr/bin/env python3
"""Clean up failed batch jobs."""
from shared.database.database import get_session
from shared.models.models import BatchJob

with get_session() as session:
    # Find failed batch jobs
    failed_jobs = session.query(BatchJob).filter(
        BatchJob.status == 'failed',
        BatchJob.job_type == 'daily_entity_extract'
    ).all()

    print(f"Found {len(failed_jobs)} failed daily_entity_extract batch jobs:")
    for job in failed_jobs:
        print(f"  - ID: {job.id}")
        print(f"    Country: {job.initiating_country}")
        print(f"    Size: {job.batch_size} requests")
        print(f"    Created: {job.created_at}")

    if failed_jobs:
        confirm = input(f"\nDelete these {len(failed_jobs)} failed jobs? (yes/no): ")
        if confirm.lower() == 'yes':
            for job in failed_jobs:
                session.delete(job)
            session.commit()
            print(f"\nDeleted {len(failed_jobs)} failed batch jobs.")
        else:
            print("Cancelled.")
    else:
        print("No failed jobs to clean up.")
