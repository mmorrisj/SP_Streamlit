# Deployment Guide: LLM Proxy Configuration

This guide explains how to configure the LLM functionality to work across development and testing systems.

## Architecture Overview

The application uses a **FastAPI proxy pattern** for LLM calls:

```
┌─────────────────┐           ┌──────────────────┐           ┌──────────────┐
│  Development    │           │  FastAPI Proxy   │           │   OpenAI     │
│  System         │  ─────>   │  (with API keys) │  ─────>   │   API        │
│  (news_event_   │  HTTPS    │                  │  HTTPS    │              │
│   tracker.py)   │           │  backend/api.py  │           │              │
└─────────────────┘           └──────────────────┘           └──────────────┘
```

**Benefits**:
- Centralized API key management
- Only FastAPI server needs OpenAI credentials
- Development/testing systems don't need direct OpenAI access
- Works in containerized environments

## Configuration

### 1. FastAPI Server (System with OpenAI Access)

This is the system that has OpenAI API credentials and will proxy LLM requests.

**Environment Variables** (`.env`):
```bash
# OpenAI API credentials (required on proxy server only)
OPENAI_PROJ_API='sk-proj-...'
OPENAI_ORG='org-...'
OPENAI_PROJ_ID='proj_...'

# FastAPI configuration
API_HOST=0.0.0.0
API_PORT=5001
```

**Start the FastAPI server**:
```bash
# From project root
uvicorn backend.api:app --host 0.0.0.0 --port 5001 --reload
```

**Test the endpoint**:
```bash
curl http://localhost:5001/health

# Test LLM endpoint
curl -X POST http://localhost:5001/material_query \
  -H "Content-Type: application/json" \
  -d '{
    "sys_prompt": "You are a helpful assistant.",
    "prompt": "Say hello in JSON format: {\"greeting\": \"...\"}",
    "model": "gpt-4o-mini"
  }'
```

### 2. Development/Testing System (No OpenAI Access Needed)

This is the system where you run the processing scripts (e.g., `news_event_tracker.py`).

**Environment Variables** (`.env`):
```bash
# Point to the FastAPI proxy server
FASTAPI_URL=http://PROXY_HOST:5001/material_query

# Example for localhost
FASTAPI_URL=http://localhost:5001/material_query

# Example for remote server
FASTAPI_URL=http://192.168.1.100:5001/material_query

# Example for Docker
FASTAPI_URL=http://host.docker.internal:5001/material_query

# Database configuration (as normal)
POSTGRES_DB=softpower-db
POSTGRES_USER=matthew50
POSTGRES_PASSWORD=softpower
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
```

**No OpenAI credentials needed** on this system!

### 3. Docker Deployment

For containerized deployments, update `docker-compose.yml` to include FastAPI service:

```yaml
services:
  fastapi-proxy:
    build:
      context: .
      dockerfile: Dockerfile.api
    ports:
      - "5001:5001"
    environment:
      - OPENAI_PROJ_API=${OPENAI_PROJ_API}
      - OPENAI_ORG=${OPENAI_ORG}
      - OPENAI_PROJ_ID=${OPENAI_PROJ_ID}
    networks:
      - softpower_net

  processing:
    build:
      context: .
      dockerfile: Dockerfile
    environment:
      - FASTAPI_URL=http://fastapi-proxy:5001/material_query
      - POSTGRES_HOST=db
      - POSTGRES_PORT=5432
    depends_on:
      - fastapi-proxy
      - db
    networks:
      - softpower_net
```

## Usage in Code

The `gai()` function in `backend/scripts/utils.py` automatically detects and uses the proxy:

### Default Behavior (Proxy Required)
```python
from backend.scripts.utils import gai

# Automatically uses FASTAPI_URL from environment
# Raises ValueError if FASTAPI_URL not set
response = gai(
    sys_prompt="You are a news analyst.",
    user_prompt="Analyze these headlines...",
    model="gpt-4o-mini"
)
```

### Explicit Proxy Usage
```python
# Force proxy mode (useful for debugging)
response = gai(
    sys_prompt="...",
    user_prompt="...",
    use_proxy=True
)
```

### Local Development Bypass (Not Recommended)
```python
# Only for local development with OPENAI_PROJ_API set
# NOT for production use
response = gai(
    sys_prompt="...",
    user_prompt="...",
    use_proxy=False
)
```

## Troubleshooting

### Error: "FASTAPI_URL environment variable not set"
**Solution**: Add `FASTAPI_URL` to your `.env` file pointing to the FastAPI server.

### Error: "FastAPI proxy call failed: Connection refused"
**Causes**:
1. FastAPI server not running → Start it: `uvicorn backend.api:app --host 0.0.0.0 --port 5001`
2. Wrong host/port in `FASTAPI_URL` → Verify the URL is correct
3. Firewall blocking connection → Check network/firewall settings

### Error: "FastAPI proxy call failed: 500 Internal Server Error"
**Causes**:
1. OpenAI API key not configured on proxy server → Check `OPENAI_PROJ_API` env var
2. OpenAI API rate limit → Wait and retry
3. Invalid model name → Check model parameter (default: gpt-4o-mini)

## Verifying Configuration

### On FastAPI Server
```bash
# Check health endpoint
curl http://localhost:5001/health

# Test LLM endpoint
curl -X POST http://localhost:5001/material_query \
  -H "Content-Type: application/json" \
  -d '{
    "sys_prompt": "Respond in JSON",
    "prompt": "Return {\"status\": \"ok\"}",
    "model": "gpt-4o-mini"
  }'
```

### On Development/Testing System
```python
# Test script: test_llm_proxy.py
import os
from backend.scripts.utils import gai

# Check environment
print(f"FASTAPI_URL: {os.getenv('FASTAPI_URL')}")

try:
    response = gai(
        sys_prompt="You are a test assistant.",
        user_prompt="Return this JSON: {\"test\": \"success\"}",
        model="gpt-4o-mini"
    )
    print(f"✅ LLM proxy working: {response}")
except Exception as e:
    print(f"❌ LLM proxy failed: {e}")
```

## Security Notes

1. **Never commit API keys** to version control
2. **Use environment variables** for all sensitive credentials
3. **Restrict FastAPI server access** to trusted networks only
4. **Consider using HTTPS** for production deployments
5. **Rotate API keys regularly**

## Migration from Direct OpenAI

If you previously called OpenAI directly, no code changes needed! Just:

1. Set `FASTAPI_URL` environment variable
2. Start the FastAPI server on the system with OpenAI credentials
3. Your existing `gai()` calls will automatically use the proxy

The function signature remains the same:
```python
# Old code (still works!)
response = gai(sys_prompt, user_prompt, model="gpt-4o-mini")

# New behavior: automatically routes through proxy
```

## Testing on Different Systems

### Development System (your local machine)
```bash
# .env
FASTAPI_URL=http://localhost:5001/material_query
```

### Testing System (remote server)
```bash
# .env
FASTAPI_URL=http://192.168.1.100:5001/material_query
```

### Production System (Docker)
```bash
# .env
FASTAPI_URL=http://fastapi-proxy:5001/material_query
```

The code automatically adapts to the configured endpoint!
