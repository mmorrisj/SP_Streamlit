# ============================================
# Air-Gapped Consolidated Application Container
# Single container running FastAPI + Streamlit
# via supervisord process manager
# ============================================
# Base images: node (React build) + python (runtime)
# Both available in air-gapped registry
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

# Install system dependencies
# - build-essential: needed to compile hdbscan, umap-learn, etc.
# - curl: health checks
# - postgresql-client: database utilities (pg_isready, psql)
# - supervisor: process manager for running both services
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        postgresql-client \
        supervisor \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt --index-url https://pypi.org/simple

# Download NLTK data (needed at runtime, no internet on target)
RUN python -c "import nltk; nltk.download('punkt', quiet=True); nltk.download('punkt_tab', quiet=True); nltk.download('stopwords', quiet=True)"

# Pre-download the sentence-transformers model for RAG/chat
# This model is loaded by services/chat/rag_service.py at runtime
ENV HF_HOME=/app/.cache/huggingface
RUN python -c "\
from sentence_transformers import SentenceTransformer; \
model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2'); \
print('Embedding model cached successfully')" \
    && chmod -R 755 /app/.cache/huggingface

# Copy application code
COPY shared/ ./shared/
COPY server/ ./server/
COPY services/chat/ ./services/chat/
COPY services/dashboard/ ./services/dashboard/
COPY services/pipeline/ ./services/pipeline/
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
