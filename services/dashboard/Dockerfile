FROM python:3.11-slim

WORKDIR /app

# Copy requirements first for better caching
COPY streamlit/requirements.txt .
COPY backend/requirements.txt backend_requirements.txt

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt --index-url https://pypi.org/simple && \
    pip install --no-cache-dir -r backend_requirements.txt --index-url https://pypi.org/simple

# Copy backend modules (modern SQLAlchemy 2.0 setup)
COPY backend/database.py /app/backend/database.py
COPY backend/models.py /app/backend/models.py
COPY backend/config.yaml /app/backend/config.yaml
COPY backend/scripts /app/backend/scripts

# Copy Streamlit application
COPY ./streamlit /app

# Create __init__.py files for proper imports
RUN touch /app/backend/__init__.py && \
    touch /app/backend/scripts/__init__.py

EXPOSE 8501

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl --fail http://localhost:8501/_stcore/health || exit 1

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.enableCORS=false"]
