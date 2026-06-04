"""TalkFlow Host — runs on the DeskFlow primary (the PC with the mic).

Why this exists
---------------
When DeskFlow hands control to another screen, it forwards your keyboard to
that screen and swallows the keypress locally — so a hotkey held while you're
on a remote screen never reaches the PC. The fix is to catch the hotkey on the
remote machine (a small "TalkFlow Agent") and have it ask THIS host to record.

Flow
----
  Agent (remote)                 Host (this PC, has the mic)
  --------------                 ---------------------------
  hold F9      ── start ──▶       start recording the PC mic
  release F9   ── stop  ──▶       stop, transcribe (Groq / self-hosted)
               ◀── text ──        send transcript back to that agent
  type locally

Only the agent that started a recording receives its transcript, so multiple
remote screens never type over each other (and only one has the cursor anyway).

Run standalone (reads client/config.json for backend, key, mic):
    python talkflow_host.py            # or: python network_server.py
"""

import asyncio
import json
import logging
from typing import Callable, Optional, Set

try:
    import websockets
    from websockets.server import WebSocketServerProtocol
except ImportError:
    print("websockets package required: pip install websockets")
    raise

from audio_capture import AudioCapture
from text_processor import clean_transcription

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(levelname)-8s  %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger("talkflow.host")


class TalkFlowHost:
    """WebSocket host: records the local mic on agent request and returns text."""

    def __init__(
        self,
        transcribe_fn: Callable[[bytes], dict],
        host: str = "0.0.0.0",
        port: int = 9877,
        mic_device: Optional[int] = None,
        on_event: Optional[Callable[[str, str], None]] = None,
    ):
        self.transcribe_fn = transcribe_fn
        self.host = host
        self.port = port
        self.mic_device = mic_device
        self.on_event = on_event            # on_event(kind, message) for UI/logging
        self.clients: Set[WebSocketServerProtocol] = set()
        self._audio = AudioCapture(device=mic_device)
        self._recording = False
        self._active_agent: Optional[WebSocketServerProtocol] = None
        self._server = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # -- helpers --------------------------------------------------------
    def _emit(self, kind: str, message: str = "") -> None:
        logger.info("%s %s", kind, message)
        if self.on_event:
            try:
                self.on_event(kind, message)
            except Exception:
                pass

    async def _send(self, ws, payload: dict) -> None:
        try:
            await ws.send(json.dumps(payload))
        except Exception as exc:
            logger.debug("send failed: %s", exc)

    # -- connection lifecycle ------------------------------------------
    async def handle_client(self, websocket: WebSocketServerProtocol) -> None:
        self.clients.add(websocket)
        peer = getattr(websocket, "remote_address", "?")
        self._emit("agent_connected", str(peer))
        await self._send(websocket, {"type": "hello", "role": "host"})
        try:
            async for message in websocket:
                await self.process_message(websocket, message)
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self.clients.discard(websocket)
            if self._active_agent is websocket:
                # Agent vanished mid-recording — abandon the capture.
                self._safe_stop_recording()
                self._active_agent = None
            self._emit("agent_disconnected", str(peer))

    async def process_message(self, websocket, message: str) -> None:
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            logger.warning("bad JSON from agent: %s", message)
            return

        if data.get("type") != "hotkey":
            return
        action = data.get("action")

        if action == "start":
            self._start_recording(websocket)
        elif action == "stop":
            await self._stop_and_transcribe(websocket)

    # -- recording / transcription -------------------------------------
    def _start_recording(self, websocket) -> None:
        if self._recording:
            return
        self._active_agent = websocket
        self._recording = True
        try:
            self._audio = AudioCapture(device=self.mic_device)
            self._audio.start()
        except Exception as exc:
            self._recording = False
            self._active_agent = None
            self._emit("error", f"mic start failed: {exc}")
            return
        self._emit("recording", "")

    def _safe_stop_recording(self) -> bytes:
        try:
            if self._recording:
                data = self._audio.stop()
                self._recording = False
                return data
        except Exception as exc:
            logger.debug("stop error: %s", exc)
        self._recording = False
        return b""

    async def _stop_and_transcribe(self, websocket) -> None:
        if not self._recording or self._active_agent is not websocket:
            return
        audio = self._safe_stop_recording()
        self._active_agent = None

        if len(audio) < 3200:  # < ~0.1s — likely an accidental tap
            self._emit("ready", "")
            await self._send(websocket, {"type": "text", "data": ""})
            return

        self._emit("transcribing", "")
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(None, self.transcribe_fn, audio)
        except Exception as exc:
            self._emit("error", f"transcribe failed: {exc}")
            await self._send(websocket, {"type": "error", "message": str(exc)})
            return

        if result.get("error"):
            self._emit("error", result["error"])
            await self._send(websocket, {"type": "error", "message": result["error"]})
            return

        text = clean_transcription((result.get("text") or "").strip())
        self._emit("ready", text)
        await self._send(websocket, {"type": "text", "data": text})

    # -- server start/stop ---------------------------------------------
    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._server = await websockets.serve(self.handle_client, self.host, self.port)
        self._emit("listening", f"ws://{self.host}:{self.port}")
        await self._server.wait_closed()

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._emit("stopped", "")


# ---------------------------------------------------------------------------
# Build a transcribe function from the saved config (backend: groq | server)
# ---------------------------------------------------------------------------
def make_transcriber(config: dict) -> Callable[[bytes], dict]:
    backend = config.get("backend", "groq")

    if backend == "groq":
        from groq_transcribe import transcribe_audio
        key = config.get("groq_api_key", "")

        def _groq(audio: bytes) -> dict:
            if not key:
                return {"error": "Groq API key not configured", "text": ""}
            return transcribe_audio(audio, key)
        return _groq

    # Self-hosted GPU server backend
    server_url = config.get("server", "")

    def _server(audio: bytes) -> dict:
        try:
            from websockets.sync.client import connect as ws_connect
        except ImportError:
            return {"error": "websockets not installed", "text": ""}
        if not server_url:
            return {"error": "Server URL not configured", "text": ""}
        try:
            with ws_connect(f"ws://{server_url}/ws/dictate") as ws:
                sent = 0
                while sent < len(audio):
                    ws.send(audio[sent:sent + 65536])
                    sent += 65536
                ws.send(json.dumps({"action": "transcribe"}))
                resp = json.loads(ws.recv(timeout=30.0))
            if resp.get("type") == "error":
                return {"error": resp.get("message", "Server error"), "text": ""}
            return {"text": resp.get("text", ""), "process_time": resp.get("process_time", 0)}
        except Exception as exc:
            return {"error": f"Connection error: {exc}", "text": ""}
    return _server


def _load_config() -> dict:
    from pathlib import Path
    cfg_path = Path(__file__).parent / "config.json"
    if cfg_path.exists():
        try:
            return json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("could not read config.json: %s", exc)
    return {}


def main() -> None:
    import argparse

    p = argparse.ArgumentParser(description="TalkFlow Host (runs on the PC with the mic)")
    p.add_argument("--port", type=int, default=9877)
    p.add_argument("--host", default="0.0.0.0")
    args = p.parse_args()

    config = _load_config()
    transcriber = make_transcriber(config)
    mic = config.get("mic_device")

    host = TalkFlowHost(transcriber, host=args.host, port=args.port, mic_device=mic)
    backend = config.get("backend", "groq")
    print(f"\n{'='*56}")
    print("  TalkFlow Host — ready for remote agents")
    print(f"  Listening : ws://{args.host}:{args.port}")
    print(f"  Backend   : {backend}")
    print(f"  Mic device: {mic if mic is not None else 'system default'}")
    print("  Run talkflow_agent.py on each remote screen.")
    print(f"{'='*56}\n")
    try:
        asyncio.run(host.start())
    except KeyboardInterrupt:
        print("\nShutting down.")


if __name__ == "__main__":
    main()
