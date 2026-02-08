#!/usr/bin/env python3
"""Test direct upload to OpenAI (bypass proxy)."""
import os
from dotenv import load_dotenv
from pathlib import Path
from openai import OpenAI
import httpx

# Load .env
env_path = Path(__file__).parent / '.env'
load_dotenv(env_path)

api_key = os.getenv('OPENAI_PROJ_API')

# Get the batch file path
from shared.database.database import get_session
from shared.models.models import BatchJob

with get_session() as session:
    job = session.query(BatchJob).filter(
        BatchJob.id == '87b939ac-abac-437d-b6d5-5586a1bc5df1'
    ).first()

    if not job:
        print("Batch job not found")
        exit(1)

    input_file = job.input_file_path
    print(f"Batch Job ID: {job.id}")
    print(f"Input file: {input_file}")

# Check file size
file_size_mb = os.path.getsize(input_file) / (1024 * 1024)
print(f"File size: {file_size_mb:.2f} MB")
print()

# Test direct upload to OpenAI (no proxy)
print("Testing DIRECT upload to OpenAI (no proxy)...")
print("Using extended timeout (10 minutes)...")
print()

try:
    client = OpenAI(
        api_key=api_key,
        timeout=httpx.Timeout(600.0, connect=60.0),  # 10min total, 60s connect
        max_retries=2
    )

    print("Starting upload (this may take 30-60 seconds for 29MB)...")
    with open(input_file, 'rb') as f:
        batch_file = client.files.create(
            file=f,
            purpose="batch"
        )

    print("\n✓ UPLOAD SUCCESSFUL!")
    print(f"File ID: {batch_file.id}")
    print(f"Filename: {batch_file.filename}")
    print(f"Size: {batch_file.bytes / 1024 / 1024:.2f} MB")
    print(f"Status: {batch_file.status}")
    print()
    print("The proxy is not needed - you can upload directly!")
    print("However, the issue might be with network/firewall on the host.")

except Exception as e:
    print("\n✗ UPLOAD FAILED")
    print(f"Error: {e}")
    print()
    import traceback
    traceback.print_exc()
    print()
    print("This confirms the issue is not with the proxy,")
    print("but with the network connection to OpenAI from this host.")
