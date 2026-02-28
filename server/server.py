"""
WhisperFlow — Transcription Server (Card 1)
============================================
FastAPI WebSocket server that loads faster-whisper on CUDA and exposes a
real-time dictation endpoint.  Clients stream raw 16 kHz / mono / 16-bit PCM
frames, then send a JSON control message to trigger transcription.

Protocol (WebSocket /ws/dictate)
---------------------------------
  Client → Server:
    - binary frames: raw PCM audio (any length, buffered server-side)
    - JSON: {"action": "transcribe"}         → transcribe buffer, clear buffer
            {"action": "transcribe_chunk"}   → transcribe buffer, keep buffer
            {"action": "transcribe_final"}   → transcribe buffer, clear buffer (alias)
            {"action": "clear"}              → discard buffer
            {"action": "ping"}               → server replies {"type": "pong"}

  Server → Client:
    - {"type": "transcription", "text": "...", "audio_duration": 3.2, "process_time": 0.14}
    - {"type": "pong"}
    - {"type": "error", "message": "..."}

Environment variables
---------------------
  WHISPER_MODEL    (default: large-v3)
  WHISPER_DEVICE   (default: cuda)
  WHISPER_COMPUTE  (default: float16)
  WHISPER_BEAM_SIZE(default: 5)
  WHISPER_LANGUAGE (default: en)
  SERVER_PORT      (default: 9876)
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import numpy as np
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from faster_whisper import WhisperModel

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("whisperflow")

# ---------------------------------------------------------------------------
# Configuration from environment
# ---------------------------------------------------------------------------
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "large-v3")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cuda")
WHISPER_COMPUTE = os.getenv("WHISPER_COMPUTE", "float16")
WHISPER_BEAM_SIZE = int(os.getenv("WHISPER_BEAM_SIZE", "5"))
WHISPER_LANGUAGE = os.getenv("WHISPER_LANGUAGE", "en") or None  # None → auto-detect
SERVER_PORT = int(os.getenv("SERVER_PORT", "9876"))

# Audio constants
SAMPLE_RATE = 16_000   # Hz
SAMPLE_WIDTH = 2       # bytes (int16)

# ---------------------------------------------------------------------------
# Model — loaded once at startup
# ---------------------------------------------------------------------------
log.info(
    "Loading faster-whisper model=%s device=%s compute=%s beam_size=%d",
    WHISPER_MODEL, WHISPER_DEVICE, WHISPER_COMPUTE, WHISPER_BEAM_SIZE,
)
_model_load_start = time.perf_counter()
whisper_model = WhisperModel(
    WHISPER_MODEL,
    device=WHISPER_DEVICE,
    compute_type=WHISPER_COMPUTE,
)
log.info("Model loaded in %.2fs", time.perf_counter() - _model_load_start)

# Thread-pool for running synchronous transcription without blocking the event loop
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="whisper")

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(title="WhisperFlow Server", version="1.0.0")


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/health")
async def health() -> JSONResponse:
    """Return server status and model info."""
    return JSONResponse({
        "status": "ok",
        "model": WHISPER_MODEL,
        "device": WHISPER_DEVICE,
        "compute_type": WHISPER_COMPUTE,
        "beam_size": WHISPER_BEAM_SIZE,
        "language": WHISPER_LANGUAGE or "auto",
        "sample_rate": SAMPLE_RATE,
    })


# ---------------------------------------------------------------------------
# Transcription helper (runs in thread pool)
# ---------------------------------------------------------------------------
def _transcribe_pcm(pcm_bytes: bytes, *, clear_buffer: bool = True) -> dict[str, Any]:
    """
    Convert raw PCM bytes to a numpy float32 array and run faster-whisper.

    Returns a dict ready to be serialised as the WebSocket response.
    """
    if not pcm_bytes:
        return {"type": "transcription", "text": "", "audio_duration": 0.0, "process_time": 0.0}

    # Convert int16 PCM → float32 in [-1, 1]
    audio_np = (
        np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    )
    audio_duration = len(audio_np) / SAMPLE_RATE

    t0 = time.perf_counter()
    segments, info = whisper_model.transcribe(
        audio_np,
        language=WHISPER_LANGUAGE,
        beam_size=WHISPER_BEAM_SIZE,
        vad_filter=True,
        vad_parameters={
            "min_silence_duration_ms": 300,
            "speech_pad_ms": 200,
        },
    )
    # Materialise the generator (transcription happens here)
    text = " ".join(seg.text.strip() for seg in segments).strip()
    process_time = time.perf_counter() - t0

    rtf = process_time / audio_duration if audio_duration > 0 else 0
    log.info(
        "Transcribed %.2fs audio in %.3fs  RTF=%.3f  text=%r",
        audio_duration, process_time, rtf, text[:80],
    )

    return {
        "type": "transcription",
        "text": text,
        "audio_duration": round(audio_duration, 3),
        "process_time": round(process_time, 3),
        "real_time_factor": round(rtf, 3),
    }


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------
@app.websocket("/ws/dictate")
async def ws_dictate(websocket: WebSocket) -> None:
    """
    Streaming dictation endpoint.

    Clients send binary PCM frames and JSON control messages.
    The server buffers audio and transcribes on demand.
    """
    await websocket.accept()
    client_addr = websocket.client
    log.info("Client connected: %s", client_addr)

    # Per-connection audio buffer
    audio_buffer = bytearray()
    loop = asyncio.get_running_loop()

    try:
        while True:
            # Receive either binary audio or a JSON control message
            message = await websocket.receive()

            if "bytes" in message and message["bytes"] is not None:
                # --- Binary frame: raw PCM audio ---
                chunk = message["bytes"]
                audio_buffer.extend(chunk)
                # (Optional) log periodic buffer size for debugging
                # log.debug("Buffer size: %d bytes", len(audio_buffer))

            elif "text" in message and message["text"] is not None:
                # --- JSON control message ---
                try:
                    ctrl = json.loads(message["text"])
                except json.JSONDecodeError:
                    await websocket.send_text(
                        json.dumps({"type": "error", "message": "Invalid JSON"})
                    )
                    continue

                action = ctrl.get("action", "")

                if action == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))

                elif action in ("transcribe", "transcribe_final"):
                    # Transcribe current buffer and clear it
                    pcm_snapshot = bytes(audio_buffer)
                    audio_buffer.clear()
                    result = await loop.run_in_executor(
                        _executor, lambda: _transcribe_pcm(pcm_snapshot, clear_buffer=True)
                    )
                    await websocket.send_text(json.dumps(result))

                elif action == "transcribe_chunk":
                    # Transcribe current buffer but keep accumulating
                    pcm_snapshot = bytes(audio_buffer)
                    result = await loop.run_in_executor(
                        _executor, lambda: _transcribe_pcm(pcm_snapshot, clear_buffer=False)
                    )
                    await websocket.send_text(json.dumps(result))

                elif action == "clear":
                    audio_buffer.clear()
                    log.info("Buffer cleared for %s", client_addr)

                else:
                    await websocket.send_text(
                        json.dumps({"type": "error", "message": f"Unknown action: {action}"})
                    )

    except WebSocketDisconnect:
        log.info("Client disconnected: %s", client_addr)
    except Exception as exc:
        log.exception("Unexpected error for client %s: %s", client_addr, exc)
        try:
            await websocket.send_text(
                json.dumps({"type": "error", "message": str(exc)})
            )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=SERVER_PORT,
        workers=1,
        log_level="info",
    )
