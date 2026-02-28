"""
TalkFlow — Groq Whisper Transcription Module
=============================================
Sends audio to Groq's Whisper API for fast cloud-based transcription.

Usage:
    from groq_transcriber import GroqTranscriber

    transcriber = GroqTranscriber(api_key="gsk_...")
    text = transcriber.transcribe(pcm_bytes)

The module accepts raw PCM bytes (16kHz, mono, int16) and converts them
to WAV format internally before sending to the API.
"""

from __future__ import annotations

import io
import wave
import logging
from typing import Optional

log = logging.getLogger("talkflow.groq")

# Audio format constants (must match audio_capture.py)
SAMPLE_RATE = 16_000
CHANNELS = 1
SAMPLE_WIDTH = 2  # bytes (int16)

# Groq API endpoint
GROQ_API_URL = "https://api.groq.com/openai/v1/audio/transcriptions"

# Whisper models available on Groq
MODEL_MULTILINGUAL = "whisper-large-v3-turbo"  # Supports all languages
MODEL_ENGLISH = "distil-whisper-large-v3-en"   # English-only, faster


def pcm_to_wav(pcm_bytes: bytes) -> bytes:
    """Convert raw PCM bytes to WAV format."""
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(SAMPLE_WIDTH)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm_bytes)
    return buffer.getvalue()


class GroqTranscriber:
    """
    Transcribes audio using Groq's Whisper API.

    Supports fallback to a local WebSocket server if the API fails.
    """

    def __init__(
        self,
        api_key: str,
        model: str = MODEL_MULTILINGUAL,
        language: Optional[str] = None,
    ):
        """
        Initialize the Groq transcriber.

        Parameters
        ----------
        api_key : str
            Groq API key (starts with gsk_).
        model : str
            Whisper model to use. Default: whisper-large-v3-turbo.
        language : str, optional
            Language code (e.g., 'en', 'es', 'fr'). Auto-detected if None.
        """
        self.api_key = api_key
        self.model = model
        self.language = language

        if not api_key or not api_key.startswith("gsk_"):
            log.warning("Invalid Groq API key format (should start with gsk_)")

    def transcribe(self, pcm_bytes: bytes, timeout: float = 30.0) -> dict:
        """
        Transcribe audio using Groq Whisper API.

        Parameters
        ----------
        pcm_bytes : bytes
            Raw PCM audio (16kHz, mono, int16).
        timeout : float
            Request timeout in seconds.

        Returns
        -------
        dict
            {"text": str, "process_time": float, "backend": "groq"}
            or {"error": str} on failure.
        """
        import time
        start_time = time.time()

        # Convert PCM to WAV
        wav_bytes = pcm_to_wav(pcm_bytes)
        log.debug("Converted %d PCM bytes to %d WAV bytes", len(pcm_bytes), len(wav_bytes))

        try:
            import requests
        except ImportError:
            # Fallback to urllib if requests not available
            return self._transcribe_urllib(wav_bytes, timeout, start_time)

        return self._transcribe_requests(wav_bytes, timeout, start_time)

    def _transcribe_requests(
        self, wav_bytes: bytes, timeout: float, start_time: float
    ) -> dict:
        """Transcribe using the requests library."""
        import requests
        import time

        headers = {
            "Authorization": f"Bearer {self.api_key}",
        }

        # Prepare multipart form data
        files = {
            "file": ("audio.wav", wav_bytes, "audio/wav"),
        }
        data = {
            "model": self.model,
            "response_format": "json",
        }
        if self.language:
            data["language"] = self.language

        try:
            response = requests.post(
                GROQ_API_URL,
                headers=headers,
                files=files,
                data=data,
                timeout=timeout,
            )

            process_time = time.time() - start_time

            if response.status_code == 200:
                result = response.json()
                text = result.get("text", "").strip()
                log.info("Groq transcription: %.2fs, %d chars", process_time, len(text))
                return {
                    "text": text,
                    "process_time": process_time,
                    "backend": "groq",
                }
            elif response.status_code == 429:
                log.warning("Groq rate limit hit")
                return {"error": "Rate limit exceeded", "status_code": 429}
            else:
                error_msg = response.text[:200]
                log.error("Groq API error %d: %s", response.status_code, error_msg)
                return {"error": f"API error {response.status_code}", "details": error_msg}

        except requests.exceptions.Timeout:
            log.error("Groq API timeout after %.1fs", timeout)
            return {"error": "Request timeout"}
        except requests.exceptions.ConnectionError as e:
            log.error("Groq connection error: %s", e)
            return {"error": f"Connection error: {e}"}
        except Exception as e:
            log.error("Groq unexpected error: %s", e)
            return {"error": f"Unexpected error: {e}"}

    def _transcribe_urllib(
        self, wav_bytes: bytes, timeout: float, start_time: float
    ) -> dict:
        """Fallback transcription using urllib (no requests dependency)."""
        import urllib.request
        import urllib.error
        import json
        import time
        import uuid

        # Build multipart form data manually
        boundary = f"----WebKitFormBoundary{uuid.uuid4().hex[:16]}"

        body_parts = []

        # Add model field
        body_parts.append(f"--{boundary}")
        body_parts.append('Content-Disposition: form-data; name="model"')
        body_parts.append("")
        body_parts.append(self.model)

        # Add response_format field
        body_parts.append(f"--{boundary}")
        body_parts.append('Content-Disposition: form-data; name="response_format"')
        body_parts.append("")
        body_parts.append("json")

        # Add language field if specified
        if self.language:
            body_parts.append(f"--{boundary}")
            body_parts.append('Content-Disposition: form-data; name="language"')
            body_parts.append("")
            body_parts.append(self.language)

        # Join text parts
        body_text = "\r\n".join(body_parts) + "\r\n"

        # Add file field (binary)
        file_header = f"--{boundary}\r\n"
        file_header += 'Content-Disposition: form-data; name="file"; filename="audio.wav"\r\n'
        file_header += "Content-Type: audio/wav\r\n\r\n"

        # Build complete body
        body = body_text.encode('utf-8')
        body += file_header.encode('utf-8')
        body += wav_bytes
        body += f"\r\n--{boundary}--\r\n".encode('utf-8')

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        }

        req = urllib.request.Request(GROQ_API_URL, data=body, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                process_time = time.time() - start_time
                result = json.loads(response.read().decode('utf-8'))
                text = result.get("text", "").strip()
                log.info("Groq transcription (urllib): %.2fs, %d chars", process_time, len(text))
                return {
                    "text": text,
                    "process_time": process_time,
                    "backend": "groq",
                }
        except urllib.error.HTTPError as e:
            log.error("Groq API HTTP error %d", e.code)
            return {"error": f"API error {e.code}"}
        except urllib.error.URLError as e:
            log.error("Groq URL error: %s", e.reason)
            return {"error": f"Connection error: {e.reason}"}
        except Exception as e:
            log.error("Groq unexpected error: %s", e)
            return {"error": f"Unexpected error: {e}"}


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    import os

    logging.basicConfig(level=logging.DEBUG)

    # Test with a sample audio file or generate test tone
    api_key = os.environ.get("GROQ_API_KEY", "REMOVED_GROQ_API_KEY")

    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
        # Load existing WAV file
        with wave.open(sys.argv[1], 'rb') as wf:
            pcm_bytes = wf.readframes(wf.getnframes())
        print(f"Loaded {len(pcm_bytes)} bytes from {sys.argv[1]}")
    else:
        # Generate a short silent audio for testing connectivity
        import numpy as np
        duration = 1.0  # 1 second
        samples = int(SAMPLE_RATE * duration)
        # Generate a simple tone instead of silence (440 Hz)
        t = np.linspace(0, duration, samples, False)
        tone = (np.sin(440 * 2 * np.pi * t) * 3000).astype(np.int16)
        pcm_bytes = tone.tobytes()
        print(f"Generated {len(pcm_bytes)} bytes test audio (440 Hz tone)")

    transcriber = GroqTranscriber(api_key=api_key)
    result = transcriber.transcribe(pcm_bytes)

    print(f"\nResult: {result}")
    if "text" in result:
        print(f"Transcription: '{result['text']}'")
        print(f"Time: {result['process_time']:.2f}s")
    else:
        print(f"Error: {result.get('error', 'Unknown')}")
