#!/usr/bin/env bash
# TalkFlow — install the AI5090 paste-helper stack as auto-starting services.
#
# Sets up two services so you never hand-run terminals again:
#   1. ydotoold              (system service, root)  — persistent uinput daemon
#                                                       at /run/ydotoold.socket
#   2. talkflow-paste-helper (user service)          — receives dictation from
#                                                       the PC and types it here
#
# Prereqs: ydotool 1.x built/installed at /usr/local/bin (ydotool + ydotoold),
# and this repo checked out at ~/talkflow. Run as your normal user (it will
# sudo for the system parts):
#
#     bash ~/talkflow/client/install-ai5090-helper.sh
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNITS="$HERE/systemd"

if [[ ! -x /usr/local/bin/ydotoold ]]; then
    echo "ERROR: /usr/local/bin/ydotoold not found. Build ydotool 1.x first:" >&2
    echo "  git clone https://github.com/ReimuNotMoe/ydotool && cd ydotool \\" >&2
    echo "    && cmake -B build && cmake --build build && sudo cmake --install build" >&2
    exit 1
fi

echo "==> Installing ydotoold system service"
sudo cp "$UNITS/ydotoold.service" /etc/systemd/system/ydotoold.service
sudo systemctl daemon-reload
sudo systemctl enable --now ydotoold.service
echo "    ydotoold: $(systemctl is-active ydotoold.service)"

echo "==> Installing talkflow-paste-helper user service"
mkdir -p "$HOME/.config/systemd/user"
cp "$UNITS/talkflow-paste-helper.service" "$HOME/.config/systemd/user/talkflow-paste-helper.service"
systemctl --user daemon-reload
systemctl --user enable --now talkflow-paste-helper.service
# Keep the user service running even when not logged in graphically.
sudo loginctl enable-linger "$USER" || true
echo "    talkflow-paste-helper: $(systemctl --user is-active talkflow-paste-helper.service)"

echo
echo "Done. Both services are enabled and will start on boot/login."
echo "Check them with:"
echo "  systemctl status ydotoold.service"
echo "  systemctl --user status talkflow-paste-helper.service"
echo "  journalctl --user -u talkflow-paste-helper -f      # live helper log"
