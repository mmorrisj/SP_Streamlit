# Use CUDA-enabled base image
FROM nvidia/cuda:12.1.1-runtime-ubuntu22.04

# Install system dependencies and Python
RUN apt-get update && \
    apt-get install -y python3 python3-pip git && \
    rm -rf /var/lib/apt/lists/* && \
    ln -s /usr/bin/python3 /usr/bin/python && \
    pip3 install --upgrade pip

# Set working directory
WORKDIR /app

# Install Python dependencies
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Set a shared cache dir for all users and pre-download the model at build time
ENV HF_HOME=/tmp/huggingface
RUN mkdir -p /tmp/huggingface && chmod -R 777 /tmp/huggingface 
RUN python3 -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# Copy application code
COPY backend/scripts /app/backend/scripts
COPY backend/tasks /app/backend/tasks
COPY backend/app.py /app/backend/app.py
COPY backend/extensions.py /app/backend/extensions.py
COPY backend/celery.py /app/backend/celery.py
COPY backend/routes.py /app/backend/routes.py
COPY backend/commands.py /app/backend/commands.py
COPY backend/config.yaml /app/backend/config.yaml

# Let Python know where to find your modules
ENV PYTHONPATH=/app

# (Optional) Test GPU access during build — can comment out later
# RUN python -c "import torch; print('CUDA available:', torch.cuda.is_available())"