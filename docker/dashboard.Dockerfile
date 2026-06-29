# Target: Rocky 9+ (kernel 5.14+, glibc 2.34+).
FROM python:3.14-slim-trixie

WORKDIR /app

# Copy requirements
COPY requirements.txt .

# Install build dependencies for hdbscan, then Python packages, then cleanup
# Note: curl removed to eliminate CVE-2025-13034 (libcurl4t64);
#       health checks use Python urllib instead.
# Also remove tar's rmt binary (TEMP-0290435-0B57B5) — remote tape server
# is unused and has insufficient input validation.
RUN apt-get update && apt-get install -y \
    build-essential \
    && pip install --no-cache-dir -r requirements.txt --index-url https://pypi.org/simple \
    && apt-get purge -y build-essential \
    && apt-get autoremove -y \
    && rm -f /usr/sbin/rmt \
    && rm -rf /var/lib/apt/lists/*

# Copy shared modules and services
COPY shared/ ./shared/
COPY services/dashboard/ ./services/dashboard/
COPY services/pipeline/embeddings/ ./services/pipeline/embeddings/
COPY services/pipeline/__init__.py ./services/pipeline/__init__.py

EXPOSE 8501

# Set Python path to find modules
ENV PYTHONPATH=/app

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')" || exit 1

CMD ["streamlit", "run", "services/dashboard/app.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.enableCORS=false"]
