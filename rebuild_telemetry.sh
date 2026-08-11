#!/usr/bin/env bash
# Rebuild telematics_server with Dockerfile apt pins, recreate, verify.
set -euo pipefail
cd "$(dirname "$0")"

echo "=== Building telemetry_server (no cache) ==="
docker compose build --no-cache telemetry_server

echo "=== Recreating container ==="
docker compose up -d --force-recreate telemetry_server
sleep 5

echo "=== Container status ==="
docker ps -a --filter name=telematics_server --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}'

echo "=== Pinned package versions ==="
docker exec telematics_server dpkg-query -W -f='${Package}\t${Version}\n' \
  libfmt9 libspdlog1.12 util-linux libc6 libgcc-s1 libstdc++6 libcurl4t64 ca-certificates

echo "=== Binary / ldd ==="
docker exec telematics_server test -x /app/telematics_bundle && echo BINARY_OK
docker exec telematics_server ldd /app/telematics_bundle | head -40

echo "=== Recent logs ==="
docker logs --tail 120 telematics_server

echo "=== DONE ==="
