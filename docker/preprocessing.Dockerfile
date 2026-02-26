# ============================================
# Preprocessing / Pipeline Runtime Container
# ============================================
# Purpose:
# - Run ingestion, event processing, entity processing, and summary jobs
# - Keep preprocessing concerns separate from webapp/streamlit runtime image
# ============================================

# Digest-pinned for Docker Scout base image compliance.
# Update digest with: docker pull python:3.13-slim && docker inspect python:3.13-slim --format='{{index .RepoDigests 0}}'
FROM python:3.13-slim@sha256:f50f56f1471fc430b394ee75fc826be2d212e35d85ed1171ac79abbba485dce9

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
