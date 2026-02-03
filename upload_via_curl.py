#!/usr/bin/env python3
"""Upload batch file using curl (more reliable than Python httpx for large files)."""
import os
import subprocess
from dotenv import load_dotenv
from pathlib import Path

# Load .env
env_path = Path(__file__).parent / '.env'
load_dotenv(env_path)

api_key = os.getenv('OPENAI_PROJ_API')

# Get batch file from command line or use default
import sys
if len(sys.argv) > 1:
    batch_file = sys.argv[1]
else:
    batch_file = "services/pipeline/batch/batches/daily_entity_extract_Iran_2024-08-01_2026-01-01_input_batch1.jsonl"

if not os.path.exists(batch_file):
    print(f"Error: File not found: {batch_file}")
    exit(1)

file_size_mb = os.path.getsize(batch_file) / 1024 / 1024
print(f"Uploading: {batch_file}")
print(f"File size: {file_size_mb:.2f} MB")
print()

# Upload using curl (more reliable for large files)
curl_cmd = [
    "curl",
    "--http1.1",  # Force HTTP/1.1 to avoid TLS multiplexing issues
    "https://api.openai.com/v1/files",
    "-H", f"Authorization: Bearer {api_key}",
    "-F", f"file=@{batch_file}",
    "-F", "purpose=batch",
    "--max-time", "600",  # 10 minute timeout
    "--connect-timeout", "60",  # 60s connect timeout
    "--tlsv1.2",  # Force TLS 1.2
]

print("Uploading via curl...")
print("(This may take 30-60 seconds for 38MB)")
print()

try:
    result = subprocess.run(curl_cmd, capture_output=True, text=True, check=True)
    print("✓ UPLOAD SUCCESSFUL!")
    print()
    print("Response:")
    print(result.stdout)
except subprocess.CalledProcessError as e:
    print("✗ UPLOAD FAILED")
    print()
    print("Error:")
    print(e.stderr)
    exit(1)
