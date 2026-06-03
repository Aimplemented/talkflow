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
Run the daemon once (e.g. at login) on the PC:

    python streamdeck_daemon.py daemon --backend groq --groq-key gsk_xxx
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
DEFAULT_PORT = 9878
DEFAULT_GROQ_KEY = os.getenv("GROQ_API_KEY", "")

# Daemon states
IDLE = "idle"
RECORDING = "recording"
PROCESSING = "processing"


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
        sync_delay_ms: int = 250,
        restore_delay_ms: int = 700,
        port: int = DEFAULT_PORT,
    ) -> None:
        self._backend = backend
        self._server_url = server_url
        self._groq_key = groq_key
        self._port = port

        from audio_capture import AudioCapture
        from clipboard_injector import ClipboardInjector
        self._audio = AudioCapture(device=device)
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
        log.info("⏹  Stopped (%.1fs) — transcribing…", duration_s)
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

            if not self._injector.deliver(cleaned + " "):
                log.warning("Delivery (clipboard paste) failed")
        finally:
            with self._lock:
                self._state = IDLE

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
def main() -> None:
    p = argparse.ArgumentParser(
        description="TalkFlow Stream Deck command trigger (DeskFlow/Wayland safe)")
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser("daemon", help="Run the recording daemon (on the PC with the mic)")
    d.add_argument("--backend", "-b", choices=["groq", "server"], default="groq")
    d.add_argument("--groq-key", "-g", default=DEFAULT_GROQ_KEY, metavar="KEY",
                   help="Groq API key (or set GROQ_API_KEY)")
    d.add_argument("--server", "-s", default="", metavar="HOST:PORT")
    d.add_argument("--device", "-d", type=int, default=None, metavar="INDEX",
                   help="Input device index (default: system default)")
    d.add_argument("--sync-delay", type=int, default=250, metavar="MS",
                   help="Delay before paste so DeskFlow can sync the clipboard")
    d.add_argument("--restore-delay", type=int, default=700, metavar="MS")
    d.add_argument("--port", "-p", type=int, default=DEFAULT_PORT)
    d.add_argument("--log-file", default="", metavar="PATH",
                   help="Append logs to this file (useful when run hidden as a service)")
    d.add_argument("--verbose", "-v", action="store_true")

    for name, help_text in (("toggle", "Start if idle, stop+transcribe if recording"),
                            ("start", "Begin recording"),
                            ("stop", "Stop recording and transcribe"),
                            ("status", "Print daemon state"),
                            ("ping", "Check the daemon is alive")):
        t = sub.add_parser(name, help=help_text)
        t.add_argument("--port", "-p", type=int, default=DEFAULT_PORT)

    args = p.parse_args()

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
        if args.backend == "server" and not args.server:
            p.error("--server is required when using --backend server")
        if args.backend == "groq" and not args.groq_key:
            p.error("--groq-key is required when using --backend groq (or set GROQ_API_KEY)")
        daemon = TalkFlowDaemon(
            backend=args.backend, server_url=args.server, groq_key=args.groq_key,
            device=args.device, sync_delay_ms=args.sync_delay,
            restore_delay_ms=args.restore_delay, port=args.port,
        )
        daemon.serve()
    else:
        sys.exit(send_command(args.command, port=args.port))


if __name__ == "__main__":
    main()
