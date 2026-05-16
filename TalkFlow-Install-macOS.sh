#!/usr/bin/env bash
#
# TalkFlow macOS Installer
# ========================
# Two modes:
#   1. If TalkFlow.app exists alongside this script (or in dist/) — copies it to /Applications.
#   2. Otherwise, sets up a Python venv in ~/TalkFlow and runs from source.
#
# Usage: ./TalkFlow-Install-macOS.sh
#

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_BUNDLE=""

for candidate in "$SCRIPT_DIR/TalkFlow.app" "$SCRIPT_DIR/client/dist/TalkFlow.app"; do
    if [ -d "$candidate" ]; then
        APP_BUNDLE="$candidate"
        break
    fi
done

if [ -n "$APP_BUNDLE" ]; then
    echo -e "${GREEN}Found $APP_BUNDLE${NC}"
    echo "Installing to /Applications..."
    rm -rf "/Applications/TalkFlow.app"
    cp -R "$APP_BUNDLE" "/Applications/TalkFlow.app"
    # Strip the quarantine bit so Gatekeeper doesn't refuse it on first open
    xattr -dr com.apple.quarantine "/Applications/TalkFlow.app" 2>/dev/null || true
    echo -e "${GREEN}Done.${NC}"
    echo "Launch from Spotlight or Launchpad. On first run you'll be asked"
    echo "to grant Microphone and Accessibility permissions."
    exit 0
fi

# --- Fallback: install from source ---
INSTALL_DIR="$HOME/TalkFlow"
VENV_DIR="$INSTALL_DIR/venv"

echo -e "${YELLOW}No prebuilt .app found — installing from source into $INSTALL_DIR${NC}"

if ! command -v python3 >/dev/null 2>&1; then
    echo -e "${RED}python3 not found. Install Python 3.11+ from python.org first.${NC}"
    exit 1
fi

mkdir -p "$INSTALL_DIR"
cp -R "$SCRIPT_DIR/client" "$INSTALL_DIR/"

python3 -m venv "$VENV_DIR"
# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate"
pip install --upgrade pip
pip install -r "$INSTALL_DIR/client/requirements.txt"

# Tiny launcher
cat > "$INSTALL_DIR/talkflow" <<EOF
#!/usr/bin/env bash
source "$VENV_DIR/bin/activate"
cd "$INSTALL_DIR/client"
exec python gui.py "\$@"
EOF
chmod +x "$INSTALL_DIR/talkflow"

echo -e "${GREEN}Installed.${NC} Launch with:"
echo "  $INSTALL_DIR/talkflow"
