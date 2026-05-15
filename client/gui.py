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
  - System tray support (Windows and Linux with libappindicator)
  - Cross-platform sound notifications
  - Saves settings to config.json

Platform notes:
  - Windows: Full support, no additional setup required
  - Linux: Requires xdotool (X11) or ydotool/wtype (Wayland) for text injection
           Requires libappindicator for system tray icon
  - macOS: Requires Accessibility permission for text injection
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
from typing import Optional, Callable, Set

import tkinter as tk
from tkinter import ttk, messagebox

# System tray support (optional)
# On Linux, requires libappindicator or similar tray implementation
try:
    import pystray
    from PIL import Image, ImageDraw
    TRAY_AVAILABLE = True
except ImportError:
    TRAY_AVAILABLE = False

# Cross-platform sound support
import shutil
import subprocess

# Text post-processing
from text_processor import clean_transcription


def _play_beep(frequency: int = 800, duration_ms: int = 100) -> None:
    """
    Play a beep sound cross-platform.
    - Windows: uses winsound.Beep
    - Linux: uses paplay with generated tone, or falls back to bell
    - macOS: uses afplay or system bell
    """
    system = platform.system()

    if system == "Windows":
        try:
            import winsound
            winsound.Beep(frequency, duration_ms)
        except Exception:
            pass

    elif system == "Linux":
        # Try paplay (PulseAudio) with a simple beep
        try:
            # Generate a simple WAV beep in memory using numpy if available
            import numpy as np
            import io
            import wave

            sample_rate = 44100
            duration = duration_ms / 1000.0
            t = np.linspace(0, duration, int(sample_rate * duration), False)
            tone = np.sin(frequency * 2 * np.pi * t)
            # Apply fade in/out to avoid clicks
            fade_samples = int(sample_rate * 0.01)
            tone[:fade_samples] *= np.linspace(0, 1, fade_samples)
            tone[-fade_samples:] *= np.linspace(1, 0, fade_samples)
            # Scale to 16-bit
            audio = (tone * 32767).astype(np.int16)

            # Write to bytes buffer
            buffer = io.BytesIO()
            with wave.open(buffer, 'wb') as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(sample_rate)
                wav.writeframes(audio.tobytes())

            wav_data = buffer.getvalue()

            # Try paplay first, then aplay
            if shutil.which("paplay"):
                proc = subprocess.Popen(
                    ["paplay", "--raw", "--channels=1", "--format=s16le", f"--rate={sample_rate}"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                proc.communicate(input=audio.tobytes())
            elif shutil.which("aplay"):
                proc = subprocess.Popen(
                    ["aplay", "-q", "-f", "S16_LE", "-r", str(sample_rate), "-c", "1"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                proc.communicate(input=audio.tobytes())
            else:
                # Fallback: terminal bell
                print("\a", end="", flush=True)
        except ImportError:
            # No numpy, use terminal bell
            print("\a", end="", flush=True)
        except Exception:
            pass

    elif system == "Darwin":
        # macOS: use afplay with system sounds or terminal bell
        try:
            # Try to play system sound
            sound_file = "/System/Library/Sounds/Tink.aiff"
            if os.path.exists(sound_file):
                subprocess.run(
                    ["afplay", sound_file],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                print("\a", end="", flush=True)
        except Exception:
            print("\a", end="", flush=True)

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
    # Transcription backend: "groq" (cloud, fast) or "server" (self-hosted)
    "backend": "groq",
    "groq_api_key": os.getenv("GROQ_API_KEY", ""),

    # Server settings (for self-hosted backend)
    "server": os.getenv("TALKFLOW_SERVER", "YOUR_SERVER:9876"),

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
# System Tray Support
# ---------------------------------------------------------------------------
def _create_tray_icon_image(size: int = 64, recording: bool = False) -> "Image.Image":
    """Create a simple microphone icon for the system tray."""
    if not TRAY_AVAILABLE:
        return None

    # Create image with transparent background
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # Colors
    if recording:
        main_color = (220, 50, 50, 255)   # Red when recording
    else:
        main_color = (70, 130, 180, 255)  # Steel blue normally

    # Draw microphone body (rounded rectangle)
    mic_left = size * 0.3
    mic_right = size * 0.7
    mic_top = size * 0.1
    mic_bottom = size * 0.55
    draw.rounded_rectangle(
        [mic_left, mic_top, mic_right, mic_bottom],
        radius=size * 0.15,
        fill=main_color
    )

    # Draw microphone stand arc
    arc_left = size * 0.2
    arc_right = size * 0.8
    arc_top = size * 0.35
    arc_bottom = size * 0.75
    draw.arc(
        [arc_left, arc_top, arc_right, arc_bottom],
        start=0, end=180,
        fill=main_color,
        width=max(2, size // 16)
    )

    # Draw stand pole
    pole_x = size * 0.5
    pole_top = size * 0.75
    pole_bottom = size * 0.9
    draw.line(
        [(pole_x, pole_top), (pole_x, pole_bottom)],
        fill=main_color,
        width=max(2, size // 16)
    )

    # Draw base
    base_left = size * 0.35
    base_right = size * 0.65
    base_y = size * 0.9
    draw.line(
        [(base_left, base_y), (base_right, base_y)],
        fill=main_color,
        width=max(2, size // 16)
    )

    return image


class SystemTrayManager:
    """Manages the system tray icon and menu."""

    def __init__(
        self,
        on_show: Callable[[], None],
        on_toggle: Callable[[], None],
        on_exit: Callable[[], None],
    ):
        self._on_show = on_show
        self._on_toggle = on_toggle
        self._on_exit = on_exit
        self._icon: Optional[pystray.Icon] = None
        self._is_recording = False

    def _load_icon_image(self, recording: bool = False):
        """Load icon from file or generate fallback."""
        # Try to load logo.ico or logo PNG
        icon_path = ASSETS_DIR / "logo.ico"
        png_path = ASSETS_DIR / "logo-64x64.png"

        try:
            if icon_path.exists():
                img = Image.open(icon_path)
                # Apply red tint if recording
                if recording:
                    img = img.convert("RGBA")
                    # Simple red tint for recording state
                    pixels = img.load()
                    for y in range(img.height):
                        for x in range(img.width):
                            r, g, b, a = pixels[x, y]
                            if a > 0:  # Only modify non-transparent pixels
                                pixels[x, y] = (min(255, r + 100), g // 2, b // 2, a)
                return img
            elif png_path.exists():
                img = Image.open(png_path)
                if recording:
                    img = img.convert("RGBA")
                    pixels = img.load()
                    for y in range(img.height):
                        for x in range(img.width):
                            r, g, b, a = pixels[x, y]
                            if a > 0:
                                pixels[x, y] = (min(255, r + 100), g // 2, b // 2, a)
                return img
        except Exception as e:
            log.debug("Could not load tray icon: %s", e)

        # Fallback to generated icon
        return _create_tray_icon_image(recording=recording)

    def start(self) -> None:
        """Start the system tray icon in a background thread."""
        if not TRAY_AVAILABLE:
            log.warning("System tray not available (pystray/PIL not installed)")
            return

        def _run_tray():
            menu = pystray.Menu(
                pystray.MenuItem("Show", self._on_show, default=True),
                pystray.MenuItem("Start/Stop", self._on_toggle),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit", self._on_exit),
            )

            self._icon = pystray.Icon(
                "TalkFlow",
                self._load_icon_image(),
                "TalkFlow - Ready",
                menu,
            )
            self._icon.run()

        threading.Thread(target=_run_tray, daemon=True).start()
        log.info("System tray icon started")

    def stop(self) -> None:
        """Stop and remove the system tray icon."""
        if self._icon:
            try:
                self._icon.stop()
            except Exception as e:
                log.debug("Error stopping tray icon: %s", e)
            self._icon = None

    def update_status(self, status: str, recording: bool = False) -> None:
        """Update the tray icon tooltip and appearance."""
        if not self._icon:
            return

        self._is_recording = recording
        try:
            self._icon.icon = self._load_icon_image(recording=recording)
            self._icon.title = f"TalkFlow - {status}"
        except Exception as e:
            log.debug("Error updating tray icon: %s", e)


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
# Hotkey Recorder Dialog
# ---------------------------------------------------------------------------
def _key_name(key) -> str | None:
    """Extract key name from pynput key object."""
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


class HotkeyRecorderDialog:
    """Dialog for recording custom hotkey combinations."""

    def __init__(self, parent: tk.Tk, current_hotkey: str, on_save: Callable[[str], None]):
        self._on_save = on_save
        self._pressed_keys: Set[str] = set()
        self._peak_keys: Set[str] = set()  # Track the maximum combo pressed
        self._recorded_combo: str = ""
        self._listener = None
        self._finalized = False  # Prevent re-finalization

        # Create toplevel dialog
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Record Hotkey")
        self.dialog.geometry("400x220")
        self.dialog.resizable(False, False)
        self.dialog.transient(parent)
        self.dialog.grab_set()

        # Center on parent
        self.dialog.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - 400) // 2
        y = parent.winfo_y() + (parent.winfo_height() - 220) // 2
        self.dialog.geometry(f"+{x}+{y}")

        self._build_ui(current_hotkey)
        self.dialog.protocol("WM_DELETE_WINDOW", self._on_cancel)

    def _build_ui(self, current_hotkey: str):
        frame = ttk.Frame(self.dialog, padding=20)
        frame.pack(fill="both", expand=True)

        # Current hotkey display
        ttk.Label(frame, text="Current hotkey:", font=("Segoe UI", 10)).pack(anchor="w")
        ttk.Label(frame, text=current_hotkey.upper(), font=("Segoe UI", 12, "bold"),
                  foreground="gray").pack(anchor="w", pady=(0, 15))

        # Instructions
        ttk.Label(frame, text="Press the key combination you want to use:",
                  font=("Segoe UI", 10)).pack(anchor="w")

        # Recording display
        self.combo_var = tk.StringVar(value="Press any key combo...")
        self.combo_label = ttk.Label(frame, textvariable=self.combo_var,
                                      font=("Segoe UI", 16, "bold"),
                                      foreground="blue")
        self.combo_label.pack(pady=15)

        # Status
        self.status_var = tk.StringVar(value="Listening for keys...")
        self.status_label = ttk.Label(frame, textvariable=self.status_var,
                                       font=("Segoe UI", 9), foreground="orange")
        self.status_label.pack()

        # Buttons
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill="x", pady=(15, 0))

        self.save_btn = ttk.Button(btn_frame, text="Save", command=self._on_confirm,
                                    state="disabled")
        self.save_btn.pack(side="right", padx=(5, 0))

        ttk.Button(btn_frame, text="Cancel", command=self._on_cancel).pack(side="right")

        self.clear_btn = ttk.Button(btn_frame, text="Clear", command=self._clear_combo)
        self.clear_btn.pack(side="left")

        # Start listening
        self._start_listener()

    def _start_listener(self):
        """Start the keyboard listener to capture key combinations."""
        from pynput import keyboard

        def on_press(key):
            name = _key_name(key)
            if name:
                self._pressed_keys.add(name)
                # Track the peak (maximum) combo - more keys = better combo
                if len(self._pressed_keys) > len(self._peak_keys):
                    self._peak_keys = self._pressed_keys.copy()
                    self._finalized = False  # New peak, allow re-finalization
                self._update_display()

        def on_release(key):
            name = _key_name(key)
            if name:
                self._pressed_keys.discard(name)
                # Finalize when all keys are released (use the peak combo)
                if not self._pressed_keys and self._peak_keys and not self._finalized:
                    self._finalize_combo()

        self._listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        self._listener.daemon = True
        self._listener.start()

    def _update_display(self):
        """Update the display with the peak combo being recorded."""
        # Show the peak combo (maximum keys pressed), not just currently held
        display_keys = self._peak_keys if self._peak_keys else self._pressed_keys
        if not display_keys:
            self.combo_var.set("Press any key combo...")
            return

        # Sort keys: modifiers first, then regular keys
        modifiers = {"ctrl_l", "ctrl_r", "ctrl", "alt_l", "alt_r", "alt",
                     "shift", "shift_l", "shift_r", "cmd", "cmd_l", "cmd_r"}
        mods = sorted([k for k in display_keys if k in modifiers])
        others = sorted([k for k in display_keys if k not in modifiers])

        # Normalize display names
        display_parts = []
        for k in mods + others:
            display = k.replace("_l", "").replace("_r", "").upper()
            if display == "CMD":
                display = "WIN" if platform.system() == "Windows" else "CMD"
            display_parts.append(display)

        display_str = " + ".join(display_parts)
        self.combo_var.set(display_str)

    def _finalize_combo(self):
        """Finalize the recorded combo using the peak keys pressed."""
        if not self._peak_keys:
            return

        # Build the hotkey string for config using the peak combo
        modifiers_order = ["ctrl", "alt", "shift", "cmd"]
        mods_found = []
        others = []

        for key in self._peak_keys:
            normalized = key.replace("_l", "").replace("_r", "")
            if normalized in modifiers_order:
                if normalized not in mods_found:
                    mods_found.append(normalized)
            else:
                others.append(key)

        # Sort modifiers in standard order
        mods_sorted = [m for m in modifiers_order if m in mods_found]
        combo_parts = mods_sorted + sorted(others)

        self._recorded_combo = "+".join(combo_parts)
        self._finalized = True  # Mark as finalized to prevent re-recording

        # Update UI
        self.status_var.set(f"Recorded: {self._recorded_combo}")
        self.status_label.config(foreground="green")
        self.save_btn.config(state="normal")

    def _clear_combo(self):
        """Clear the recorded combo and restart listening."""
        self._pressed_keys.clear()
        self._peak_keys.clear()
        self._recorded_combo = ""
        self._finalized = False
        self.combo_var.set("Press any key combo...")
        self.status_var.set("Listening for keys...")
        self.status_label.config(foreground="orange")
        self.save_btn.config(state="disabled")

    def _on_confirm(self):
        """Save the recorded hotkey and close."""
        if self._recorded_combo:
            self._on_save(self._recorded_combo)
        self._cleanup()
        self.dialog.destroy()

    def _on_cancel(self):
        """Cancel and close the dialog."""
        self._cleanup()
        self.dialog.destroy()

    def _cleanup(self):
        """Stop the keyboard listener."""
        if self._listener:
            self._listener.stop()
            self._listener = None


# ---------------------------------------------------------------------------
# Version and branding
# ---------------------------------------------------------------------------
VERSION = "2.0"
ASSETS_DIR = Path(__file__).parent / "assets"


# ---------------------------------------------------------------------------
# About Dialog
# ---------------------------------------------------------------------------
class AboutDialog:
    """Professional About dialog with logo and branding."""

    def __init__(self, parent: tk.Tk):
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("About TalkFlow")
        self.dialog.geometry("420x480")
        self.dialog.resizable(False, False)
        self.dialog.transient(parent)
        self.dialog.grab_set()

        # Center on parent
        self.dialog.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - 420) // 2
        y = parent.winfo_y() + (parent.winfo_height() - 480) // 2
        self.dialog.geometry(f"+{x}+{y}")

        self._build_ui()

    def _build_ui(self):
        # Main frame with padding
        frame = ttk.Frame(self.dialog, padding=30)
        frame.pack(fill="both", expand=True)

        # Try to load logo
        logo_loaded = False
        try:
            from PIL import Image, ImageTk
            logo_path = ASSETS_DIR / "logo-128x128.png"
            if logo_path.exists():
                img = Image.open(logo_path)
                self._logo_photo = ImageTk.PhotoImage(img)
                logo_label = ttk.Label(frame, image=self._logo_photo)
                logo_label.pack(pady=(0, 15))
                logo_loaded = True
        except ImportError:
            pass

        if not logo_loaded:
            # Fallback: text-based logo
            ttk.Label(frame, text="🎙", font=("Segoe UI", 48)).pack(pady=(0, 10))

        # App name
        ttk.Label(frame, text="TalkFlow",
                  font=("Segoe UI", 24, "bold")).pack()

        # Version
        ttk.Label(frame, text=f"Version {VERSION}",
                  font=("Segoe UI", 12), foreground="gray").pack(pady=(5, 20))

        # Description
        desc = ttk.Label(frame,
                         text="Push-to-talk voice dictation.\n"
                              "Hold your hotkey, speak, release —\n"
                              "text appears wherever your cursor is.",
                         font=("Segoe UI", 10),
                         justify="center")
        desc.pack(pady=(0, 20))

        # Separator
        ttk.Separator(frame, orient="horizontal").pack(fill="x", pady=10)

        # Features
        features_frame = ttk.Frame(frame)
        features_frame.pack(fill="x", pady=10)

        features = [
            "Real-time speech transcription",
            "Universal hotkey support",
            "System tray integration",
            "Automatic text injection",
        ]
        for feature in features:
            ttk.Label(features_frame, text=f"  •  {feature}",
                      font=("Segoe UI", 9), foreground="#0891b2").pack(anchor="w")

        # Separator
        ttk.Separator(frame, orient="horizontal").pack(fill="x", pady=15)

        # AI branding
        ai_frame = ttk.Frame(frame)
        ai_frame.pack(pady=(5, 15))

        ttk.Label(ai_frame, text="AI Implemented",
                  font=("Segoe UI", 11, "bold"), foreground="#0d9488").pack()
        ttk.Label(ai_frame, text="Built with Claude by Anthropic",
                  font=("Segoe UI", 9), foreground="gray").pack()

        # Copyright
        ttk.Label(frame, text="© 2026 TalkFlow",
                  font=("Segoe UI", 8), foreground="gray").pack(pady=(10, 0))

        # Close button
        ttk.Button(frame, text="Close", command=self.dialog.destroy,
                   width=12).pack(pady=(15, 0))


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
        self._tray_manager: Optional[SystemTrayManager] = None
        self._is_hidden = False

        self.root = tk.Tk()
        self.root.title("TalkFlow")
        self.root.geometry("520x700")
        self.root.resizable(False, False)

        # Set window icon (taskbar and title bar)
        self._set_window_icon()

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

        # Setup system tray (Windows and Linux with libappindicator)
        # On Linux, requires libappindicator or ayatana-appindicator
        if TRAY_AVAILABLE and platform.system() in ("Windows", "Linux"):
            self._setup_system_tray()

        # Handle window close button
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Handle minimize button - hide to tray instead of taskbar
        self.root.bind("<Unmap>", self._on_minimize)

    def _set_window_icon(self):
        """Set the window icon for taskbar and title bar."""
        icon_path = ASSETS_DIR / "logo.ico"
        png_path = ASSETS_DIR / "logo-256x256.png"

        try:
            if platform.system() == "Windows" and icon_path.exists():
                # Windows: use .ico file
                self.root.iconbitmap(str(icon_path))
            elif png_path.exists():
                # Linux/macOS: use PNG with PhotoImage
                from PIL import Image, ImageTk
                img = Image.open(png_path)
                self._icon_photo = ImageTk.PhotoImage(img)
                self.root.iconphoto(True, self._icon_photo)
        except Exception as e:
            log.debug("Could not set window icon: %s", e)

    def _build_ui(self):
        root = self.root

        # Header
        header = ttk.Frame(root)
        header.pack(fill="x", padx=15, pady=(15, 5))
        ttk.Label(header, text="🎙 TalkFlow",
                  font=("Segoe UI", 18, "bold")).pack(side="left")

        # About button (small, unobtrusive)
        self.about_btn = ttk.Button(header, text="ℹ", width=3,
                                     command=self._show_about)
        self.about_btn.pack(side="left", padx=(10, 0))

        self.status_label = ttk.Label(header, text="● Stopped", foreground="gray",
                                       font=("Segoe UI", 11))
        self.status_label.pack(side="right")

        ttk.Separator(root, orient="horizontal").pack(fill="x", padx=15, pady=5)

        # === Transcription Backend ===
        backend_frame = ttk.LabelFrame(root, text="  Transcription  ", padding=10)
        backend_frame.pack(fill="x", padx=15, pady=5)

        # Backend selection row
        backend_row = ttk.Frame(backend_frame)
        backend_row.pack(fill="x")
        ttk.Label(backend_row, text="Backend:").pack(side="left")
        self.backend_var = tk.StringVar(value=self.config.get("backend", "groq"))
        self.backend_combo = ttk.Combobox(
            backend_row, textvariable=self.backend_var,
            values=["Groq Cloud (Fast)", "Self-Hosted Server"],
            state="readonly", width=20
        )
        # Set display value based on config
        if self.config.get("backend", "groq") == "groq":
            self.backend_combo.set("Groq Cloud (Fast)")
        else:
            self.backend_combo.set("Self-Hosted Server")
        self.backend_combo.pack(side="left", padx=(10, 0))
        self.backend_combo.bind("<<ComboboxSelected>>", self._on_backend_change)

        # Groq API key row
        api_row = ttk.Frame(backend_frame)
        api_row.pack(fill="x", pady=(8, 0))
        ttk.Label(api_row, text="Groq API Key:").pack(side="left")
        self.groq_key_var = tk.StringVar(value=self.config.get("groq_api_key", ""))
        self.groq_key_entry = ttk.Entry(api_row, textvariable=self.groq_key_var, width=40, show="*")
        self.groq_key_entry.pack(side="left", padx=(10, 0))
        self.show_key_btn = ttk.Button(api_row, text="👁", width=3, command=self._toggle_key_visibility)
        self.show_key_btn.pack(side="left", padx=(5, 0))

        self.backend_status = ttk.Label(backend_frame, text="", font=("Segoe UI", 9))
        self.backend_status.pack(fill="x", pady=(5, 0))

        # === Server (for self-hosted backend) ===
        self.srv_frame = ttk.LabelFrame(root, text="  Server (Self-Hosted)  ", padding=10)
        self.srv_frame.pack(fill="x", padx=15, pady=5)

        row = ttk.Frame(self.srv_frame)
        row.pack(fill="x")
        ttk.Label(row, text="Address:").pack(side="left")
        self.server_var = tk.StringVar(value=self.config["server"])
        self.server_entry = ttk.Entry(row, textvariable=self.server_var, width=30)
        self.server_entry.pack(side="left", padx=(10, 10))
        self.test_server_btn = ttk.Button(row, text="Test Connection",
                                           command=self._test_server)
        self.test_server_btn.pack(side="right")

        self.server_status = ttk.Label(self.srv_frame, text="", font=("Segoe UI", 9))
        self.server_status.pack(fill="x", pady=(5, 0))

        # Update server section visibility based on backend
        self._update_backend_ui()

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
        for label, combo in HOTKEY_PRESETS[:4]:  # Show first 4 presets
            btn = ttk.Button(presets, text=label, width=max(len(label) + 1, 5),
                              command=lambda c=combo: self.hotkey_var.set(c))
            btn.pack(side="left", padx=2)

        ttk.Label(hk_frame, text="Hold the key to record, release to transcribe. "
                  "Supports any combo (e.g., ctrl+win, ctrl+alt+v).",
                  font=("Segoe UI", 9), foreground="gray", wraplength=480).pack(fill="x", pady=(4, 0))

        row5 = ttk.Frame(hk_frame)
        row5.pack(fill="x", pady=(6, 0))
        self.test_hk_btn = ttk.Button(row5, text="⌨ Test Hotkey",
                                       command=self._test_hotkey)
        self.test_hk_btn.pack(side="left")

        self.record_hk_btn = ttk.Button(row5, text="🎹 Record Hotkey",
                                         command=self._record_hotkey)
        self.record_hk_btn.pack(side="left", padx=(10, 0))

        self.hotkey_status = ttk.Label(hk_frame, text="", font=("Segoe UI", 9))
        self.hotkey_status.pack(fill="x", pady=(5, 0))

        # === Preferences ===
        pref_frame = ttk.LabelFrame(root, text="  Preferences  ", padding=10)
        pref_frame.pack(fill="x", padx=15, pady=5)

        # Row 1: Minimize to tray + Start minimized
        pref_row1 = ttk.Frame(pref_frame)
        pref_row1.pack(fill="x")

        self.minimize_to_tray_var = tk.BooleanVar(
            value=self.config.get("minimize_to_tray", True))
        tray_check = ttk.Checkbutton(
            pref_row1, text="Minimize to system tray",
            variable=self.minimize_to_tray_var,
            command=self._on_pref_change)
        tray_check.pack(side="left")

        if not TRAY_AVAILABLE:
            tray_check.config(state="disabled")
            ttk.Label(pref_row1, text="(requires pystray)",
                      font=("Segoe UI", 8), foreground="gray").pack(side="left", padx=(5, 0))

        self.play_sounds_var = tk.BooleanVar(
            value=self.config.get("play_sounds", True))
        ttk.Checkbutton(
            pref_row1, text="Play sounds",
            variable=self.play_sounds_var,
            command=self._on_pref_change).pack(side="right")

        # Row 2: Auto-start
        pref_row2 = ttk.Frame(pref_frame)
        pref_row2.pack(fill="x", pady=(4, 0))

        self.auto_start_var = tk.BooleanVar(
            value=self.config.get("auto_start_on_launch", False))
        ttk.Checkbutton(
            pref_row2, text="Auto-start on launch",
            variable=self.auto_start_var,
            command=self._on_pref_change).pack(side="left")

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

    def _show_about(self):
        """Show the About dialog."""
        AboutDialog(self.root)

    # ------------------------------------------------------------------
    # System Tray
    # ------------------------------------------------------------------
    def _setup_system_tray(self):
        """Initialize system tray icon and callbacks."""
        self._tray_manager = SystemTrayManager(
            on_show=self._show_window,
            on_toggle=self._toggle_service,
            on_exit=self._exit_app,
        )
        self._tray_manager.start()

    def _show_window(self):
        """Show and bring window to front."""
        self._is_hidden = False
        self.root.after(0, lambda: (
            self.root.deiconify(),
            self.root.lift(),
            self.root.focus_force(),
        ))

    def _hide_to_tray(self):
        """Hide window to system tray."""
        if not TRAY_AVAILABLE or not self._tray_manager:
            return False
        self._is_hidden = True
        self.root.withdraw()
        self._log("Minimized to system tray")
        return True

    def _on_minimize(self, event):
        """Handle minimize button - hide to tray instead of taskbar."""
        # Only handle if the window is being iconified (minimized)
        if event.widget != self.root:
            return
        if not self.root.winfo_viewable():
            return
        # Check if minimize to tray is enabled
        if (self.config.get("minimize_to_tray", True) and
            TRAY_AVAILABLE and self._tray_manager):
            # Schedule hide after tkinter processes the iconify
            self.root.after(10, self._hide_to_tray)

    def _on_close(self):
        """Handle window close button - minimize to tray or exit."""
        if (self.config.get("minimize_to_tray", True) and
            TRAY_AVAILABLE and self._tray_manager):
            self._hide_to_tray()
        else:
            self._exit_app()

    def _exit_app(self):
        """Clean shutdown - stop service, tray, and exit."""
        self._log("Shutting down...")

        # Stop the service if running
        if self.is_running:
            self._stop_service()

        # Stop system tray
        if self._tray_manager:
            self._tray_manager.stop()

        # Quit tkinter
        self.root.after(100, self.root.quit)

    def _update_tray_status(self, status: str, recording: bool = False):
        """Update tray icon status."""
        if self._tray_manager:
            self._tray_manager.update_status(status, recording)

    # ------------------------------------------------------------------
    # Preferences
    # ------------------------------------------------------------------
    def _on_pref_change(self):
        """Handle preference checkbox changes - auto-save."""
        self.config["minimize_to_tray"] = self.minimize_to_tray_var.get()
        self.config["play_sounds"] = self.play_sounds_var.get()
        self.config["auto_start_on_launch"] = self.auto_start_var.get()
        save_config(self.config)

    # ------------------------------------------------------------------
    # Backend selection
    # ------------------------------------------------------------------
    def _on_backend_change(self, event=None):
        """Handle backend dropdown change."""
        selection = self.backend_combo.get()
        if "Groq" in selection:
            self.config["backend"] = "groq"
        else:
            self.config["backend"] = "server"
        self._update_backend_ui()
        save_config(self.config)

    def _update_backend_ui(self):
        """Show/hide UI elements based on selected backend."""
        is_groq = self.config.get("backend", "groq") == "groq"

        # Show/hide server section
        if is_groq:
            self.srv_frame.pack_forget()
            self.groq_key_entry.config(state="normal")
            self.backend_status.config(
                text="Using Groq Cloud — fast transcription via API",
                foreground="green"
            )
        else:
            # Re-pack server frame after backend frame
            self.srv_frame.pack(fill="x", padx=15, pady=5, after=self.backend_combo.master.master)
            self.groq_key_entry.config(state="disabled")
            self.backend_status.config(
                text="Using self-hosted server — configure address below",
                foreground="blue"
            )

    def _toggle_key_visibility(self):
        """Toggle API key visibility."""
        current = self.groq_key_entry.cget("show")
        if current == "*":
            self.groq_key_entry.config(show="")
            self.show_key_btn.config(text="🔒")
        else:
            self.groq_key_entry.config(show="*")
            self.show_key_btn.config(text="👁")

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

    def _record_hotkey(self):
        """Open the hotkey recorder dialog."""
        current = self.hotkey_var.get().strip() or "f9"

        def on_save(new_hotkey: str):
            self.hotkey_var.set(new_hotkey)
            self._apply_recorded_hotkey(new_hotkey)

        HotkeyRecorderDialog(self.root, current, on_save)

    def _apply_recorded_hotkey(self, new_hotkey: str):
        """Apply the new hotkey: save to config and reload listener if running."""
        # Update config
        self.config["hotkey"] = new_hotkey
        save_config(self.config)
        self._log(f"Hotkey changed to: {new_hotkey}")
        self.hotkey_status.config(text=f"✓ Saved: {new_hotkey}", foreground="green")

        # Reload hotkey listener if service is running
        if self.is_running:
            self._reload_hotkey(new_hotkey)

    def _reload_hotkey(self, new_hotkey: str):
        """Reload the hotkey listener with a new hotkey without restarting the service."""
        from hotkey_listener import HotkeyListener

        # Stop the old listener
        if hasattr(self, "_listener") and self._listener:
            self._listener.stop()
            self._log("Hotkey listener stopped for reload")

        # Create and start a new listener with the new hotkey
        self._listener = HotkeyListener(
            hotkey=new_hotkey,
            on_press_start=self._on_hold_start,
            on_press_stop=self._on_hold_stop,
            mode="push-to-talk",
        )
        self._listener.start()
        self._log(f"Hotkey listener reloaded — now using: {new_hotkey}")

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------
    def _save_settings(self):
        # Backend settings
        selection = self.backend_combo.get()
        self.config["backend"] = "groq" if "Groq" in selection else "server"
        self.config["groq_api_key"] = self.groq_key_var.get().strip()

        # Server settings
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
            self._last_text: str = ""          # for punctuation continuity
            self._last_text_time: float = 0.0  # timestamp of last transcription

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
            self._update_tray_status("Ready")
            self._log(f"TalkFlow started — hold {self.config['hotkey']} to talk")

            self.server_entry.config(state="disabled")
            self.mic_combo.config(state="disabled")
            self.hotkey_entry.config(state="disabled")

            # Auto-minimize to tray when started (runs in background)
            if TRAY_AVAILABLE and self._tray_manager:
                self.root.after(500, self._hide_to_tray)

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
        self._update_tray_status("Stopped")
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
        self.root.after(0, lambda: self._update_tray_status("Recording...", recording=True))
        self.root.after(0, lambda: self._log("⏺ Hold to speak..."))

        # Play start beep (if sounds enabled)
        if self.config.get("play_sounds", True):
            threading.Thread(target=lambda: _play_beep(800, 100), daemon=True).start()

    def _on_hold_stop(self):
        """User released the hotkey — stop recording and transcribe."""
        if not self._is_recording:
            return

        audio_bytes = self._audio.stop()
        self._is_recording = False

        self.root.after(0, lambda: self.status_label.config(
            text="● Transcribing...", foreground="orange"))
        self.root.after(0, lambda: self._update_tray_status("Transcribing..."))

        # Play stop beep (if sounds enabled)
        if self.config.get("play_sounds", True):
            threading.Thread(target=lambda: _play_beep(600, 100), daemon=True).start()

        n_bytes = len(audio_bytes)
        if n_bytes < 3200:
            self.root.after(0, lambda: self._log("⚠ Too short — skipped"))
            self.root.after(0, lambda: self.status_label.config(
                text="● Ready", foreground="green"))
            self.root.after(0, lambda: self._update_tray_status("Ready"))
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
        backend = self.config.get("backend", "groq")

        # Build context prompt for punctuation continuity (clear if > 30s since last chunk)
        now = time.time()
        initial_prompt = self._last_text if (now - self._last_text_time) < 30.0 else ""

        if backend == "groq":
            response = self._transcribe_groq(audio_bytes, initial_prompt=initial_prompt)
        else:
            response = self._transcribe_server(audio_bytes)

        if response is None:
            return

        # Handle errors
        if response.get("error"):
            error_msg = response["error"]
            self.root.after(0, lambda e=error_msg: self._log(f"✗ {e}"))
            self.root.after(0, lambda: self.status_label.config(
                text="● Ready", foreground="green"))
            self.root.after(0, lambda: self._update_tray_status("Ready"))
            return

        text = response.get("text", "").strip()
        proc_time = response.get("process_time", 0)

        if not text:
            self.root.after(0, lambda: self._log("⚠ No speech detected"))
            self.root.after(0, lambda: self.status_label.config(
                text="● Ready", foreground="green"))
            self.root.after(0, lambda: self._update_tray_status("Ready"))
            return

        backend_label = "Groq" if backend == "groq" else "Server"
        self.root.after(0, lambda: self._log(f"✓ [{proc_time:.2f}s] {text}"))
        self.root.after(0, lambda: self.status_label.config(
            text="● Ready", foreground="green"))
        self.root.after(0, lambda: self._update_tray_status("Ready"))

        # Restore focus to the original window BEFORE injecting text
        _restore_foreground_window(target_hwnd)

        # Small delay to let focus settle
        time.sleep(0.1)

        try:
            cleaned_text = clean_transcription(text)
            # Update context for next chunk (punctuation continuity)
            self._last_text = (self._last_text + " " + cleaned_text).strip()[-900:]
            self._last_text_time = time.time()
            self._injector.type_text(cleaned_text + " ")
        except Exception as exc:
            self.root.after(0, lambda: self._log(f"✗ Injection failed: {exc}"))

    def _transcribe_groq(self, audio_bytes: bytes, initial_prompt: str = "") -> dict:
        """Transcribe using Groq Cloud API."""
        from groq_transcribe import transcribe_audio

        api_key = self.config.get("groq_api_key", "")
        if not api_key:
            return {"error": "Groq API key not configured", "text": "", "process_time": 0}

        return transcribe_audio(audio_bytes, api_key, initial_prompt=initial_prompt or None)

    def _transcribe_server(self, audio_bytes: bytes) -> dict:
        """Transcribe using self-hosted WebSocket server."""
        try:
            from websockets.sync.client import connect as ws_connect
        except ImportError:
            return {"error": "websockets not installed", "text": "", "process_time": 0}

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

            if response.get("type") == "error":
                return {"error": response.get("message", "Server error"), "text": "", "process_time": 0}

            return {
                "text": response.get("text", ""),
                "process_time": response.get("process_time", 0),
                "error": None,
            }

        except Exception as exc:
            return {"error": f"Connection error: {exc}", "text": "", "process_time": 0}

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------
    def run(self):
        self._log("TalkFlow ready — configure and press Start")
        self._log(f"Server: {self.config['server']}")
        self._log(f"Hotkey: {self.config['hotkey']} (push-to-talk)")

        if TRAY_AVAILABLE:
            self._log("System tray: enabled (close button minimizes to tray)")
        else:
            if platform.system() == "Linux":
                self._log("System tray: disabled (install pystray, pillow, libappindicator)")
            else:
                self._log("System tray: disabled (install pystray + pillow to enable)")

        # Auto-start if configured
        if self.config.get("auto_start_on_launch", False):
            self.root.after(500, self._start_service)

        self.root.mainloop()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    app = TalkFlowGUI()
    app.run()


if __name__ == "__main__":
    main()
