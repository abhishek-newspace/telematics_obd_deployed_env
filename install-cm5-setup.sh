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

# --- CM5 CAN persistent names (.link) ----------------------------------------
install_file "${UDEV_DIR}/10-telematics-can-control-cm5.link" \
    /etc/systemd/network/10-telematics-can-control-cm5.link
install_file "${UDEV_DIR}/10-telematics-can-auxiliary-cm5.link" \
    /etc/systemd/network/10-telematics-can-auxiliary-cm5.link
install_file "${UDEV_DIR}/10-telematics-eth-cm5.link" \
    /etc/systemd/network/10-telematics-eth-cm5.link

# Disable Dynalog-specific links if present
rm -f /etc/systemd/network/10-telematics-can-control.link
rm -f /etc/systemd/network/10-telematics-can-auxiliary.link
rm -f /etc/systemd/network/10-telematics-eth.link

# --- udev rules --------------------------------------------------------------
install_file "${UDEV_DIR}/99-telematics-can-cm5.rules" /etc/udev/rules.d/99-telematics-can-cm5.rules
rm -f /etc/udev/rules.d/99-telematics-can.rules

if [[ -f "${UDEV_DIR}/99-telematics-usb-serial.rules" ]]; then
    install_file "${UDEV_DIR}/99-telematics-usb-serial.rules" \
        /etc/udev/rules.d/99-telematics-usb-serial.rules
fi
if [[ -f "${UDEV_DIR}/99-telematics-mm-ignore.rules" ]]; then
    install_file "${UDEV_DIR}/99-telematics-mm-ignore.rules" \
        /etc/udev/rules.d/99-telematics-mm-ignore.rules
fi

install_exec "${UDEV_DIR}/telematics-can-rename.sh" /usr/local/sbin/telematics-can-rename.sh
install_exec "${UDEV_DIR}/cm5-can-up.sh" /usr/local/sbin/cm5-can-up.sh

install_file "${UDEV_DIR}/telematics-can-names-cm5.service" \
    /etc/systemd/system/telematics-can-names-cm5.service
systemctl disable telematics-can-names.service 2>/dev/null || true

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
echo "=== /dev/telematics ==="
ls -la /dev/telematics/ 2>/dev/null || echo "  (none yet — plug USB-CAN CH340 for can_actuator)"

echo
echo "=== Ethernet (expected: telematics_eth) ==="
if [[ -e /sys/class/net/telematics_eth ]]; then
    echo "OK: telematics_eth $(ip -br addr show telematics_eth 2>/dev/null)"
elif [[ -e /sys/class/net/eth0 ]]; then
    echo "PENDING: eth0 present — reboot once for telematics_eth rename"
else
    echo "MISSING: no eth0"
fi

echo
echo "=== Prerequisites still needed ==="
command -v docker >/dev/null && echo "OK: Docker installed" || echo "TODO: Install Docker (not done by this script)"
[[ -d "${SCRIPT_DIR}/../telematics_src" ]] && echo "OK: telematics_src found" || \
    echo "TODO: Clone telematics_src next to deploy folder (../telematics_src)"

echo
echo "=== CAN port names (same as Dynalog) ==="
echo "  can_control    ← onboard CAN-0 (MCP2518FD / reComputer-R21)"
echo "  can_auxiliary  ← onboard CAN-1 (MCP2518FD / reComputer-R21)"
echo "  can_actuator   ← USB CH340 → /dev/telematics/can_actuator"
echo
echo "can_log.conf already uses these names. Reboot recommended."
