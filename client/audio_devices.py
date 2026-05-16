"""
Audio device enumeration + smoke-test helpers.

Lives in its own module so the setup wizard and the doctor command can
use them without re-importing gui.py (which is the entry-point script).
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional, Callable

log = logging.getLogger("talkflow.audio_devices")


def list_microphones() -> list[dict]:
    """Return all input-capable audio devices visible to sounddevice."""
    devices = []
    try:
        import sounddevice as sd
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0:
                devices.append({
                    "index": i,
                    "name": d["name"],
                    "channels": d["max_input_channels"],
                    "rate": int(d["default_samplerate"]),
                })
    except Exception as e:
        log.warning("Device enumeration failed: %s", e)
    return devices


def test_microphone(
    device_index: Optional[int],
    duration: float = 3.0,
    on_level: Optional[Callable[[float], None]] = None,
    on_done: Optional[Callable[[bool, str], None]] = None,
) -> None:
    """Record `duration` seconds from the given device and report back.

    Runs in a background thread; calls `on_done(ok, message)` when finished
    and (optionally) `on_level(level)` for each audio block.
    """
    def _run():
        try:
            import sounddevice as sd
            import numpy as np

            frames = []

            def callback(indata, frame_count, time_info, status):
                frames.append(indata.copy())
                if on_level:
                    level = float(np.abs(indata).mean()) / 32768.0 * 10
                    on_level(min(level, 1.0))

            kwargs = dict(samplerate=16000, channels=1, dtype="int16",
                          blocksize=1600, callback=callback)
            if device_index is not None:
                kwargs["device"] = device_index

            with sd.InputStream(**kwargs):
                time.sleep(duration)

            total = sum(len(f) for f in frames)
            if on_done:
                if total > 0:
                    on_done(True, f"✓ Captured {total} samples ({duration:.1f}s)")
                else:
                    on_done(False, "✗ No audio captured")
        except Exception as e:
            if on_done:
                on_done(False, f"✗ Error: {e}")

    threading.Thread(target=_run, daemon=True).start()
