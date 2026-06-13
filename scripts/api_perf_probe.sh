#!/usr/bin/env sh
set -eu

BASE_URL="${1:-http://localhost:8080}"

probe() {
  path="$1"
  curl -s -o /tmp/megadoc-api-probe.json \
    -w "%{time_total} %{size_download} ${path}\n" \
    "${BASE_URL}${path}"
}

probe "/knowledge/topics?include_inactive=false"
probe "/knowledge/graph/stats"
probe "/knowledge/topic-proposals?include_consolidated=false"
probe "/knowledge/contexts?limit=40"
probe "/knowledge/nodes?limit=60"
probe "/knowledge/assertions?limit=80"
probe "/knowledge/entities?limit=40"
probe "/knowledge/canonical-entities?limit=40"
probe "/knowledge/specialists/accounting-statements?limit=40"
probe "/knowledge/specialists/utility-bills?limit=40"
probe "/knowledge/consolidation/suggestions?limit_per_axis=12"
probe "/system/status"
