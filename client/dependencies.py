"""
Dependency Check & Installation Helper
========================================
Checks for missing dependencies and provides helpful instructions.
"""

import sys
import platform
import importlib.util
import logging

log = logging.getLogger("talkflow.dependencies")

# Dependency definitions
DEPENDENCIES = {
    "sounddevice": {
        "package": "sounddevice",
        "required": True,
        "platforms": ["all"],
        "install": "pip install sounddevice>=0.4.6",
    },
    "numpy": {
        "package": "numpy",
        "required": True,
        "platforms": ["all"],
        "install": "pip install numpy>=1.24.0",
    },
    "websockets": {
        "package": "websockets",
        "required": True,
        "platforms": ["all"],
        "install": "pip install websockets>=13.0",
    },
    "pynput": {
        "package": "pynput",
        "required": True,
        "platforms": ["all"],
        "install": "pip install pynput>=1.7.6",
    },
    "pystray": {
        "package": "pystray",
        "required": False,
        "platforms": ["all"],
        "install": "pip install pystray>=0.19.5",
        "fallback": "System tray will be unavailable",
    },
    "PIL": {
        "package": "PIL",
        "required": False,
        "platforms": ["all"],
        "install": "pip install Pillow>=10.0.0",
        "fallback": "Some UI features will be limited",
    },
    "groq": {
        "package": "groq",
        "required": False,
        "platforms": ["all"],
        "install": "pip install groq>=0.4.0",
        "fallback": "Groq backend will be unavailable",
    },
    # macOS specific
    "Quartz": {
        "package": "Quartz",
        "required": True,
        "platforms": ["darwin"],
        "install": "pip install pyobjc-framework-Quartz>=9.0.0",
        "fallback": "Text injection will use AppleScript (slower)",
    },
    "pyperclip": {
        "package": "pyperclip",
        "required": False,
        "platforms": ["darwin", "win32"],
        "install": "pip install pyperclip>=1.8.2",
        "fallback": "Clipboard text injection fallback will be unavailable",
    },
}

SYSTEM_DEPENDENCIES = {
    "linux": {
        "x11": [
            "xdotool (required for X11 text injection)",
            "Install: sudo apt install xdotool  (Debian/Ubuntu)",
            "        sudo dnf install xdotool  (Fedora/RHEL)",
            "        sudo pacman -S xdotool    (Arch)",
        ],
        "wayland": [
            "ydotool or wtype (required for Wayland text injection)",
            "Install ydotool: sudo apt install ydotool",
            "        wtype: sudo apt install wtype",
            "        (may also need to run: sudo systemctl start ydotoold)",
        ],
        "gui": [
            "libappindicator3-1, gir1.2-appindicator3-0.1 (optional, for system tray)",
            "Install: sudo apt install libappindicator3-1 gir1.2-appindicator3-0.1",
        ],
        "audio": [
            "portaudio19-dev (for audio capture)",
            "Install: sudo apt install portaudio19-dev python3-pip python3-tk",
        ],
    },
    "darwin": {},
    "win32": {},
}


def _is_available(package_name: str) -> bool:
    """Check if a Python package is available."""
    spec = importlib.util.find_spec(package_name)
    return spec is not None


def check_python_version() -> bool:
    """Check if Python version is 3.10+."""
    if sys.version_info < (3, 10):
        log.error(
            "Python 3.10+ is required. You have %d.%d.%d",
            sys.version_info.major,
            sys.version_info.minor,
            sys.version_info.micro,
        )
        return False
    log.info("Python version OK: %d.%d.%d", *sys.version_info[:3])
    return True


def check_dependencies() -> tuple[bool, list[str]]:
    """
    Check all dependencies.
    
    Returns:
        (all_ok, list_of_issues)
    """
    issues = []
    current_platform = sys.platform
    if platform.system() == "Darwin":
        current_platform = "darwin"

    # Check Python version first
    if not check_python_version():
        return False, ["Python 3.10+ is required"]

    # Check each dependency
    for dep_name, dep_info in DEPENDENCIES.items():
        platforms = dep_info["platforms"]
        if platforms != ["all"] and current_platform not in platforms:
            continue

        if _is_available(dep_info["package"]):
            log.info("✓ %s", dep_name)
        else:
            msg = f"✗ {dep_name} not found"
            if dep_info["required"]:
                msg += f" (REQUIRED) — {dep_info['install']}"
                issues.append(msg)
                log.error(msg)
            else:
                msg += f" (optional) — {dep_info.get('fallback', 'feature unavailable')}"
                issues.append(msg)
                log.warning(msg)

    return len(issues) == 0, issues


def check_system_dependencies() -> list[str]:
    """
    Check system dependencies (non-Python packages).
    
    Returns:
        List of missing system dependencies and install instructions.
    """
    import shutil
    import os

    current_platform = sys.platform
    if platform.system() == "Darwin":
        current_platform = "darwin"
    elif platform.system() == "Windows":
        current_platform = "win32"

    issues = []

    # Linux-specific checks
    if current_platform == "linux":
        # Check for typing tools
        session_type = os.environ.get("XDG_SESSION_TYPE", "x11").lower()
        has_typing_tool = False

        if session_type == "wayland":
            has_ydotool = shutil.which("ydotool")
            has_wtype = shutil.which("wtype")
            if not (has_ydotool or has_wtype):
                issues.append(
                    "\n".join(SYSTEM_DEPENDENCIES["linux"]["wayland"])
                )
                log.warning("No Wayland typing tool found")
            else:
                has_typing_tool = True
                log.info("✓ Wayland typing tool found")
        else:
            has_xdotool = shutil.which("xdotool")
            if not has_xdotool:
                issues.append(
                    "\n".join(SYSTEM_DEPENDENCIES["linux"]["x11"])
                )
                log.warning("xdotool not found")
            else:
                has_typing_tool = True
                log.info("✓ xdotool found")

        # Check for system tray support (optional)
        has_appindicator = (
            shutil.which("apt-get")  # Debian-based with libappindicator installed
            or shutil.which("dnf")   # Fedora-based
        )
        if not has_appindicator:
            log.warning("AppIndicator may not be available (system tray might not work)")

    return issues


def print_missing_dependencies(issues: list[str]) -> None:
    """Print formatted list of missing dependencies."""
    if not issues:
        return

    print("\n" + "=" * 70)
    print("MISSING DEPENDENCIES")
    print("=" * 70)
    for issue in issues:
        print(f"\n{issue}")
    print("\n" + "=" * 70 + "\n")


def install_prompt() -> bool:
    """
    Ask user if they want to install missing dependencies.
    
    Returns:
        True if user wants to continue, False otherwise.
    """
    response = input("\nContinue anyway? [y/N] ").strip().lower()
    return response == "y"


def verify_installation() -> bool:
    """
    Verify that all required dependencies are installed.
    Returns True if installation can proceed, False otherwise.
    """
    all_ok, py_issues = check_dependencies()
    sys_issues = check_system_dependencies()

    if py_issues or sys_issues:
        all_issues = py_issues + sys_issues
        print_missing_dependencies(all_issues)

        # Check if any REQUIRED dependencies are missing
        has_required_missing = any("REQUIRED" in issue for issue in py_issues)
        if has_required_missing:
            print("Cannot proceed without required dependencies.")
            return False

        # Optional dependencies missing - ask user
        return install_prompt()

    log.info("All dependencies OK!")
    return True


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
    )
    all_ok, _ = check_dependencies()
    sys_issues = check_system_dependencies()
    print_missing_dependencies((_ if not all_ok else []) + sys_issues)
    sys.exit(0 if all_ok and not sys_issues else 1)
