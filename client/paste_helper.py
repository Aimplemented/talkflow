"""
TalkFlow — Remote Paste Helper (runs on the AI5090 / remote DeskFlow screen)
============================================================================
Why this exists
---------------
The Stream Deck daemon on the PC records + transcribes, then tries to deliver
the text by copying it to the clipboard and sending a synthetic Ctrl+V, relying
on DeskFlow to (a) sync the clipboard to the active screen and (b) forward the
injected keystroke.  That round-trip works when the cursor is on the PC but is
unreliable when the cursor is on the remote screen (the AI5090): DeskFlow may
not forward a *synthetic* paste keystroke, and the clipboard-sync timing races.

This helper sidesteps DeskFlow entirely.  It listens on the LAN; the PC daemon
sends it the transcript directly; the helper types the text into whatever window
is focused *on this machine* using ydotool/wtype (Wayland) or xdotool (X11) via
the existing KeystrokeInjector.  No clipboard, no DeskFlow, no timing race.

Protocol
--------
Dead simple and line/format agnostic: the client opens a connection, writes the
UTF-8 transcript bytes, then half-closes the write side (shutdown SHUT_WR).  The
helper reads to EOF, types the text locally, and replies "ok\\n" (or "error: …").
This keeps multi-line / unicode transcripts intact without any framing.

Run on the AI5090
-----------------
    python paste_helper.py --port 9879 --bind 0.0.0.0

Then point the PC daemon at it:

    python streamdeck_daemon.py daemon --groq-key gsk_... \\
        --remote-paste 192.168.1.123:9879

Security note: this types whatever it receives into the focused window, so only
bind it on a trusted LAN (or a Tailscale/VPN interface).  Default bind is the
loopback-friendly 0.0.0.0 for LAN use; restrict with --bind if needed.
"""

from __future__ import annotations

import argparse
import logging
import os
import platform
import shutil
import socket
import sys

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(levelname)-8s  %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("talkflow.pastehelper")

DEFAULT_PORT = 9879
MAX_BYTES = 1_000_000  # guard against a runaway sender


def _injection_tool() -> str | None:
    """Return the name of an available text-injection tool, or None.

    KeystrokeInjector logs but does not raise when no tool is present, so we
    probe up front: a misconfigured remote box should fail loudly at startup
    rather than silently swallow every transcript.
    """
    if platform.system() != "Linux":
        return "native"  # macOS/Windows backends don't need an external tool
    session = os.environ.get("XDG_SESSION_TYPE", "").lower()
    candidates = ("ydotool", "wtype") if session == "wayland" else ("xdotool",)
    for tool in candidates:
        if shutil.which(tool):
            return tool
    # On X11, ydotool also works; check it as a last resort either way.
    return "ydotool" if shutil.which("ydotool") else None


def _recv_all(conn: socket.socket) -> bytes:
    """Read from *conn* until the peer half-closes (EOF) or MAX_BYTES."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = conn.recv(64 * 1024)
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total >= MAX_BYTES:
            log.warning("Payload exceeded %d bytes — truncating", MAX_BYTES)
            break
    return b"".join(chunks)


class PasteHelper:
    """Receives transcript text over TCP and types it into the focused window."""

    def __init__(self, bind: str = "0.0.0.0", port: int = DEFAULT_PORT) -> None:
        self._bind = bind
        self._port = port

        tool = _injection_tool()
        if tool is None:
            session = os.environ.get("XDG_SESSION_TYPE", "") or "unknown"
            log.error(
                "No text-injection tool found (session=%s). Install one:\n"
                "    Wayland: sudo apt install ydotool   (and run the ydotoold daemon)\n"
                "             or: sudo apt install wtype\n"
                "    X11:     sudo apt install xdotool\n"
                "Refusing to start so the PC daemon falls back to clipboard paste.",
                session)
            sys.exit(2)
        log.info("Injection tool: %s", tool)

        from keystroke_injector import KeystrokeInjector
        self._injector = KeystrokeInjector()

    def serve(self) -> None:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            srv.bind((self._bind, self._port))
        except OSError as exc:
            log.error("Cannot bind %s:%d — already in use? (%s)",
                      self._bind, self._port, exc)
            sys.exit(1)
        srv.listen(8)

        print(f"\n{'='*60}")
        print(f"  TalkFlow — remote paste helper ready")
        print(f"  Listening : {self._bind}:{self._port}")
        print(f"  Delivery  : types received text into the focused window")
        print(f"  Ctrl+C to quit.")
        print(f"{'='*60}\n")

        try:
            while True:
                conn, addr = srv.accept()
                with conn:
                    try:
                        conn.settimeout(5.0)
                        raw = _recv_all(conn)
                        text = raw.decode("utf-8", "replace")
                        if not text:
                            conn.sendall(b"error: empty\n")
                            continue
                        preview = text if len(text) <= 60 else text[:57] + "…"
                        log.info("⌨  from %s — typing %d chars: %s",
                                 addr[0], len(text), preview)
                        self._injector.type_text(text)
                        conn.sendall(b"ok\n")
                    except Exception as exc:
                        log.exception("Paste failed: %s", exc)
                        try:
                            conn.sendall(f"error: {exc}\n".encode("utf-8"))
                        except Exception:
                            pass
        except KeyboardInterrupt:
            print("\nShutting down.")
        finally:
            srv.close()


def main() -> None:
    p = argparse.ArgumentParser(
        description="TalkFlow remote paste helper (run on the AI5090).")
    p.add_argument("--port", "-p", type=int, default=DEFAULT_PORT)
    p.add_argument("--bind", "-b", default="0.0.0.0",
                   help="Interface to listen on (default 0.0.0.0; "
                        "use a Tailscale/VPN IP to restrict exposure)")
    args = p.parse_args()
    PasteHelper(bind=args.bind, port=args.port).serve()


if __name__ == "__main__":
    main()
