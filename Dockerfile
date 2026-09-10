FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PORT=7860

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements-web.txt .
RUN pip install --no-cache-dir -r requirements-web.txt

# Copy source code
COPY . .

# Create storage directories and grant write permissions (for non-root users like HF Spaces user 1000)
RUN mkdir -p backend/storage/uploads backend/storage/translated && chmod -R 777 /app

# Expose default port (7860 for HuggingFace Spaces, dynamic on Render/Fly.io)
EXPOSE 7860

# Launch FastAPI app with dynamic port fallback
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-7860}"]
