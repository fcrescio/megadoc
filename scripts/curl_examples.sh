#!/usr/bin/env sh
set -eu

API_BASE_URL="${API_BASE_URL:-http://localhost:8080}"
PDF_PATH="${1:-tests/fixtures/sample.pdf}"

curl -X POST "${API_BASE_URL}/documents/upload?auto_submit=true" \
  -F "file=@${PDF_PATH};type=application/pdf"

