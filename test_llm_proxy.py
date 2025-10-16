#!/usr/bin/env python3
"""
Test script for LLM proxy configuration.

Usage:
    python test_llm_proxy.py

This script verifies:
1. Environment variables are configured
2. FastAPI server is reachable
3. LLM proxy endpoint works correctly
"""

import os
import sys
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


def check_environment():
    """Check required environment variables."""
    print("\n" + "="*60)
    print("Step 1: Checking Environment Variables")
    print("="*60)

    fastapi_url = os.getenv('FASTAPI_URL', '').strip()
    api_url = os.getenv('API_URL', '').strip()

    if fastapi_url:
        print(f"✅ FASTAPI_URL is set: {fastapi_url}")
        return fastapi_url
    elif api_url:
        constructed_url = f"{api_url.rstrip('/')}/material_query"
        print(f"⚠️  FASTAPI_URL not set, but API_URL found")
        print(f"   Constructed URL: {constructed_url}")
        return constructed_url
    else:
        print("❌ FASTAPI_URL not set in environment")
        print("   Please add to .env file:")
        print("   FASTAPI_URL=http://HOST:PORT/material_query")
        return None


def check_fastapi_health(base_url):
    """Check if FastAPI server is running."""
    print("\n" + "="*60)
    print("Step 2: Checking FastAPI Server Health")
    print("="*60)

    # Extract base URL (remove /material_query if present)
    if '/material_query' in base_url:
        health_url = base_url.replace('/material_query', '/health')
    else:
        health_url = f"{base_url.rstrip('/')}/health"

    try:
        print(f"Testing: {health_url}")
        response = requests.get(health_url, timeout=5)
        response.raise_for_status()

        data = response.json()
        print(f"✅ FastAPI server is healthy")
        print(f"   Status: {data.get('status', 'unknown')}")
        print(f"   Service: {data.get('service', 'unknown')}")
        return True

    except requests.exceptions.ConnectionError:
        print(f"❌ Cannot connect to FastAPI server at {health_url}")
        print(f"   Make sure the server is running:")
        print(f"   uvicorn backend.api:app --host 0.0.0.0 --port 5001")
        return False

    except requests.exceptions.Timeout:
        print(f"❌ Connection timeout to {health_url}")
        return False

    except Exception as e:
        print(f"❌ Error checking health endpoint: {e}")
        return False


def test_llm_proxy(fastapi_url):
    """Test the LLM proxy endpoint."""
    print("\n" + "="*60)
    print("Step 3: Testing LLM Proxy Endpoint")
    print("="*60)

    payload = {
        "sys_prompt": "You are a helpful assistant. Respond only with valid JSON.",
        "prompt": "Return this exact JSON object: {\"status\": \"success\", \"message\": \"LLM proxy is working\"}",
        "model": "gpt-4o-mini"
    }

    try:
        print(f"Calling: {fastapi_url}")
        print(f"Model: {payload['model']}")

        response = requests.post(fastapi_url, json=payload, timeout=60)
        response.raise_for_status()

        data = response.json()
        print(f"✅ LLM proxy call successful!")
        print(f"   Response: {data}")

        return True

    except requests.exceptions.ConnectionError:
        print(f"❌ Cannot connect to {fastapi_url}")
        print(f"   Check that the URL is correct and server is running")
        return False

    except requests.exceptions.HTTPError as e:
        print(f"❌ HTTP error: {e}")
        if e.response.status_code == 500:
            print(f"   This usually means OpenAI credentials are not configured on the FastAPI server")
            print(f"   Check OPENAI_PROJ_API environment variable on the server")
        print(f"   Response: {e.response.text}")
        return False

    except Exception as e:
        print(f"❌ Error calling LLM proxy: {e}")
        return False


def test_via_gai_function():
    """Test using the gai() function from utils.py."""
    print("\n" + "="*60)
    print("Step 4: Testing via gai() Function")
    print("="*60)

    try:
        # Import after environment is loaded
        from backend.scripts.utils import gai

        print("Calling gai() function...")
        response = gai(
            sys_prompt="You are a test assistant. Respond with valid JSON only.",
            user_prompt='Return this JSON: {"test": "success", "function": "gai"}',
            model="gpt-4o-mini"
        )

        print(f"✅ gai() function works!")
        print(f"   Response: {response}")
        return True

    except ValueError as e:
        print(f"❌ Configuration error: {e}")
        return False

    except RuntimeError as e:
        print(f"❌ Runtime error: {e}")
        return False

    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("LLM PROXY CONFIGURATION TEST")
    print("="*60)

    # Step 1: Check environment
    fastapi_url = check_environment()
    if not fastapi_url:
        print("\n❌ Environment not configured. Exiting.")
        sys.exit(1)

    # Step 2: Check health
    if not check_fastapi_health(fastapi_url):
        print("\n❌ FastAPI server not accessible. Exiting.")
        print("\nTroubleshooting:")
        print("1. Start the FastAPI server: uvicorn backend.api:app --host 0.0.0.0 --port 5001")
        print("2. Check firewall settings")
        print("3. Verify the URL in FASTAPI_URL matches the server host/port")
        sys.exit(1)

    # Step 3: Test LLM endpoint
    if not test_llm_proxy(fastapi_url):
        print("\n❌ LLM proxy endpoint failed. Exiting.")
        print("\nTroubleshooting:")
        print("1. Verify OPENAI_PROJ_API is set on the FastAPI server")
        print("2. Check OpenAI API quota and rate limits")
        print("3. Verify the model name is correct (default: gpt-4o-mini)")
        sys.exit(1)

    # Step 4: Test via gai() function
    if not test_via_gai_function():
        print("\n❌ gai() function test failed.")
        sys.exit(1)

    # All tests passed!
    print("\n" + "="*60)
    print("✅ ALL TESTS PASSED!")
    print("="*60)
    print("\nYour LLM proxy is configured correctly and ready to use.")
    print("The news_event_tracker.py script will now use the FastAPI proxy for LLM calls.")
    print("\nNext steps:")
    print("1. Deploy this configuration to your testing system")
    print("2. Update FASTAPI_URL to point to the server with OpenAI credentials")
    print("3. Run your processing scripts normally")


if __name__ == "__main__":
    main()
