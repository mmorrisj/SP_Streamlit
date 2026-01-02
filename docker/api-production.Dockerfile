# ============================================
# Multi-stage Docker Build
# Stage 1: Build React Frontend
# Stage 2: Python FastAPI + Serve React
# ============================================

# ============================================
# Stage 1: Frontend Builder
# ============================================
FROM node:20-slim AS frontend-builder

WORKDIR /app/client

# Copy package files and install ALL dependencies (including devDependencies for build)
COPY client/package*.json ./
RUN npm ci

# Copy source files
COPY client/ ./

# Build production bundle
RUN npm run build

# Verify build output
RUN ls -la dist/ && echo "✅ React build complete"

# ============================================
# Stage 2: Python Backend + API Server
# ============================================
FROM python:3.11-slim AS backend

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python requirements
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt --index-url https://pypi.org/simple

# Download NLTK data
RUN python -c "import nltk; nltk.download('punkt', quiet=True); nltk.download('stopwords', quiet=True)"

# Copy application code
COPY shared/ ./shared/
COPY server/ ./server/
COPY services/api/ ./services/api/
COPY services/pipeline/ ./services/pipeline/
COPY alembic/ ./alembic/
COPY alembic.ini .
COPY shared/config/config.yaml ./shared/config/config.yaml

# Copy built React app from frontend-builder stage
COPY --from=frontend-builder /app/client/dist ./client/dist

# Verify React files copied
RUN ls -la client/dist/ && echo "✅ React static files ready"

# Set Python path
ENV PYTHONPATH=/app
ENV NODE_ENV=production

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8000/api/health || exit 1

# Start FastAPI server (serves React + API)
CMD ["uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8000"]
