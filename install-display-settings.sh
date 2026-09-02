#!/bin/bash
# Keep display always on and disable auto-rotation (persist across reboot).
# Run once:  sudo bash ~/Desktop/telematics_obd_deployed_env/install-display-settings.sh

set -euo pipefail

USER_NAME="${SUDO_USER:-${USER:-pi}}"
USER_HOME="$(getent passwd "$USER_NAME" | cut -d: -f6)"
LABWC_SYSTEM_AUTOSTART="/etc/xdg/labwc/autostart"
LABWC_USER_AUTOSTART="${USER_HOME}/.config/labwc/autostart"
LOGIND_DROPIN="/etc/systemd/logind.conf.d/99-display-always-on.conf"
CMDLINE="/boot/firmware/cmdline.txt"

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    echo "Run as root: sudo bash $0"
    exit 1
fi

echo "=== 1. Disable screen blanking (raspi-config / labwc) ==="
raspi-config nonint do_blanking 1 || true
sed -i '/swayidle/d' "$LABWC_USER_AUTOSTART" 2>/dev/null || true
sed -i '/swayidle/d' /etc/xdg/labwc-greeter/autostart 2>/dev/null || true

echo "=== 2. Disable kanshi auto-rotation (system autostart) ==="
if [[ -f "$LABWC_SYSTEM_AUTOSTART" ]]; then
    sed -i '/^\/usr\/bin\/kanshi/d' "$LABWC_SYSTEM_AUTOSTART"
    sed -i '/^kanshi/d' "$LABWC_SYSTEM_AUTOSTART"
fi

echo "=== 3. systemd-logind: never sleep on idle ==="
install -d /etc/systemd/logind.conf.d
cat > "$LOGIND_DROPIN" << 'EOF'
[Login]
IdleAction=ignore
IdleActionSec=0
HandleLidSwitch=ignore
HandleLidSwitchExternalPower=ignore
HandleLidSwitchDocked=ignore
EOF

echo "=== 4. Kernel console blanking off ==="
if [[ -f "$CMDLINE" ]] && ! grep -q 'consoleblank=0' "$CMDLINE"; then
    sed -i 's/$/ consoleblank=0/' "$CMDLINE"
fi

echo "=== 5. User labwc autostart (fixed rotation, no kanshi/swayidle) ==="
install -d -o "$USER_NAME" -g "$USER_NAME" "${USER_HOME}/.config/labwc"
cat > "$LABWC_USER_AUTOSTART" << 'EOF'
# Fixed display policy: no auto-rotation (kanshi disabled), no screen sleep (swayidle disabled).
/usr/bin/lwrespawn /usr/bin/pcmanfm-pi &
/usr/bin/lwrespawn /usr/bin/wf-panel-pi &
/usr/bin/lxsession-xdg-autostart

# Re-apply fixed orientation after outputs appear (adjust transform if needed).
(sleep 2; \
  wlr-randr --output DSI-1 --transform 270 2>/dev/null; \
  wlr-randr --output DSI-2 --transform normal 2>/dev/null; \
  wlr-randr --output HDMI-A-1 --transform normal 2>/dev/null; \
  wlr-randr --output HDMI-A-2 --transform normal 2>/dev/null) &
EOF
chown "$USER_NAME:$USER_NAME" "$LABWC_USER_AUTOSTART"
chmod 644 "$LABWC_USER_AUTOSTART"

echo "=== 6. Disable dynamic kanshi profile (empty = no auto config) ==="
install -d -o "$USER_NAME" -g "$USER_NAME" "${USER_HOME}/.config/kanshi"
: > "${USER_HOME}/.config/kanshi/config"
chown "$USER_NAME:$USER_NAME" "${USER_HOME}/.config/kanshi/config"

systemctl restart systemd-logind 2>/dev/null || true

echo
echo "=== Done ==="
echo "  - Screen blanking: OFF (no swayidle)"
echo "  - Auto rotation: OFF (kanshi removed from session)"
echo "  - Fixed rotation: DSI-1 transform 270 (edit ~/.config/labwc/autostart to change)"
echo
echo "Reboot or re-login to apply fully:"
echo "  sudo reboot"
