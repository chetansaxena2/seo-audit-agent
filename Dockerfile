FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    DATA_DIR=/app/data

WORKDIR /app

# Chromium needs these for screenshots and PDF rendering
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates fonts-liberation libnss3 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
    libxrandr2 libgbm1 libasound2 libpango-1.0-0 libcairo2 curl \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt \
 && python -m playwright install chromium \
 && chmod -R a+rX /ms-playwright

COPY app ./app

# world-writable so the image also runs as a non-root user (Hugging Face Spaces)
RUN mkdir -p /app/data/screenshots /app/data/reports && chmod -R 777 /app/data
VOLUME ["/app/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s \
  CMD curl -fsS http://localhost:${PORT:-8000}/healthz || exit 1

# $PORT is injected by Render, Railway, Koyeb and friends; defaults to 8000
CMD ["sh", "-c", "uvicorn app.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
