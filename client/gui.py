"""
TalkFlow — Settings GUI
========================
Push-to-talk voice dictation. Hold your hotkey, speak, release — text
appears wherever your cursor is.

Features:
  - Microphone selection + test
  - Hotkey configuration + test (supports any key combo including Ctrl+Win)
  - Server connection test
  - Push-to-talk dictation
  - System tray support (minimize to tray on Windows)
  - Saves settings to config.json
"""

from __future__ import annotations

import json
import logging
import os
import platform
import sys
import threading
import time
from pathlib import Path
from typing import Optional, Callable

import tkinter as tk
from tkinter import ttk, messagebox

# System tray support (optional)
try:
    import pystray
    from PIL import Image, ImageDraw
    TRAY_AVAILABLE = True
except ImportError:
    TRAY_AVAILABLE = False

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("talkflow.gui")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
CONFIG_DIR = Path(__file__).parent
CONFIG_FILE = CONFIG_DIR / "config.json"
LEGACY_CONFIG_FILE = CONFIG_DIR / "talkflow_config.json"

DEFAULT_CONFIG = {
    # Server settings
    "server": "YOUR_SERVER:9876",

    # Hotkey settings - supports any key combo (e.g., "f9", "ctrl+win", "ctrl+shift+d")
    "hotkey": "f9",

    # Microphone settings
    "mic_device": None,
    "mic_device_name": "System Default",

    # UI preferences
    "minimize_to_tray": True,
    "start_minimized": False,
    "show_notifications": True,
    "play_sounds": True,

    # Advanced settings
    "auto_start_on_launch": False,
    "transcription_timeout": 30,
}

# Common hotkey presets for quick selection
HOTKEY_PRESETS = [
    ("F9", "f9"),
    ("F10", "f10"),
    ("F8", "f8"),
    ("Ctrl+Win", "ctrl+cmd"),       # cmd maps to Win key on Windows
    ("Ctrl+Shift+D", "ctrl+shift+d"),
    ("Ctrl+Alt+V", "ctrl+alt+v"),
]


def load_config() -> dict:
    """Load configuration from config.json, with fallback to legacy file."""
    # Try new config file first
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                cfg = json.load(f)
            # Merge with defaults to handle new config keys
            for k, v in DEFAULT_CONFIG.items():
                cfg.setdefault(k, v)
            log.info("Loaded config from %s", CONFIG_FILE)
            return cfg
        except Exception as e:
            log.warning("Failed to load config: %s", e)

    # Try legacy config file
    if LEGACY_CONFIG_FILE.exists():
        try:
            with open(LEGACY_CONFIG_FILE, encoding="utf-8") as f:
                cfg = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                cfg.setdefault(k, v)
            log.info("Migrated config from legacy file %s", LEGACY_CONFIG_FILE)
            # Save to new location
            save_config(cfg)
            return cfg
        except Exception as e:
            log.warning("Failed to load legacy config: %s", e)

    return dict(DEFAULT_CONFIG)


def save_config(cfg: dict) -> None:
    """Save configuration to config.json."""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        log.debug("Config saved to %s", CONFIG_FILE)
    except Exception as e:
        log.error("Failed to save config: %s", e)


# ---------------------------------------------------------------------------
# Audio device enumeration
# ---------------------------------------------------------------------------
def list_microphones() -> list[dict]:
    devices = []
    try:
        import sounddevice as sd
        all_devs = sd.query_devices()
        for i, d in enumerate(all_devs):
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


# ---------------------------------------------------------------------------
# Mic test
# ---------------------------------------------------------------------------
def test_microphone(device_index: Optional[int], duration: float = 3.0,
                    on_level=None, on_done=None) -> None:
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


# ---------------------------------------------------------------------------
# Server test
# ---------------------------------------------------------------------------
def test_server(server_url: str, on_done=None) -> None:
    def _run():
        try:
            import urllib.request
            resp = urllib.request.urlopen(f"http://{server_url}/health", timeout=5)
            data = json.loads(resp.read())
            model = data.get("model", "unknown")
            device = data.get("device", "unknown")
            if on_done:
                on_done(True, f"✓ Connected — model: {model}, device: {device}")
        except Exception as e:
            if on_done:
                on_done(False, f"✗ Cannot reach server: {e}")

    threading.Thread(target=_run, daemon=True).start()


# ---------------------------------------------------------------------------
# Windows focus helper
# ---------------------------------------------------------------------------
def _save_foreground_window():
    """Save handle to the currently focused window (Windows only)."""
    if platform.system() != "Windows":
        return None
    try:
        import ctypes
        return ctypes.windll.user32.GetForegroundWindow()
    except:
        return None


def _restore_foreground_window(hwnd):
    """Restore focus to a previously saved window handle (Windows only)."""
    if hwnd is None or platform.system() != "Windows":
        return
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        # Constants
        SW_RESTORE = 9
        SW_SHOW = 5
        ALT_KEY = 0x12
        KEYEVENTF_KEYUP = 0x0002

        # Get thread IDs for thread input attachment
        current_thread = kernel32.GetCurrentThreadId()
        target_thread = user32.GetWindowThreadProcessId(hwnd, None)

        # Attach our thread's input to the target window's thread
        # This allows us to call SetForegroundWindow successfully
        attached = False
        if current_thread != target_thread:
            attached = user32.AttachThreadInput(current_thread, target_thread, True)

        try:
            # Ensure the window is visible and not minimized
            if user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, SW_RESTORE)
            else:
                user32.ShowWindow(hwnd, SW_SHOW)

            # Alt key trick to bypass foreground lock (send Alt press/release)
            user32.keybd_event(ALT_KEY, 0, 0, 0)
            user32.keybd_event(ALT_KEY, 0, KEYEVENTF_KEYUP, 0)

            # Multiple attempts to set foreground window
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)

            # Wait for focus to settle
            time.sleep(0.05)

        finally:
            # Detach thread input if we attached it
            if attached:
                user32.AttachThreadInput(current_thread, target_thread, False)

    except Exception as e:
        log.warning("Could not restore focus: %s", e)


# ---------------------------------------------------------------------------
# Hotkey test
# ---------------------------------------------------------------------------
class HotkeyTester:
    def __init__(self):
        self._listener = None
        self._detected = False

    def start(self, hotkey_str: str, on_detected=None, timeout: float = 10.0):
        from hotkey_listener import HotkeyListener
        self._detected = False

        def on_start():
            self._detected = True
            if on_detected:
                on_detected()
            self.stop()

        self._listener = HotkeyListener(
            hotkey=hotkey_str,
            on_press_start=on_start,
            mode="push-to-talk"
        )
        self._listener.start()

        def _timeout():
            time.sleep(timeout)
            if not self._detected:
                self.stop()

        threading.Thread(target=_timeout, daemon=True).start()

    def stop(self):
        if self._listener:
            self._listener.stop()
            self._listener = None


# ---------------------------------------------------------------------------
# Main GUI
# ---------------------------------------------------------------------------
class TalkFlowGUI:
    def __init__(self):
        self.config = load_config()
        self.is_running = False
        self.hotkey_tester = HotkeyTester()
        self._target_hwnd = None  # Window to inject text into

        self.root = tk.Tk()
        self.root.title("TalkFlow")
        self.root.geometry("520x640")
        self.root.resizable(False, False)

        # Prevent the GUI from stealing focus when possible
        if platform.system() == "Windows":
            # Make the window not steal focus on click-through
            self.root.attributes("-topmost", False)

        style = ttk.Style()
        if platform.system() == "Windows":
            try:
                style.theme_use("vista")
            except:
                style.theme_use("clam")
        else:
            try:
                style.theme_use("aqua")
            except:
                style.theme_use("clam")

        self._build_ui()
        self._load_devices()

    def _build_ui(self):
        root = self.root

        # Header
        header = ttk.Frame(root)
        header.pack(fill="x", padx=15, pady=(15, 5))
        ttk.Label(header, text="🎙 TalkFlow",
                  font=("Segoe UI", 18, "bold")).pack(side="left")

        self.status_label = ttk.Label(header, text="● Stopped", foreground="gray",
                                       font=("Segoe UI", 11))
        self.status_label.pack(side="right")

        ttk.Separator(root, orient="horizontal").pack(fill="x", padx=15, pady=5)

        # === Server ===
        srv_frame = ttk.LabelFrame(root, text="  Server  ", padding=10)
        srv_frame.pack(fill="x", padx=15, pady=5)

        row = ttk.Frame(srv_frame)
        row.pack(fill="x")
        ttk.Label(row, text="Address:").pack(side="left")
        self.server_var = tk.StringVar(value=self.config["server"])
        self.server_entry = ttk.Entry(row, textvariable=self.server_var, width=30)
        self.server_entry.pack(side="left", padx=(10, 10))
        self.test_server_btn = ttk.Button(row, text="Test Connection",
                                           command=self._test_server)
        self.test_server_btn.pack(side="right")

        self.server_status = ttk.Label(srv_frame, text="", font=("Segoe UI", 9))
        self.server_status.pack(fill="x", pady=(5, 0))

        # === Microphone ===
        mic_frame = ttk.LabelFrame(root, text="  Microphone  ", padding=10)
        mic_frame.pack(fill="x", padx=15, pady=5)

        row2 = ttk.Frame(mic_frame)
        row2.pack(fill="x")
        ttk.Label(row2, text="Device:").pack(side="left")
        self.mic_var = tk.StringVar(value="System Default")
        self.mic_combo = ttk.Combobox(row2, textvariable=self.mic_var,
                                       state="readonly", width=35)
        self.mic_combo.pack(side="left", padx=(10, 10))
        self.refresh_mic_btn = ttk.Button(row2, text="↻", width=3,
                                           command=self._load_devices)
        self.refresh_mic_btn.pack(side="left")

        row3 = ttk.Frame(mic_frame)
        row3.pack(fill="x", pady=(8, 0))
        self.test_mic_btn = ttk.Button(row3, text="🎤 Test Microphone (3s)",
                                        command=self._test_mic)
        self.test_mic_btn.pack(side="left")
        self.mic_level = ttk.Progressbar(row3, length=200, mode="determinate",
                                          maximum=100)
        self.mic_level.pack(side="left", padx=(10, 0))

        self.mic_status = ttk.Label(mic_frame, text="", font=("Segoe UI", 9))
        self.mic_status.pack(fill="x", pady=(5, 0))

        # === Hotkey ===
        hk_frame = ttk.LabelFrame(root, text="  Hotkey (Push-to-Talk)  ", padding=10)
        hk_frame.pack(fill="x", padx=15, pady=5)

        row4 = ttk.Frame(hk_frame)
        row4.pack(fill="x")
        ttk.Label(row4, text="Key:").pack(side="left")
        self.hotkey_var = tk.StringVar(value=self.config["hotkey"])
        self.hotkey_entry = ttk.Entry(row4, textvariable=self.hotkey_var, width=20)
        self.hotkey_entry.pack(side="left", padx=(10, 10))

        presets = ttk.Frame(row4)
        presets.pack(side="left")
        for label, combo in [("F9", "f9"), ("F10", "f10"), ("F8", "f8"),
                              ("Ctrl+Shift+D", "ctrl+shift+d")]:
            btn = ttk.Button(presets, text=label, width=max(len(label) + 1, 5),
                              command=lambda c=combo: self.hotkey_var.set(c))
            btn.pack(side="left", padx=2)

        ttk.Label(hk_frame, text="Hold the key to record, release to transcribe.",
                  font=("Segoe UI", 9), foreground="gray").pack(fill="x", pady=(4, 0))

        row5 = ttk.Frame(hk_frame)
        row5.pack(fill="x", pady=(6, 0))
        self.test_hk_btn = ttk.Button(row5, text="⌨ Test Hotkey",
                                       command=self._test_hotkey)
        self.test_hk_btn.pack(side="left")

        self.hotkey_status = ttk.Label(hk_frame, text="", font=("Segoe UI", 9))
        self.hotkey_status.pack(fill="x", pady=(5, 0))

        # === Controls ===
        ttk.Separator(root, orient="horizontal").pack(fill="x", padx=15, pady=8)

        ctrl_frame = ttk.Frame(root)
        ctrl_frame.pack(fill="x", padx=15, pady=5)

        self.start_btn = ttk.Button(ctrl_frame, text="▶  Start TalkFlow",
                                     command=self._toggle_service)
        self.start_btn.pack(side="left")

        self.save_btn = ttk.Button(ctrl_frame, text="💾 Save Settings",
                                    command=self._save_settings)
        self.save_btn.pack(side="right")

        # === Log ===
        log_frame = ttk.LabelFrame(root, text="  Log  ", padding=5)
        log_frame.pack(fill="both", expand=True, padx=15, pady=(5, 15))

        self.log_text = tk.Text(log_frame, height=8, wrap="word",
                                 font=("Consolas", 9), bg="#1e1e1e", fg="#cccccc",
                                 insertbackground="#cccccc")
        self.log_text.pack(fill="both", expand=True)

    def _log(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        self.log_text.insert("end", f"[{ts}] {msg}\n")
        self.log_text.see("end")

    # ------------------------------------------------------------------
    # Devices
    # ------------------------------------------------------------------
    def _load_devices(self):
        devs = list_microphones()
        self._devices = devs
        names = ["System Default"] + [d["name"] for d in devs]
        self.mic_combo["values"] = names

        saved = self.config.get("mic_device_name", "System Default")
        self.mic_var.set(saved if saved in names else "System Default")
        self._log(f"Found {len(devs)} input device(s)")

    def _get_device_index(self) -> Optional[int]:
        name = self.mic_var.get()
        if name == "System Default":
            return None
        for d in self._devices:
            if d["name"] == name:
                return d["index"]
        return None

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------
    def _test_server(self):
        self.server_status.config(text="Testing...", foreground="orange")
        self.test_server_btn.config(state="disabled")

        def done(ok, msg):
            self.root.after(0, lambda: (
                self.test_server_btn.config(state="normal"),
                self.server_status.config(text=msg,
                    foreground="green" if ok else "red"),
                self._log(msg),
            ))

        test_server(self.server_var.get(), on_done=done)

    def _test_mic(self):
        self.mic_status.config(text="Recording 3 seconds — speak!",
                                foreground="orange")
        self.test_mic_btn.config(state="disabled")
        self.mic_level["value"] = 0

        def on_level(lvl):
            self.root.after(0, lambda: self.mic_level.config(
                value=int(lvl * 100)))

        def done(ok, msg):
            self.root.after(0, lambda: (
                self.test_mic_btn.config(state="normal"),
                self.mic_status.config(text=msg,
                    foreground="green" if ok else "red"),
                self.mic_level.config(value=0),
                self._log(msg),
            ))

        test_microphone(self._get_device_index(), 3.0, on_level, done)

    def _test_hotkey(self):
        hotkey = self.hotkey_var.get().strip()
        if not hotkey:
            self.hotkey_status.config(text="Enter a hotkey first", foreground="red")
            return

        self.hotkey_status.config(
            text=f"Press and hold {hotkey} now... (10s timeout)",
            foreground="orange")
        self.test_hk_btn.config(state="disabled")
        self._log(f"Waiting for hotkey: {hotkey}")

        def on_detected():
            self.root.after(0, lambda: self._hotkey_done(True))

        self.hotkey_tester.start(hotkey, on_detected, 10.0)

        def _timeout():
            time.sleep(10.5)
            if not self.hotkey_tester._detected:
                self.root.after(0, lambda: self._hotkey_done(False))

        threading.Thread(target=_timeout, daemon=True).start()

    def _hotkey_done(self, ok):
        self.test_hk_btn.config(state="normal")
        if ok:
            self.hotkey_status.config(text="✓ Hotkey detected!", foreground="green")
            self._log("✓ Hotkey test passed")
        else:
            self.hotkey_status.config(
                text="✗ Not detected — try F9, F10, or F8",
                foreground="red")
            self._log("✗ Hotkey not detected")

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------
    def _save_settings(self):
        self.config["server"] = self.server_var.get().strip()
        self.config["hotkey"] = self.hotkey_var.get().strip()
        self.config["mic_device"] = self._get_device_index()
        self.config["mic_device_name"] = self.mic_var.get()
        save_config(self.config)
        self._log("Settings saved ✓")

    # ------------------------------------------------------------------
    # Start / Stop
    # ------------------------------------------------------------------
    def _toggle_service(self):
        if not self.is_running:
            self._start_service()
        else:
            self._stop_service()

    def _start_service(self):
        self._save_settings()

        try:
            from audio_capture import AudioCapture
            from hotkey_listener import HotkeyListener
            from keystroke_injector import KeystrokeInjector

            self._audio = AudioCapture()
            self._injector = KeystrokeInjector()
            self._server_url = self.config["server"]
            self._is_recording = False

            self._listener = HotkeyListener(
                hotkey=self.config["hotkey"],
                on_press_start=self._on_hold_start,
                on_press_stop=self._on_hold_stop,
                mode="push-to-talk",
            )
            self._listener.start()

            self.is_running = True
            self.start_btn.config(text="⏹  Stop TalkFlow")
            self.status_label.config(text="● Ready", foreground="green")
            self._log(f"TalkFlow started — hold {self.config['hotkey']} to talk")

            self.server_entry.config(state="disabled")
            self.mic_combo.config(state="disabled")
            self.hotkey_entry.config(state="disabled")

        except Exception as e:
            self._log(f"✗ Failed to start: {e}")
            messagebox.showerror("TalkFlow", f"Failed to start:\n{e}")

    def _stop_service(self):
        try:
            if hasattr(self, "_listener"):
                self._listener.stop()
            if hasattr(self, "_audio") and self._is_recording:
                self._audio.stop()
        except:
            pass

        self.is_running = False
        self._is_recording = False
        self.start_btn.config(text="▶  Start TalkFlow")
        self.status_label.config(text="● Stopped", foreground="gray")
        self._log("TalkFlow stopped")

        self.server_entry.config(state="normal")
        self.mic_combo.config(state="readonly")
        self.hotkey_entry.config(state="normal")

    # ------------------------------------------------------------------
    # Push-to-talk callbacks
    # ------------------------------------------------------------------
    def _on_hold_start(self):
        """User pressed and is holding the hotkey — start recording."""
        if self._is_recording:
            return

        # IMPORTANT: Save the currently focused window BEFORE we do anything
        # so we can inject text back into it after transcription
        self._target_hwnd = _save_foreground_window()

        self._is_recording = True

        # Start recording with selected device
        dev_idx = self._get_device_index()
        original_start = self._audio._start_sounddevice

        def patched_start():
            import sounddevice as sd
            kwargs = dict(samplerate=16000, channels=1, dtype="int16",
                          blocksize=1600,
                          callback=self._audio._sounddevice_callback)
            if dev_idx is not None:
                kwargs["device"] = dev_idx
            self._audio._sd_stream = sd.InputStream(**kwargs)
            self._audio._sd_stream.start()

        self._audio._start_sounddevice = patched_start
        self._audio.start()

        self.root.after(0, lambda: self.status_label.config(
            text="● Recording...", foreground="red"))
        self.root.after(0, lambda: self._log("⏺ Hold to speak..."))

        # Beep on Windows
        if platform.system() == "Windows":
            try:
                import winsound
                threading.Thread(target=lambda: winsound.Beep(800, 100),
                                 daemon=True).start()
            except:
                pass

    def _on_hold_stop(self):
        """User released the hotkey — stop recording and transcribe."""
        if not self._is_recording:
            return

        audio_bytes = self._audio.stop()
        self._is_recording = False

        self.root.after(0, lambda: self.status_label.config(
            text="● Transcribing...", foreground="orange"))

        # Beep on Windows
        if platform.system() == "Windows":
            try:
                import winsound
                threading.Thread(target=lambda: winsound.Beep(600, 100),
                                 daemon=True).start()
            except:
                pass

        n_bytes = len(audio_bytes)
        if n_bytes < 3200:
            self.root.after(0, lambda: self._log("⚠ Too short — skipped"))
            self.root.after(0, lambda: self.status_label.config(
                text="● Ready", foreground="green"))
            return

        duration_s = n_bytes / (16000 * 2)
        self.root.after(0, lambda: self._log(
            f"⏹ Released ({duration_s:.1f}s) — transcribing..."))

        # Save the target window handle for the background thread
        target_hwnd = self._target_hwnd

        threading.Thread(
            target=self._send_and_inject,
            args=(audio_bytes, target_hwnd),
            daemon=True
        ).start()

    # ------------------------------------------------------------------
    # Network + injection
    # ------------------------------------------------------------------
    def _send_and_inject(self, audio_bytes: bytes, target_hwnd=None):
        try:
            from websockets.sync.client import connect as ws_connect
        except ImportError:
            self.root.after(0, lambda: self._log("✗ websockets not installed"))
            return

        ws_url = f"ws://{self._server_url}/ws/dictate"

        try:
            with ws_connect(ws_url) as ws:
                total = len(audio_bytes)
                sent = 0
                while sent < total:
                    chunk = audio_bytes[sent:sent + 65536]
                    ws.send(chunk)
                    sent += len(chunk)

                ws.send(json.dumps({"action": "transcribe"}))
                raw = ws.recv(timeout=30.0)
                response = json.loads(raw)

        except Exception as exc:
            self.root.after(0, lambda: self._log(f"✗ Connection error: {exc}"))
            self.root.after(0, lambda: self.status_label.config(
                text="● Ready", foreground="green"))
            return

        if response.get("type") == "error":
            msg = response.get("message", "Unknown")
            self.root.after(0, lambda: self._log(f"✗ Server error: {msg}"))
            self.root.after(0, lambda: self.status_label.config(
                text="● Ready", foreground="green"))
            return

        text = response.get("text", "").strip()
        proc_time = response.get("process_time", 0)

        if not text:
            self.root.after(0, lambda: self._log("⚠ No speech detected"))
            self.root.after(0, lambda: self.status_label.config(
                text="● Ready", foreground="green"))
            return

        self.root.after(0, lambda: self._log(f"✓ [{proc_time:.2f}s] {text}"))
        self.root.after(0, lambda: self.status_label.config(
            text="● Ready", foreground="green"))

        # Restore focus to the original window BEFORE injecting text
        _restore_foreground_window(target_hwnd)

        # Small delay to let focus settle
        time.sleep(0.1)

        try:
            self._injector.type_text(text)
        except Exception as exc:
            self.root.after(0, lambda: self._log(f"✗ Injection failed: {exc}"))

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------
    def run(self):
        self._log("TalkFlow ready — configure and press Start")
        self._log(f"Server: {self.config['server']}")
        self._log(f"Hotkey: {self.config['hotkey']} (push-to-talk)")
        self.root.mainloop()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    app = TalkFlowGUI()
    app.run()


if __name__ == "__main__":
    main()
