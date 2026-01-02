# Multi-stage build for production API + React
FROM node:20-slim AS frontend-builder

WORKDIR /app/client

# Copy package files and install dependencies
COPY client/package*.json ./
RUN npm ci --only=production

# Copy source and build
COPY client/ ./
RUN npm run build

# Python stage
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python requirements
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Download NLTK data
RUN python -c "import nltk; nltk.download('punkt', quiet=True); nltk.download('stopwords', quiet=True)"

# Copy application code
COPY shared/ ./shared/
COPY server/ ./server/
COPY services/api/ ./services/api/
COPY services/pipeline/ ./services/pipeline/
COPY alembic/ ./alembic/
COPY alembic.ini .

# Copy built React app from frontend-builder stage
COPY --from=frontend-builder /app/client/dist ./client/dist

# Set Python path
ENV PYTHONPATH=/app

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8000/api/health || exit 1

CMD ["uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8000"]
