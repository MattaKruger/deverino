# Deverino Python container
# Auto-built by container_spawn if missing — or build manually:
#   docker build -t deverino-python:latest .
FROM python:3.14-slim

# --- Pre-installed packages ---
# Add your dependencies here — the harness will rebuild if the Dockerfile changes.
RUN pip install --no-cache-dir \
    httpx \
    uv \
    numpy \
    pandas \
    matplotlib

# Lightweight system deps for matplotlib
RUN apt-get update && apt-get install -y --no-install-recommends \
    libfreetype6-dev \
    && rm -rf /var/lib/apt/lists/*

# Ensure /scratch exists (harness mounts it rw)
RUN mkdir -p /scratch

# Default workdir matches harness mount
WORKDIR /workspace

# Python: unbuffered stdout, no .pyc in workspace
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
