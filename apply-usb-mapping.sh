#!/bin/bash
# Apply reComputer USB mapping for can_actuator + motor_front + motor_rear.
# Run: sudo ./apply-usb-mapping.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "Run as root: sudo $0"
  exit 1
fi

install -D -m 644 "$ROOT/udev/99-telematics-can-cm5.rules" \
  /etc/udev/rules.d/99-telematics-can-cm5.rules
install -D -m 644 "$ROOT/udev/99-telematics-usb-serial-cm5.rules" \
  /etc/udev/rules.d/99-telematics-usb-serial-cm5.rules
rm -f /etc/udev/rules.d/99-telematics-usb-serial.rules
rm -f /etc/udev/rules.d/99-telematics-can.rules

udevadm control --reload-rules
udevadm trigger --subsystem-match=tty --action=add
sleep 2

echo "=== /dev/telematics ==="
ls -la /dev/telematics/ || true
for link in can_actuator motor_front motor_rear; do
  if [[ -e "/dev/telematics/$link" ]]; then
    real="$(readlink -f "/dev/telematics/$link")"
    path="$(udevadm info -q property -n "/dev/telematics/$link" | awk -F= '/^ID_PATH=/{print $2}')"
    echo "OK  $link -> $real  (ID_PATH=$path)"
  else
    echo "MISSING  $link"
  fi
done

echo
echo "Restart telematics to pick up devices:"
echo "  cd $ROOT && docker compose restart telemetry_server"
