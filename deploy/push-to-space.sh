#!/usr/bin/env bash
# Pushes this repo to a Hugging Face Space and makes it live.
#
#   ./deploy/push-to-space.sh YOUR-HF-USERNAME seo-audit-agent
#
# Create the Space first (huggingface.co → New Space → SDK: Docker → Blank).
set -euo pipefail
cd "$(dirname "$0")/.."

USER="${1:-}"
SPACE="${2:-seo-audit-agent}"
if [ -z "$USER" ]; then
  echo "Usage: ./deploy/push-to-space.sh YOUR-HF-USERNAME [space-name]"
  exit 1
fi

# Hugging Face reads its config from YAML front matter at the top of README.md.
if ! head -1 README.md | grep -q '^---$'; then
  echo "→ Adding the Space config header to README.md"
  cp README.md /tmp/readme-body.md
  cat deploy/huggingface/README.md > README.md
  echo "" >> README.md
  cat /tmp/readme-body.md >> README.md
fi

if [ ! -d .git ]; then
  git init -q && git add . && git commit -qm "SEO Audit Agent"
fi

git remote remove space 2>/dev/null || true
git remote add space "https://huggingface.co/spaces/$USER/$SPACE"

git add -A
git commit -qm "Deploy to Hugging Face Space" || echo "→ Nothing new to commit"

echo "→ Pushing to https://huggingface.co/spaces/$USER/$SPACE"
echo "  (username: $USER · password: paste an access token from huggingface.co/settings/tokens)"
git push space HEAD:main --force

cat <<EOF

Pushed. Now open:
  https://huggingface.co/spaces/$USER/$SPACE/settings

Add these under "Variables and secrets" → New variable:
  STATELESS            true
  REQUIRE_AUTH         false
  DATA_DIR             /tmp/seoagent
  PUBLIC_BASE_URL      https://$USER-$SPACE.hf.space
  RATE_LIMIT_PER_HOUR  3
  PUBLIC_MAX_PAGES     8

Build takes 5-8 minutes. Your live link will be:
  https://$USER-$SPACE.hf.space
EOF
