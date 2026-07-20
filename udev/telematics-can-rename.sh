#!/bin/sh
# Fallback rename if systemd .link did not apply (e.g. late emucd create).
# Called from udev RUN+= on EMUC net add. Idempotent.

set -eu

SRC="${1:-}"
DST="${2:-}"

[ -n "$SRC" ] && [ -n "$DST" ] || exit 0

# Already renamed
if [ -e "/sys/class/net/${DST}" ]; then
    exit 0
fi

# Source gone
if [ ! -e "/sys/class/net/${SRC}" ]; then
    exit 0
fi

ip link set dev "$SRC" down 2>/dev/null || true
ip link set dev "$SRC" name "$DST" 2>/dev/null || true
ip link set dev "$DST" up 2>/dev/null || true
ip link set dev "$DST" txqueuelen 1000 2>/dev/null || true

exit 0
