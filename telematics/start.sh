#!/bin/bash
set -euo pipefail

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTAINER=telematics_server

# systemd (root) needs compose on PATH
export PATH="/usr/local/lib/docker/cli-plugins:/home/pi/.docker/cli-plugins:${PATH}"

# Avoid compose warnings when only starting telematics (OBD uses these).
export DISPLAY="${DISPLAY:-:0}"
export XAUTHORITY="${XAUTHORITY:-}"

log() {
    echo "[telematics] $*"
}

host_btime() {
    awk '/^btime/{print $2}' /proc/stat
}

container_running() {
    [[ -n "$(docker ps -q --filter "name=^${CONTAINER}$")" ]]
}

container_exists() {
    [[ -n "$(docker ps -aq --filter "name=^${CONTAINER}$")" ]]
}

container_started_this_boot() {
    if ! container_running; then
        return 1
    fi

    local btime started_at started_epoch
    btime="$(host_btime)"
    started_at="$(docker inspect "$CONTAINER" --format '{{.State.StartedAt}}' 2>/dev/null || echo "")"
    if [[ -z "$started_at" || "$started_at" == "0001-01-01T00:00:00Z" ]]; then
        return 1
    fi
    started_epoch="$(date -d "$started_at" +%s 2>/dev/null || echo 0)"
    [[ "$started_epoch" -ge "$btime" ]]
}

wait_for_docker() {
    log "Waiting for Docker..."
    for _ in $(seq 1 60); do
        if docker info >/dev/null 2>&1; then
            log "Docker is ready."
            return
        fi
        sleep 1
    done
    log "Docker failed to start."
    exit 1
}

start_telematics() {
    if container_exists; then
        log "Starting telematics container: $(date -Iseconds)"
        docker start "$CONTAINER"
    else
        log "Creating telematics container: $(date -Iseconds)"
        docker compose up -d --no-recreate telemetry_server
    fi
}

cd "$DEPLOY_DIR"
wait_for_docker

if container_running && container_started_this_boot; then
    log "Telematics already running for this boot; leaving as-is."
    exit 0
fi

if container_running; then
    log "Telematics running from a previous boot; stopping for a fresh session."
    docker stop "$CONTAINER"
fi

start_telematics
log "Telematics start complete: $(date -Iseconds)"
