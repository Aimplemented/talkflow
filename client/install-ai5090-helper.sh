#!/usr/bin/env bash
# TalkFlow — AI5090 paste-helper installer (guided, one-shot)
# ==========================================================
# Sets up the remote-screen side so dictation from the PC types into the focused
# window here — and survives reboots. It will, as needed:
#
#   1. detect the display server (X11 / Wayland / GNOME-KDE-wlroots);
#   2. ensure a working injection tool — building ydotool 1.x (with ydotoold)
#      from source if the distro package lacks the daemon (a common gap);
#   3. enable /dev/uinput;
#   4. install + enable two services:
#        - ydotoold              (system, root)  → /run/ydotoold.socket (0666)
#        - talkflow-paste-helper (user)          → paste_helper.py at login
#   5. run `doctor` to confirm everything is green.
#
# Run as your normal desktop user (it sudo's for the system bits):
#     bash install-ai5090-helper.sh            # install
#     bash install-ai5090-helper.sh --uninstall
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${CYAN}==>${NC} $*"; }
ok()    { echo -e "${GREEN}  ✓${NC} $*"; }
warn()  { echo -e "${YELLOW}  ⚠${NC} $*"; }
die()   { echo -e "${RED}  ✗${NC} $*" >&2; exit 1; }

PORT="${TALKFLOW_HELPER_PORT:-9879}"
SOCKET="/run/ydotoold.socket"
SYS_UNIT="/etc/systemd/system/ydotoold.service"
USER_UNIT="$HOME/.config/systemd/user/talkflow-paste-helper.service"

# ---------------------------------------------------------------------------
uninstall() {
    info "Removing TalkFlow helper services"
    systemctl --user disable --now talkflow-paste-helper.service 2>/dev/null || true
    rm -f "$USER_UNIT"; systemctl --user daemon-reload 2>/dev/null || true
    sudo systemctl disable --now ydotoold.service 2>/dev/null || true
    sudo rm -f "$SYS_UNIT"; sudo systemctl daemon-reload 2>/dev/null || true
    ok "Services removed (ydotool binaries left installed)."
    exit 0
}
[[ "${1:-}" == "--uninstall" ]] && uninstall

command -v sudo >/dev/null || die "sudo is required."
command -v systemctl >/dev/null || die "systemd is required (this targets a systemd Linux)."

PYTHON="$(command -v python3 || true)"
[[ -n "$PYTHON" ]] || die "python3 not found — install it first."
[[ -f "$HERE/paste_helper.py" ]] || die "paste_helper.py not found next to this script."

# ---------------------------------------------------------------------------
# 1. Display server / compositor (informational; ydotool works regardless)
# ---------------------------------------------------------------------------
SESSION="${XDG_SESSION_TYPE:-unknown}"
COMPOSITOR="$(ps -e -o comm= | grep -m1 -E 'gnome-shell|kwin_wayland|kwin_x11|sway|weston|hyprland|labwc|mutter' || true)"
info "Display: session=${SESSION:-unknown} compositor=${COMPOSITOR:-unknown}"

# ---------------------------------------------------------------------------
# 2. Ensure ydotool + ydotoold
# ---------------------------------------------------------------------------
find_ydotoold() { command -v ydotoold 2>/dev/null || ([[ -x /usr/local/bin/ydotoold ]] && echo /usr/local/bin/ydotoold) || true; }

YDOTOOLD="$(find_ydotoold)"
if [[ -z "$YDOTOOLD" ]]; then
    info "ydotoold not found — building ydotool 1.x from source"
    if command -v apt-get >/dev/null; then
        sudo apt-get update -y
        sudo apt-get install -y git build-essential cmake scdoc
    elif command -v dnf >/dev/null; then
        sudo dnf install -y git gcc make cmake scdoc
    elif command -v pacman >/dev/null; then
        sudo pacman -Sy --noconfirm git base-devel cmake scdoc
    else
        die "Unknown package manager — install git, a C toolchain, cmake, scdoc, then re-run."
    fi
    BUILD_DIR="$(mktemp -d)"
    git clone --depth 1 https://github.com/ReimuNotMoe/ydotool.git "$BUILD_DIR/ydotool"
    ( cd "$BUILD_DIR/ydotool" && cmake -B build && cmake --build build && sudo cmake --install build )
    hash -r
    YDOTOOLD="$(find_ydotoold)"
    [[ -n "$YDOTOOLD" ]] || die "Build finished but ydotoold still not found."
fi
ok "ydotoold: $YDOTOOLD"
ok "ydotool : $(command -v ydotool || echo '/usr/local/bin/ydotool')"

# ---------------------------------------------------------------------------
# 3. Enable /dev/uinput
# ---------------------------------------------------------------------------
sudo modprobe uinput 2>/dev/null || true
echo "uinput" | sudo tee /etc/modules-load.d/uinput.conf >/dev/null
[[ -e /dev/uinput ]] && ok "/dev/uinput present" || warn "/dev/uinput missing — a reboot may be needed to load the module."

# ---------------------------------------------------------------------------
# 4a. ydotoold system service (generated so the binary path is correct)
# ---------------------------------------------------------------------------
info "Installing ydotoold system service"
sudo tee "$SYS_UNIT" >/dev/null <<EOF
[Unit]
Description=ydotoold — virtual input daemon for TalkFlow
After=multi-user.target

[Service]
ExecStart=$YDOTOOLD --socket-path=$SOCKET --socket-perm=0666
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now ydotoold.service
sleep 1
[[ -S "$SOCKET" ]] && ok "ydotoold running (socket $SOCKET)" || warn "ydotoold socket not present yet — check: systemctl status ydotoold"

# ---------------------------------------------------------------------------
# 4b. paste-helper user service (generated with this checkout's real path)
# ---------------------------------------------------------------------------
info "Installing talkflow-paste-helper user service"
mkdir -p "$(dirname "$USER_UNIT")"
cat > "$USER_UNIT" <<EOF
[Unit]
Description=TalkFlow remote paste helper
After=ydotoold.service graphical-session.target
Wants=ydotoold.service

[Service]
Environment=YDOTOOL_SOCKET=$SOCKET
ExecStart=$PYTHON $HERE/paste_helper.py --port $PORT --ydotool-socket $SOCKET
Restart=always
RestartSec=2

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now talkflow-paste-helper.service
# Keep the user service alive across logout/reboot.
sudo loginctl enable-linger "$USER" 2>/dev/null || true
sleep 1
systemctl --user is-active --quiet talkflow-paste-helper.service \
    && ok "paste helper running on :$PORT" \
    || warn "paste helper not active — check: systemctl --user status talkflow-paste-helper"

# ---------------------------------------------------------------------------
# 5. Final self-check
# ---------------------------------------------------------------------------
echo
info "Running doctor"
YDOTOOL_SOCKET="$SOCKET" "$PYTHON" "$HERE/doctor.py" --role remote || true

echo
ok "AI5090 helper installed. It will auto-start on boot/login."
echo -e "  Logs:   ${CYAN}journalctl --user -u talkflow-paste-helper -f${NC}"
echo -e "  On the PC, point the daemon here with:  ${CYAN}setup --remote-paste $(hostname -I | awk '{print $1}'):$PORT${NC}"
