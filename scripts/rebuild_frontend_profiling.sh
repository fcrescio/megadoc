#!/usr/bin/env bash
set -euo pipefail

git_hash="${VITE_GIT_HASH:-$(git rev-parse --short HEAD)}"
react_profiling="${REACT_PROFILING:-true}"

export VITE_GIT_HASH="$git_hash"
export REACT_PROFILING="$react_profiling"

echo "Building frontend with VITE_GIT_HASH=$VITE_GIT_HASH REACT_PROFILING=$REACT_PROFILING"

docker compose build --no-cache frontend
docker compose up -d frontend

echo "Frontend build metadata:"
docker compose exec -T frontend sh -lc '
  for attempt in $(seq 1 20); do
    wget -qO- http://127.0.0.1:3030/build-info.json && exit 0
    sleep 1
  done
  echo "frontend did not serve build-info.json in time" >&2
  exit 1
'
echo
