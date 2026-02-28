"""
TalkFlow — CLI Client (Push-to-Talk)
=====================================
Hold your hotkey to record, release to transcribe and inject text.

Usage:
    python client.py --server YOUR_SERVER:9876
    python client.py --server YOUR_SERVER:9876 --hotkey f9
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

try:
    from websockets.sync.client import connect as ws_connect
except ImportError:
    print("ERROR: websockets>=13.0 required. pip install 'websockets>=13.0'",
          file=sys.stderr)
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("talkflow.client")

MIN_AUDIO_BYTES = 3200
WS_CHUNK_SIZE = 64 * 1024
TRANSCRIBE_TIMEOUT = 30.0


def _play_sound(path: str) -> None:
    if platform.system() != "Darwin":
        return
    try:
        subprocess.Popen(["afplay", path], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        pass


class TalkFlowClient:
    def __init__(self, server_url: str, hotkey: str) -> None:
        self._server_url = server_url
        self._hotkey = hotkey
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
        print(f"  Server : {self._server_url}")
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
        except Exception as exc:
            print(f"✗  Connection error: {exc}")
            return

        text = response.get("text", "").strip()
        proc_time = response.get("process_time", 0)

        if not text:
            print("⚠  No speech detected.")
            return

        print(f"✓  [{proc_time:.2f}s] {text}")

        try:
            self._injector.type_text(text)
        except Exception as exc:
            print(f"✗  Injection failed: {exc}")


def main() -> None:
    p = argparse.ArgumentParser(description="TalkFlow — push-to-talk voice dictation")
    p.add_argument("--server", "-s", required=True, metavar="HOST:PORT")
    p.add_argument("--hotkey", "-k", default="f9", metavar="COMBO")
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    client = TalkFlowClient(server_url=args.server, hotkey=args.hotkey)
    client.run()


if __name__ == "__main__":
    main()
