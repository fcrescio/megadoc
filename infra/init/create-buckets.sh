#!/usr/bin/env sh
set -eu

mc alias set local "$S3_ENDPOINT_URL" "$S3_ACCESS_KEY" "$S3_SECRET_KEY"
mc mb --ignore-existing "local/$S3_BUCKET_RAW"
mc mb --ignore-existing "local/$S3_BUCKET_DERIVATIVES"
mc anonymous set private "local/$S3_BUCKET_RAW"
mc anonymous set private "local/$S3_BUCKET_DERIVATIVES"

