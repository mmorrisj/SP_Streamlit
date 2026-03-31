# ============================================
# Preprocessing / Pipeline Runtime Container
# ============================================
# Purpose:
# - Run ingestion, event processing, entity processing, and summary jobs
# - Keep preprocessing concerns separate from webapp/streamlit runtime image
# ============================================

# Target: Rocky 9+ (kernel 5.14+, glibc 2.34+).
# Digest-pinned for Docker Scout base image compliance.
# Update digest with: docker pull python:3.13-slim-trixie && docker inspect python:3.13-slim-trixie --format='{{index .RepoDigests 0}}'
FROM python:3.13-slim-trixie

WORKDIR /app

# Build deps are needed for scientific packages (for example hdbscan),
# then removed to reduce final image size and attack surface.
# curl is intentionally omitted to avoid pulling vulnerable libcurl packages.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt --index-url https://pypi.org/simple

# Remove build tools after pip install.
# Also remove tar's rmt binary (TEMP-0290435-0B57B5), which is unused here.
RUN apt-get purge -y build-essential \
    && apt-get autoremove -y \
    && rm -f /usr/sbin/rmt \
    && rm -rf /var/lib/apt/lists/*

# NLTK resources used by some pipeline jobs.
RUN python -c "import nltk; nltk.download('punkt', quiet=True); nltk.download('stopwords', quiet=True)"

# Bake in ML models (same pattern as registry.Dockerfile).
# nomic-embed-text-v1.5: 768-dim, 8192-token context, requires trust_remote_code=True.
# cross-encoder/ms-marco-MiniLM-L-6-v2: reranker used by RAG pipeline.
# Both saved via model.save() for a clean, symlink-free layout, then HF hub
# cache purged — all in one RUN step so downloads don't persist as layers.
ENV HF_HOME=/app/.cache/huggingface
ENV SENTENCE_TRANSFORMERS_HOME=/app/.cache/huggingface/hub

RUN python3 -c "\
import os, shutil; \
from sentence_transformers import SentenceTransformer, CrossEncoder; \
\
# 1. Embedding model (revision-pinned to prevent unexpected custom code updates) \
emb = SentenceTransformer('nomic-ai/nomic-embed-text-v1.5', trust_remote_code=True, revision='e5cf08aadaa33385f5990def41f7a23405aec398'); \
emb_path = '/app/.cache/huggingface/models/nomic-embed-text-v1.5'; \
os.makedirs(emb_path, exist_ok=True); \
emb.save(emb_path); \
assert os.path.isfile(os.path.join(emb_path, 'modules.json')), 'Embedding model save failed'; \
print(f'Embedding model baked in at {emb_path}'); \
\
# 2. Reranker model \
reranker = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2', max_length=512); \
reranker_path = '/app/.cache/huggingface/models/ms-marco-MiniLM-L-6-v2'; \
os.makedirs(reranker_path, exist_ok=True); \
reranker.save(reranker_path); \
assert os.path.isfile(os.path.join(reranker_path, 'config.json')), 'Reranker save failed'; \
print(f'Reranker baked in at {reranker_path}'); \
\
# 3. Purge HF hub cache \
shutil.rmtree('/app/.cache/huggingface/hub', ignore_errors=True); \
print('HF hub cache purged'); \
"

# Offline mode: models are baked in, no network access to HuggingFace needed at runtime.
ENV TRANSFORMERS_OFFLINE=1
ENV HF_HUB_OFFLINE=1

# Copy only code needed for preprocessing/pipeline execution.
COPY shared/ ./shared/
COPY services/__init__.py ./services/__init__.py
COPY services/run_ingestion_pipeline.py ./services/run_ingestion_pipeline.py
COPY services/pipeline/ ./services/pipeline/
COPY services/publication/ ./services/publication/
COPY alembic/ ./alembic/
COPY alembic.ini ./

ENV PYTHONPATH=/app
ENV BATCH_SCRATCHPAD_DIR=/app/_data/batch

# Runtime directories commonly used by pipeline tooling.
RUN mkdir -p /app/_data/batch /app/_data/processed/embeddings /app/_data/publications /app/output

# Run as non-root.
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser \
    && chown -R appuser:appuser /app
USER appuser

# Job image: command is expected to be overridden per task.
CMD ["python", "-m", "services.pipeline.batch.batch_queue_runner", "--help"]
