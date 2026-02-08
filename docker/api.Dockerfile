# ============================================
# Multi-stage Docker Build for API Service
# Stage 1: Build React Frontend
# Stage 2: Python FastAPI + Serve React
# ============================================

# ============================================
# Stage 1: Frontend Builder
# ============================================
FROM node:20-slim AS frontend-builder

WORKDIR /app/client

# Copy package files first for better caching
# This layer is cached until package.json or package-lock.json changes
COPY client/package*.json ./
RUN npm ci

# Copy source files and build
COPY client/ ./
RUN npm run build

# ============================================
# Stage 2: Python Backend + API Server
# ============================================
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python requirements (cached until requirements.txt changes)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt --index-url https://pypi.org/simple

# Download NLTK data
RUN python -c "import nltk; nltk.download('punkt', quiet=True); nltk.download('stopwords', quiet=True)"

# Copy application code
COPY shared shared/
COPY server server/
COPY services/chat services/chat/
COPY alembic alembic/
COPY alembic.ini .

# Copy built React app from frontend-builder stage
COPY --from=frontend-builder /app/client/dist client/dist/

EXPOSE 8000

# Set Python path to find modules
ENV PYTHONPATH=/app

# Use server that serves React UI + API endpoints
CMD ["uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8000"]
