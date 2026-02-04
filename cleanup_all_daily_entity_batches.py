#!/usr/bin/env python3
"""Clean up all daily_entity_extract batch jobs and files."""
import os
import glob
from shared.database.database import get_session
from shared.models.models import BatchJob

# Delete batch files
batch_files = glob.glob('services/pipeline/batch/batches/daily_entity_extract_*.jsonl')
print(f"Found {len(batch_files)} batch files to delete:")
for f in batch_files:
    size_mb = os.path.getsize(f) / 1024 / 1024
    print(f"  - {os.path.basename(f)} ({size_mb:.2f} MB)")

if batch_files:
    confirm = input(f"\nDelete these {len(batch_files)} files? (yes/no): ")
    if confirm.lower() == 'yes':
        for f in batch_files:
            os.remove(f)
            print(f"  Deleted: {os.path.basename(f)}")
    else:
        print("Cancelled file deletion.")
        exit(0)

# Delete batch_job records
with get_session() as session:
    jobs = session.query(BatchJob).filter(
        BatchJob.job_type == 'daily_entity_extract'
    ).all()

    print(f"\nFound {len(jobs)} batch job records:")
    for job in jobs:
        print(f"  - {job.id} ({job.status})")

    if jobs:
        confirm = input(f"\nDelete these {len(jobs)} batch job records? (yes/no): ")
        if confirm.lower() == 'yes':
            for job in jobs:
                session.delete(job)
            session.commit()
            print(f"Deleted {len(jobs)} batch job records.")
        else:
            print("Cancelled.")
    else:
        print("No batch jobs to delete.")

print("\nCleanup complete! Now run batch_prepare.py again with 10K chunks.")
