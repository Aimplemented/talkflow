"""
TalkFlow Doctor — end-to-end smoke test.

Run with: python gui.py --doctor

Walks through every layer that has to work for TalkFlow to do its job
and prints PASS/FAIL/WARN for each. The goal: when something doesn't work,
you know *which* piece broke instead of staring at a silent window.

Exit code: 0 if every required check passes, 1 otherwise.
"""

from __future__ import annotations

import json
import platform
import socket
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

# Make these explicit for readability
PASS = "\033[92m  PASS\033[0m"
FAIL = "\033[91m  FAIL\033[0m"
WARN = "\033[93m  WARN\033[0m"
INFO = "\033[94m  ----\033[0m"


def section(title: str) -> None:
    print(f"\n\033[1m=== {title} ===\033[0m")


def line(status: str, name: str, detail: str = "") -> None:
    print(f"{status}  {name:<38} {detail}")


class Result:
    def __init__(self):
        self.failures = 0

    def passed(self, name, detail=""):
        line(PASS, name, detail)

    def warned(self, name, detail=""):
        line(WARN, name, detail)

    def failed(self, name, detail=""):
        line(FAIL, name, detail)
        self.failures += 1

    def info(self, name, detail=""):
        line(INFO, name, detail)


def check_environment(r: Result) -> None:
    section("Environment")
    r.info("Platform", f"{platform.system()} {platform.release()}")
    r.info("Python", sys.version.split()[0])
    if platform.system() == "Linux":
        import os
        session = os.environ.get("XDG_SESSION_TYPE", "?")
        if session == "wayland":
            r.warned("Display server",
                     "Wayland — pynput can't capture global hotkeys here. "
                     "Switch to an X11 session for now.")
        else:
            r.passed("Display server", session)


def check_imports(r: Result) -> None:
    section("Python dependencies")
    deps = {
        "sounddevice": "audio capture",
        "numpy": "audio processing",
        "websockets": "server transport",
        "pynput": "global hotkey listener",
        "PIL": "icon rendering",
    }
    for mod, why in deps.items():
        try:
            __import__(mod)
            r.passed(f"import {mod}", why)
        except Exception as e:
            r.failed(f"import {mod}", f"{why} — {e}")


def check_config(r: Result) -> dict:
    section("Configuration")
    try:
        from paths import config_path, log_path
    except Exception as e:
        r.failed("paths module", str(e))
        return {}

    cp = config_path()
    if not cp.exists():
        r.warned("config.json", f"missing at {cp} — wizard will run on first launch")
        return {}
    try:
        cfg = json.loads(cp.read_text())
        r.passed("config.json", str(cp))
    except Exception as e:
        r.failed("config.json", f"unreadable: {e}")
        return {}

    backend = cfg.get("backend", "?")
    r.info("Backend", backend)
    if backend == "groq":
        if cfg.get("groq_api_key"):
            r.passed("Groq API key", "present")
        else:
            r.failed("Groq API key", "missing — paste one in Settings")
    elif backend == "server":
        if cfg.get("server"):
            r.passed("Server address", cfg["server"])
        else:
            r.failed("Server address", "empty — enter host:port in Settings")
    r.info("Hotkey", cfg.get("hotkey", "?"))
    r.info("Mic device", cfg.get("mic_device_name", "?"))
    r.info("Log file", str(log_path()))
    return cfg


def check_microphone(r: Result, cfg: dict) -> None:
    section("Microphone")
    try:
        from audio_devices import list_microphones
    except Exception as e:
        r.failed("audio_devices", str(e))
        return

    devs = list_microphones()
    if not devs:
        r.failed("Enumerate microphones", "none found (or sounddevice missing)")
        return
    r.passed("Enumerate microphones", f"{len(devs)} input device(s)")

    # Try a 1-second capture from the configured device
    try:
        import sounddevice as sd
        import numpy as np
        idx = cfg.get("mic_device")
        kwargs = dict(samplerate=16000, channels=1, dtype="int16", blocksize=1600)
        if idx is not None:
            kwargs["device"] = idx
        frames = []

        def cb(indata, *_):
            frames.append(indata.copy())

        with sd.InputStream(callback=cb, **kwargs):
            time.sleep(1.0)
        total = sum(len(f) for f in frames)
        if total > 0:
            level = float(np.abs(np.concatenate(frames)).mean())
            r.passed("Capture 1s of audio", f"{total} samples, mean level {level:.1f}")
        else:
            r.failed("Capture 1s of audio", "got zero samples")
    except Exception as e:
        r.failed("Capture 1s of audio", str(e))


def check_hotkey_listener(r: Result, cfg: dict) -> None:
    section("Hotkey listener")
    try:
        from hotkey_listener import HotkeyListener
    except Exception as e:
        r.failed("hotkey_listener import", str(e))
        return
    try:
        hl = HotkeyListener(hotkey=cfg.get("hotkey", "f9"), on_toggle=lambda: None)
        hl.start()
        time.sleep(0.3)
        hl.stop()
        r.passed("Listener start/stop", "OK (this does not prove global capture)")
    except Exception as e:
        r.failed("Listener start/stop", str(e))


def check_keystroke_injector(r: Result) -> None:
    section("Keystroke injector")
    try:
        from keystroke_injector import KeystrokeInjector
        KeystrokeInjector()  # constructor probes the platform backend
        r.passed("Injector constructs", platform.system())
    except Exception as e:
        r.failed("Injector constructs", str(e))


def check_macos_permissions(r: Result) -> None:
    if platform.system() != "Darwin":
        return
    section("macOS permissions")
    try:
        from macos_support import (
            check_accessibility_trusted,
            check_input_monitoring_trusted,
        )
    except Exception as e:
        r.warned("pyobjc import", f"{e} — install pyobjc-framework-ApplicationServices")
        return
    a = check_accessibility_trusted()
    if a is True:
        r.passed("Accessibility permission", "granted")
    elif a is False:
        r.failed("Accessibility permission",
                 "not granted — System Settings → Privacy & Security → Accessibility")
    else:
        r.warned("Accessibility permission", "unknown")

    im = check_input_monitoring_trusted()
    if im is True:
        r.passed("Input Monitoring permission", "granted")
    elif im is False:
        r.failed("Input Monitoring permission",
                 "not granted — hotkey will never fire")
    else:
        r.warned("Input Monitoring permission", "unknown (may not be prompted yet)")


def check_backend_reachable(r: Result, cfg: dict) -> None:
    section("Transcription backend")
    backend = cfg.get("backend")
    if backend == "groq":
        try:
            req = urllib.request.Request(
                "https://api.groq.com/openai/v1/models",
                headers={"Authorization": f"Bearer {cfg.get('groq_api_key', '')}"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    r.passed("Groq API reachable", "auth OK")
                else:
                    r.failed("Groq API reachable", f"HTTP {resp.status}")
        except Exception as e:
            r.failed("Groq API reachable", str(e))
    elif backend == "server":
        server = cfg.get("server", "")
        if not server:
            r.failed("Server reachable", "no server configured")
            return
        if ":" in server:
            host, port = server.rsplit(":", 1)
            try:
                port = int(port)
            except ValueError:
                r.failed("Server reachable", f"bad port in {server!r}")
                return
        else:
            host, port = server, 9876
        try:
            with socket.create_connection((host, port), timeout=3):
                r.passed("Server TCP connect", f"{host}:{port}")
        except Exception as e:
            r.failed("Server TCP connect", f"{host}:{port} — {e}")
    else:
        r.warned("Backend", f"unrecognized: {backend!r}")


def run_doctor() -> int:
    print("\n\033[1mTalkFlow Doctor\033[0m  — checking that every layer works\n")
    r = Result()
    check_environment(r)
    check_imports(r)
    cfg = check_config(r)
    check_microphone(r, cfg)
    check_hotkey_listener(r, cfg)
    check_keystroke_injector(r)
    check_macos_permissions(r)
    if cfg:
        check_backend_reachable(r, cfg)

    print()
    if r.failures == 0:
        print("\033[92mAll required checks passed.\033[0m "
              "You should be able to hold the hotkey and dictate.")
        return 0
    print(f"\033[91m{r.failures} check(s) failed.\033[0m "
          "Fix the items marked FAIL above, then re-run with --doctor.")
    return 1


if __name__ == "__main__":
    sys.exit(run_doctor())
