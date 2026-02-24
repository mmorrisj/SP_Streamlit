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
FROM python:3.13-slim

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

# Install lightweight Python dependencies only.
# Heavy ML packages (torch, sentence-transformers, langchain-huggingface)
# are shipped as wheels and installed on the target via:
#   ./airgap-deploy.sh setup
# This keeps the image ~1.5GB smaller for transfer.
COPY requirements-airgap.txt ./
RUN pip install --no-cache-dir -r requirements-airgap.txt --index-url https://pypi.org/simple

# Remove build tools after pip install to reduce attack surface
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

# HuggingFace model is mounted as a volume at runtime (not baked into image).
# This keeps the image ~90MB smaller for transfer.
# The model directory is exported separately by airgap-build.sh.
#
# HF_HOME is the root for the HuggingFace Hub cache.  The hub library stores
# models under $HF_HOME/hub/models--<org>--<name>/.
#
# SENTENCE_TRANSFORMERS_HOME must point to $HF_HOME/hub so that the
# sentence-transformers library can find cached models directly (it looks
# under $SENTENCE_TRANSFORMERS_HOME/models--<org>--<name>/ without adding
# a hub/ prefix).  This is essential for any code that calls
# SentenceTransformer(model_name) directly instead of going through
# shared/utils/model_cache.py.
ENV HF_HOME=/app/.cache/huggingface
ENV SENTENCE_TRANSFORMERS_HOME=/app/.cache/huggingface/hub

# Copy application code (no pipeline — not needed on air-gapped system)
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
    && echo "All application files verified"

# Create non-root user for runtime security
# Supervisord, Streamlit, and FastAPI all run as this user
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser \
    && mkdir -p /var/log/supervisor /var/run/supervisor /app/.streamlit /app/output \
    && chown -R appuser:appuser /app /var/log/supervisor /var/run/supervisor

ENV PYTHONPATH=/app
ENV NODE_ENV=production
# Ensure HuggingFace uses the cached model, not network
ENV TRANSFORMERS_OFFLINE=1
ENV HF_HUB_OFFLINE=1

EXPOSE 8000 8501

USER appuser

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${API_PORT:-8000}/api/health')" || exit 1

CMD ["supervisord", "-c", "/etc/supervisor/conf.d/softpower.conf"]
