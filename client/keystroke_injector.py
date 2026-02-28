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

def _windows_clipboard_fallback(text: str) -> bool:
    """
    Fallback: inject text via clipboard (Ctrl+V).
    Works in apps that block SendInput (e.g., some elevated or protected apps).
    Returns True on success, False on failure.
    """
    import ctypes
    from ctypes import wintypes

    try:
        import pyperclip
    except ImportError:
        log.debug("pyperclip not installed, clipboard fallback unavailable")
        return False

    try:
        # Save current clipboard content
        try:
            old_clipboard = pyperclip.paste()
        except Exception:
            old_clipboard = None

        # Copy our text to clipboard
        pyperclip.copy(text)
        time.sleep(0.05)  # Brief pause for clipboard to update

        # Send Ctrl+V via SendInput
        user32 = ctypes.windll.user32

        INPUT_KEYBOARD = 1
        KEYEVENTF_KEYUP = 0x0002
        VK_CONTROL = 0x11
        VK_V = 0x56

        # ULONG_PTR: 8 bytes on 64-bit, 4 bytes on 32-bit
        ULONG_PTR = ctypes.c_uint64 if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_uint32

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [
                ("wVk",         wintypes.WORD),
                ("wScan",       wintypes.WORD),
                ("dwFlags",     wintypes.DWORD),
                ("time",        wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR),
            ]

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [
                ("dx",          wintypes.LONG),
                ("dy",          wintypes.LONG),
                ("mouseData",   wintypes.DWORD),
                ("dwFlags",     wintypes.DWORD),
                ("time",        wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR),
            ]

        class HARDWAREINPUT(ctypes.Structure):
            _fields_ = [
                ("uMsg",    wintypes.DWORD),
                ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD),
            ]

        class INPUT_UNION(ctypes.Union):
            _fields_ = [
                ("ki", KEYBDINPUT),
                ("mi", MOUSEINPUT),
                ("hi", HARDWAREINPUT),
            ]

        class INPUT(ctypes.Structure):
            _fields_ = [("type", wintypes.DWORD), ("_input", INPUT_UNION)]

        def make_key_input(vk: int, key_up: bool) -> INPUT:
            ki = KEYBDINPUT(
                wVk=vk,
                wScan=0,
                dwFlags=KEYEVENTF_KEYUP if key_up else 0,
                time=0,
                dwExtraInfo=0,
            )
            inp = INPUT()
            inp.type = INPUT_KEYBOARD
            inp._input.ki = ki
            return inp

        # Ctrl down, V down, V up, Ctrl up
        events = (INPUT * 4)(
            make_key_input(VK_CONTROL, False),
            make_key_input(VK_V, False),
            make_key_input(VK_V, True),
            make_key_input(VK_CONTROL, True),
        )

        user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
        user32.SendInput.restype = wintypes.UINT
        result = user32.SendInput(4, events, ctypes.sizeof(INPUT))

        time.sleep(0.1)  # Wait for paste to complete

        # Restore old clipboard content
        if old_clipboard is not None:
            try:
                pyperclip.copy(old_clipboard)
            except Exception:
                pass

        return result == 4

    except Exception as e:
        log.warning("Clipboard fallback failed: %s", e)
        return False


def _windows_type(text: str) -> None:
    """
    Inject text via SendInput with KEYEVENTF_UNICODE.
    Falls back to clipboard paste (Ctrl+V) if SendInput fails.
    """
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32

    # INPUT structure constants
    INPUT_KEYBOARD = 1
    KEYEVENTF_UNICODE = 0x0004
    KEYEVENTF_KEYUP   = 0x0002

    # ULONG_PTR: pointer-sized integer (8 bytes on 64-bit, 4 bytes on 32-bit)
    ULONG_PTR = ctypes.c_uint64 if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_uint32

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk",         wintypes.WORD),
            ("wScan",       wintypes.WORD),
            ("dwFlags",     wintypes.DWORD),
            ("time",        wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]

    # MOUSEINPUT is the largest union member - needed for correct INPUT sizing
    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx",          wintypes.LONG),
            ("dy",          wintypes.LONG),
            ("mouseData",   wintypes.DWORD),
            ("dwFlags",     wintypes.DWORD),
            ("time",        wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [
            ("uMsg",    wintypes.DWORD),
            ("wParamL", wintypes.WORD),
            ("wParamH", wintypes.WORD),
        ]

    # Union must include all input types for correct structure sizing
    class INPUT_UNION(ctypes.Union):
        _fields_ = [
            ("ki", KEYBDINPUT),
            ("mi", MOUSEINPUT),
            ("hi", HARDWAREINPUT),
        ]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("_input", INPUT_UNION)]

    # Set argtypes/restype for proper 64-bit calling convention
    user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    user32.SendInput.restype = wintypes.UINT

    # Build array of INPUT events for the entire text (key down + key up for each char)
    events_list = []
    for char in text:
        # Handle surrogate pairs for characters outside BMP (e.g., emoji)
        code = ord(char)
        if code > 0xFFFF:
            # Split into UTF-16 surrogate pair
            code -= 0x10000
            high = 0xD800 + (code >> 10)
            low = 0xDC00 + (code & 0x3FF)
            codes = [high, low]
        else:
            codes = [code]

        for scan_code in codes:
            # Key down
            ki_down = KEYBDINPUT(
                wVk=0,
                wScan=scan_code,
                dwFlags=KEYEVENTF_UNICODE,
                time=0,
                dwExtraInfo=0,
            )
            inp_down = INPUT()
            inp_down.type = INPUT_KEYBOARD
            inp_down._input.ki = ki_down
            events_list.append(inp_down)

            # Key up
            ki_up = KEYBDINPUT(
                wVk=0,
                wScan=scan_code,
                dwFlags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP,
                time=0,
                dwExtraInfo=0,
            )
            inp_up = INPUT()
            inp_up.type = INPUT_KEYBOARD
            inp_up._input.ki = ki_up
            events_list.append(inp_up)

    if not events_list:
        return

    # Create array and send all events at once for better reliability
    n_events = len(events_list)
    EventArray = INPUT * n_events
    events = EventArray(*events_list)

    result = user32.SendInput(n_events, events, ctypes.sizeof(INPUT))

    if result != n_events:
        error = ctypes.get_last_error()
        log.warning("SendInput sent %d/%d events (error=%d), trying clipboard fallback",
                    result, n_events, error)
        # Fall back to clipboard paste
        if _windows_clipboard_fallback(text):
            log.info("Clipboard fallback succeeded")
        else:
            log.error("Both SendInput and clipboard fallback failed")


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
