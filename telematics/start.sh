#!/bin/bash
set -euo pipefail

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTAINER=telematics_server

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
        sleep 2
    done
    log "Docker failed to start."
    exit 1
}

clock_synchronized() {
    timedatectl show -p NTPSynchronized --value 2>/dev/null | grep -qi '^yes$' && return 0
    [[ -f /run/systemd/timesync/synchronized ]] && return 0
    return 1
}

wait_for_rtc() {
    # 5s hardware grace after boot, then up to 25s for NTP/RTC (30s total max).
    log "RTC boot wait: 5s grace, then up to 25s for time sync..."
    sleep 5

    for _ in $(seq 1 25); do
        if clock_synchronized; then
            log "RTC updated: $(date -Iseconds)"
            return
        fi
        sleep 1
    done

    log "Starting with current system time: $(date -Iseconds)"
}

start_telematics() {
    wait_for_rtc

    if container_exists; then
        log "Starting telematics container (no recreate): $(date -Iseconds)"
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
