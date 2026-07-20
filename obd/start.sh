#!/bin/bash
set -euo pipefail

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DISPLAY="${DISPLAY:-:0}"
XAUTHORITY="${XAUTHORITY:-}"
SESSION_USER="${SESSION_USER:-testing}"
export DISPLAY

export PATH="/usr/local/lib/docker/cli-plugins:/home/testing/.docker/cli-plugins:${PATH}"

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
    if [[ "$(id -un)" == "$SESSION_USER" ]]; then
        env DISPLAY="$DISPLAY" XAUTHORITY="$XAUTHORITY" "$@"
    else
        sudo -u "$SESSION_USER" \
            env DISPLAY="$DISPLAY" XAUTHORITY="$XAUTHORITY" \
            "$@"
    fi
}

auth_candidates() {
    local f session_type

    session_type="$(loginctl show-session "$(loginctl list-sessions --no-legend 2>/dev/null | awk -v u="$SESSION_USER" '$3==u {print $1; exit}')" -p Type --value 2>/dev/null || true)"

    if [[ "$session_type" == "wayland" ]]; then
        for f in /run/user/1000/.mutter-Xwaylandauth.*; do
            [[ -f "$f" ]] && echo "$f"
        done
    fi

    [[ -f /run/user/1000/gdm/Xauthority ]] && echo /run/user/1000/gdm/Xauthority
    for f in /run/user/1000/.mutter-Xwaylandauth.*; do
        [[ -f "$f" ]] && echo "$f"
    done
    [[ -n "${XAUTHORITY:-}" && -f "$XAUTHORITY" ]] && echo "$XAUTHORITY"
    [[ -f /home/${SESSION_USER}/.Xauthority ]] && echo "/home/${SESSION_USER}/.Xauthority"
}

discover_display() {
    local candidates=()
    local sock disp auth

    for sock in /tmp/.X11-unix/X*; do
        [[ -S "$sock" ]] || continue
        disp=":${sock##*X}"
        candidates+=("$disp")
    done

    if [[ ${#candidates[@]} -eq 0 ]]; then
        candidates=("${DISPLAY:-:0}")
    fi

    for disp in "${candidates[@]}"; do
        while IFS= read -r auth; do
            [[ -n "$auth" && -f "$auth" ]] || continue
            if env DISPLAY="$disp" XAUTHORITY="$auth" xset q >/dev/null 2>&1; then
                DISPLAY="$disp"
                XAUTHORITY="$auth"
                export DISPLAY XAUTHORITY
                return 0
            fi
        done < <(auth_candidates)
    done

    return 1
}

drm_to_xrandr_output() {
    local base="$1"
    if [[ "$base" =~ HDMI-A-([0-9]+)$ ]]; then
        echo "HDMI-${BASH_REMATCH[1]}"
    elif [[ "$base" =~ DP-([0-9]+)$ ]]; then
        echo "DP-${BASH_REMATCH[1]}"
    fi
}

xrandr_connected_output() {
    run_as_user xrandr 2>/dev/null | awk '/ connected/{print $1; exit}'
}

enable_physical_output() {
    local out port base candidate

    out="$(xrandr_connected_output)"
    if [[ -n "$out" ]]; then
        run_as_user xrandr --output "$out" --auto --primary >/dev/null 2>&1 || true
        return 0
    fi

    for port in /sys/class/drm/card*-HDMI-* /sys/class/drm/card*-DP-*; do
        [[ -f "$port/status" ]] || continue
        [[ "$(cat "$port/status")" == "connected" ]] || continue
        candidate="$(drm_to_xrandr_output "$(basename "$port")")"
        [[ -n "$candidate" ]] || continue
        if run_as_user xrandr --output "$candidate" --auto --primary >/dev/null 2>&1; then
            out="$(xrandr_connected_output)"
            [[ -n "$out" ]] && return 0
        fi
        if run_as_user xrandr --output "$candidate" --mode 1024x768 --primary >/dev/null 2>&1; then
            out="$(xrandr_connected_output)"
            [[ -n "$out" ]] && return 0
        fi
    done

    while read -r candidate; do
        [[ -n "$candidate" ]] || continue
        if run_as_user xrandr --output "$candidate" --auto --primary >/dev/null 2>&1; then
            out="$(xrandr_connected_output)"
            [[ -n "$out" ]] && return 0
        fi
    done < <(run_as_user xrandr 2>/dev/null | awk '/^(HDMI|DP)-[0-9]+ /{print $1}')

    return 1
}

display_ready() {
    local resolution width height connected

    run_as_user xset q >/dev/null 2>&1 || return 1
    enable_physical_output || true

    connected="$(xrandr_connected_output)"
    [[ -n "$connected" ]] || return 1

    resolution="$(run_as_user xrandr 2>/dev/null | awk '
        /current/ {
            for (i = 1; i <= NF; i++) {
                if ($i == "current") {
                    gsub(",", "", $(i+1))
                    gsub(",", "", $(i+3))
                    print $(i+1) "x" $(i+3)
                    exit
                }
            }
        }')"
    width="${resolution%x*}"
    height="${resolution#*x}"

    if ! [[ "$width" =~ ^[0-9]+$ && "$height" =~ ^[0-9]+$ ]]; then
        return 1
    fi
    if (( width < 640 || height < 480 )); then
        return 1
    fi

    run_as_user xhost +local:docker >/dev/null 2>&1 || true
    run_as_user xhost +SI:localuser:root >/dev/null 2>&1 || true
    return 0
}

wait_for_display() {
    local waited=0
    local last_log=-999

    log "Waiting for monitor and graphical session (no timeout)..."
    while true; do
        if discover_display; then
            if display_ready; then
                local connected resolution
                connected="$(xrandr_connected_output)"
                resolution="$(run_as_user xrandr 2>/dev/null | awk '/current/{gsub(",","",$8); print $8"x"$10; exit}')"
                log "Display ready: ${connected} ${resolution} on ${DISPLAY} (XAUTHORITY=${XAUTHORITY})."
                sleep 2
                return 0
            fi
            if (( waited - last_log >= 30 )); then
                log "X session up on ${DISPLAY}, waiting for connected monitor..."
                last_log=$waited
            fi
        elif (( waited - last_log >= 30 )); then
            log "Waiting for X session..."
            last_log=$waited
        fi
        sleep 1
        waited=$((waited + 1))
    done
}

obd_window_viewable() {
    local wid

    wid="$(run_as_user xwininfo -root -tree 2>/dev/null | awk '/"scout_display"/{print $1; exit}')"
    [[ -n "$wid" ]] || return 1
    run_as_user xwininfo -id "$wid" 2>/dev/null | grep -q 'Map State: IsViewable'
}

obd_failed_drawable() {
    docker logs obd 2>&1 | tail -20 | grep -q 'failed to create drawable'
}

start_obd() {
    export DISPLAY XAUTHORITY
    log "Starting OBD on ${DISPLAY} (XAUTHORITY=${XAUTHORITY})..."
    docker compose up -d --force-recreate --remove-orphans obd

    for attempt in $(seq 1 8); do
        sleep 4
        local status exit_code
        status="$(docker inspect obd --format '{{.State.Status}}' 2>/dev/null || echo missing)"
        exit_code="$(docker inspect obd --format '{{.State.ExitCode}}' 2>/dev/null || echo 1)"

        if [[ "$status" == "running" ]]; then
            if obd_window_viewable; then
                log "OBD container is running and window is visible."
                return 0
            fi
            if obd_failed_drawable; then
                log "OBD drawable failed; enabling display and retry $attempt/8..."
            else
                log "OBD running but window not visible; retry $attempt/8..."
            fi
            enable_physical_output || true
            sleep 2
            export DISPLAY XAUTHORITY
            docker compose up -d --force-recreate obd
            continue
        fi

        if [[ "$status" == "exited" && ( "$exit_code" == "139" || "$exit_code" == "1" ) ]]; then
            log "OBD exited ($exit_code); retry $attempt/8 after display settle..."
            enable_physical_output || true
            sleep 2
            export DISPLAY XAUTHORITY
            docker compose up -d --force-recreate obd
            continue
        fi

        log "OBD status=$status exit=$exit_code; waiting..."
    done

    log "OBD failed to stay running. Recent logs:"
    docker logs obd 2>&1 | tail -20 || true
    return 1
}

cd "$DEPLOY_DIR"
wait_for_docker

if container_running obd && discover_display && obd_window_viewable; then
    log "OBD already running with visible UI; skipping."
    exit 0
fi

if container_running obd; then
    log "OBD running without visible UI; restarting..."
    docker compose stop obd >/dev/null 2>&1 || true
fi

if wait_for_display; then
    start_obd
else
    log "Display not ready; OBD not started."
    exit 1
fi
