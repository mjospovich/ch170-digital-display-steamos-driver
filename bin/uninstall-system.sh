#!/bin/bash
# Removes the boot service, udev rule, menu entry, and launcher symlink.
# Leaves this directory in place.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OWNER="${SUDO_USER:-$USER}"
OWNER_HOME="$(getent passwd "$OWNER" | cut -d: -f6)"
RUNTIME="/run/user/$(id -u "$OWNER")"

systemctl disable --now deepcool-digital.service || true
rm -f /etc/systemd/system/deepcool-digital.service
rm -f /etc/udev/rules.d/99-deepcool-digital.rules
systemctl daemon-reload
udevadm control --reload-rules || true

if [ -S "$RUNTIME/bus" ]; then
  runuser -u "$OWNER" -- env \
    XDG_RUNTIME_DIR="$RUNTIME" \
    DBUS_SESSION_BUS_ADDRESS="unix:path=$RUNTIME/bus" \
    systemctl --user disable --now deepcool-digital.service \
    || true
fi

rm -f "$OWNER_HOME/.local/share/applications/ch170-display.desktop"
LINK="$OWNER_HOME/.local/bin/ch170-display"
if [ -L "$LINK" ] && [ "$(readlink -f "$LINK")" = "$ROOT/bin/ch170-display" ]; then
  rm -f "$LINK"
fi

echo "Removed the CH170 display service, udev rule, menu entry, and launcher."
echo "The project directory was left in place: $ROOT"
