#!/usr/bin/env bash
# Local dev launcher: installs deps, gets a browser, starts the API + dashboard.
set -euo pipefail
python3 -m venv .venv 2>/dev/null || true
source .venv/bin/activate
pip install -q -r requirements.txt
python -m playwright install chromium || echo "Chromium install failed — screenshots/PDF will fall back to ReportLab."
[ -f .env ] || cp .env.example .env
set -a; source .env; set +a
echo "Dashboard: http://localhost:${PORT:-8000}"
exec uvicorn app.api:app --host "${HOST:-0.0.0.0}" --port "${PORT:-8000}"
