#!/bin/bash
set -euo pipefail

USER_NAME="${SUDO_USER:-${USER:-pi}}"
USER_UID="$(id -u "$USER_NAME")"
USER_HOME="$(getent passwd "$USER_NAME" | cut -d: -f6)"
USER_SYSTEMD_DIR="${USER_HOME}/.config/systemd/user"

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    echo "Run as root: sudo $0"
    exit 1
fi

systemctl disable --now telematics.service 2>/dev/null || true
systemctl disable --now obd-apps.service 2>/dev/null || true
rm -f /etc/systemd/system/telematics.service
rm -f /etc/systemd/system/obd-apps.service

sudo -u "$USER_NAME" \
    XDG_RUNTIME_DIR="/run/user/${USER_UID}" \
    DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/${USER_UID}/bus" \
    systemctl --user disable --now obd-apps.service 2>/dev/null || true
rm -f "${USER_SYSTEMD_DIR}/obd-apps.service"
rm -f "${USER_SYSTEMD_DIR}/graphical-session.target.wants/obd-apps.service"
rm -f "${USER_SYSTEMD_DIR}/default.target.wants/obd-apps.service"

systemctl daemon-reload
sudo -u "$USER_NAME" \
    XDG_RUNTIME_DIR="/run/user/${USER_UID}" \
    DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/${USER_UID}/bus" \
    systemctl --user daemon-reload 2>/dev/null || true

echo "Removed:"
echo "  telematics.service"
echo "  obd-apps.service"
