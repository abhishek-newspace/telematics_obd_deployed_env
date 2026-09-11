#!/bin/bash
# CM5 migration installer — CAN naming, udev, autostart paths for Raspberry Pi CM5
# Does NOT install Docker or packages (user permission required).
#
# Run once:
#   cd ~/Desktop/telematics_obd_deployed_env
#   sudo ./install-cm5-setup.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UDEV_DIR="${SCRIPT_DIR}/udev"
USER_NAME="${SUDO_USER:-${USER:-pi}}"

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    echo "Run as root: sudo $0"
    exit 1
fi

install_file() {
    local src="$1" dst="$2"
    [[ -f "$src" ]] || { echo "Missing: $src"; exit 1; }
    echo "Installing $dst"
    install -D -m 644 "$src" "$dst"
}

install_exec() {
    local src="$1" dst="$2"
    echo "Installing $dst"
    install -D -m 755 "$src" "$dst"
}

echo "=== CM5 Telematics Migration Setup ==="
echo "Deploy dir: ${SCRIPT_DIR}"
echo "User:       ${USER_NAME}"
echo

# --- CM5 required .link + udev only (see udev/README.md) ----------------------
bash "${UDEV_DIR}/sync-cm5-udev.sh"

# --- dialout for serial CAN / motor UART -------------------------------------
usermod -aG dialout "$USER_NAME" 2>/dev/null || true

# --- brltty can steal CH340 ttyUSB --------------------------------------------
if systemctl list-unit-files brltty-udev.service &>/dev/null; then
    systemctl stop brltty-udev.service 2>/dev/null || true
    systemctl mask brltty.service brltty-udev.service 2>/dev/null || true
fi

echo "Reloading udev + systemd..."
udevadm control --reload-rules
systemctl daemon-reload
systemctl enable telematics-can-names-cm5.service

udevadm trigger --subsystem-match=tty --action=add
udevadm trigger --subsystem-match=net --action=add
sleep 2

systemctl restart telematics-can-names-cm5.service 2>/dev/null || \
    /usr/local/sbin/cm5-can-up.sh || true

# --- Autostart (telematics + OBD) --------------------------------------------
echo
echo "=== Installing autostart services ==="
bash "${SCRIPT_DIR}/install-autostart.sh"

# --- Status -------------------------------------------------------------------
echo
echo "=== SocketCAN (expected: can_control + can_auxiliary) ==="
for iface in can_control can_auxiliary; do
    if [[ -e "/sys/class/net/${iface}" ]]; then
        echo "OK: ${iface} — $(ip -details link show "${iface}" 2>/dev/null | grep -oE 'state [A-Z-]+|bitrate [0-9]+' | tr '\n' ' ')"
    else
        echo "MISSING: ${iface} — install Seeed reComputer-R21 overlay (see ~/Desktop/RECOMPUTER_INDUSTRIAL_SETUP.md)"
    fi
done

echo
echo "=== /dev/telematics (expected: can_actuator, motor_front, motor_rear) ==="
ls -la /dev/telematics/ 2>/dev/null || echo "  (none yet — check CH340 USB cables)"
for link in can_actuator motor_front motor_rear; do
    if [[ -e "/dev/telematics/${link}" ]]; then
        echo "OK: ${link} → $(readlink -f "/dev/telematics/${link}")"
    else
        echo "MISSING: ${link}"
    fi
done

echo
echo "=== Ethernet (expected: telematics_eth + eth1) ==="
if [[ -e /sys/class/net/telematics_eth ]]; then
    echo "OK: telematics_eth $(ip -br addr show telematics_eth 2>/dev/null)"
else
    echo "PENDING: telematics_eth — reboot once for .link rename"
fi
if [[ -e /sys/class/net/eth1 ]]; then
    echo "OK: eth1 $(ip -br addr show eth1 2>/dev/null)"
elif [[ -e /sys/class/net/eth0 ]]; then
    echo "NOTE: eth0 still present — reboot applies eth1 onboard rename"
fi

echo
echo "=== Prerequisites still needed ==="
command -v docker >/dev/null && echo "OK: Docker installed" || echo "TODO: Install Docker (not done by this script)"
[[ -d "${SCRIPT_DIR}/../telematics_src" ]] && echo "OK: telematics_src found" || \
    echo "TODO: Clone telematics_src next to deploy folder (../telematics_src)"

echo
echo "=== CAN port names (same as Dynalog) ==="
echo "  can_auxiliary  ← MCP2518FD SPI CS1 (physical AUX silkscreen)"
echo "  can_control    ← MCP2518FD SPI CS0 (physical CONTROL silkscreen)"
echo "  can_actuator   ← USB CH340 → /dev/telematics/can_actuator"
echo
echo "can_log.conf already uses these names. Reboot recommended."
