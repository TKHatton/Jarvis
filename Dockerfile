# Jarvis AI Assistant - Docker Image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV JARVIS_PORT=8080
ENV JARVIS_MEMORY_DB=/data/jarvis_memory.db
ENV JARVIS_OUTPUT_DIR=/data/output

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Create data directory for persistent storage
RUN mkdir -p /data/output

# Copy requirements first (for Docker layer caching)
COPY requirements.txt .

# Cache buster - update this date to force pip reinstall
ARG CACHEBUST=2026-06-23-v2

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY agent.py .
COPY prompts.py .
COPY tools.py .
COPY jarvis_memory.py .
COPY jarvis_server.py .
COPY jarvis-ui.html .
COPY google_auth.py .
COPY supervisord.conf .

# Expose port
EXPOSE 8080

# Default command - run with supervisor (both server and agent)
CMD ["supervisord", "-c", "supervisord.conf"]
