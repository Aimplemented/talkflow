"""
TalkFlow — CLI Client (Push-to-Talk)
=====================================
Hold your hotkey to record, release to transcribe and inject text.

Usage:
    python client.py --backend groq --groq-key gsk_xxx
    python client.py --backend server --server 192.168.1.100:9876
    python client.py --hotkey f9 --backend groq
"""

from __future__ import annotations

import argparse
import json
import logging
import platform
import subprocess
import sys
import threading
import time

from audio_capture import AudioCapture
from hotkey_listener import HotkeyListener
from keystroke_injector import KeystrokeInjector
from text_processor import clean_transcription

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("talkflow.client")

MIN_AUDIO_BYTES = 3200
WS_CHUNK_SIZE = 64 * 1024
TRANSCRIBE_TIMEOUT = 30.0

# Default Groq API key (can be overridden via --groq-key)
DEFAULT_GROQ_KEY = "REMOVED_GROQ_API_KEY"


def _play_sound(path: str) -> None:
    if platform.system() != "Darwin":
        return
    try:
        subprocess.Popen(["afplay", path], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        pass


class TalkFlowClient:
    def __init__(
        self,
        hotkey: str,
        backend: str = "groq",
        server_url: str = "",
        groq_key: str = "",
    ) -> None:
        self._hotkey = hotkey
        self._backend = backend
        self._server_url = server_url
        self._groq_key = groq_key
        self._is_recording = False
        self._audio = AudioCapture()
        self._injector = KeystrokeInjector()
        self._listener = HotkeyListener(
            hotkey=hotkey,
            on_press_start=self._on_hold_start,
            on_press_stop=self._on_hold_stop,
            mode="push-to-talk",
        )

    def run(self) -> None:
        self._listener.start()
        print(f"\n{'='*60}")
        print(f"  TalkFlow — ready (push-to-talk)")
        if self._backend == "groq":
            print(f"  Backend: Groq Cloud (fast)")
        else:
            print(f"  Backend: Self-hosted server ({self._server_url})")
        print(f"  Hotkey : {self._hotkey}")
        print(f"  Hold {self._hotkey} to record, release to transcribe.")
        print(f"  Ctrl+C to quit.")
        print(f"{'='*60}\n")
        try:
            while True:
                time.sleep(0.1)
        except KeyboardInterrupt:
            print("\nShutting down.")
            self._listener.stop()

    def _on_hold_start(self) -> None:
        if self._is_recording:
            return
        self._is_recording = True
        self._audio.start()
        _play_sound("/System/Library/Sounds/Tink.aiff")
        print("⏺  RECORDING — speak now (release to stop)")

    def _on_hold_stop(self) -> None:
        if not self._is_recording:
            return
        audio_bytes = self._audio.stop()
        self._is_recording = False
        _play_sound("/System/Library/Sounds/Pop.aiff")

        if len(audio_bytes) < MIN_AUDIO_BYTES:
            print("⚠  Too short — skipped.")
            return

        duration_s = len(audio_bytes) / (16000 * 2)
        print(f"⏹  Released ({duration_s:.1f}s) — transcribing…")

        threading.Thread(target=self._send_and_inject, args=(audio_bytes,),
                          daemon=True).start()

    def _send_and_inject(self, audio_bytes: bytes) -> None:
        if self._backend == "groq":
            response = self._transcribe_groq(audio_bytes)
        else:
            response = self._transcribe_server(audio_bytes)

        if response.get("error"):
            print(f"✗  {response['error']}")
            return

        text = response.get("text", "").strip()
        proc_time = response.get("process_time", 0)

        if not text:
            print("⚠  No speech detected.")
            return

        cleaned_text = clean_transcription(text)
        print(f"✓  [{proc_time:.2f}s] {cleaned_text}")

        try:
            self._injector.type_text(cleaned_text)
        except Exception as exc:
            print(f"✗  Injection failed: {exc}")

    def _transcribe_groq(self, audio_bytes: bytes) -> dict:
        """Transcribe using Groq Cloud API."""
        try:
            from groq_transcriber import GroqTranscriber
        except ImportError:
            return {"error": "groq_transcriber module not found", "text": "", "process_time": 0}

        if not self._groq_key:
            return {"error": "Groq API key not configured", "text": "", "process_time": 0}

        transcriber = GroqTranscriber(api_key=self._groq_key)
        return transcriber.transcribe(audio_bytes)

    def _transcribe_server(self, audio_bytes: bytes) -> dict:
        """Transcribe using self-hosted WebSocket server."""
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
                return {"error": response.get("message", "Server error"), "text": "", "process_time": 0}

            return {
                "text": response.get("text", ""),
                "process_time": response.get("process_time", 0),
                "error": None,
            }

        except Exception as exc:
            return {"error": f"Connection error: {exc}", "text": "", "process_time": 0}


def main() -> None:
    p = argparse.ArgumentParser(description="TalkFlow — push-to-talk voice dictation")
    p.add_argument("--backend", "-b", choices=["groq", "server"], default="groq",
                   help="Transcription backend: groq (cloud) or server (self-hosted)")
    p.add_argument("--groq-key", "-g", default=DEFAULT_GROQ_KEY, metavar="KEY",
                   help="Groq API key (default: built-in key)")
    p.add_argument("--server", "-s", default="", metavar="HOST:PORT",
                   help="Server address for self-hosted backend")
    p.add_argument("--hotkey", "-k", default="f9", metavar="COMBO",
                   help="Hotkey combo (default: f9)")
    p.add_argument("--verbose", "-v", action="store_true",
                   help="Enable debug logging")
    args = p.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Validate arguments
    if args.backend == "server" and not args.server:
        p.error("--server is required when using --backend server")

    client = TalkFlowClient(
        hotkey=args.hotkey,
        backend=args.backend,
        server_url=args.server,
        groq_key=args.groq_key,
    )
    client.run()


if __name__ == "__main__":
    main()
