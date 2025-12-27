FROM python:3.11

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy and install requirements
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt --index-url https://pypi.org/simple

# Download NLTK data
RUN python -c "import nltk; nltk.download('punkt'); nltk.download('stopwords')"

# Copy shared modules and API services
COPY shared shared/

# NEW: React-serving API
COPY server server/

# OLD: Legacy API endpoints
COPY services/api services/api/

COPY alembic alembic/
COPY alembic.ini .

# Copy built React frontend
COPY client/dist client/dist/

EXPOSE 8000

# Set Python path to find modules
ENV PYTHONPATH=/app

# Use new server that serves React UI + API endpoints
CMD ["uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8000"]
