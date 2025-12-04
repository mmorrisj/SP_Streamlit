FROM python:3.11-slim

WORKDIR /app

# Copy requirements
COPY requirements.txt .

# Install dependencies including curl for healthcheck
RUN apt-get update && apt-get install -y curl && \
    pip install --no-cache-dir -r requirements.txt --index-url https://pypi.org/simple && \
    rm -rf /var/lib/apt/lists/*

# Copy shared modules and services
COPY shared/ ./shared/
COPY services/dashboard/ ./services/dashboard/
COPY services/agent/ ./services/agent/
COPY services/pipeline/embeddings/ ./services/pipeline/embeddings/
COPY services/pipeline/__init__.py ./services/pipeline/__init__.py

EXPOSE 8501

# Set Python path to find modules
ENV PYTHONPATH=/app

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl --fail http://localhost:8501/_stcore/health || exit 1

CMD ["streamlit", "run", "services/dashboard/app.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.enableCORS=false"]
