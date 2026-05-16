"""
macOS-specific helpers: Accessibility + Microphone permission checks.

Keystroke injection silently fails without Accessibility permission, and
mic access silently records silence without Microphone permission. We
detect both and walk the user to the right System Settings pane.
"""

from __future__ import annotations

import platform
import subprocess


def is_macos() -> bool:
    return platform.system() == "Darwin"


def check_accessibility_trusted() -> bool | None:
    """Return True if this process has Accessibility permission, False if not,
    or None if we can't determine (e.g. PyObjC missing).

    Uses the public AXIsProcessTrustedWithOptions API via pyobjc.
    """
    if not is_macos():
        return None
    try:
        from ApplicationServices import (
            AXIsProcessTrustedWithOptions,
            kAXTrustedCheckOptionPrompt,
        )
        # Passing False means "don't show the system prompt now"
        opts = {kAXTrustedCheckOptionPrompt: False}
        return bool(AXIsProcessTrustedWithOptions(opts))
    except Exception:
        return None


def open_accessibility_settings() -> bool:
    """Open System Settings to the Accessibility pane (Privacy & Security)."""
    if not is_macos():
        return False
    try:
        subprocess.Popen([
            "open",
            "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
        ])
        return True
    except Exception:
        return False


def open_microphone_settings() -> bool:
    if not is_macos():
        return False
    try:
        subprocess.Popen([
            "open",
            "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone",
        ])
        return True
    except Exception:
        return False
