#!/usr/bin/env python3
"""Test OpenAI API connectivity and permissions."""
import os
from dotenv import load_dotenv
from pathlib import Path

# Load .env
env_path = Path(__file__).parent / '.env'
load_dotenv(env_path)

api_key = os.getenv('OPENAI_PROJ_API')
print(f"API Key loaded: {api_key[:20]}..." if api_key else "ERROR: No API key")
print()

# Test 1: Basic API connection
print("Test 1: Basic OpenAI API connection...")
try:
    from openai import OpenAI
    import httpx

    client = OpenAI(
        api_key=api_key,
        timeout=httpx.Timeout(60.0, connect=10.0)
    )

    # Try to list models (lightweight API call)
    models = client.models.list()
    print(f"  [OK] Connected! Found {len(models.data)} models")
except Exception as e:
    print(f"  [ERROR] {e}")
    exit(1)

# Test 2: Check batch API access (list files)
print("\nTest 2: Batch API access (list files)...")
try:
    files = client.files.list(purpose="batch")
    print(f"  [OK] Batch API accessible. Found {len(files.data)} batch files")
    for f in files.data[:3]:
        print(f"    - {f.filename} ({f.bytes / 1024:.1f} KB)")
except Exception as e:
    print(f"  [ERROR] {e}")
    print("  Note: If this fails, your API key may not have batch API access")
    exit(1)

# Test 3: Upload a small test file
print("\nTest 3: Upload small test file...")
try:
    import tempfile
    import json

    # Create tiny test JSONL file (1 request)
    test_data = {
        "custom_id": "test-123",
        "method": "POST",
        "url": "/v1/chat/completions",
        "body": {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": "You are a test assistant."},
                {"role": "user", "content": "Say 'test successful'"}
            ]
        }
    }

    with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as tmp:
        tmp.write(json.dumps(test_data) + '\n')
        tmp_path = tmp.name

    try:
        with open(tmp_path, 'rb') as f:
            batch_file = client.files.create(file=f, purpose="batch")

        print(f"  [OK] Upload successful!")
        print(f"    File ID: {batch_file.id}")
        print(f"    Size: {batch_file.bytes} bytes")

        # Clean up test file
        print(f"\nTest 4: Delete test file...")
        client.files.delete(batch_file.id)
        print(f"  [OK] Cleanup successful")

    finally:
        os.unlink(tmp_path)

except Exception as e:
    print(f"  [ERROR] {e}")
    import traceback
    traceback.print_exc()
    exit(1)

print("\n" + "="*60)
print("All tests passed! OpenAI API is working correctly.")
print("The issue is likely with large file uploads (network/timeout).")
print("="*60)
