"""
TalkFlow — Clipboard Paste Injector (DeskFlow delivery path)
============================================================
Delivers transcribed text by *clipboard paste* instead of synthetic
per-character typing.  This is the technique used by Wispr Flow and friends,
and it is the right tool for the DeskFlow ("software KVM") setup:

  1. Save the current clipboard contents.
  2. Copy the transcript onto the clipboard.
  3. Wait `sync_delay_ms` so DeskFlow can sync the clipboard to whichever
     screen currently has the cursor.
  4. Send the paste hotkey (Ctrl+V / Cmd+V).  On the DeskFlow *primary*
     (the machine with the keyboard/mouse/mic), the low-level keyboard hook
     captures this injected keystroke and forwards it to the active remote
     screen — so the paste lands wherever the cursor is.
  5. Wait `restore_delay_ms`, then restore the original clipboard.

Why this works with DeskFlow
----------------------------
DeskFlow's server-side keyboard hook only ignores *injected* keystrokes when
it is running as a client (to avoid feedback loops).  On the primary it
forwards injected keystrokes normally, so a SendInput Ctrl+V generated here is
delivered to the active screen.  DeskFlow also synchronises the clipboard
between screens, so the pasted content arrives on the remote machine.

Cross-OS note
-------------
When the active screen runs a different OS than the primary (e.g. a Windows
primary pasting to a macOS client), DeskFlow is responsible for mapping the
Ctrl modifier to Cmd.  This is configured per-screen in DeskFlow's settings
("swap Cmd and Ctrl"/modifier mapping).  We always send the *primary's* native
paste combo and let DeskFlow translate it.

Usage
-----
    from clipboard_injector import ClipboardInjector
    ci = ClipboardInjector(sync_delay_ms=250, restore_delay_ms=700)
    ci.deliver("Hello from the other screen!")
"""

from __future__ import annotations

import logging
import platform
import shutil
import subprocess
import time

log = logging.getLogger("talkflow.clipboard")


# ---------------------------------------------------------------------------
# Clipboard get / set — pyperclip primary, native fallbacks
# ---------------------------------------------------------------------------
def _clipboard_get() -> str | None:
    """Return current clipboard text, or None if it cannot be read."""
    try:
        import pyperclip
        return pyperclip.paste()
    except Exception:
        pass

    system = platform.system()
    try:
        if system == "Darwin":
            return subprocess.run(["pbpaste"], capture_output=True, text=True).stdout
        if system == "Windows":
            # PowerShell Get-Clipboard
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
                capture_output=True, text=True,
            )
            return out.stdout.rstrip("\r\n")
        # Linux
        for tool in (["xclip", "-selection", "clipboard", "-o"], ["xsel", "-b"]):
            if shutil.which(tool[0]):
                return subprocess.run(tool, capture_output=True, text=True).stdout
    except Exception as exc:
        log.debug("Clipboard read failed: %s", exc)
    return None


def _clipboard_set(text: str) -> bool:
    """Set clipboard text. Returns True on success."""
    try:
        import pyperclip
        pyperclip.copy(text)
        return True
    except Exception:
        pass

    system = platform.system()
    try:
        if system == "Darwin":
            p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
            p.communicate(text.encode("utf-8"))
            return p.returncode == 0
        if system == "Windows":
            # clip.exe reads stdin and sets the clipboard
            p = subprocess.Popen(["clip"], stdin=subprocess.PIPE)
            p.communicate(text.encode("utf-16-le"))
            return p.returncode == 0
        # Linux
        for tool in (["xclip", "-selection", "clipboard"], ["xsel", "-b", "-i"]):
            if shutil.which(tool[0]):
                p = subprocess.Popen(tool, stdin=subprocess.PIPE)
                p.communicate(text.encode("utf-8"))
                return p.returncode == 0
    except Exception as exc:
        log.warning("Clipboard write failed: %s", exc)
    return False


# ---------------------------------------------------------------------------
# Paste hotkey — platform specific
# ---------------------------------------------------------------------------
def _send_paste_windows() -> bool:
    """Send Ctrl+V via SendInput. Returns True if all 4 events were sent."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32

    INPUT_KEYBOARD = 1
    KEYEVENTF_KEYUP = 0x0002
    VK_CONTROL = 0x11
    VK_V = 0x56

    ULONG_PTR = ctypes.c_uint64 if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_uint32

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", wintypes.LONG),
            ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [
            ("uMsg", wintypes.DWORD),
            ("wParamL", wintypes.WORD),
            ("wParamH", wintypes.WORD),
        ]

    class INPUT_UNION(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("_input", INPUT_UNION)]

    def make_key(vk: int, key_up: bool) -> INPUT:
        ki = KEYBDINPUT(wVk=vk, wScan=0,
                        dwFlags=KEYEVENTF_KEYUP if key_up else 0,
                        time=0, dwExtraInfo=0)
        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        inp._input.ki = ki
        return inp

    events = (INPUT * 4)(
        make_key(VK_CONTROL, False),
        make_key(VK_V, False),
        make_key(VK_V, True),
        make_key(VK_CONTROL, True),
    )
    user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    user32.SendInput.restype = wintypes.UINT
    sent = user32.SendInput(4, events, ctypes.sizeof(INPUT))
    return sent == 4


def _send_paste_macos() -> bool:
    """Send Cmd+V via osascript (System Events)."""
    script = 'tell application "System Events" to keystroke "v" using command down'
    result = subprocess.run(["osascript", "-e", script],
                            capture_output=True, text=True)
    if result.returncode != 0:
        log.warning("osascript paste error: %s", result.stderr.strip())
        return False
    return True


def _send_paste_linux() -> bool:
    """Send Ctrl+V via xdotool (X11) or ydotool/wtype (Wayland)."""
    import os

    session = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if session == "wayland":
        if shutil.which("ydotool"):
            return subprocess.run(["ydotool", "key", "29:1", "47:1", "47:0", "29:0"]).returncode == 0
        log.error("Wayland paste needs ydotool installed")
        return False
    if shutil.which("xdotool"):
        return subprocess.run(["xdotool", "key", "--clearmodifiers", "ctrl+v"]).returncode == 0
    log.error("xdotool not found — install it: sudo apt install xdotool")
    return False


def _send_paste() -> bool:
    system = platform.system()
    if system == "Windows":
        return _send_paste_windows()
    if system == "Darwin":
        return _send_paste_macos()
    return _send_paste_linux()


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------
class ClipboardInjector:
    """Delivers text by copy → (let DeskFlow sync) → paste → restore clipboard."""

    def __init__(self, sync_delay_ms: int = 250, restore_delay_ms: int = 700,
                 restore_clipboard: bool = True) -> None:
        self.sync_delay_ms = sync_delay_ms
        self.restore_delay_ms = restore_delay_ms
        self.restore_clipboard = restore_clipboard
        log.info("ClipboardInjector ready — sync=%dms restore=%dms platform=%s",
                 sync_delay_ms, restore_delay_ms, platform.system())

    def deliver(self, text: str) -> bool:
        """
        Copy *text*, let DeskFlow sync it to the active screen, then paste.

        Returns True if the paste keystroke was sent successfully.
        """
        if not text:
            return False

        original = _clipboard_get() if self.restore_clipboard else None

        if not _clipboard_set(text):
            log.error("Could not set clipboard — aborting paste delivery")
            return False

        # Give DeskFlow time to propagate the clipboard to the active screen.
        time.sleep(self.sync_delay_ms / 1000.0)

        ok = _send_paste()
        if not ok:
            log.warning("Paste keystroke failed to send")

        # Restore the user's previous clipboard after the paste has landed.
        if self.restore_clipboard and original is not None:
            time.sleep(self.restore_delay_ms / 1000.0)
            _clipboard_set(original)

        return ok


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.DEBUG)
    msg = sys.argv[1] if len(sys.argv) > 1 else "Hello from TalkFlow clipboard paste!"
    print(f"Pasting in 3s — focus the target (or move DeskFlow cursor to a screen): {msg!r}")
    time.sleep(3)
    ClipboardInjector().deliver(msg)
    print("Done.")
