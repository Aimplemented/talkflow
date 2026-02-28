"""
TalkFlow — Global Hotkey Listener
===================================
Supports two modes:
  1. Push-to-talk (default): hold key to record, release to stop
  2. Toggle: press once to start, press again to stop

Uses pynput for cross-platform key monitoring.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional, Set

from pynput import keyboard

log = logging.getLogger("talkflow.hotkey")


# ---------------------------------------------------------------------------
# Key alias normalisation
# ---------------------------------------------------------------------------

_ALIASES: dict[str, str] = {
    "ctrl":    "ctrl_l",
    "control": "ctrl_l",
    "alt":     "alt_l",
    "option":  "alt_l",
    "shift":   "shift",
    "cmd":     "cmd",
    "command": "cmd",
    "super":   "cmd",
    "win":     "cmd",
    "meta":    "cmd",
}

_PYNPUT_SPECIALS: Set[str] = {
    attr.name for attr in keyboard.Key
}


def _normalize_key(raw: str) -> str:
    s = raw.strip().lower()
    return _ALIASES.get(s, s)


def _parse_hotkey(hotkey_str: str) -> Set[str]:
    parts = [p for p in hotkey_str.split("+") if p]
    return {_normalize_key(p) for p in parts}


def _key_name(key) -> str | None:
    try:
        return key.name.lower()
    except AttributeError:
        pass
    try:
        if key.char is not None:
            return key.char.lower()
    except AttributeError:
        pass
    return None


# ---------------------------------------------------------------------------
# HotkeyListener
# ---------------------------------------------------------------------------

class HotkeyListener:
    """
    Global hotkey listener with push-to-talk and toggle modes.

    Push-to-talk mode:
        on_press_start() fires when hotkey combo is pressed down.
        on_press_stop()  fires when hotkey combo is released.

    Toggle mode (legacy):
        on_toggle() fires on each press.
    """

    def __init__(
        self,
        hotkey: str,
        on_toggle: Optional[Callable[[], None]] = None,
        on_press_start: Optional[Callable[[], None]] = None,
        on_press_stop: Optional[Callable[[], None]] = None,
        mode: str = "push-to-talk",
    ) -> None:
        self._hotkey_str = hotkey
        self._target_keys = _parse_hotkey(hotkey)
        self._on_toggle = on_toggle
        self._on_press_start = on_press_start
        self._on_press_stop = on_press_stop
        self._mode = mode  # "push-to-talk" or "toggle"

        self._pressed: Set[str] = set()
        self._is_held = False      # For push-to-talk: currently holding
        self._toggle_fired = False  # For toggle: prevent repeats
        self._lock = threading.Lock()
        self._listener: keyboard.Listener | None = None

        log.info("HotkeyListener: %r mode=%s keys=%s", hotkey, mode, self._target_keys)

    def start(self) -> None:
        self._listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
        )
        self._listener.daemon = True
        self._listener.start()
        log.info("Hotkey listener started (hotkey=%r, mode=%s)", self._hotkey_str, self._mode)

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
            log.info("Hotkey listener stopped")

    # ------------------------------------------------------------------
    # pynput callbacks
    # ------------------------------------------------------------------

    def _on_press(self, key) -> None:
        name = _key_name(key)
        if name is None:
            return

        with self._lock:
            self._pressed.add(name)
            combo_active = self._target_keys.issubset(self._pressed)

        if self._mode == "push-to-talk":
            if combo_active and not self._is_held:
                self._is_held = True
                log.debug("Push-to-talk: START")
                if self._on_press_start:
                    try:
                        self._on_press_start()
                    except Exception as exc:
                        log.exception("Error in on_press_start: %s", exc)

        else:  # toggle mode
            if combo_active and not self._toggle_fired:
                self._toggle_fired = True
                with self._lock:
                    self._pressed.clear()
                log.debug("Toggle: FIRED")
                if self._on_toggle:
                    try:
                        self._on_toggle()
                    except Exception as exc:
                        log.exception("Error in on_toggle: %s", exc)

    def _on_release(self, key) -> None:
        name = _key_name(key)
        if name is None:
            return

        with self._lock:
            self._pressed.discard(name)
            combo_still_active = self._target_keys.issubset(self._pressed)

        if self._mode == "push-to-talk":
            # Fire stop when ANY key in the combo is released
            if self._is_held and not combo_still_active:
                self._is_held = False
                log.debug("Push-to-talk: STOP")
                if self._on_press_stop:
                    try:
                        self._on_press_stop()
                    except Exception as exc:
                        log.exception("Error in on_press_stop: %s", exc)

        else:  # toggle mode
            if not combo_still_active:
                self._toggle_fired = False


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import time
    import sys

    logging.basicConfig(level=logging.INFO)

    hotkey = sys.argv[1] if len(sys.argv) > 1 else "f9"
    mode = sys.argv[2] if len(sys.argv) > 2 else "push-to-talk"

    def on_start():
        print(f"[HOLD] Recording started!")

    def on_stop():
        print(f"[RELEASE] Recording stopped!")

    def on_toggle():
        print(f"[TOGGLE] Hotkey fired!")

    print(f"Listening: {hotkey!r} mode={mode} (Ctrl+C to quit)")

    if mode == "push-to-talk":
        hl = HotkeyListener(hotkey=hotkey, on_press_start=on_start,
                             on_press_stop=on_stop, mode="push-to-talk")
    else:
        hl = HotkeyListener(hotkey=hotkey, on_toggle=on_toggle, mode="toggle")

    hl.start()

    try:
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("Exiting.")
        hl.stop()
