"""
TalkFlow — Groq Whisper API Transcription
==========================================
Transcribes audio using Groq's Whisper API (fast cloud-based transcription).

Usage:
    from groq_transcribe import transcribe_audio

    text = transcribe_audio(pcm_bytes, api_key="gsk_...")
"""

from __future__ import annotations

import io
import json
import logging
import wave
from typing import Optional

log = logging.getLogger("talkflow.groq")

# Audio format constants (must match audio_capture.py)
SAMPLE_RATE = 16_000
CHANNELS = 1
SAMPLE_WIDTH = 2  # bytes (int16)

# Groq API endpoint
GROQ_API_URL = "https://api.groq.com/openai/v1/audio/transcriptions"

# Available Whisper models on Groq
GROQ_MODEL_MULTILINGUAL = "whisper-large-v3-turbo"  # Multilingual, very fast
GROQ_MODEL_ENGLISH = "distil-whisper-large-v3-en"   # English-only, fastest


def pcm_to_wav(pcm_bytes: bytes) -> bytes:
    """
    Convert raw PCM audio bytes to WAV format.

    Args:
        pcm_bytes: Raw 16-bit mono PCM audio at 16kHz

    Returns:
        WAV file bytes (with headers)
    """
    wav_buffer = io.BytesIO()
    with wave.open(wav_buffer, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(SAMPLE_WIDTH)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm_bytes)
    return wav_buffer.getvalue()


def transcribe_audio(
    pcm_bytes: bytes,
    api_key: str,
    model: str = GROQ_MODEL_MULTILINGUAL,
    language: Optional[str] = None,
    timeout: float = 30.0,
) -> dict:
    """
    Transcribe audio using Groq's Whisper API.

    Args:
        pcm_bytes: Raw 16-bit mono PCM audio at 16kHz
        api_key: Groq API key (starts with "gsk_")
        model: Whisper model to use
        language: Optional language code (e.g., "en")
        timeout: Request timeout in seconds

    Returns:
        dict with keys:
            - "text": Transcribed text (empty string if no speech)
            - "process_time": Processing time in seconds
            - "error": Error message if failed (None on success)

    Raises:
        No exceptions - errors are returned in the result dict
    """
    import time
    start_time = time.time()

    # Convert PCM to WAV
    try:
        wav_bytes = pcm_to_wav(pcm_bytes)
    except Exception as e:
        log.error("Failed to convert PCM to WAV: %s", e)
        return {"text": "", "process_time": 0, "error": f"WAV conversion failed: {e}"}

    # Prepare multipart form data
    try:
        import urllib.request
        import urllib.error

        # Build multipart form data manually (no external deps)
        boundary = "----TalkFlowBoundary7MA4YWxkTrZu0gW"
        body_parts = []

        # File part
        body_parts.append(f"--{boundary}".encode())
        body_parts.append(b'Content-Disposition: form-data; name="file"; filename="audio.wav"')
        body_parts.append(b"Content-Type: audio/wav")
        body_parts.append(b"")
        body_parts.append(wav_bytes)

        # Model part
        body_parts.append(f"--{boundary}".encode())
        body_parts.append(b'Content-Disposition: form-data; name="model"')
        body_parts.append(b"")
        body_parts.append(model.encode())

        # Language part (optional)
        if language:
            body_parts.append(f"--{boundary}".encode())
            body_parts.append(b'Content-Disposition: form-data; name="language"')
            body_parts.append(b"")
            body_parts.append(language.encode())

        # Response format
        body_parts.append(f"--{boundary}".encode())
        body_parts.append(b'Content-Disposition: form-data; name="response_format"')
        body_parts.append(b"")
        body_parts.append(b"json")

        # End boundary
        body_parts.append(f"--{boundary}--".encode())
        body_parts.append(b"")

        body = b"\r\n".join(body_parts)

        # Make request
        req = urllib.request.Request(
            GROQ_API_URL,
            data=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "User-Agent": "TalkFlow/1.0",
            },
            method="POST",
        )

        log.debug("Sending %d bytes to Groq API (model=%s)", len(wav_bytes), model)

        with urllib.request.urlopen(req, timeout=timeout) as response:
            response_data = response.read().decode("utf-8")
            result = json.loads(response_data)

        process_time = time.time() - start_time
        text = result.get("text", "").strip()

        log.info("Groq transcription completed in %.2fs: %d chars", process_time, len(text))

        return {
            "text": text,
            "process_time": process_time,
            "error": None,
        }

    except urllib.error.HTTPError as e:
        process_time = time.time() - start_time
        error_body = e.read().decode("utf-8", errors="replace")
        log.error("Groq API HTTP error %d: %s", e.code, error_body)

        # Parse error message if JSON
        try:
            error_data = json.loads(error_body)
            error_msg = error_data.get("error", {}).get("message", str(e))
        except:
            error_msg = f"HTTP {e.code}: {error_body[:200]}"

        return {"text": "", "process_time": process_time, "error": error_msg}

    except urllib.error.URLError as e:
        process_time = time.time() - start_time
        log.error("Groq API connection error: %s", e.reason)
        return {"text": "", "process_time": process_time, "error": f"Connection error: {e.reason}"}

    except Exception as e:
        process_time = time.time() - start_time
        log.error("Groq API error: %s", e)
        return {"text": "", "process_time": process_time, "error": str(e)}


def transcribe_with_fallback(
    pcm_bytes: bytes,
    api_key: str,
    server_url: str,
    model: str = GROQ_MODEL_MULTILINGUAL,
    timeout: float = 30.0,
) -> dict:
    """
    Transcribe using Groq API, falling back to WebSocket server on failure.

    Args:
        pcm_bytes: Raw PCM audio bytes
        api_key: Groq API key
        server_url: WebSocket server URL (e.g., "192.168.1.100:9876")
        model: Groq Whisper model
        timeout: Request timeout

    Returns:
        dict with "text", "process_time", "error", "backend" keys
    """
    # Try Groq first
    if api_key:
        result = transcribe_audio(pcm_bytes, api_key, model=model, timeout=timeout)
        if result["error"] is None:
            result["backend"] = "groq"
            return result
        log.warning("Groq failed, falling back to server: %s", result["error"])

    # Fallback to WebSocket server
    if server_url:
        result = _transcribe_via_websocket(pcm_bytes, server_url, timeout)
        result["backend"] = "server"
        return result

    return {
        "text": "",
        "process_time": 0,
        "error": "No transcription backend available",
        "backend": None,
    }


def _transcribe_via_websocket(pcm_bytes: bytes, server_url: str, timeout: float) -> dict:
    """Transcribe via the self-hosted WebSocket server."""
    import time

    start_time = time.time()

    try:
        from websockets.sync.client import connect as ws_connect
    except ImportError:
        return {"text": "", "process_time": 0, "error": "websockets not installed"}

    ws_url = f"ws://{server_url}/ws/dictate"
    chunk_size = 64 * 1024

    try:
        with ws_connect(ws_url) as ws:
            # Send audio in chunks
            sent = 0
            while sent < len(pcm_bytes):
                ws.send(pcm_bytes[sent:sent + chunk_size])
                sent += chunk_size

            # Request transcription
            ws.send(json.dumps({"action": "transcribe"}))
            raw = ws.recv(timeout=timeout)
            response = json.loads(raw)

        process_time = time.time() - start_time
        return {
            "text": response.get("text", "").strip(),
            "process_time": response.get("process_time", process_time),
            "error": None,
        }

    except Exception as e:
        process_time = time.time() - start_time
        log.error("WebSocket server error: %s", e)
        return {"text": "", "process_time": process_time, "error": str(e)}


# ---------------------------------------------------------------------------
# Quick test (run this file directly)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.DEBUG)

    if len(sys.argv) < 3:
        print("Usage: python groq_transcribe.py <api_key> <wav_file>")
        print("       python groq_transcribe.py <api_key> --record 3")
        sys.exit(1)

    api_key = sys.argv[1]

    if sys.argv[2] == "--record":
        # Record live audio
        duration = float(sys.argv[3]) if len(sys.argv) > 3 else 3.0
        print(f"Recording {duration}s of audio — speak now!")

        from audio_capture import AudioCapture
        import time

        cap = AudioCapture()
        cap.start()
        time.sleep(duration)
        pcm_bytes = cap.stop()
    else:
        # Load WAV file
        wav_path = sys.argv[2]
        with wave.open(wav_path, "rb") as wf:
            pcm_bytes = wf.readframes(wf.getnframes())
        print(f"Loaded {len(pcm_bytes)} bytes from {wav_path}")

    print("Transcribing via Groq API...")
    result = transcribe_audio(pcm_bytes, api_key)

    if result["error"]:
        print(f"ERROR: {result['error']}")
    else:
        print(f"Text: {result['text']}")
        print(f"Time: {result['process_time']:.2f}s")
