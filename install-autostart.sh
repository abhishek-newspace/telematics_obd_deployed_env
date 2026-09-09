#!/bin/bash
# Install systemd units so telematics + OBD start on boot.
#   sudo ./install-autostart.sh
set -euo pipefail

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USER_NAME="${SUDO_USER:-${USER:-pi}}"
USER_UID="$(id -u "$USER_NAME")"
USER_HOME="$(getent passwd "$USER_NAME" | cut -d: -f6)"
USER_SYSTEMD_DIR="${USER_HOME}/.config/systemd/user"
COMPOSE_PLUGIN_SRC="${USER_HOME}/.docker/cli-plugins/docker-compose"
COMPOSE_PLUGIN_DST="/usr/local/lib/docker/cli-plugins/docker-compose"

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    echo "Run as root: sudo $0"
    exit 1
fi

echo "Installing docker compose plugin for systemd..."
install -d /usr/local/lib/docker/cli-plugins
if [[ -f "$COMPOSE_PLUGIN_SRC" ]]; then
    cp "$COMPOSE_PLUGIN_SRC" "$COMPOSE_PLUGIN_DST"
    chmod 755 "$COMPOSE_PLUGIN_DST"
else
    echo "WARN: compose plugin not found at ${COMPOSE_PLUGIN_SRC}"
fi

echo "Installing telematics.service (system)..."
install -D -m 644 "${DEPLOY_DIR}/telematics/telematics.service" \
    /etc/systemd/system/telematics.service

echo "Installing obd-apps.service (system — graphical.target)..."
install -D -m 644 "${DEPLOY_DIR}/obd/obd-apps.service" \
    /etc/systemd/system/obd-apps.service

# Disable legacy user-unit copy so we don't double-start OBD.
if [[ -f "${USER_SYSTEMD_DIR}/obd-apps.service" ]]; then
    sudo -u "$USER_NAME" \
        XDG_RUNTIME_DIR="/run/user/${USER_UID}" \
        DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/${USER_UID}/bus" \
        systemctl --user disable --now obd-apps.service 2>/dev/null || true
    rm -f "${USER_SYSTEMD_DIR}/obd-apps.service"
    rm -f "${USER_SYSTEMD_DIR}/graphical-session.target.wants/obd-apps.service"
    rm -f "${USER_SYSTEMD_DIR}/default.target.wants/obd-apps.service"
fi

loginctl enable-linger "$USER_NAME" 2>/dev/null || true

# Ensure pi can talk to Docker from the OBD unit (User=pi).
usermod -aG docker "$USER_NAME" 2>/dev/null || true

systemctl daemon-reload
systemctl enable telematics.service
systemctl enable obd-apps.service

echo
echo "Installed and enabled:"
echo "  telematics.service  -> multi-user.target (Docker telematics_server)"
echo "  obd-apps.service    -> graphical.target  (Docker obd, waits for display)"
echo
echo "Start now (optional):"
echo "  sudo systemctl start telematics.service"
echo "  sudo systemctl start obd-apps.service"
echo
echo "Verify:"
echo "  systemctl is-enabled telematics.service obd-apps.service"
echo "  systemctl status telematics.service obd-apps.service --no-pager"
echo "  docker ps --filter name=telematics_server --filter name=obd"
