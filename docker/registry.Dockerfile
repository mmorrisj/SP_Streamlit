# ============================================
# Registry-Ready Consolidated Application Container
# Single container running FastAPI + Streamlit
# via supervisord process manager
#
# Designed for deployment via Docker Hub mirror:
#   - ML packages (torch, sentence-transformers) baked in
#   - HuggingFace model (all-MiniLM-L6-v2) baked in
#   - React frontend built and included
#   - No pipeline/ingestion code
#   - Pull-and-run: no manual setup steps required
#
# Image size: ~2GB
# ============================================

# ============================================
# Stage 1: Build React Frontend
# ============================================
FROM node:20-slim AS frontend-builder

WORKDIR /app/client

COPY client/package*.json ./
RUN npm ci

COPY client/ ./
RUN npm run build \
    && ls -la dist/ \
    && echo "React build complete"

# ============================================
# Stage 2: Python Runtime (FastAPI + Streamlit + ML)
# ============================================
FROM python:3.13-slim

WORKDIR /app

# System dependencies
# - curl: health checks
# - postgresql-client: pg_isready, psql utilities
# - supervisor: process manager for FastAPI + Streamlit
# - build-essential: required by some Python packages at install time
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        postgresql-client \
        supervisor \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install lightweight runtime dependencies
COPY requirements-airgap.txt ./
RUN pip install --no-cache-dir -r requirements-airgap.txt

# Install heavy ML dependencies
# PyTorch CPU-only from the official PyTorch index (avoids pulling CUDA variant)
# sentence-transformers and langchain-huggingface from PyPI
COPY requirements-airgap-heavy.txt ./
RUN pip install --no-cache-dir \
        torch>=2.6.0 \
        --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir \
        sentence-transformers>=3.3.1 \
        langchain-huggingface==0.1.2

# Remove build tools after pip install to reduce attack surface
# Eliminates 39 binutils CVEs from the final image
# dpkg --purge removes residual config files so Scout doesn't flag removed packages
RUN apt-get purge -y build-essential \
    && apt-get autoremove -y \
    && dpkg --purge --force-all $(dpkg -l | grep '^rc' | awk '{print $2}') 2>/dev/null || true \
    && rm -rf /var/lib/apt/lists/*

# Upgrade setuptools to fix CVE-2025-47273 (HIGH - path traversal),
# pip to fix CVE-2026-1703 (LOW - path traversal),
# and jaraco.context to fix CVE-2026-23949 (HIGH - Zip Slip path traversal)
RUN pip install --no-cache-dir "setuptools>=78.1.1" "pip>=26.0" "jaraco.context>=6.1.0" \
    && dpkg --purge --force-depends python3-jaraco.context \
    && ln -sf /usr/local/lib/python3.13/site-packages/jaraco/context \
              /usr/lib/python3/dist-packages/jaraco/context

# Download and bake in the HuggingFace sentence-transformers model.
# Saved via model.save() for a clean, symlink-free layout that survives
# image layers and registry transfer without manual volume setup.
#
# HF_HOME is the root for the HuggingFace Hub cache.
# SENTENCE_TRANSFORMERS_HOME points to hub/ so the sentence-transformers
# library finds cached models at $SENTENCE_TRANSFORMERS_HOME/models--<org>--<name>/
ENV HF_HOME=/app/.cache/huggingface
ENV SENTENCE_TRANSFORMERS_HOME=/app/.cache/huggingface/hub

RUN python3 -c "\
import os; \
from sentence_transformers import SentenceTransformer; \
model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2'); \
save_path = '/app/.cache/huggingface/models/all-MiniLM-L6-v2'; \
os.makedirs(save_path, exist_ok=True); \
model.save(save_path); \
assert os.path.isfile(os.path.join(save_path, 'modules.json')), 'Model save verification failed'; \
print(f'Model baked in at {save_path}') \
"

# Copy application code (pipeline/ingestion excluded)
COPY shared/ ./shared/
COPY server/ ./server/
COPY services/chat/ ./services/chat/
COPY services/dashboard/ ./services/dashboard/
COPY scripts/create_admin.py ./scripts/create_admin.py
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
    && ls -la /app/.cache/huggingface/models/all-MiniLM-L6-v2/modules.json \
    && echo "All application files verified"

# Create non-root user for runtime security (Scout health check requirement)
# Supervisord, Streamlit, and FastAPI all run as this user
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser \
    && mkdir -p /var/log/supervisor /var/run/supervisor /app/.streamlit /app/output \
    && chown -R appuser:appuser /app /var/log/supervisor /var/run/supervisor

ENV PYTHONPATH=/app
ENV NODE_ENV=production
# Model is baked in — no network access to HuggingFace needed at runtime
ENV TRANSFORMERS_OFFLINE=1
ENV HF_HUB_OFFLINE=1

EXPOSE 8000 8501

USER appuser

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:${API_PORT:-8000}/api/health || exit 1

CMD ["supervisord", "-c", "/etc/supervisor/conf.d/softpower.conf"]
