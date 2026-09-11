#!/bin/bash
# Install ONLY the CM5-required udev/.link files; remove obsolete telematics ones.
set -euo pipefail

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "Run: sudo $0"
  exit 1
fi

UDEV_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

install_file() {
  install -D -m 644 "$1" "$2"
  echo "OK  $2"
}

install_exec() {
  install -D -m 755 "$1" "$2"
  echo "OK  $2"
}

echo "=== Install required CM5 rules ==="
# Ethernet rename (.link — not udev)
install_file "${UDEV_DIR}/10-telematics-eth-cm5.link" /etc/systemd/network/10-telematics-eth-cm5.link
install_file "${UDEV_DIR}/10-eth1-cm5-onboard.link" /etc/systemd/network/10-eth1-cm5-onboard.link
# CAN rename (.link)
install_file "${UDEV_DIR}/10-telematics-can-control-cm5.link" /etc/systemd/network/10-telematics-can-control-cm5.link
install_file "${UDEV_DIR}/10-telematics-can-auxiliary-cm5.link" /etc/systemd/network/10-telematics-can-auxiliary-cm5.link
# Single combined udev rules file
install_file "${UDEV_DIR}/99-telematics-cm5.rules" /etc/udev/rules.d/99-telematics-cm5.rules
# helpers
install_exec "${UDEV_DIR}/telematics-can-rename.sh" /usr/local/sbin/telematics-can-rename.sh
install_exec "${UDEV_DIR}/cm5-can-up.sh" /usr/local/sbin/cm5-can-up.sh
install_file "${UDEV_DIR}/telematics-can-names-cm5.service" /etc/systemd/system/telematics-can-names-cm5.service

echo
echo "=== Remove obsolete telematics rules (if present) ==="
rm -fv \
  /etc/systemd/network/10-telematics-eth.link \
  /etc/systemd/network/10-telematics-can-control.link \
  /etc/systemd/network/10-telematics-can-auxiliary.link \
  /etc/systemd/network/10-eth0-cm5-usb.link \
  /etc/udev/rules.d/99-telematics-can.rules \
  /etc/udev/rules.d/99-telematics-can-cm5.rules \
  /etc/udev/rules.d/99-telematics-usb-serial.rules \
  /etc/udev/rules.d/99-telematics-usb-serial-cm5.rules \
  /etc/udev/rules.d/99-telematics-mm-ignore.rules \
  /etc/systemd/system/telematics-can-names.service

systemctl disable telematics-can-names.service 2>/dev/null || true
systemctl enable telematics-can-names-cm5.service

echo
echo "=== Reload ==="
udevadm control --reload-rules
systemctl daemon-reload
udevadm trigger --subsystem-match=tty --action=add || true
udevadm trigger --subsystem-match=net --action=add || true

echo
echo "Kept .link files:"
ls -1 /etc/systemd/network/10-telematics-*.link /etc/systemd/network/10-eth1-*.link 2>/dev/null || true
echo
echo "Kept udev rules (telematics):"
ls -1 /etc/udev/rules.d/99-telematics*.rules 2>/dev/null || true
echo
echo "Done. Reboot if ethernet names must refresh: sudo reboot"
