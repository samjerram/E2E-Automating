#!/usr/bin/env bash
# Build a portable zip for Google Drive / Windows (excludes venv and caches).
set -euo pipefail
cd "$(dirname "$0")"
STAMP=$(date +%Y-%m-%d)
OUT="E2E_Automating_backup_${STAMP}.zip"
rm -f "$OUT"
zip -r "$OUT" . \
  -x "./venv/*" \
  -x "./.venv/*" \
  -x "./regression_results/*" \
  -x "./p2nni_regression_results/*" \
  -x "*__pycache__/*" \
  -x "*.pyc" \
  -x "./.DS_Store" \
  -x "./.cursor/*" \
  -x "./.git/cursor/*" \
  -x "./${OUT}"
echo "Created $(pwd)/$OUT"
echo "If uploading to shared Drive, consider removing config.json and auth.json from the zip first (secrets)."
