# ============================================
# Registry-Ready Consolidated Application Container
# Single container running FastAPI + Streamlit
# via supervisord process manager
#
# Designed for deployment via Docker Hub mirror:
#   - ML packages (torch, sentence-transformers) baked in
#   - HuggingFace model (nomic-ai/nomic-embed-text-v1.5) baked in
#   - React frontend built and included
#   - No pipeline/ingestion code
#   - Pull-and-run: no manual setup steps required
#
# Image size: ~1.7-2.2GB
# ============================================

# ============================================
# Stage 1: Build React Frontend
# ============================================
# Target: Rocky 9+ (kernel 5.14+, glibc 2.34+).
# Node 22 is the current LTS (supported through April 2027).
FROM node:22-bookworm-slim@sha256:80fdb3f57c815e1b638d221f30a826823467c4a56c8f6a8d7aa091cd9b1675ea AS frontend-builder

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
# Target: Rocky 9+ (kernel 5.14+, glibc 2.34+).
# Trixie (Debian 13, glibc 2.38) is safe — clone3 syscall requires kernel 5.3+.
FROM python:3.13-slim-trixie@sha256:739e7213785e88c0f702dcdc12c0973afcbd606dbf021a589cab77d6b00b579d

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
        'langchain-huggingface>=1.0' \
        'langchain-postgres>=0.0.16,<0.1.0'

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

# Download and bake in ML models in a single layer to avoid HF hub cache bloat.
# Both the embedding model and reranker are saved via model.save() for a clean,
# symlink-free layout, then the HF hub cache is purged — all in one RUN step
# so intermediate downloads don't persist as separate Docker layers.
#
# Embedding: nomic-ai/nomic-embed-text-v1.5 (~280MB)
#   - 768-dim vectors, 8192-token context window (vs 256-token MiniLM limit)
#   - Requires trust_remote_code=True (custom NomicBert pooling code)
#   - Apache 2.0 license, enterprise-safe
# Reranker: cross-encoder/ms-marco-MiniLM-L-6-v2 (~90MB)
ENV HF_HOME=/app/.cache/huggingface
ENV SENTENCE_TRANSFORMERS_HOME=/app/.cache/huggingface/hub

RUN python3 -c "\
import os, shutil; \
from sentence_transformers import SentenceTransformer, CrossEncoder; \
\
# 1. Embedding model (nomic-embed-text-v1.5: 768-dim, 8192-token context) \
# revision-pinned to prevent unexpected custom code updates on rebuild \
emb = SentenceTransformer('nomic-ai/nomic-embed-text-v1.5', trust_remote_code=True, revision='e5cf08aadaa33385f5990def41f7a23405aec398'); \
emb_path = '/app/.cache/huggingface/models/nomic-embed-text-v1.5'; \
os.makedirs(emb_path, exist_ok=True); \
emb.save(emb_path); \
assert os.path.isfile(os.path.join(emb_path, 'modules.json')), 'Embedding model save failed'; \
print(f'Embedding model baked in at {emb_path}'); \
\
# 2. Reranker model (lightweight MiniLM variant) \
reranker = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2', max_length=512); \
reranker_path = '/app/.cache/huggingface/models/ms-marco-MiniLM-L-6-v2'; \
os.makedirs(reranker_path, exist_ok=True); \
reranker.save(reranker_path); \
assert os.path.isfile(os.path.join(reranker_path, 'config.json')), 'Reranker save failed'; \
print(f'Reranker model baked in at {reranker_path}'); \
\
# 3. Purge HF hub cache (downloads already saved to final paths above) \
shutil.rmtree('/app/.cache/huggingface/hub', ignore_errors=True); \
print('HF hub cache purged'); \
"

# Pre-cache tiktoken encoding files.
# tiktoken downloads encoding data from Azure blob storage on first use;
# this fails when TRANSFORMERS_OFFLINE=1 blocks network access.
ENV TIKTOKEN_CACHE_DIR=/app/.cache/tiktoken
RUN python3 -c "\
import tiktoken; \
enc = tiktoken.encoding_for_model('gpt-4o'); \
print(f'Tiktoken encoding cached: {enc.name}') \
"

# Copy application code (pipeline/ingestion excluded)
COPY shared/ ./shared/
COPY server/ ./server/
COPY services/chat/ ./services/chat/
COPY services/dashboard/ ./services/dashboard/
COPY scripts/create_admin.py ./scripts/create_admin.py
COPY scripts/generate_report.py ./scripts/generate_report.py
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
    && ls -la /app/.cache/huggingface/models/nomic-embed-text-v1.5/modules.json \
    && ls -la /app/.cache/huggingface/models/ms-marco-MiniLM-L-6-v2/config.json \
    && test -d /app/.cache/tiktoken \
    && echo "All application files verified"

# Create non-root user for runtime security (Scout health check requirement)
# Supervisord, Streamlit, and FastAPI all run as this user
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser \
    && mkdir -p /var/log/supervisor /var/run/supervisor /app/.streamlit /app/output \
    && chown -R appuser:appuser /app /var/log/supervisor /var/run/supervisor

ENV PYTHONPATH=/app
ENV NODE_ENV=production
# Models are baked in — no network access to HuggingFace/Azure needed at runtime
ENV TRANSFORMERS_OFFLINE=1
ENV HF_HUB_OFFLINE=1
# TIKTOKEN_CACHE_DIR set earlier in build; repeated here for runtime clarity
ENV TIKTOKEN_CACHE_DIR=/app/.cache/tiktoken

EXPOSE 8000 8501

USER appuser

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${API_PORT:-8000}/api/health')" || exit 1

CMD ["supervisord", "-c", "/etc/supervisor/conf.d/softpower.conf"]
