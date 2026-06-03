"""
TalkFlow — Stream Deck Command Trigger (DeskFlow / Wayland safe)
================================================================
A button-driven dictation path that does NOT rely on a global hotkey.

Why this exists
---------------
With DeskFlow on Wayland, input forwarded to a remote screen is injected via
libei/the RemoteDesktop portal and is invisible to evdev/pynput/global
shortcuts on the remote machine.  So no key press can be *detected* on the
remote screen to start recording.

A Stream Deck button sidesteps this entirely: it runs a *command* over USB-HID
through its own software — it is never part of the keyboard event stream that
DeskFlow hooks.  Everything runs on the PC (the machine with the mic), and the
transcript is delivered to whichever screen the cursor is on via the existing
clipboard-paste path (ClipboardInjector).

Architecture
------------
A Stream Deck "System: Open" / "Run command" action returns immediately, so it
cannot hold a recording open between two presses.  We therefore split into:

  * a long-running DAEMON that owns the recording state, transcribes, and
    delivers via clipboard paste; and
  * a tiny TRIGGER command the button fires (`toggle` / `start` / `stop`) that
    connects to the daemon over a localhost socket and exits instantly.

Usage
-----
Save your settings ONCE (key/mic/remote target are stored in a per-user config
file, so you never have to find and re-paste the key again):

    python streamdeck_daemon.py setup --groq-key gsk_xxx --device 5 \
        --remote-paste 192.168.1.123:9879
    python streamdeck_daemon.py setup --show        # view current config

Then run the daemon on the PC with NO flags — it reads the config:

    python streamdeck_daemon.py daemon

CLI flags still work and override the saved config for one-off runs:

    python streamdeck_daemon.py daemon --backend server --server 192.168.1.50:9876

Point your Stream Deck button (System > Open, or a "Run command" plugin) at:

    python streamdeck_daemon.py toggle          # single button: press=start, press=stop

…or use two actions / a hold button:

    python streamdeck_daemon.py start            # on key-down
    python streamdeck_daemon.py stop             # on key-up

On Windows, use `pythonw.exe` for the trigger to avoid a console flash.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import platform
import socket
import subprocess
import sys
import threading
import time

# NB: heavy imports (audio_capture, clipboard_injector, text_processor) are
# done lazily inside the daemon so the trigger command — what the Stream Deck
# button actually runs — needs nothing but the standard library.

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(levelname)-8s  %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("talkflow.streamdeck")

MIN_AUDIO_BYTES = 3200
WS_CHUNK_SIZE = 64 * 1024
TRANSCRIBE_TIMEOUT = 30.0
REMOTE_PASTE_TIMEOUT = 5.0
DEFAULT_PORT = 9878
DEFAULT_GROQ_KEY = os.getenv("GROQ_API_KEY", "")


# ---------------------------------------------------------------------------
# Persistent config — so you set the API key (and mic, remote target) ONCE.
# ---------------------------------------------------------------------------
# The daemon reads this file on startup; CLI flags override it.  This means a
# bare `python streamdeck_daemon.py daemon` just works after a one-time setup,
# and you never have to hunt down / re-paste your Groq key again.
def config_path() -> str:
    """Stable per-user config location, created on demand."""
    if platform.system() == "Windows":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(base, "TalkFlow", "config.json")
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "talkflow", "config.json")


def load_config() -> dict:
    """Return the saved config dict, or {} if none / unreadable."""
    path = config_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as exc:
        log.warning("Could not read config %s: %s", path, exc)
        return {}


def save_config(updates: dict, remove: tuple = ()) -> str:
    """Merge *updates* (dropping None values) into the config file, deleting any
    keys in *remove*. Returns the config path."""
    path = config_path()
    cfg = load_config()
    cfg.update({k: v for k, v in updates.items() if v is not None})
    for key in remove:
        cfg.pop(key, None)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
    try:
        os.chmod(path, 0o600)  # the file holds an API key — keep it private
    except Exception:
        pass
    return path


# Daemon states
IDLE = "idle"
RECORDING = "recording"
PROCESSING = "processing"


def _pcm_peak(pcm: bytes) -> int:
    """Peak absolute amplitude (0..32767) of int16 PCM, for level diagnostics."""
    if not pcm:
        return 0
    try:
        import numpy as np
        return int(np.abs(np.frombuffer(pcm, dtype=np.int16)).max())
    except Exception:
        import array
        a = array.array("h")
        a.frombytes(pcm[: len(pcm) - (len(pcm) % 2)])
        return max((abs(x) for x in a), default=0)


def _resolve_input_device(device: int | None, device_name: str = "") -> int | None:
    """Resolve a mic to a current index.

    Device indices reshuffle when hardware is added/removed or on reboot, so a
    saved numeric index goes stale.  If *device_name* is given, find the lowest
    input device whose name contains that substring (case-insensitive) and use
    its *current* index — stable across reshuffles.  Falls back to the numeric
    *device* (or system default) if no name match is found.
    """
    if device_name:
        try:
            import sounddevice as sd
            needle = device_name.lower()
            for idx, dev in enumerate(sd.query_devices()):
                if dev.get("max_input_channels", 0) >= 1 and needle in dev["name"].lower():
                    return idx
            log.warning("No input device matching %r — falling back to %s",
                        device_name,
                        f"index {device}" if device is not None else "system default")
        except Exception as exc:
            log.warning("Device-name lookup failed (%s) — using numeric index", exc)
    return device


def _device_name(device: int | None) -> str:
    """Human-readable name of the input device the daemon will actually open."""
    try:
        import sounddevice as sd
        idx = device if device is not None else sd.default.device[0]
        return f"#{idx} {sd.query_devices(idx)['name']}"
    except Exception:
        return "system default" if device is None else f"#{device}"


def _send_remote_paste(host: str, port: int, text: str,
                       timeout: float = REMOTE_PASTE_TIMEOUT) -> bool:
    """Ship *text* to a paste_helper on the remote screen (the AI5090).

    Opens a connection, writes the UTF-8 text, half-closes the write side so
    the helper reads to EOF, then waits for an "ok" reply.  The timeout means a
    dead/unreachable helper can never wedge the daemon's processing thread.
    Returns True only if the helper acknowledged with "ok".
    """
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(text.encode("utf-8"))
            sock.shutdown(socket.SHUT_WR)
            reply = sock.recv(256).decode("utf-8", "replace").strip()
        if reply == "ok":
            return True
        log.warning("Remote paste helper replied: %s", reply or "<empty>")
        return False
    except Exception as exc:
        log.warning("Remote paste to %s:%d failed: %s", host, port, exc)
        return False


def _beep(kind: str) -> None:
    """Best-effort, cross-platform audio cue. Never raises."""
    try:
        system = platform.system()
        if system == "Darwin":
            snd = "Tink.aiff" if kind == "start" else "Pop.aiff"
            subprocess.Popen(["afplay", f"/System/Library/Sounds/{snd}"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif system == "Windows":
            import winsound
            freq = 880 if kind == "start" else 440
            winsound.Beep(freq, 120)
        else:  # Linux — best effort, silent if tools absent
            import shutil
            for player, arg in (("paplay", "/usr/share/sounds/freedesktop/stereo/"
                                 + ("message.oga" if kind == "start" else "complete.oga")),):
                if shutil.which(player):
                    subprocess.Popen([player, arg], stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
                    break
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Daemon
# ---------------------------------------------------------------------------
class TalkFlowDaemon:
    """Owns recording state; transcribes and delivers via clipboard paste."""

    def __init__(
        self,
        backend: str = "groq",
        server_url: str = "",
        groq_key: str = "",
        device: int | None = None,
        device_name: str = "",
        sync_delay_ms: int = 250,
        restore_delay_ms: int = 700,
        port: int = DEFAULT_PORT,
        remote_paste: str = "",
    ) -> None:
        self._backend = backend
        self._server_url = server_url
        self._groq_key = groq_key
        self._port = port

        # Optional remote paste target: "HOST:PORT" of a paste_helper running on
        # the active remote screen (the AI5090).  When set, transcripts are typed
        # locally on that machine — bypassing DeskFlow's clipboard/keystroke
        # forwarding — with a fallback to the local clipboard-paste path.
        self._remote_host = ""
        self._remote_port = 0
        if remote_paste:
            host, _, port_str = remote_paste.partition(":")
            self._remote_host = host.strip()
            self._remote_port = int(port_str) if port_str.strip() else 9879

        from audio_capture import AudioCapture
        from clipboard_injector import ClipboardInjector
        resolved = _resolve_input_device(device, device_name)
        self._device = resolved
        self._audio = AudioCapture(device=resolved)
        log.info("🎙  Mic: %s%s", _device_name(resolved),
                 f"  (matched name {device_name!r})" if device_name else "")
        self._injector = ClipboardInjector(sync_delay_ms=sync_delay_ms,
                                           restore_delay_ms=restore_delay_ms)
        self._state = IDLE
        self._lock = threading.Lock()
        self._last_text = ""
        self._last_text_time = 0.0

    # ------------------------------------------------------------------
    # Command handling (called from the socket-accept loop)
    # ------------------------------------------------------------------
    def handle(self, command: str) -> str:
        command = command.strip().lower()
        if command == "status":
            return self._state
        if command == "ping":
            return "pong"
        if command in ("toggle", "start", "stop"):
            return self._dispatch(command)
        return f"error: unknown command {command!r}"

    def _dispatch(self, command: str) -> str:
        with self._lock:
            state = self._state
            if command == "toggle":
                command = "stop" if state == RECORDING else "start"

            if command == "start":
                if state != IDLE:
                    return f"busy: {state}"
                self._state = RECORDING
                self._audio.start()
                _beep("start")
                log.info("⏺  RECORDING — speak now")
                return "recording"

            if command == "stop":
                if state != RECORDING:
                    return f"noop: {state}"
                audio_bytes = self._audio.stop()
                self._state = PROCESSING
                _beep("stop")

        # Outside the lock: handle short clip + spawn processing thread.
        if len(audio_bytes) < MIN_AUDIO_BYTES:
            with self._lock:
                self._state = IDLE
            log.info("⚠  Too short — skipped.")
            return "skipped: too short"

        duration_s = len(audio_bytes) / (16000 * 2)
        peak = _pcm_peak(audio_bytes)
        pct = peak * 100 // 32767
        log.info("⏹  Stopped (%.1fs) — peak level %d%% — transcribing…", duration_s, pct)
        if pct < 2:
            log.warning("⚠  Audio is essentially silent (peak %d%%). Whisper may "
                        "hallucinate text like 'thank you'. Check the mic with: "
                        "python streamdeck_daemon.py mictest", pct)
        threading.Thread(target=self._process, args=(audio_bytes,),
                         daemon=True).start()
        return "transcribing"

    # ------------------------------------------------------------------
    # Background: transcribe + deliver
    # ------------------------------------------------------------------
    def _process(self, audio_bytes: bytes) -> None:
        try:
            now = time.time()
            initial_prompt = self._last_text if (now - self._last_text_time) < 30.0 else ""

            if self._backend == "groq":
                response = self._transcribe_groq(audio_bytes, initial_prompt)
            else:
                response = self._transcribe_server(audio_bytes)

            if response.get("error"):
                log.error("✗  %s", response["error"])
                return

            text = response.get("text", "").strip()
            if not text:
                log.info("⚠  No speech detected.")
                return

            from text_processor import clean_transcription
            cleaned = clean_transcription(text)
            log.info("✓  [%.2fs] %s", response.get("process_time", 0), cleaned)

            self._last_text = (self._last_text + " " + cleaned).strip()[-900:]
            self._last_text_time = time.time()

            if not self._deliver(cleaned + " "):
                log.warning("Delivery failed")
        finally:
            with self._lock:
                self._state = IDLE

    def _deliver(self, text: str) -> bool:
        """Deliver *text* to the active screen.

        If a remote paste helper is configured, type it directly on that machine
        (reliable across DeskFlow).  Fall back to the local clipboard-paste path
        if the helper is unreachable so delivery still works on the PC screen.
        """
        if self._remote_host:
            if _send_remote_paste(self._remote_host, self._remote_port, text):
                log.info("→  delivered to remote helper %s:%d",
                         self._remote_host, self._remote_port)
                return True
            log.info("Remote helper unreachable — falling back to local clipboard paste")
        return self._injector.deliver(text)

    def _transcribe_groq(self, audio_bytes: bytes, initial_prompt: str = "") -> dict:
        from groq_transcribe import transcribe_audio
        if not self._groq_key:
            return {"error": "Groq API key not configured", "text": "", "process_time": 0}
        return transcribe_audio(audio_bytes, self._groq_key,
                                initial_prompt=initial_prompt or None)

    def _transcribe_server(self, audio_bytes: bytes) -> dict:
        try:
            from websockets.sync.client import connect as ws_connect
        except ImportError:
            return {"error": "websockets not installed", "text": "", "process_time": 0}
        if not self._server_url:
            return {"error": "Server URL not configured", "text": "", "process_time": 0}

        ws_url = f"ws://{self._server_url}/ws/dictate"
        try:
            with ws_connect(ws_url) as ws:
                sent = 0
                while sent < len(audio_bytes):
                    ws.send(audio_bytes[sent:sent + WS_CHUNK_SIZE])
                    sent += WS_CHUNK_SIZE
                ws.send(json.dumps({"action": "transcribe"}))
                raw = ws.recv(timeout=TRANSCRIBE_TIMEOUT)
                response = json.loads(raw)
            if response.get("type") == "error":
                return {"error": response.get("message", "Server error"),
                        "text": "", "process_time": 0}
            return {"text": response.get("text", ""),
                    "process_time": response.get("process_time", 0), "error": None}
        except Exception as exc:
            return {"error": f"Connection error: {exc}", "text": "", "process_time": 0}

    # ------------------------------------------------------------------
    # Socket server
    # ------------------------------------------------------------------
    def serve(self) -> None:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            srv.bind(("127.0.0.1", self._port))
        except OSError as exc:
            log.error("Cannot bind 127.0.0.1:%d — is a daemon already running? (%s)",
                      self._port, exc)
            sys.exit(1)
        srv.listen(8)

        print(f"\n{'='*60}")
        print(f"  TalkFlow — Stream Deck daemon ready")
        print(f"  Backend : {'Groq Cloud' if self._backend == 'groq' else self._server_url}")
        if self._remote_host:
            print(f"  Deliver : remote helper {self._remote_host}:{self._remote_port} "
                  f"(fallback: local clipboard paste)")
        else:
            print(f"  Deliver : local clipboard paste (DeskFlow forwarding)")
        print(f"  Control : 127.0.0.1:{self._port}")
        print(f"  Trigger : python streamdeck_daemon.py toggle")
        print(f"  Ctrl+C to quit.")
        print(f"{'='*60}\n")

        try:
            while True:
                conn, _ = srv.accept()
                with conn:
                    try:
                        data = conn.recv(256).decode("utf-8", "replace")
                        if not data:
                            continue
                        reply = self.handle(data.splitlines()[0] if data else "")
                        conn.sendall((reply + "\n").encode("utf-8"))
                    except Exception as exc:
                        log.exception("Connection error: %s", exc)
        except KeyboardInterrupt:
            print("\nShutting down.")
        finally:
            srv.close()


# ---------------------------------------------------------------------------
# Trigger client
# ---------------------------------------------------------------------------
def send_command(command: str, port: int = DEFAULT_PORT, timeout: float = 2.0) -> int:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout) as sock:
            sock.sendall((command + "\n").encode("utf-8"))
            reply = sock.recv(256).decode("utf-8", "replace").strip()
        print(reply)
        return 0
    except ConnectionRefusedError:
        print(f"error: daemon not running on 127.0.0.1:{port} "
              f"(start it with: python streamdeck_daemon.py daemon ...)",
              file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def mic_test(device: int | None, device_name: str = "", seconds: float = 4.0) -> None:
    """Record from a mic and report the audio level — proves the mic works
    without involving Whisper or DeskFlow.  Falls back to saved config; resolves
    by name when given so it tracks index reshuffles."""
    cfg = load_config()
    if device is None and not device_name:
        device = cfg.get("device")
        device_name = cfg.get("device_name", "")
    device = _resolve_input_device(device, device_name)
    from audio_capture import AudioCapture
    print(f"Recording {seconds:.0f}s from {_device_name(device)} — SPEAK NOW…")
    cap = AudioCapture(device=device)
    try:
        cap.start()
        time.sleep(seconds)
        pcm = cap.stop()
    except Exception as exc:
        print(f"\n  ✗ Could not open this device as a microphone: {exc}")
        print("    (It may be an output/loopback device. Run `devices` and pick a real mic,")
        print('     or select by name:  python streamdeck_daemon.py mictest --device-name "MOVO")')
        return
    peak = _pcm_peak(pcm)
    pct = peak * 100 // 32767
    bar = "#" * (pct // 2)
    print(f"\n  peak level: {pct:3d}%  |{bar:<50}|")
    if pct < 2:
        print("\n  ✗ SILENT — this mic captured no sound. Likely causes:")
        print("    • wrong device index (run `devices` and pick the one you speak into)")
        print("    • mic muted / unplugged / wrong input selected in Windows Sound settings")
        print("    • another app (e.g. Voicemod) is holding the device")
        print("  Set the right one with:  python streamdeck_daemon.py setup --device <IDX>")
    elif pct < 10:
        print("\n  ⚠ Very quiet — speech may transcribe poorly. Raise the mic gain or move closer.")
    else:
        print("\n  ✓ Good signal — this mic is working.")


def list_input_devices() -> None:
    """Print all input-capable audio devices with their indices and the default."""
    try:
        import sounddevice as sd
    except Exception:
        print("sounddevice is not installed; cannot list devices.\n"
              "  pip install sounddevice", file=sys.stderr)
        return

    try:
        default_in = sd.default.device[0]
    except Exception:
        default_in = None

    print("Input devices (microphones):\n")
    print(f"  {'IDX':>3}  {'CH':>2}  {'RATE':>6}  NAME")
    print(f"  {'-'*3}  {'-'*2}  {'-'*6}  {'-'*30}")
    for idx, dev in enumerate(sd.query_devices()):
        if dev.get("max_input_channels", 0) < 1:
            continue
        mark = "  <- default" if idx == default_in else ""
        print(f"  {idx:>3}  {dev['max_input_channels']:>2}  "
              f"{int(dev['default_samplerate']):>6}  {dev['name']}{mark}")
    print("\nLock in a mic by NAME so it survives index reshuffles/reboots:")
    print('  python streamdeck_daemon.py setup --device-name "MOVO GM-5"')


# ---------------------------------------------------------------------------
def main() -> None:
    p = argparse.ArgumentParser(
        description="TalkFlow Stream Deck command trigger (DeskFlow/Wayland safe)")
    sub = p.add_subparsers(dest="command", required=True)

    # Defaults are None so we can distinguish "flag not given" from a real value
    # and fall back to the saved config (see resolution below).
    d = sub.add_parser("daemon", help="Run the recording daemon (on the PC with the mic)")
    d.add_argument("--backend", "-b", choices=["groq", "server"], default=None)
    d.add_argument("--groq-key", "-g", default=None, metavar="KEY",
                   help="Groq API key (saved by `setup`; or set GROQ_API_KEY)")
    d.add_argument("--server", "-s", default=None, metavar="HOST:PORT")
    d.add_argument("--device", "-d", type=int, default=None, metavar="INDEX",
                   help="Input device index (default: system default)")
    d.add_argument("--device-name", default=None, metavar="SUBSTR",
                   help="Match the mic by name substring instead of index "
                        "(survives index reshuffles); overrides --device")
    d.add_argument("--sync-delay", type=int, default=None, metavar="MS",
                   help="Delay before paste so DeskFlow can sync the clipboard")
    d.add_argument("--restore-delay", type=int, default=None, metavar="MS")
    d.add_argument("--remote-paste", default=None, metavar="HOST:PORT",
                   help="Send transcripts to a paste_helper on the active remote "
                        "screen (the AI5090) instead of relying on DeskFlow's "
                        "clipboard/keystroke forwarding. Falls back to local "
                        "clipboard paste if unreachable. Port defaults to 9879.")
    d.add_argument("--port", "-p", type=int, default=None)
    d.add_argument("--log-file", default="", metavar="PATH",
                   help="Append logs to this file (useful when run hidden as a service)")
    d.add_argument("--verbose", "-v", action="store_true")

    # One-time setup: save the API key / mic / remote target so you never have
    # to pass them again.  `python streamdeck_daemon.py setup --groq-key gsk_...`
    st = sub.add_parser("setup", help="Save config (Groq key, mic, remote paste) so "
                                      "you set it ONCE — then run `daemon` with no flags")
    st.add_argument("--backend", "-b", choices=["groq", "server"])
    st.add_argument("--groq-key", "-g", metavar="KEY")
    st.add_argument("--server", "-s", metavar="HOST:PORT")
    st.add_argument("--device", "-d", type=int, metavar="INDEX")
    st.add_argument("--device-name", metavar="SUBSTR",
                    help='Match the mic by name, e.g. --device-name "MOVO GM-5" '
                         "(stable across index reshuffles)")
    st.add_argument("--remote-paste", metavar="HOST:PORT")
    st.add_argument("--port", "-p", type=int)
    st.add_argument("--show", action="store_true",
                    help="Print the current saved config and its path, then exit")

    for name, help_text in (("toggle", "Start if idle, stop+transcribe if recording"),
                            ("start", "Begin recording"),
                            ("stop", "Stop recording and transcribe"),
                            ("status", "Print daemon state"),
                            ("ping", "Check the daemon is alive")):
        t = sub.add_parser(name, help=help_text)
        t.add_argument("--port", "-p", type=int, default=DEFAULT_PORT)

    sub.add_parser("devices", help="List available microphones (input devices) and their indices")

    mt = sub.add_parser("mictest", help="Record a few seconds and show the audio level "
                                        "(diagnose silent-mic / 'thank you' hallucinations)")
    mt.add_argument("--device", "-d", type=int, default=None, metavar="INDEX",
                    help="Device index to test (default: the one saved by setup)")
    mt.add_argument("--device-name", default=None, metavar="SUBSTR",
                    help='Match the mic by name, e.g. --device-name "G06"')
    mt.add_argument("--seconds", type=float, default=4.0)

    args = p.parse_args()

    if args.command == "devices":
        list_input_devices()
        return

    if args.command == "mictest":
        mic_test(args.device, device_name=args.device_name or "", seconds=args.seconds)
        return

    if args.command == "setup":
        if args.show:
            cfg = load_config()
            shown = dict(cfg)
            if shown.get("groq_key"):  # never print the full secret
                shown["groq_key"] = shown["groq_key"][:6] + "…" + shown["groq_key"][-4:]
            print(f"Config file: {config_path()}")
            print(json.dumps(shown, indent=2, ensure_ascii=False)
                  if shown else "(empty — run setup to populate)")
            return
        updates = {k: getattr(args, k) for k in
                   ("backend", "groq_key", "server", "device", "device_name",
                    "remote_paste", "port")}
        if not any(v is not None for v in updates.values()):
            p.error("nothing to save — pass at least one of "
                    "--groq-key/--device/--device-name/--remote-paste/--backend/--server/--port "
                    "(or --show to view current config)")
        # Selecting a mic by name supersedes a stale numeric index — drop the
        # saved index so the two can't disagree after the indices reshuffle.
        remove = ("device",) if args.device_name else ()
        path = save_config(updates, remove=remove)
        print(f"Saved config to {path}")
        print("You can now run the daemon with no flags:  python streamdeck_daemon.py daemon")
        return

    if args.command == "daemon":
        if args.verbose:
            logging.getLogger().setLevel(logging.DEBUG)
        if args.log_file:
            from logging.handlers import RotatingFileHandler
            os.makedirs(os.path.dirname(os.path.abspath(args.log_file)), exist_ok=True)
            fh = RotatingFileHandler(args.log_file, maxBytes=1_000_000, backupCount=3,
                                     encoding="utf-8")
            fh.setFormatter(logging.Formatter(
                "%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
            logging.getLogger().addHandler(fh)

        # Resolve each setting: CLI flag → saved config → built-in default.
        cfg = load_config()

        def resolve(name: str, default):
            val = getattr(args, name)
            if val is not None:
                return val
            if cfg.get(name) is not None:
                return cfg[name]
            return default

        backend = resolve("backend", "groq")
        server = resolve("server", "")
        # Groq key precedence: flag → config → GROQ_API_KEY env var.
        groq_key = args.groq_key or cfg.get("groq_key") or DEFAULT_GROQ_KEY
        device = resolve("device", None)
        device_name = resolve("device_name", "")
        sync_delay = resolve("sync_delay", 250)
        restore_delay = resolve("restore_delay", 700)
        remote_paste = resolve("remote_paste", "")
        port = resolve("port", DEFAULT_PORT)

        if backend == "server" and not server:
            p.error("--server is required when using --backend server "
                    "(set it once with: streamdeck_daemon.py setup --backend server --server HOST:PORT)")
        if backend == "groq" and not groq_key:
            p.error("No Groq key found. Set it once with:\n"
                    "    python streamdeck_daemon.py setup --groq-key gsk_...")
        daemon = TalkFlowDaemon(
            backend=backend, server_url=server, groq_key=groq_key,
            device=device, device_name=device_name, sync_delay_ms=sync_delay,
            restore_delay_ms=restore_delay, port=port,
            remote_paste=remote_paste,
        )
        daemon.serve()
    else:
        sys.exit(send_command(args.command, port=args.port))


if __name__ == "__main__":
    main()
