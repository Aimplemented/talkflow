#!/usr/bin/env bash
#
# TalkFlow Linux Installer
# =========================
# Installs TalkFlow push-to-talk voice dictation on Linux systems.
# Supports: Ubuntu/Debian, Fedora/RHEL, Arch Linux
#
# Usage: ./TalkFlow-Install.sh [--uninstall]
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Installation paths
INSTALL_DIR="$HOME/TalkFlow"
VENV_DIR="$INSTALL_DIR/venv"
DESKTOP_FILE="$HOME/.local/share/applications/talkflow.desktop"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Minimum Python version
MIN_PYTHON_MAJOR=3
MIN_PYTHON_MINOR=10

# ============================================================================
# Helper functions
# ============================================================================

print_header() {
    echo -e "${CYAN}"
    echo "╔═══════════════════════════════════════════════════════════════╗"
    echo "║                    TalkFlow Installer                         ║"
    echo "║              Push-to-Talk Voice Dictation                     ║"
    echo "╚═══════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_command() {
    command -v "$1" &> /dev/null
}

# ============================================================================
# Detect package manager and distro
# ============================================================================

detect_distro() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        DISTRO_ID="$ID"
        DISTRO_NAME="$NAME"
        DISTRO_VERSION="$VERSION_ID"
    elif check_command lsb_release; then
        DISTRO_ID=$(lsb_release -si | tr '[:upper:]' '[:lower:]')
        DISTRO_NAME=$(lsb_release -sd)
        DISTRO_VERSION=$(lsb_release -sr)
    else
        DISTRO_ID="unknown"
        DISTRO_NAME="Unknown Linux"
        DISTRO_VERSION=""
    fi

    # Detect package manager
    if check_command apt-get; then
        PKG_MANAGER="apt"
        PKG_INSTALL="sudo apt-get install -y"
        PKG_UPDATE="sudo apt-get update"
    elif check_command dnf; then
        PKG_MANAGER="dnf"
        PKG_INSTALL="sudo dnf install -y"
        PKG_UPDATE="sudo dnf check-update || true"
    elif check_command yum; then
        PKG_MANAGER="yum"
        PKG_INSTALL="sudo yum install -y"
        PKG_UPDATE="sudo yum check-update || true"
    elif check_command pacman; then
        PKG_MANAGER="pacman"
        PKG_INSTALL="sudo pacman -S --noconfirm"
        PKG_UPDATE="sudo pacman -Sy"
    elif check_command zypper; then
        PKG_MANAGER="zypper"
        PKG_INSTALL="sudo zypper install -y"
        PKG_UPDATE="sudo zypper refresh"
    else
        PKG_MANAGER="unknown"
    fi

    log_info "Detected: $DISTRO_NAME (package manager: $PKG_MANAGER)"
}

# ============================================================================
# Check Python version
# ============================================================================

check_python() {
    log_info "Checking Python version..."

    # Try python3 first, then python
    if check_command python3; then
        PYTHON_CMD="python3"
    elif check_command python; then
        PYTHON_CMD="python"
    else
        log_error "Python not found. Please install Python $MIN_PYTHON_MAJOR.$MIN_PYTHON_MINOR or newer."
        exit 1
    fi

    # Get version
    PYTHON_VERSION=$($PYTHON_CMD -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    PYTHON_MAJOR=$($PYTHON_CMD -c 'import sys; print(sys.version_info.major)')
    PYTHON_MINOR=$($PYTHON_CMD -c 'import sys; print(sys.version_info.minor)')

    if [ "$PYTHON_MAJOR" -lt "$MIN_PYTHON_MAJOR" ] || \
       ([ "$PYTHON_MAJOR" -eq "$MIN_PYTHON_MAJOR" ] && [ "$PYTHON_MINOR" -lt "$MIN_PYTHON_MINOR" ]); then
        log_error "Python $PYTHON_VERSION found, but $MIN_PYTHON_MAJOR.$MIN_PYTHON_MINOR+ is required."
        log_info "Install a newer Python version and try again."
        exit 1
    fi

    log_success "Python $PYTHON_VERSION found ($PYTHON_CMD)"
}

# ============================================================================
# Install system dependencies
# ============================================================================

install_system_deps() {
    log_info "Installing system dependencies..."

    # Detect display server for appropriate typing tool
    SESSION_TYPE="${XDG_SESSION_TYPE:-x11}"
    log_info "Display server: $SESSION_TYPE"

    case "$PKG_MANAGER" in
        apt)
            $PKG_UPDATE
            # Core deps
            $PKG_INSTALL python3-venv python3-pip python3-tk
            # Audio
            $PKG_INSTALL libportaudio2 portaudio19-dev
            # Typing tool
            if [ "$SESSION_TYPE" = "wayland" ]; then
                $PKG_INSTALL ydotool || $PKG_INSTALL wtype || log_warn "Could not install Wayland typing tool"
            else
                $PKG_INSTALL xdotool
            fi
            # Tray icon support (optional)
            $PKG_INSTALL libayatana-appindicator3-1 gir1.2-ayatanaappindicator3-0.1 || \
            $PKG_INSTALL libappindicator3-1 gir1.2-appindicator3-0.1 || \
            log_warn "AppIndicator not available - tray icon may not work"
            # Sound playback
            $PKG_INSTALL pulseaudio-utils alsa-utils || log_warn "Sound utilities not installed"
            ;;

        dnf|yum)
            $PKG_UPDATE
            # Core deps
            $PKG_INSTALL python3-devel python3-pip python3-tkinter
            # Audio
            $PKG_INSTALL portaudio portaudio-devel
            # Typing tool
            if [ "$SESSION_TYPE" = "wayland" ]; then
                $PKG_INSTALL ydotool || $PKG_INSTALL wtype || log_warn "Could not install Wayland typing tool"
            else
                $PKG_INSTALL xdotool
            fi
            # Tray icon support
            $PKG_INSTALL libappindicator-gtk3 || log_warn "AppIndicator not available"
            # Sound playback
            $PKG_INSTALL pulseaudio-utils alsa-utils || log_warn "Sound utilities not installed"
            ;;

        pacman)
            $PKG_UPDATE
            # Core deps
            $PKG_INSTALL python python-pip tk
            # Audio
            $PKG_INSTALL portaudio
            # Typing tool
            if [ "$SESSION_TYPE" = "wayland" ]; then
                $PKG_INSTALL ydotool || $PKG_INSTALL wtype || log_warn "Could not install Wayland typing tool"
            else
                $PKG_INSTALL xdotool
            fi
            # Tray icon support
            $PKG_INSTALL libappindicator-gtk3 || log_warn "AppIndicator not available"
            # Sound playback
            $PKG_INSTALL pulseaudio alsa-utils || log_warn "Sound utilities not installed"
            ;;

        zypper)
            $PKG_UPDATE
            # Core deps
            $PKG_INSTALL python3-devel python3-pip python3-tk
            # Audio
            $PKG_INSTALL portaudio portaudio-devel
            # Typing tool
            $PKG_INSTALL xdotool
            # Tray icon support
            $PKG_INSTALL typelib-1_0-AppIndicator3-0_1 || log_warn "AppIndicator not available"
            ;;

        *)
            log_warn "Unknown package manager. Please install manually:"
            log_warn "  - portaudio / libportaudio2"
            log_warn "  - xdotool (X11) or ydotool/wtype (Wayland)"
            log_warn "  - python3-venv python3-tk"
            log_warn "  - libappindicator (for system tray)"
            read -p "Press Enter to continue anyway, or Ctrl+C to abort..."
            ;;
    esac

    log_success "System dependencies installed"
}

# ============================================================================
# Create installation directory and copy files
# ============================================================================

install_files() {
    log_info "Installing TalkFlow to $INSTALL_DIR..."

    # Create directory
    mkdir -p "$INSTALL_DIR"
    mkdir -p "$INSTALL_DIR/assets"

    # Copy client files
    if [ -d "$SCRIPT_DIR/client" ]; then
        cp -r "$SCRIPT_DIR/client/"* "$INSTALL_DIR/"
        log_success "Copied client files"
    else
        log_error "Client directory not found at $SCRIPT_DIR/client"
        log_error "Run this script from the TalkFlow source directory"
        exit 1
    fi

    # Create Python virtual environment
    log_info "Creating Python virtual environment..."
    $PYTHON_CMD -m venv "$VENV_DIR"
    log_success "Virtual environment created"

    # Install Python dependencies
    log_info "Installing Python packages (this may take a minute)..."
    "$VENV_DIR/bin/pip" install --upgrade pip wheel
    "$VENV_DIR/bin/pip" install websockets pynput sounddevice numpy pystray Pillow

    log_success "Python packages installed"
}

# ============================================================================
# Create launcher script
# ============================================================================

create_launcher() {
    log_info "Creating launcher script..."

    cat > "$INSTALL_DIR/talkflow.sh" << 'LAUNCHER_EOF'
#!/usr/bin/env bash
#
# TalkFlow Launcher
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"

# Activate virtual environment and run GUI
source "$VENV_DIR/bin/activate"
cd "$SCRIPT_DIR"
exec python gui.py "$@"
LAUNCHER_EOF

    chmod +x "$INSTALL_DIR/talkflow.sh"
    log_success "Launcher script created: $INSTALL_DIR/talkflow.sh"
}

# ============================================================================
# Create desktop entry
# ============================================================================

create_desktop_entry() {
    log_info "Creating desktop entry..."

    mkdir -p "$HOME/.local/share/applications"

    # Use logo if available, otherwise generic icon
    if [ -f "$INSTALL_DIR/assets/logo-256x256.png" ]; then
        ICON_PATH="$INSTALL_DIR/assets/logo-256x256.png"
    else
        ICON_PATH="audio-input-microphone"
    fi

    cat > "$DESKTOP_FILE" << DESKTOP_EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=TalkFlow
GenericName=Voice Dictation
Comment=Push-to-talk voice dictation - speak and text appears
Exec=$INSTALL_DIR/talkflow.sh
Icon=$ICON_PATH
Terminal=false
Categories=AudioVideo;Audio;Utility;
Keywords=voice;dictation;speech;transcription;
StartupNotify=true
StartupWMClass=talkflow
DESKTOP_EOF

    # Update desktop database
    if check_command update-desktop-database; then
        update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
    fi

    log_success "Desktop entry created: $DESKTOP_FILE"
}

# ============================================================================
# Uninstall
# ============================================================================

uninstall() {
    print_header
    log_info "Uninstalling TalkFlow..."

    if [ -d "$INSTALL_DIR" ]; then
        rm -rf "$INSTALL_DIR"
        log_success "Removed $INSTALL_DIR"
    else
        log_info "Installation directory not found"
    fi

    if [ -f "$DESKTOP_FILE" ]; then
        rm -f "$DESKTOP_FILE"
        log_success "Removed desktop entry"
    fi

    # Update desktop database
    if check_command update-desktop-database; then
        update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
    fi

    log_success "TalkFlow has been uninstalled"
}

# ============================================================================
# Post-install verification
# ============================================================================

verify_installation() {
    log_info "Verifying installation..."

    local errors=0

    # Check venv
    if [ ! -f "$VENV_DIR/bin/python" ]; then
        log_error "Virtual environment not found"
        ((errors++))
    fi

    # Check key files
    for file in gui.py keystroke_injector.py hotkey_listener.py audio_capture.py; do
        if [ ! -f "$INSTALL_DIR/$file" ]; then
            log_error "Missing file: $file"
            ((errors++))
        fi
    done

    # Check typing tool
    SESSION_TYPE="${XDG_SESSION_TYPE:-x11}"
    if [ "$SESSION_TYPE" = "wayland" ]; then
        if ! check_command ydotool && ! check_command wtype; then
            log_warn "No Wayland typing tool found (ydotool/wtype)"
            log_warn "Text injection may not work. Install ydotool or wtype."
        fi
    else
        if ! check_command xdotool; then
            log_warn "xdotool not found - text injection may not work"
        fi
    fi

    # Test Python imports
    log_info "Testing Python imports..."
    if "$VENV_DIR/bin/python" -c "import sounddevice, websockets, pynput, numpy" 2>/dev/null; then
        log_success "Python packages OK"
    else
        log_error "Some Python packages failed to import"
        ((errors++))
    fi

    if [ $errors -eq 0 ]; then
        log_success "Installation verified successfully!"
    else
        log_warn "Installation completed with $errors warning(s)"
    fi
}

# ============================================================================
# Print completion message
# ============================================================================

print_completion() {
    echo ""
    echo -e "${GREEN}╔═══════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║              TalkFlow Installation Complete!                  ║${NC}"
    echo -e "${GREEN}╚═══════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "  ${CYAN}Installation directory:${NC} $INSTALL_DIR"
    echo ""
    echo -e "  ${CYAN}To launch TalkFlow:${NC}"
    echo "    • From terminal: $INSTALL_DIR/talkflow.sh"
    echo "    • From app menu: Search for 'TalkFlow'"
    echo ""
    echo -e "  ${CYAN}Configuration:${NC}"
    echo "    1. Set your TalkFlow server address in the GUI"
    echo "    2. Choose your microphone"
    echo "    3. Set your hotkey (default: F9)"
    echo "    4. Click Start!"
    echo ""
    echo -e "  ${YELLOW}Note:${NC} If the system tray icon doesn't appear, you may need"
    echo "  to install a tray extension for your desktop environment."
    echo ""
}

# ============================================================================
# Main
# ============================================================================

main() {
    print_header

    # Handle uninstall
    if [ "$1" = "--uninstall" ] || [ "$1" = "-u" ]; then
        uninstall
        exit 0
    fi

    # Check if running as root (not recommended)
    if [ "$EUID" -eq 0 ]; then
        log_warn "Running as root is not recommended. Install as regular user."
        read -p "Continue anyway? [y/N] " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi

    # Run installation steps
    detect_distro
    check_python
    install_system_deps
    install_files
    create_launcher
    create_desktop_entry
    verify_installation
    print_completion
}

main "$@"
