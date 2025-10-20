# Use CUDA-enabled base image for ML workloads
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
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Set a shared cache dir for all users and pre-download the model at build time
ENV HF_HOME=/tmp/huggingface
RUN mkdir -p /tmp/huggingface && chmod -R 777 /tmp/huggingface
RUN python3 -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# Copy shared modules and pipeline service
COPY shared/ ./shared/
COPY services/pipeline/ ./services/pipeline/

# Let Python know where to find your modules
ENV PYTHONPATH=/app

# (Optional) Test GPU access during build — can comment out later
# RUN python -c "import torch; print('CUDA available:', torch.cuda.is_available())"

# Default command (can be overridden in docker-compose)
CMD ["python", "-c", "print('Pipeline service ready. Run specific scripts via docker-compose exec.')"]