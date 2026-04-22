#!/usr/bin/env sh
set -eu

API_BASE_URL="${API_BASE_URL:-http://localhost:8080}"
PDF_PATH="${1:-tests/fixtures/sample.pdf}"

UPLOAD_RESPONSE="$(curl -sS -X POST "${API_BASE_URL}/documents/upload?auto_submit=true" \
  -F "file=@${PDF_PATH};type=application/pdf")"

printf '%s\n' "$UPLOAD_RESPONSE"

DOCUMENT_ID="$(printf '%s' "$UPLOAD_RESPONSE" | python3 -c 'import json,sys; print(json.load(sys.stdin)["document_id"])')"

curl -sS "${API_BASE_URL}/documents/${DOCUMENT_ID}"
curl -sS "${API_BASE_URL}/documents/${DOCUMENT_ID}/ocr"
curl -sS "${API_BASE_URL}/documents/${DOCUMENT_ID}/versions"
curl -sS "${API_BASE_URL}/documents/${DOCUMENT_ID}/assets"
