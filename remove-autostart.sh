#!/bin/bash
set -euo pipefail

DEPLOY_DIR="/home/jetson/Desktop/telematics_obd_deploy"

if [[ "$EUID" -eq 0 ]]; then
    systemctl stop telematics.service 2>/dev/null || true
    systemctl disable telematics.service 2>/dev/null || true
    rm -f /etc/systemd/system/telematics.service
    rm -f /etc/systemd/system/automotive-apps.service
    systemctl daemon-reload
    systemctl reset-failed
fi

systemctl --user stop obd-apps.service 2>/dev/null || true
systemctl --user disable obd-apps.service 2>/dev/null || true
systemctl --user stop automotive-apps.service 2>/dev/null || true
systemctl --user disable automotive-apps.service 2>/dev/null || true
rm -f "$HOME/.config/systemd/user/obd-apps.service"
rm -f "$HOME/.config/systemd/user/automotive-apps.service"
systemctl --user daemon-reload
systemctl --user reset-failed

echo "Autostart removed."
