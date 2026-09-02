#!/usr/bin/env bash
# Colorful store-and-forward dashboard for telematics log_sync / rclone.
# Usage:
#   ./tools/log_sync_status.sh           # one snapshot
#   ./tools/log_sync_status.sh --watch   # refresh every 3s (Ctrl-C to quit)

set -euo pipefail

WATCH=0
INTERVAL=3
CONTAINER="${LOG_SYNC_CONTAINER:-telematics_server}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        -w|--watch) WATCH=1; shift ;;
        -n|--interval) INTERVAL="${2:-3}"; shift 2 ;;
        -h|--help)
            cat <<'EOF'
log_sync_status.sh — live view of vehicle log offload

  --watch, -w          Refresh until Ctrl-C
  --interval, -n SEC   Watch interval (default 3)
  env LOG_SYNC_CONTAINER  Docker name (default telematics_server)
  env LOG_SYNC_DATA       Override data directory
  env LOG_SYNC_CONF       Override log_sync.conf path
EOF
            exit 0
            ;;
        *) echo "Unknown option: $1 (try --help)" >&2; exit 1 ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DEPLOY_ROOT="$(cd "$SRC_ROOT/../telematics_obd_deployed_env" 2>/dev/null && pwd || true)"

if [[ -n "${LOG_SYNC_DATA:-}" ]]; then
    DATA="$LOG_SYNC_DATA"
elif [[ -n "$DEPLOY_ROOT" && -d "$DEPLOY_ROOT/telematics/data" ]]; then
    DATA="$DEPLOY_ROOT/telematics/data"
elif [[ -d "$SRC_ROOT/data" ]]; then
    DATA="$SRC_ROOT/data"
else
    DATA="$SRC_ROOT/data"
fi

if [[ -n "${LOG_SYNC_CONF:-}" ]]; then
    CONF="$LOG_SYNC_CONF"
elif [[ -n "$DEPLOY_ROOT" && -f "$DEPLOY_ROOT/telematics/config/log_sync.conf" ]]; then
    CONF="$DEPLOY_ROOT/telematics/config/log_sync.conf"
else
    CONF="$SRC_ROOT/config/log_sync.conf"
fi

CAN_CONF="$(dirname "$CONF")/can_log.conf"
[[ -f "$CAN_CONF" ]] || CAN_CONF="$SRC_ROOT/config/can_log.conf"

STREAMS=(can_logs motor_logs gnss_logs lband_logs ve_charger_logs)

if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
    R=$'\033[0m'
    BOLD=$'\033[1m'
    DIM=$'\033[2m'
    RED=$'\033[31m'
    GREEN=$'\033[32m'
    YELLOW=$'\033[33m'
    BLUE=$'\033[34m'
    MAGENTA=$'\033[35m'
    CYAN=$'\033[36m'
    WHITE=$'\033[97m'
    BG=$'\033[44m'
    HI_GREEN=$'\033[92m'
    HI_YELLOW=$'\033[93m'
    HI_RED=$'\033[91m'
    HI_CYAN=$'\033[96m'
else
    R= BOLD= DIM= RED= GREEN= YELLOW= BLUE= MAGENTA= CYAN= WHITE= BG=
    HI_GREEN= HI_YELLOW= HI_RED= HI_CYAN=
fi

conf_get() {
    local key="$1" file="${2:-$CONF}" def="${3:-}"
    [[ -f "$file" ]] || { printf '%s' "$def"; return; }
    local line
    line="$(grep -E "^[[:space:]]*${key}=" "$file" 2>/dev/null | tail -1 || true)"
    if [[ -z "$line" ]]; then
        printf '%s' "$def"
        return
    fi
    printf '%s' "${line#*=}" | tr -d '\r' | sed 's/[[:space:]]*$//'
}

human() {
    local b="${1:-0}"
    awk -v b="$b" 'BEGIN {
        if (b < 1024) { printf "%d B", b; exit }
        split("KB MB GB TB", u, " ")
        x = b
        i = 0
        while (x >= 1024 && i < 3) { x /= 1024; i++ }
        printf "%.1f %s", x, u[i]
    }'
}

count_cycles() {
    local root="$1"
    [[ -d "$root" ]] || { echo 0; return; }
    find "$root" -mindepth 1 -type d -name 'power_cycle_*' 2>/dev/null | wc -l | tr -d ' '
}

dir_bytes() {
    local root="$1"
    [[ -d "$root" ]] || { echo 0; return; }
    du -sb "$root" 2>/dev/null | awk '{print $1+0}'
}

bar() {
    local pct="$1" width="${2:-28}"
    local filled empty i
    if [[ "$pct" -lt 0 ]]; then pct=0; fi
    if [[ "$pct" -gt 100 ]]; then pct=100; fi
    filled=$((pct * width / 100))
    empty=$((width - filled))
    printf '%s' "${HI_GREEN}"
    for ((i = 0; i < filled; i++)); do printf '█'; done
    printf '%s' "${DIM}"
    for ((i = 0; i < empty; i++)); do printf '░'; done
    printf '%s' "$R"
}

badge() {
    local ok="$1" yes="${2:-CONNECTED}" no="${3:-DOWN}"
    if [[ "$ok" == 1 ]]; then
        printf '%s● %s%s' "$HI_GREEN$BOLD" "$yes" "$R"
    else
        printf '%s● %s%s' "$HI_RED$BOLD" "$no" "$R"
    fi
}

tcp_up() {
    local host="$1" port="$2"
    timeout 2 bash -c "echo >/dev/tcp/${host}/${port}" 2>/dev/null
}

render() {
    local host port user remote_path keep bwlimit disk_min ugv enabled remote_type
    host="$(conf_get host "$CONF" "10.10.60.250")"
    port="$(conf_get port "$CONF" 22)"
    user="$(conf_get user "$CONF" server)"
    remote_path="$(conf_get remote_path "$CONF" telematics_logs)"
    keep="$(conf_get keep_archive "$CONF" true)"
    bwlimit="$(conf_get bwlimit "$CONF" 1M)"
    disk_min="$(conf_get disk_min_free_mb "$CAN_CONF" 500)"
    enabled="$(conf_get enabled "$CONF" true)"
    remote_type="$(conf_get remote_type "$CONF" sftp)"
    ugv="$(conf_get ugv_id "$CAN_CONF" UGV_IRIS_DEFAULT_01)"

    local link=0 rclone_on=0 container_on=0
    if tcp_up "$host" "$port"; then link=1; fi
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$CONTAINER"; then
        container_on=1
        if docker exec "$CONTAINER" sh -c 'ps -eo args | grep -E "^rclone copy " | grep -v grep' >/dev/null 2>&1; then
            rclone_on=1
        fi
    fi

    local outbox="$DATA/log_sync/outbox"
    local archive="$DATA/log_sync/archive"
    local pending_n pending_b synced_n synced_b active_n active_b
    pending_n="$(count_cycles "$outbox")"
    synced_n="$(count_cycles "$archive")"
    pending_b="$(dir_bytes "$outbox")"
    synced_b="$(dir_bytes "$archive")"

    active_n=0
    active_b=0
    local s n b
    for s in "${STREAMS[@]}"; do
        n="$(count_cycles "$DATA/$s")"
        b="$(dir_bytes "$DATA/$s")"
        active_n=$((active_n + n))
        active_b=$((active_b + b))
    done

    local closed=$((pending_n + synced_n))
    local pct=0
    if [[ "$closed" -gt 0 ]]; then
        pct=$((synced_n * 100 / closed))
    fi

    local used_pct="?" free_mb="?"
    if [[ -d "$DATA" ]]; then
        used_pct="$(df -P "$DATA" 2>/dev/null | awk 'NR==2 {gsub("%","",$5); print $5}')"
        free_mb="$(df -Pm "$DATA" 2>/dev/null | awk 'NR==2 {print $4}')"
    fi

    local last_sync
    last_sync="$(docker logs --tail 400 "$CONTAINER" 2>/dev/null | grep '\[LOG_SYNC\]' | grep -v Harvested | tail -3 || true)"

    local now
    now="$(date '+%Y-%m-%d %H:%M:%S %Z')"

    printf '%s%s' "$BG$WHITE$BOLD"
    printf '  LOG SYNC  store-and-forward dashboard                                          '
    printf '%s\n' "$R"
    printf '  %s%s%s\n' "$DIM" "$now" "$R"
    printf '\n'

    printf '  %sLink%s        %s:%s   ' "$BOLD" "$R" "$host" "$port"
    badge "$link" "CONNECTED" "NOT CONNECTED"
    printf '\n'
    printf '  %sTransfer%s    rclone copy   ' "$BOLD" "$R"
    if [[ "$rclone_on" == 1 ]]; then
        printf '%s● RUNNING%s  %s(bwlimit %s)%s' "$HI_GREEN$BOLD" "$R" "$DIM" "$bwlimit" "$R"
    else
        printf '%s● IDLE%s' "$HI_YELLOW$BOLD" "$R"
    fi
    printf '\n'
    printf '  %sContainer%s   %s  ' "$BOLD" "$R" "$CONTAINER"
    badge "$container_on" "UP" "DOWN"
    printf '   %soffload=%s  keep_archive=%s%s\n' "$DIM" "$enabled" "$keep" "$R"
    printf '  %sRemote%s      %s %s@%s:%s/%s/%s/\n' \
        "$BOLD" "$R" "$remote_type" "$user" "$host" "$port" "$remote_path" "$ugv"
    printf '\n'

    printf '  %s┌──────────────┬──────────┬────────────┐%s\n' "$CYAN" "$R"
    printf '  %s│ Stage        │ Cycles   │ Size       │%s\n' "$CYAN" "$R"
    printf '  %s├──────────────┼──────────┼────────────┤%s\n' "$CYAN" "$R"
    printf '  │ %sACTIVE%s       │ %s%8s%s │ %s%10s%s │  %slive session — not uploaded until cycle closes%s\n' \
        "$MAGENTA$BOLD" "$R" "$MAGENTA$BOLD" "$active_n" "$R" "$MAGENTA" "$(human "$active_b")" "$R" "$DIM" "$R"
    printf '  │ %sOUTBOX%s       │ %s%8s%s │ %s%10s%s │  %swaiting / in-flight%s\n' \
        "$HI_YELLOW$BOLD" "$R" "$HI_YELLOW$BOLD" "$pending_n" "$R" "$HI_YELLOW" "$(human "$pending_b")" "$R" "$DIM" "$R"
    printf '  │ %sARCHIVE%s      │ %s%8s%s │ %s%10s%s │  %ssynced, kept locally%s\n' \
        "$HI_GREEN$BOLD" "$R" "$HI_GREEN$BOLD" "$synced_n" "$R" "$HI_GREEN" "$(human "$synced_b")" "$R" "$DIM" "$R"
    printf '  %s└──────────────┴──────────┴────────────┘%s\n' "$CYAN" "$R"
    printf '\n'

    printf '  %sProgress%s  ' "$BOLD" "$R"
    bar "$pct" 30
    printf '  %s%s%%%s  %s%d synced / %d closed%s\n' \
        "$BOLD" "$pct" "$R" "$DIM" "$synced_n" "$closed" "$R"
    if [[ "$pending_n" -gt 0 && "$rclone_on" == 1 ]]; then
        printf "  %s           copying oldest closed cycle → %s (checksum + ACK)%s\n" "$DIM" "$host" "$R"
    elif [[ "$rclone_on" == 1 ]]; then
        printf "  %s           rclone copy in progress → %s%s\n" "$DIM" "$host" "$R"
    elif [[ "$pending_n" -gt 0 && "$link" == 0 ]]; then
        printf '  %s           %soutbox parked — endpoint not reachable%s\n' "$DIM" "$HI_RED" "$R"
    elif [[ "$pending_n" -gt 0 ]]; then
        printf '  %s           outbox queued — rclone idle (next poll ~30s)%s\n' "$DIM" "$R"
    elif [[ "$closed" -eq 0 && "$active_n" -gt 0 ]]; then
        printf '  %s           live cycle open — upload starts after vehicle restart%s\n' "$DIM" "$R"
    else
        printf '  %s           outbox empty — all closed cycles ACKed%s\n' "$DIM" "$R"
    fi
    printf '\n'

    printf '  %sPer stream%s\n' "$BOLD" "$R"
    printf '  %s%-18s %8s %8s %8s%s\n' "$DIM" "STREAM" "ACTIVE" "OUTBOX" "ARCHIVE" "$R"
    local a o ar
    for s in "${STREAMS[@]}"; do
        a="$(count_cycles "$DATA/$s")"
        o="$(count_cycles "$outbox/$s")"
        ar="$(count_cycles "$archive/$s")"
        printf '  %-18s %s%8s%s %s%8s%s %s%8s%s\n' \
            "$s" "$MAGENTA" "$a" "$R" "$HI_YELLOW" "$o" "$R" "$HI_GREEN" "$ar" "$R"
    done
    printf '\n'

    printf '  %sDisk%s        data fs %s%% used  %s MB free  (delete oldest cycle if ≤ %s MB)  keep_archive=%s\n' \
        "$BOLD" "$R" "${used_pct:-?}" "${free_mb:-?}" "$disk_min" "$keep"
    if [[ "$free_mb" != "?" && "$free_mb" -le "$disk_min" ]]; then
        printf '  %s            WARNING: free ≤ %s MB — oldest power_cycle_* may be deleted%s\n' \
            "$HI_RED$BOLD" "$disk_min" "$R"
    fi
    printf '  %sData%s        %s\n' "$BOLD" "$R" "$DATA"
    printf '  %sConf%s        %s\n' "$BOLD" "$R" "$CONF"
    printf '\n'

    printf '  %sLegend%s      %sACTIVE%s write-now, not uploaded   %sOUTBOX%s closed, not ACKed   %sARCHIVE%s transferred / ACKed\n' \
        "$BOLD" "$R" "$MAGENTA" "$R" "$HI_YELLOW" "$R" "$HI_GREEN" "$R"
    printf '  %sAfter ACK%s   closed cycle only: keep_archive=true → archive;  false → delete. Active stays in data/\n' \
        "$BOLD" "$R"
    printf '  %sPC path%s     ~/%s/%s/<stream>/power_cycle_*\n' "$BOLD" "$R" "$remote_path" "$ugv"

    if [[ -n "$last_sync" ]]; then
        printf '\n  %sRecent [LOG_SYNC]%s\n' "$BOLD" "$R"
        while IFS= read -r line; do
            [[ -z "$line" ]] && continue
            if [[ "$line" == *"failed"* || "$line" == *"not reachable"* ]]; then
                printf '  %s%s%s\n' "$HI_RED" "$line" "$R"
            elif [[ "$line" == *"ACK"* || "$line" == *"completed"* ]]; then
                printf '  %s%s%s\n' "$HI_GREEN" "$line" "$R"
            else
                printf '  %s%s%s\n' "$DIM" "$line" "$R"
            fi
        done <<<"$last_sync"
    fi

    if [[ "$WATCH" == 1 ]]; then
        printf '\n  %s--watch every %ss — Ctrl-C to quit%s\n' "$DIM" "$INTERVAL" "$R"
    fi
}

if [[ "$WATCH" == 1 ]]; then
    while true; do
        printf '\033[2J\033[H'
        render || true
        sleep "$INTERVAL"
    done
else
    render
fi
