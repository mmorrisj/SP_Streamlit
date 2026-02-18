# ============================================
# Air-Gapped Consolidated Application Container
# Single container running FastAPI + Streamlit
# via supervisord process manager
# ============================================
# Stripped-down image: no pipeline/ingestion/clustering
# Only serves the web UI, API, RAG chat, and dashboard
# ============================================

# ============================================
# Stage 1: Build React Frontend
# ============================================
FROM node:20-slim AS frontend-builder

WORKDIR /app/client

# Install dependencies
COPY client/package*.json ./
RUN npm ci

# Build production bundle
COPY client/ ./
RUN npm run build \
    && ls -la dist/ \
    && echo "React build complete"

# ============================================
# Stage 2: Python Runtime (FastAPI + Streamlit)
# ============================================
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies (no build-essential — no C packages to compile)
# - curl: health checks
# - postgresql-client: database utilities (pg_isready, psql)
# - supervisor: process manager for running both services
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        postgresql-client \
        supervisor \
    && rm -rf /var/lib/apt/lists/*

# Install lightweight Python dependencies only.
# Heavy ML packages (torch, sentence-transformers, langchain-huggingface)
# are shipped as wheels and installed on the target via:
#   ./airgap-deploy.sh setup
# This keeps the image ~1.5GB smaller for transfer.
COPY requirements-airgap.txt ./
RUN pip install --no-cache-dir -r requirements-airgap.txt --index-url https://pypi.org/simple

# HuggingFace model is mounted as a volume at runtime (not baked into image).
# This keeps the image ~90MB smaller for transfer.
# The model directory is exported separately by airgap-build.sh.
#
# HF_HOME is the root for the HuggingFace Hub cache.  The hub library stores
# models under $HF_HOME/hub/models--<org>--<name>/.  Do NOT also set
# SENTENCE_TRANSFORMERS_HOME — it bypasses the hub/ layer and causes a path
# mismatch (the model is stored with hub/ but looked up without it).
ENV HF_HOME=/app/.cache/huggingface

# Copy application code (no pipeline — not needed on air-gapped system)
COPY shared/ ./shared/
COPY server/ ./server/
COPY services/chat/ ./services/chat/
COPY services/dashboard/ ./services/dashboard/
COPY alembic/ ./alembic/
COPY alembic.ini .

# Copy built React app from Stage 1
COPY --from=frontend-builder /app/client/dist ./client/dist

# Copy supervisord configuration
COPY docker/supervisord.conf /etc/supervisor/conf.d/softpower.conf

# Verify key files are in place
RUN ls -la client/dist/ \
    && ls -la server/main.py \
    && ls -la services/dashboard/app.py \
    && echo "All application files verified"

# Environment
ENV PYTHONPATH=/app
ENV NODE_ENV=production
# Ensure HuggingFace uses the cached model, not network
ENV TRANSFORMERS_OFFLINE=1
ENV HF_HUB_OFFLINE=1

# Expose both service ports
EXPOSE 8000 8501

# Health check targets the FastAPI service
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

# Start both services via supervisord
CMD ["supervisord", "-c", "/etc/supervisor/conf.d/softpower.conf"]
