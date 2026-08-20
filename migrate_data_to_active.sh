#!/usr/bin/env bash
# Move live log streams under data/active/; leave data/log_sync/ untouched.
# Root-owned dirs from Docker: run via
#   docker run --rm -v "$(pwd)/telematics/data:/data" alpine:3.20 sh /migrate.sh
# or stop the container first and use sudo locally.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DATA="${1:-$SCRIPT_DIR/telematics/data}"

if [[ ! -d "$DATA" ]]; then
    echo "Usage: $0 [path/to/telematics/data]" >&2
    exit 1
fi

ACTIVE="$DATA/active"
STREAMS=(can_logs motor_logs gnss_logs lband_logs ve_charger_logs)

mkdir -p "$ACTIVE"

for stream in "${STREAMS[@]}"; do
    src="$DATA/$stream"
    dest="$ACTIVE/$stream"
    [[ -d "$src" ]] || continue

    if [[ -d "$dest" ]]; then
        echo "Merge $src -> $dest"
        shopt -s dotglob nullglob
        for item in "$src"/*; do
            base="$(basename "$item")"
            if [[ -e "$dest/$base" ]]; then
                echo "  skip (exists): $dest/$base"
            else
                mv "$item" "$dest/"
                echo "  moved: $base"
            fi
        done
        rmdir "$src" 2>/dev/null || rm -rf "$src"
    else
        mv "$src" "$dest"
        echo "Moved $src -> $dest"
    fi
done

echo "Done. Layout:"
echo "  $ACTIVE/          live power_cycle_*"
echo "  $DATA/log_sync/   outbox + archive"
ls -la "$DATA"
