#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UDEV_DIR="${SCRIPT_DIR}/udev"

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    echo "Run as root: sudo $0"
    exit 1
fi

install_rule() {
    local src="$1"
    local dst="/etc/udev/rules.d/$(basename "$src")"
    if [[ ! -f "$src" ]]; then
        echo "Missing: $src"
        exit 1
    fi
    echo "Installing $dst"
    cp "$src" "$dst"
    chmod 644 "$dst"
}

install_rule "${UDEV_DIR}/99-telematics-usb-serial.rules"
install_rule "${UDEV_DIR}/99-telematics-mm-ignore.rules"

echo "Reloading udev..."
udevadm control --reload-rules
udevadm trigger --subsystem-match=tty --action=add

sleep 1
echo
echo "=== /dev/telematics ==="
ls -la /dev/telematics/ 2>/dev/null || echo "  (none — check USB cables on hub ports 1–3)"

echo
echo "=== Expected config paths ==="
echo "  can_log.conf:   can0_device=/dev/telematics/can0          (hub 1-2.2)"
echo "  motor_log.conf: front_serial=/dev/telematics/motor_front  (hub 1-2.3)"
echo "  motor_log.conf: rear_serial=/dev/telematics/motor_rear    (hub 1-2.1)"
echo "  can_log.conf:   sec_comp_interface_health_ethernet_interface=enP8p1s0"

for link in /dev/telematics/can0 /dev/telematics/motor_front /dev/telematics/motor_rear; do
    if [[ -L "$link" ]]; then
        echo "OK: $link -> $(readlink -f "$link")"
    else
        echo "MISSING: $link"
    fi
done

if ip link show enP8p1s0 >/dev/null 2>&1; then
    echo "OK: enP8p1s0 present ($(ip -br addr show enP8p1s0 | awk '{print $3}'))"
else
    echo "WARN: enP8p1s0 not found — check ethernet cable / PCI NIC"
fi
