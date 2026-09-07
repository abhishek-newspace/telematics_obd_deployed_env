#!/bin/bash
set -euo pipefail

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DISPLAY="${DISPLAY:-:0}"
XAUTHORITY="${XAUTHORITY:-/run/user/1000/gdm/Xauthority}"
export DISPLAY XAUTHORITY

log() {
    echo "[obd] $*"
}

container_running() {
    [[ "$(docker inspect "$1" --format '{{.State.Running}}' 2>/dev/null || echo false)" == "true" ]]
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

run_as_user() {
    sudo -u jetson \
        DISPLAY="$DISPLAY" \
        XAUTHORITY="$XAUTHORITY" \
        "$@"
}

wait_for_display() {
    log "Waiting for NVIDIA driver..."
    for i in $(seq 1 60); do
        if nvidia-smi >/dev/null 2>&1; then
            log "NVIDIA driver is ready."
            break
        fi
        if [[ "$i" -eq 60 ]]; then
            log "Timed out waiting for NVIDIA driver."
            return 1
        fi
        sleep 1
    done

    log "Waiting for graphical session at ${DISPLAY}..."
    for i in $(seq 1 120); do
        if run_as_user xset q >/dev/null 2>&1; then
            local resolution
            resolution="$(run_as_user xrandr 2>/dev/null | awk '/ connected/{getline; print $1; exit}')"
            if run_as_user xrandr 2>/dev/null | grep -q " connected"; then
                log "Display is ready (${resolution:-unknown resolution})."
                run_as_user xhost +local:docker >/dev/null 2>&1 || true
                sleep 3
                return 0
            fi
        fi
        sleep 1
    done

    log "Timed out waiting for graphical session."
    return 1
}

start_obd() {
    log "Starting OBD display..."
    docker compose up -d --force-recreate --remove-orphans obd

    for attempt in $(seq 1 5); do
        sleep 4
        local status exit_code
        status="$(docker inspect obd --format '{{.State.Status}}' 2>/dev/null || echo missing)"
        exit_code="$(docker inspect obd --format '{{.State.ExitCode}}' 2>/dev/null || echo 1)"

        if [[ "$status" == "running" ]]; then
            log "OBD container is running."
            return
        fi

        if [[ "$status" == "exited" && "$exit_code" == "139" ]]; then
            log "OBD crashed with SIGSEGV (139); retry $attempt/5 after display settle..."
            docker compose up -d --force-recreate obd
            continue
        fi

        log "OBD status=$status exit=$exit_code; waiting..."
    done

    if [[ "$(docker inspect obd --format '{{.State.Status}}' 2>/dev/null)" != "running" ]]; then
        log "OBD failed to stay running. Recent logs:"
        docker logs obd 2>&1 | tail -20 || true
        return 1
    fi
}

cd "$DEPLOY_DIR"
wait_for_docker

if container_running obd; then
    log "OBD already running; skipping."
    exit 0
fi

if wait_for_display; then
    start_obd
else
    log "Display not ready; OBD not started."
    exit 1
fi
