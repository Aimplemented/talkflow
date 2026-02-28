"""
WhisperFlow — Audio Capture Module (Card 3)
============================================
Cross-platform microphone capture producing 16 kHz / mono / 16-bit PCM
(the exact format faster-whisper expects, no resampling required).

Usage
-----
    from audio_capture import AudioCapture

    cap = AudioCapture()
    cap.start()          # begin capturing
    ...                  # user speaks
    pcm_bytes = cap.stop()   # returns raw PCM bytes

Two audio backends are supported and auto-detected:
  1. pyaudio   (preferred)  — low latency, callback mode
  2. sounddevice (fallback) — InputStream with callback

Platform requirements
---------------------
  macOS   : Microphone permission granted to the terminal app
              System Settings → Privacy & Security → Microphone
  Linux   : portaudio19-dev system package  (apt-get install portaudio19-dev)
  Windows : No special setup — standard audio drivers work
"""

from __future__ import annotations

import threading
import logging
from typing import Optional

log = logging.getLogger("whisperflow.audio")

# Audio format constants — must match Whisper's expected input
SAMPLE_RATE = 16_000   # Hz
CHANNELS = 1           # mono
SAMPLE_WIDTH = 2       # bytes — int16
CHUNK_DURATION_MS = 100                       # milliseconds per callback chunk
CHUNK_FRAMES = SAMPLE_RATE * CHUNK_DURATION_MS // 1000  # = 1600 frames


# ---------------------------------------------------------------------------
# Detect available backend at import time
# ---------------------------------------------------------------------------
def _detect_backend() -> str:
    """Return 'pyaudio' or 'sounddevice' based on what is installed."""
    try:
        import pyaudio  # noqa: F401
        return "pyaudio"
    except ImportError:
        pass
    try:
        import sounddevice  # noqa: F401
        return "sounddevice"
    except ImportError:
        pass
    raise RuntimeError(
        "No audio backend found.  Install either 'pyaudio' or 'sounddevice':\n"
        "  pip install pyaudio\n"
        "  pip install sounddevice"
    )


_BACKEND = _detect_backend()
log.info("Audio backend: %s", _BACKEND)


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------
class AudioCapture:
    """
    Thread-safe microphone recorder.

    Call start() to begin, stop() to end — returns raw int16 PCM bytes.
    get_buffered_audio() returns a snapshot without stopping.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buffer = bytearray()
        self._is_recording = False

        # Backend-specific handles (populated during start())
        self._pa_instance = None   # PyAudio instance
        self._pa_stream = None     # PyAudio stream
        self._sd_stream = None     # sounddevice InputStream

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Open the microphone and begin buffering audio."""
        if self._is_recording:
            log.warning("AudioCapture.start() called while already recording — ignored")
            return

        with self._lock:
            self._buffer = bytearray()

        self._is_recording = True

        if _BACKEND == "pyaudio":
            self._start_pyaudio()
        else:
            self._start_sounddevice()

        log.info("Recording started (%s backend, %d Hz mono int16)", _BACKEND, SAMPLE_RATE)

    def stop(self) -> bytes:
        """
        Stop recording and return all buffered PCM bytes.
        Cleans up backend resources.
        """
        if not self._is_recording:
            log.warning("AudioCapture.stop() called while not recording")
            return bytes(self._buffer)

        self._is_recording = False

        if _BACKEND == "pyaudio":
            self._stop_pyaudio()
        else:
            self._stop_sounddevice()

        with self._lock:
            data = bytes(self._buffer)

        duration_s = len(data) / (SAMPLE_RATE * SAMPLE_WIDTH)
        log.info("Recording stopped — captured %.2f s (%d bytes)", duration_s, len(data))
        return data

    def get_buffered_audio(self) -> bytes:
        """Return a snapshot of the current buffer without stopping recording."""
        with self._lock:
            return bytes(self._buffer)

    # ------------------------------------------------------------------
    # PyAudio backend
    # ------------------------------------------------------------------

    def _pyaudio_callback(self, in_data, frame_count, time_info, status_flags):
        """Non-blocking callback: append raw PCM to buffer."""
        import pyaudio
        if status_flags:
            log.debug("PyAudio status flags: %s", status_flags)
        if in_data:
            with self._lock:
                self._buffer.extend(in_data)
        return (None, pyaudio.paContinue)

    def _start_pyaudio(self) -> None:
        import pyaudio
        pa = pyaudio.PyAudio()
        self._pa_instance = pa
        self._pa_stream = pa.open(
            format=pyaudio.paInt16,
            channels=CHANNELS,
            rate=SAMPLE_RATE,
            input=True,
            frames_per_buffer=CHUNK_FRAMES,
            stream_callback=self._pyaudio_callback,
        )
        self._pa_stream.start_stream()

    def _stop_pyaudio(self) -> None:
        if self._pa_stream is not None:
            try:
                self._pa_stream.stop_stream()
                self._pa_stream.close()
            except Exception as exc:
                log.debug("Error closing PyAudio stream: %s", exc)
            finally:
                self._pa_stream = None
        if self._pa_instance is not None:
            try:
                self._pa_instance.terminate()
            except Exception as exc:
                log.debug("Error terminating PyAudio: %s", exc)
            finally:
                self._pa_instance = None

    # ------------------------------------------------------------------
    # sounddevice backend
    # ------------------------------------------------------------------

    def _sounddevice_callback(self, indata, frames, time_info, status) -> None:
        """Callback from sounddevice InputStream — append raw bytes."""
        if status:
            log.debug("sounddevice status: %s", status)
        raw = indata.tobytes()
        with self._lock:
            self._buffer.extend(raw)

    def _start_sounddevice(self) -> None:
        import sounddevice as sd
        import numpy as np
        self._sd_stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=CHUNK_FRAMES,
            callback=self._sounddevice_callback,
        )
        self._sd_stream.start()

    def _stop_sounddevice(self) -> None:
        if self._sd_stream is not None:
            try:
                self._sd_stream.stop()
                self._sd_stream.close()
            except Exception as exc:
                log.debug("Error closing sounddevice stream: %s", exc)
            finally:
                self._sd_stream = None


# ---------------------------------------------------------------------------
# Quick smoke-test (run this file directly)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import time
    import wave
    import sys

    logging.basicConfig(level=logging.INFO)
    duration = float(sys.argv[1]) if len(sys.argv) > 1 else 3.0
    out_path = sys.argv[2] if len(sys.argv) > 2 else "/tmp/whisperflow_test.wav"

    print(f"Recording {duration}s of audio — speak now!")
    cap = AudioCapture()
    cap.start()
    time.sleep(duration)
    pcm = cap.stop()

    # Save as WAV for playback verification
    with wave.open(out_path, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(SAMPLE_WIDTH)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm)

    print(f"Saved {len(pcm)} bytes → {out_path}")
    print(f"Play back with: afplay {out_path}  (macOS)  or  aplay {out_path}  (Linux)")
