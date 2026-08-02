# Hugging Face Space — full version WITH screenshots in the PDF.
#
# HOW TO USE:
#   1. Change YOUR-GITHUB-USERNAME on the GITHUB_REPO line below to your own.
#   2. Paste this whole file into your Space as a file named exactly: Dockerfile
#
# It pulls the code straight from your public GitHub repo at build time, so this
# is the only file you need to create in the Space.

FROM python:3.12-slim

# ---- change this one line ----
ARG GITHUB_REPO=https://github.com/YOUR-GITHUB-USERNAME/seo-audit-agent.git
# ------------------------------

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    DATA_DIR=/tmp/seoagent \
    PORT=7860 \
    STATELESS=true \
    REQUIRE_AUTH=false \
    SCREENSHOTS_ENABLED=true \
    SCREENSHOT_MAX=8 \
    RATE_LIMIT_PER_HOUR=3 \
    PUBLIC_MAX_PAGES=8 \
    MAX_PAGES=8

WORKDIR /app

# git to fetch the code, plus the system libraries Chromium needs
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl ca-certificates fonts-liberation libnss3 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
    libxrandr2 libgbm1 libasound2 libpango-1.0-0 libcairo2 \
 && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 "$GITHUB_REPO" /src \
 && cp -r /src/app /app/app \
 && cp /src/requirements.txt /app/requirements.txt \
 && rm -rf /src

RUN pip install -r requirements.txt \
 && python -m playwright install chromium \
 && chmod -R a+rX /ms-playwright

# Spaces run as a non-root user, so everything the app writes lives in /tmp
RUN mkdir -p /tmp/seoagent/screenshots /tmp/seoagent/reports && chmod -R 777 /tmp/seoagent

EXPOSE 7860

CMD ["sh", "-c", "uvicorn app.api:app --host 0.0.0.0 --port ${PORT:-7860}"]
