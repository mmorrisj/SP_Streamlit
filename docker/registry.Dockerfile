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
# Digest-pinned for Docker Scout "Outdated base images" compliance.
# Update digest with: docker pull node:20-slim && docker inspect node:20-slim --format='{{index .RepoDigests 0}}'
FROM node:20-slim@sha256:d8a35d586fad3af7abb6fdb9ba972388395405f4d462da9e4a4ddcde67b5e0fb AS frontend-builder

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
# Digest-pinned for Docker Scout "Outdated base images" compliance.
# Update digest with: docker pull python:3.13-slim && docker inspect python:3.13-slim --format='{{index .RepoDigests 0}}'
FROM python:3.13-slim@sha256:f50f56f1471fc430b394ee75fc826be2d212e35d85ed1171ac79abbba485dce9

WORKDIR /app

# System dependencies
# - build-essential: required by some Python packages at install time
# Note: curl removed to eliminate CVE-2025-13034 (libcurl4t64).
# Note: postgresql-client removed — app uses psycopg2-binary which bundles
#       its own libpq; pg_isready runs in the DB container, not here;
#       no CLI tools (psql/pg_isready) are used at runtime. Removing it
#       eliminates libpq5 → libldap2 → libtasn1 and Kerberos library chains.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install lightweight runtime dependencies
COPY requirements-production.txt ./
RUN pip install --no-cache-dir -r requirements-production.txt

# Install heavy ML dependencies
# PyTorch CPU-only from the official PyTorch index (avoids pulling CUDA variant)
# sentence-transformers and langchain-huggingface from PyPI
COPY requirements-production-heavy.txt ./
RUN pip install --no-cache-dir \
        torch>=2.6.0 \
        --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir \
        sentence-transformers>=3.3.1 \
        'langchain-huggingface>=1.0'

# Remove build tools after pip install to reduce attack surface
# Eliminates 39 binutils CVEs from the final image
# dpkg --purge removes residual config files so Scout doesn't flag removed packages
# Also remove tar's rmt binary (TEMP-0290435-0B57B5) — remote tape server
# is unused and has insufficient input validation.
RUN apt-get purge -y build-essential \
    && apt-get autoremove -y \
    && dpkg --purge --force-all $(dpkg -l | grep '^rc' | awk '{print $2}') 2>/dev/null || true \
    && rm -f /usr/sbin/rmt \
    && rm -rf /var/lib/apt/lists/*

# Install supervisor from PyPI (instead of distro package) to avoid pulling
# Debian python3.13 runtime packages into the final image.
# Also upgrade setuptools/pip and jaraco.context for known CVE fixes.
RUN pip install --no-cache-dir \
        "setuptools>=78.1.1" \
        "pip>=26.0" \
        "jaraco.context>=6.1.0" \
        "supervisor>=4.2.5"

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
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${API_PORT:-8000}/api/health')" || exit 1

CMD ["supervisord", "-c", "/etc/supervisor/conf.d/softpower.conf"]
