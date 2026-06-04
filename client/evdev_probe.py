#!/usr/bin/env python3
"""evdev probe — shows keyboard events at the /dev/input layer.

Purpose
-------
On a Wayland machine, neither pynput (X11) nor a normal global shortcut can
reliably see a hotkey that DeskFlow forwarded from another computer. The
question is whether those forwarded keys are visible at the raw input (evdev)
layer — if they are, a Wayland TalkFlow agent can capture the hotkey via evdev.

This probe lists your keyboard input devices and prints every key down/up it
sees, along with which device produced it. Run it, then press keys BOTH on a
local keyboard AND via DeskFlow (move the cursor to this screen and press F9).
If the DeskFlow-forwarded keys show up here (often from a virtual/uinput
device), the evdev approach will work.

Run (needs read access to /dev/input — use sudo or join the 'input' group):
    sudo ~/talkflow/.venv/bin/python evdev_probe.py
"""

import selectors
import sys


def main() -> None:
    try:
        import evdev
        from evdev import ecodes, categorize
    except ImportError:
        print("python-evdev not installed. In your venv: pip install evdev")
        sys.exit(1)

    devices = []
    for path in evdev.list_devices():
        try:
            dev = evdev.InputDevice(path)
        except PermissionError:
            print(f"  (no permission for {path} — run with sudo or join 'input' group)")
            continue
        caps = dev.capabilities()
        if ecodes.EV_KEY in caps:
            devices.append(dev)

    if not devices:
        print("No readable keyboard devices found. Try: sudo ~/talkflow/.venv/bin/python evdev_probe.py")
        return

    selector = selectors.DefaultSelector()
    print("Watching input devices:")
    for dev in devices:
        selector.register(dev, selectors.EVENT_READ)
        print(f"  {dev.path}   {dev.name}")
    print("\nPress keys now — locally AND via DeskFlow (press F9 while on this screen).")
    print("Watch whether DeskFlow-forwarded keys appear, and from which device.")
    print("Ctrl+C to stop.\n")

    try:
        while True:
            for key, _ in selector.select():
                for event in key.fileobj.read():
                    if event.type == ecodes.EV_KEY and event.value in (0, 1):
                        keycode = categorize(event).keycode
                        state = "DOWN" if event.value == 1 else "up"
                        print(f"  {state:4}  {keycode:14}  <- {key.fileobj.name}")
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
