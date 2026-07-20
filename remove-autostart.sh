#!/bin/bash
set -euo pipefail

USER_NAME="${SUDO_USER:-${USER:-testing}}"
USER_UID="$(id -u "$USER_NAME")"
USER_HOME="$(getent passwd "$USER_NAME" | cut -d: -f6)"
USER_SYSTEMD_DIR="${USER_HOME}/.config/systemd/user"

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    echo "Run as root: sudo $0"
    exit 1
fi

systemctl stop telematics.service 2>/dev/null || true
systemctl disable telematics.service 2>/dev/null || true
rm -f /etc/systemd/system/telematics.service
rm -f /etc/systemd/system/multi-user.target.wants/telematics.service
systemctl daemon-reload
systemctl reset-failed

sudo -u "$USER_NAME" \
    XDG_RUNTIME_DIR="/run/user/${USER_UID}" \
    DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/${USER_UID}/bus" \
    systemctl --user stop obd-apps.service 2>/dev/null || true
sudo -u "$USER_NAME" \
    XDG_RUNTIME_DIR="/run/user/${USER_UID}" \
    DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/${USER_UID}/bus" \
    systemctl --user disable obd-apps.service 2>/dev/null || true

rm -f "${USER_SYSTEMD_DIR}/obd-apps.service"

sudo -u "$USER_NAME" \
    XDG_RUNTIME_DIR="/run/user/${USER_UID}" \
    DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/${USER_UID}/bus" \
    systemctl --user daemon-reload 2>/dev/null || true
sudo -u "$USER_NAME" \
    XDG_RUNTIME_DIR="/run/user/${USER_UID}" \
    DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/${USER_UID}/bus" \
    systemctl --user reset-failed 2>/dev/null || true

echo "Stopped, disabled, and removed:"
echo "  telematics.service"
echo "  obd-apps.service"
