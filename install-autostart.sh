#!/bin/bash
set -euo pipefail

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USER_NAME="${SUDO_USER:-${USER:-testing}}"
USER_UID="$(id -u "$USER_NAME")"
USER_HOME="$(getent passwd "$USER_NAME" | cut -d: -f6)"
USER_SYSTEMD_DIR="${USER_HOME}/.config/systemd/user"
COMPOSE_PLUGIN_SRC="${USER_HOME}/.docker/cli-plugins/docker-compose"
COMPOSE_PLUGIN_DST="/usr/local/lib/docker/cli-plugins/docker-compose"

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    echo "Run as root: sudo $0"
    exit 1
fi

echo "Installing docker compose plugin for root systemd..."
install -d /usr/local/lib/docker/cli-plugins
if [[ -f "$COMPOSE_PLUGIN_SRC" ]]; then
    cp "$COMPOSE_PLUGIN_SRC" "$COMPOSE_PLUGIN_DST"
    chmod 755 "$COMPOSE_PLUGIN_DST"
else
    echo "WARN: compose plugin not found at ${COMPOSE_PLUGIN_SRC}"
fi

echo "Installing telematics system service..."
cp "${DEPLOY_DIR}/telematics/telematics.service" /etc/systemd/system/telematics.service
chmod 644 /etc/systemd/system/telematics.service

echo "Installing OBD user service..."
install -d -o "$USER_NAME" -g "$USER_NAME" "$USER_SYSTEMD_DIR"
cp "${DEPLOY_DIR}/obd/obd-apps.service" "${USER_SYSTEMD_DIR}/obd-apps.service"
chown "$USER_NAME:$USER_NAME" "${USER_SYSTEMD_DIR}/obd-apps.service"
chmod 644 "${USER_SYSTEMD_DIR}/obd-apps.service"

loginctl enable-linger "$USER_NAME" 2>/dev/null || true

systemctl daemon-reload
systemctl enable telematics.service

sudo -u "$USER_NAME" \
    XDG_RUNTIME_DIR="/run/user/${USER_UID}" \
    DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/${USER_UID}/bus" \
    systemctl --user daemon-reload
sudo -u "$USER_NAME" \
    XDG_RUNTIME_DIR="/run/user/${USER_UID}" \
    DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/${USER_UID}/bus" \
    systemctl --user enable obd-apps.service
rm -f "${USER_SYSTEMD_DIR}/default.target.wants/obd-apps.service"
sudo -u "$USER_NAME" \
    XDG_RUNTIME_DIR="/run/user/${USER_UID}" \
    DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/${USER_UID}/bus" \
    systemctl --user reset-failed obd-apps.service 2>/dev/null || true

echo "Installed and enabled:"
echo "  telematics.service"
echo "  obd-apps.service"
