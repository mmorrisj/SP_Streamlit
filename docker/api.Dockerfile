# ============================================
# Multi-stage Docker Build for API Service
# Stage 1: Build React Frontend
# Stage 2: Python FastAPI + Serve React
# ============================================

# ============================================
# Stage 1: Frontend Builder
# ============================================
# Bookworm (Debian 12) for CentOS 7 kernel 3.10 compatibility.
FROM node:20-slim-bookworm AS frontend-builder

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
# Bookworm (Debian 12) for CentOS 7 kernel 3.10 compatibility.
FROM python:3.13-slim-bookworm

WORKDIR /app

# Install system dependencies, build Python packages, then remove build-essential
# to eliminate 39 binutils CVEs from the final image
# Note: curl removed to eliminate CVE-2025-13034 (libcurl4t64)
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python requirements (cached until requirements.txt changes)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt --index-url https://pypi.org/simple

# Remove build tools after pip install to reduce attack surface
# Also remove tar's rmt binary (TEMP-0290435-0B57B5) — remote tape server
# is unused and has insufficient input validation.
RUN apt-get purge -y build-essential \
    && apt-get autoremove -y \
    && rm -f /usr/sbin/rmt \
    && rm -rf /var/lib/apt/lists/*

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
CMD uvicorn server.main:app --host 0.0.0.0 --port ${API_PORT:-8000}
