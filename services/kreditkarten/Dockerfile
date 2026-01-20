# Multi-stage build for DDEV development
FROM python:3.11-slim AS builder

WORKDIR /app

# System dependencies for build
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files
COPY pyproject.toml uv.lock* ./

# Install dependencies to system Python
RUN uv pip install --system --no-cache -r pyproject.toml

# Production Image
FROM python:3.11-slim

# System dependencies for runtime (Tesseract, Poppler, Fonts)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-deu \
    tesseract-ocr-eng \
    poppler-utils \
    fonts-dejavu-core \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 appuser

WORKDIR /app

# Copy Python packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Create directories for data (will be overwritten by volume mounts)
RUN mkdir -p /app/data /app/exports /app/belege/inbox /app/belege/archiv /app/imports/inbox /app/imports/archiv /app/logs \
    && chown -R appuser:appuser /app

USER appuser

# Environment
ENV PYTHONUNBUFFERED=1
ENV FLASK_APP=app.py

# Health Check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:5000/health || exit 1

EXPOSE 5000

# Gunicorn server
CMD ["gunicorn", "--config", "gunicorn.conf.py", "app:app"]
