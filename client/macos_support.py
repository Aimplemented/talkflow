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


def open_input_monitoring_settings() -> bool:
    """Input Monitoring is a SEPARATE permission from Accessibility on macOS.
    pynput's global hotkey listener needs Input Monitoring to receive
    key events from other apps. Without it, the hotkey silently never fires.
    """
    if not is_macos():
        return False
    try:
        subprocess.Popen([
            "open",
            "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent",
        ])
        return True
    except Exception:
        return False


def check_input_monitoring_trusted() -> bool | None:
    """Best-effort check for Input Monitoring permission.

    Unlike Accessibility, macOS doesn't expose a clean public API for
    Input Monitoring status. We use IOHIDCheckAccess if available — it
    returns 0 (granted), 1 (denied), or 2 (unknown/not-yet-prompted).
    Returns None if we can't determine.
    """
    if not is_macos():
        return None
    try:
        # IOHIDCheckAccess lives in IOKit and is exposed via pyobjc-framework-IOKit
        # which we don't require, so fall back gracefully.
        from Quartz import CGPreflightListenEventAccess  # type: ignore
        return bool(CGPreflightListenEventAccess())
    except Exception:
        return None
