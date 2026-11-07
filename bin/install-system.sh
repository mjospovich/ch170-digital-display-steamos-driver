#!/bin/bash
# Installs the CH170 boot service, udev rule, menu entry, and launcher symlink.
# Does not open the window. Needs root once: the CPU wattage counter is mode 0400.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OWNER="${SUDO_USER:-$USER}"
OWNER_HOME="$(getent passwd "$OWNER" | cut -d: -f6)"

sed "s|@ROOT@|$ROOT|g" "$ROOT/etc/99-deepcool-digital.rules" > /tmp/99-deepcool-digital.rules
sed "s|@ROOT@|$ROOT|g" "$ROOT/etc/deepcool-digital.service" > /tmp/deepcool-digital.service
sed "s|@ROOT@|$ROOT|g" "$ROOT/etc/ch170-display.desktop" > /tmp/ch170-display.desktop

install -D -m 0644 /tmp/99-deepcool-digital.rules /etc/udev/rules.d/99-deepcool-digital.rules
install -D -m 0644 /tmp/deepcool-digital.service /etc/systemd/system/deepcool-digital.service
install -o "$OWNER" -g "$OWNER" -D -m 0644 /tmp/ch170-display.desktop \
  "$OWNER_HOME/.local/share/applications/ch170-display.desktop"
install -o "$OWNER" -g "$OWNER" -d "$OWNER_HOME/.local/bin"
ln -sfn "$ROOT/bin/ch170-display" "$OWNER_HOME/.local/bin/ch170-display"

chmod 444 /sys/class/powercap/intel-rapl/intel-rapl:0/energy_uj
chmod 444 /sys/class/powercap/intel-rapl/intel-rapl:0/intel-rapl:0:0/energy_uj || true
udevadm control --reload-rules
udevadm trigger --subsystem-match=hidraw --attr-match=idVendor=3633 || true
udevadm trigger --subsystem-match=powercap || true

if [ -d "/run/user/$(id -u "$OWNER")" ]; then
  runuser -u "$OWNER" -- env \
    XDG_RUNTIME_DIR="/run/user/$(id -u "$OWNER")" \
    DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u "$OWNER")/bus" \
    systemctl --user disable --now deepcool-digital.service \
    || true
fi

systemctl daemon-reload
systemctl enable deepcool-digital.service
systemctl restart deepcool-digital.service
systemctl --no-pager --full status deepcool-digital.service
