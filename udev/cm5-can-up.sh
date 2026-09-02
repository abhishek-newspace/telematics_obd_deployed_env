#!/bin/sh
# Bring up CM5 CAN interfaces at 500 kbit/s (matches can_log.conf log_can_bitrate)
# Idempotent — safe to run from systemd on every boot.

set -eu

BITRATE=500000
TXQLEN=1000

bring_up() {
    iface="$1"
    [ -e "/sys/class/net/${iface}" ] || return 0
    ip link set "$iface" down 2>/dev/null || true
    ip link set "$iface" type can bitrate "$BITRATE" restart-ms 100 2>/dev/null || true
    ip link set "$iface" txqueuelen "$TXQLEN" 2>/dev/null || true
    ip link set "$iface" up 2>/dev/null || true
}

# Rename fallbacks (if systemd .link not applied yet)
/usr/local/sbin/telematics-can-rename.sh can0 can_control 2>/dev/null || true
/usr/local/sbin/telematics-can-rename.sh can1 can_auxiliary 2>/dev/null || true
/usr/local/sbin/telematics-can-rename.sh comp_can can_control 2>/dev/null || true

bring_up can_control
bring_up can_auxiliary

exit 0
