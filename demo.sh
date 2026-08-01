#!/usr/bin/env bash
# Two-minute demo: audits the bundled test site (which has 24 deliberate SEO faults)
# and writes a real HTML + PDF report you can open.
set -euo pipefail
cd "$(dirname "$0")"

PORT=8901
OUT="./demo-output"

echo "→ Installing dependencies (first run only)…"
pip install -q -r requirements.txt
python -m playwright install chromium >/dev/null 2>&1 || \
  echo "  (chromium unavailable — the PDF will use the ReportLab engine, without screenshots)"

echo "→ Serving the demo site on http://127.0.0.1:$PORT"
python -m http.server "$PORT" --directory tests/demo_site >/dev/null 2>&1 &
SERVER=$!
trap 'kill $SERVER 2>/dev/null || true' EXIT
sleep 2

echo "→ Running the audit…"
mkdir -p "$OUT"
python -m app.cli audit "http://127.0.0.1:$PORT/" --pages 8 --pdf --no-competitors --out "$OUT"

echo
echo "Done. Open the report:"
ls -1 "$OUT"/*.html "$OUT"/*.pdf 2>/dev/null | sed 's/^/  /'
echo
echo "Then try a real site:  python -m app.cli audit https://yoursite.com --pdf"
