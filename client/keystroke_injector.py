"""
WhisperFlow — Keystroke Injector Module (Card 4)
=================================================
Cross-platform text injection — makes transcribed text appear in whatever
application currently has keyboard focus, exactly as if the user typed it.

Platform implementations
-------------------------
  macOS   : Quartz CGEvents via pyobjc (primary) or osascript (fallback)
              Requires Accessibility permission for the terminal app:
              System Settings → Privacy & Security → Accessibility
  Windows : ctypes.windll.user32.SendInput with KEYEVENTF_UNICODE
              No special permissions required
  Linux   : xdotool (X11) or ydotool / wtype (Wayland)
              Requires: xdotool installed (apt install xdotool)
              For Wayland: ydotool (+ ydotoold daemon) or wtype installed

Usage
-----
    from keystroke_injector import KeystrokeInjector
    ki = KeystrokeInjector()
    ki.type_text("Hello, world!")
"""

from __future__ import annotations

import logging
import platform
import subprocess
import time

log = logging.getLogger("whisperflow.keys")

# Delay between individual character events (in seconds)
_MACOS_CHAR_DELAY  = 0.002   # 2 ms
_WIN_CHAR_DELAY    = 0.001   # 1 ms


# ---------------------------------------------------------------------------
# macOS implementation
# ---------------------------------------------------------------------------

def _macos_type_quartz(text: str) -> None:
    """
    Inject text via Quartz CGEvents (pyobjc-framework-Quartz).
    This is the most reliable method and works in virtually every app.
    """
    try:
        from Quartz import (
            CGEventCreateKeyboardEvent,
            CGEventKeyboardSetUnicodeString,
            CGEventPost,
            kCGHIDEventTap,
        )
    except ImportError:
        raise ImportError("pyobjc-framework-Quartz not installed")

    for char in text:
        # Key down
        event_down = CGEventCreateKeyboardEvent(None, 0, True)
        CGEventKeyboardSetUnicodeString(event_down, 1, char)
        CGEventPost(kCGHIDEventTap, event_down)
        # Key up
        event_up = CGEventCreateKeyboardEvent(None, 0, False)
        CGEventKeyboardSetUnicodeString(event_up, 1, char)
        CGEventPost(kCGHIDEventTap, event_up)

        time.sleep(_MACOS_CHAR_DELAY)


def _macos_type_applescript(text: str) -> None:
    """
    Fallback: inject text via osascript / System Events.
    Slower but doesn't require pyobjc.
    Note: special characters (quotes, backslashes) need escaping.
    """
    # Escape double-quotes and backslashes for AppleScript string literal
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    script = f'tell application "System Events" to keystroke "{escaped}"'
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        log.warning("osascript error: %s", result.stderr.strip())


# ---------------------------------------------------------------------------
# Windows implementation
# ---------------------------------------------------------------------------

def _windows_type(text: str) -> None:
    """
    Inject text via SendInput with KEYEVENTF_UNICODE.
    Sends each character as a Unicode keydown + keyup pair.
    """
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32

    # INPUT structure constants
    INPUT_KEYBOARD = 1
    KEYEVENTF_UNICODE = 0x0004
    KEYEVENTF_KEYUP   = 0x0002

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk",         wintypes.WORD),
            ("wScan",       wintypes.WORD),
            ("dwFlags",     wintypes.DWORD),
            ("time",        wintypes.DWORD),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]

    class INPUT_UNION(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("_input", INPUT_UNION)]

    def make_unicode_input(char: str, key_up: bool) -> INPUT:
        flags = KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if key_up else 0)
        ki = KEYBDINPUT(
            wVk=0,
            wScan=ord(char),
            dwFlags=flags,
            time=0,
            dwExtraInfo=None,
        )
        inp = INPUT(type=INPUT_KEYBOARD, _input=INPUT_UNION(ki=ki))
        return inp

    for char in text:
        down = make_unicode_input(char, key_up=False)
        up   = make_unicode_input(char, key_up=True)
        events = (INPUT * 2)(down, up)
        user32.SendInput(2, events, ctypes.sizeof(INPUT))
        time.sleep(_WIN_CHAR_DELAY)


# ---------------------------------------------------------------------------
# Linux implementation
# ---------------------------------------------------------------------------

def _linux_type(text: str) -> None:
    """
    Inject text via xdotool (X11) or ydotool/wtype (Wayland).
    Auto-detects the display server from $XDG_SESSION_TYPE.
    """
    import os
    import shutil

    session_type = os.environ.get("XDG_SESSION_TYPE", "").lower()

    if session_type == "wayland":
        # Try ydotool first, then wtype
        if shutil.which("ydotool"):
            log.debug("Using ydotool for Wayland")
            result = subprocess.run(
                ["ydotool", "type", "--", text],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                log.warning("ydotool error: %s", result.stderr.strip())
            return

        if shutil.which("wtype"):
            log.debug("Using wtype for Wayland")
            result = subprocess.run(
                ["wtype", "--", text],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                log.warning("wtype error: %s", result.stderr.strip())
            return

        log.error(
            "Wayland session detected but neither ydotool nor wtype is installed.\n"
            "  Install ydotool: sudo apt install ydotool  (may need ydotoold daemon)\n"
            "  Install wtype:   sudo apt install wtype"
        )
        return

    # Default: X11 via xdotool
    if shutil.which("xdotool"):
        log.debug("Using xdotool for X11")
        result = subprocess.run(
            ["xdotool", "type", "--clearmodifiers", "--", text],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            log.warning("xdotool error: %s", result.stderr.strip())
        return

    log.error(
        "xdotool not found.  Install it: sudo apt install xdotool"
    )


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class KeystrokeInjector:
    """
    Injects text as synthetic keystrokes on the focused application.

    Auto-detects the platform and selects the appropriate backend.
    """

    def __init__(self) -> None:
        self._platform = platform.system()
        self._backend_name: str

        if self._platform == "Darwin":
            # Try Quartz; fall back to AppleScript
            try:
                from Quartz import CGEventCreateKeyboardEvent  # noqa: F401
                self._backend = _macos_type_quartz
                self._backend_name = "Quartz (pyobjc)"
            except ImportError:
                self._backend = _macos_type_applescript
                self._backend_name = "AppleScript (osascript)"
        elif self._platform == "Windows":
            self._backend = _windows_type
            self._backend_name = "SendInput (ctypes)"
        else:
            # Linux / FreeBSD / other POSIX
            self._backend = _linux_type
            self._backend_name = "xdotool/ydotool/wtype"

        log.info("KeystrokeInjector ready — platform=%s backend=%s",
                 self._platform, self._backend_name)

    def type_text(self, text: str) -> None:
        """
        Type *text* into whatever application currently has keyboard focus.

        Parameters
        ----------
        text : str
            The string to inject.  Unicode characters are supported on all
            platforms.
        """
        if not text:
            return
        log.debug("Injecting %d characters via %s", len(text), self._backend_name)
        self._backend(text)


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.DEBUG)

    test_text = sys.argv[1] if len(sys.argv) > 1 else "Hello from WhisperFlow!"
    print(f"Injecting in 3 seconds: {test_text!r}")
    print("Focus the target window now...")
    time.sleep(3)
    ki = KeystrokeInjector()
    ki.type_text(test_text)
    print("Done.")
