FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 appuser

COPY --chown=appuser:appuser app/ ./

USER appuser

EXPOSE 8080

CMD ["python", "main.py"]
