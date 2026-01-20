# Multi-stage build für kleineres Image
FROM python:3.11-slim AS builder

WORKDIR /app

# System-Dependencies für Build
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# uv installieren
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Dependencies installieren
COPY pyproject.toml .
RUN uv pip install --system --no-cache -r pyproject.toml

# Production Image
FROM python:3.11-slim

# System-Dependencies für Runtime (Tesseract, Poppler, Fonts)
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-deu \
    tesseract-ocr-eng \
    poppler-utils \
    fonts-dejavu-core \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root User erstellen
RUN useradd -m -u 1000 appuser

WORKDIR /app

# Python packages vom Builder kopieren
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# App-Code kopieren
COPY --chown=appuser:appuser app.py matching.py ./
COPY --chown=appuser:appuser parsers/ ./parsers/
COPY --chown=appuser:appuser templates/ ./templates/
COPY --chown=appuser:appuser docs/handbuch/ ./docs/handbuch/

# Gunicorn Config kopieren
COPY --chown=appuser:appuser gunicorn.conf.py ./

# Verzeichnisse für Daten
RUN mkdir -p /app/data /app/exports /app/belege/inbox /app/belege/archiv /app/imports/inbox /app/imports/archiv /app/logs \
    && chown -R appuser:appuser /app

USER appuser

# Environment
ENV PYTHONUNBUFFERED=1
ENV FLASK_APP=app.py

# Health Check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:5000/health || exit 1

EXPOSE 5000

# Gunicorn statt Flask Dev-Server
CMD ["gunicorn", "--config", "gunicorn.conf.py", "app:app"]
