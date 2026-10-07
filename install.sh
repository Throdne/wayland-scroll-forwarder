#!/usr/bin/env bash
# Install wayland-scroll-forwarder as a systemd user service.
#
# Usage: ./install.sh [--udev] [--uninstall] [WINDOW_CLASS ...]
#   WINDOW_CLASS  WM_CLASS of the app (find with: xprop WM_CLASS). Default: GeForceNOW
#   --udev        also install the udev rule so mice are readable without the 'input' group (uses sudo)
#   --uninstall   stop and remove the service and script
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN="$HOME/.local/bin/wayland_scroll_forwarder"
UNIT_DIR="$HOME/.config/systemd/user"
UNIT="$UNIT_DIR/wayland-scroll-forwarder.service"
RULE=/etc/udev/rules.d/99-scroll-forwarder.rules

udev=0 uninstall=0 classes=()
for arg in "$@"; do
    case "$arg" in
        --udev) udev=1 ;;
        --uninstall) uninstall=1 ;;
        -h|--help) sed -n '2,7p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        -*) echo "Unknown option: $arg" >&2; exit 2 ;;
        *) classes+=("$arg") ;;
    esac
done
[ ${#classes[@]} -gt 0 ] || classes=(GeForceNOW)

if [ "$uninstall" = 1 ]; then
    systemctl --user disable --now wayland-scroll-forwarder 2>/dev/null || true
    rm -f "$UNIT" "$BIN"
    systemctl --user daemon-reload
    if [ -f "$RULE" ]; then
        sudo rm -f "$RULE"
        sudo udevadm control --reload
    fi
    echo "Uninstalled."
    exit 0
fi

if ! python3 -c 'import evdev, Xlib' 2>/dev/null; then
    echo "Missing dependencies: python-evdev and python-xlib (plus libXtst)." >&2
    echo "  Arch:   sudo pacman -S python-evdev python-xlib libxtst" >&2
    echo "  Debian: sudo apt install python3-evdev python3-xlib libxtst6" >&2
    echo "  Fedora: sudo dnf install python3-evdev python3-xlib libXtst" >&2
    exit 1
fi

if [ "$udev" = 1 ]; then
    sudo install -m 644 "$SRC/contrib/99-scroll-forwarder.rules" "$RULE"
    sudo udevadm control --reload
    sudo udevadm trigger --subsystem-match=input
    echo "Installed udev rule."
fi

mkdir -p "$(dirname "$BIN")" "$UNIT_DIR"
install -m 755 "$SRC/scroll_forwarder.py" "$BIN"
# Point the unit at the installed script and the requested window class(es).
sed "s|^ExecStart=.*|ExecStart=$BIN ${classes[*]}|" \
    "$SRC/contrib/wayland-scroll-forwarder.service" > "$UNIT"

systemctl --user daemon-reload
systemctl --user enable wayland-scroll-forwarder
systemctl --user restart wayland-scroll-forwarder
sleep 1
systemctl --user --no-pager status wayland-scroll-forwarder | head -5 || true

echo
echo "Installed for: ${classes[*]}"
echo "Logs: journalctl --user -u wayland-scroll-forwarder -f"
