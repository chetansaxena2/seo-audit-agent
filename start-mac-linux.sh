#!/usr/bin/env bash
# SEO Audit Agent - start on Mac or Linux without Docker
set -e
cd "$(dirname "$0")"

command -v python3 >/dev/null || { echo "Python 3 needed: https://www.python.org/downloads/"; exit 1; }
echo "Using $(python3 --version)"

[ -x .venv/bin/python ] || python3 -m venv .venv
PY=.venv/bin/python

if ! $PY -c "import uvicorn, fastapi, lxml, httpx, reportlab" 2>/dev/null; then
  echo "Installing components (first run only, 5-8 minutes)..."
  $PY -m pip install --upgrade pip --quiet
  $PY -m pip install -r requirements.txt || {
    echo "Retrying with flexible versions..."
    $PY -m pip install -r requirements-flexible.txt; }
  $PY -c "import uvicorn, fastapi, lxml, httpx, reportlab" || {
    echo "Install failed. Try Python 3.12."; exit 1; }
  echo "Downloading the browser used for screenshots..."
  if ! $PY -m playwright install chromium; then
    echo
    echo "NOTE: the browser could not be downloaded (network or firewall)."
    echo "The agent still works - reports just come without screenshots."
    echo
  fi
fi

echo
echo "Open your browser at:  http://localhost:8000"
echo "Press Ctrl+C to stop."
echo
$PY -m uvicorn app.api:app --host 127.0.0.1 --port 8000
