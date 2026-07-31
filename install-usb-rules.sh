#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UDEV_DIR="${SCRIPT_DIR}/udev"

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    echo "Run as root: sudo $0"
    exit 1
fi

install_file() {
    local src="$1"
    local dst="$2"
    if [[ ! -f "$src" ]]; then
        echo "Missing: $src"
        exit 1
    fi
    echo "Installing $dst"
    install -D -m 644 "$src" "$dst"
}

install_exec() {
    local src="$1"
    local dst="$2"
    echo "Installing $dst"
    install -D -m 755 "$src" "$dst"
}

# --- Persistent CAN name map (systemd .link) --------------------------------
install_file "${UDEV_DIR}/10-telematics-can-control.link" \
    /etc/systemd/network/10-telematics-can-control.link
install_file "${UDEV_DIR}/10-telematics-can-auxiliary.link" \
    /etc/systemd/network/10-telematics-can-auxiliary.link
rm -f /etc/systemd/network/10-telematics-can-actuator.link

# --- Persistent Ethernet name for hub NIC (GNSS / L-band) -------------------
if [[ -f "${UDEV_DIR}/10-telematics-eth.link" ]]; then
    install_file "${UDEV_DIR}/10-telematics-eth.link" \
        /etc/systemd/network/10-telematics-eth.link
fi

# --- udev rules + rename helper --------------------------------------------
install_file "${UDEV_DIR}/99-telematics-can.rules" /etc/udev/rules.d/99-telematics-can.rules
if [[ -f "${UDEV_DIR}/99-telematics-usb-serial.rules" ]]; then
    install_file "${UDEV_DIR}/99-telematics-usb-serial.rules" /etc/udev/rules.d/99-telematics-usb-serial.rules
fi
if [[ -f "${UDEV_DIR}/99-telematics-mm-ignore.rules" ]]; then
    install_file "${UDEV_DIR}/99-telematics-mm-ignore.rules" /etc/udev/rules.d/99-telematics-mm-ignore.rules
fi
install_exec "${UDEV_DIR}/telematics-can-rename.sh" /usr/local/sbin/telematics-can-rename.sh

install_file "${UDEV_DIR}/telematics-can-names.service" \
    /etc/systemd/system/telematics-can-names.service

# EMUC: control (ch1) + auxiliary (ch2). USB is actuator.
if [[ -f /etc/init.d/run_emucd ]]; then
    if [[ ! -f /etc/init.d/run_emucd.telematics.bak ]]; then
        cp -a /etc/init.d/run_emucd /etc/init.d/run_emucd.telematics.bak
        echo "Backed up /etc/init.d/run_emucd → run_emucd.telematics.bak"
    fi
    sed -i \
        -e 's/^socket_name_1=.*/socket_name_1=can_control/' \
        -e 's/^socket_name_2=.*/socket_name_2=can_auxiliary/' \
        /etc/init.d/run_emucd
    echo "Updated EMUC socket names → can_control / can_auxiliary"
fi

if systemctl list-unit-files brltty-udev.service &>/dev/null; then
    systemctl stop brltty-udev.service 2>/dev/null || true
    systemctl mask brltty.service brltty-udev.service 2>/dev/null || true
fi

echo "Reloading udev + systemd..."
udevadm control --reload-rules
systemctl daemon-reload
systemctl enable telematics-can-names.service

echo "Restarting EMUC..."
systemctl restart run_emucd.service 2>/dev/null || /etc/init.d/run_emucd start || true
sleep 2
systemctl restart telematics-can-names.service 2>/dev/null || true
/usr/local/sbin/telematics-can-rename.sh comp_can can_control || true
/usr/local/sbin/telematics-can-rename.sh can_actuator can_control || true
/usr/local/sbin/telematics-can-rename.sh can1 can_auxiliary || true
ip link set can_control up 2>/dev/null || true
ip link set can_auxiliary up 2>/dev/null || true

udevadm trigger --subsystem-match=tty --action=add
udevadm trigger --subsystem-match=net --action=add

# Drop stale USB symlinks
rm -f /dev/telematics/can0 /dev/telematics/can_control

sleep 1
echo
echo "=== SocketCAN (expected: can_control + can_auxiliary) ==="
for iface in can_control can_auxiliary; do
    if [[ -e "/sys/class/net/${iface}" ]]; then
        echo "OK: ${iface} ($(ip -br link show "${iface}" | awk '{print $2}'))"
    else
        echo "MISSING: ${iface}"
    fi
done

echo
echo "=== /dev/telematics (USB actuator + motor UARTs) ==="
ls -la /dev/telematics/ 2>/dev/null || echo "  (none yet — CAN actuator, front Port 3 / ttyUSB1, rear Port 5 / ttyUSB2)"

echo
echo "=== Ethernet hub (expected: telematics_eth) ==="
if [[ -e /sys/class/net/telematics_eth ]]; then
    echo "OK: telematics_eth ($(ip -br link show telematics_eth | awk '{print $2}')) MAC=$(cat /sys/class/net/telematics_eth/address)"
elif [[ -e /sys/class/net/enp2s0 ]]; then
    echo "PENDING rename: enp2s0 still present — reboot once, or:"
    echo "  sudo ip link set enp2s0 down"
    echo "  sudo ip link set enp2s0 name telematics_eth"
    echo "  sudo ip link set telematics_eth up"
    echo "  sudo nmcli connection modify \"Wired connection 2\" connection.interface-name telematics_eth"
    echo "  sudo nmcli connection up \"Wired connection 2\""
else
    echo "MISSING: telematics_eth / enp2s0"
fi

echo
echo "=== can_log.conf should use ==="
echo "  can0_device=can_auxiliary"
echo "  can1_device=/dev/telematics/can_actuator"
echo "  can2_device=can_control"
echo "  sec_comp_interface_health_ethernet_interface=telematics_eth"
echo
echo "=== motor_log.conf should use ==="
echo "  front_serial=/dev/telematics/motor_front   # Prolific ENBDb2A6709 (Port 3 / ttyUSB1)"
echo "  rear_serial=/dev/telematics/motor_rear     # Prolific DFBOo151406 (Port 5 / ttyUSB2)"
echo "  can1_device=/dev/telematics/can_actuator   # CH340 Port 6 / ttyUSB0"
echo
echo "Then: docker restart telematics_server"
