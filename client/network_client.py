"""TalkFlow Agent — runs on a remote DeskFlow screen (e.g. the Ubuntu box).

When DeskFlow gives this machine the keyboard, your hotkey (F9) arrives HERE,
not on the PC. This agent catches it locally, asks the TalkFlow Host (the PC,
which has the mic) to record + transcribe, then types the returned text into
whatever app is focused on THIS screen.

Run:
    python talkflow_agent.py --host 192.168.1.50:9877 --hotkey f9
    # --host is the PC's IP (LAN or Tailscale) and the host port.
"""

import asyncio
import json
import logging

try:
    import websockets
except ImportError:
    print("websockets package required: pip install websockets")
    raise

from hotkey_listener import HotkeyListener
from keystroke_injector import KeystrokeInjector

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(levelname)-8s  %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger("talkflow.agent")


class TalkFlowAgent:
    """Catches the local hotkey, drives the remote host, injects returned text."""

    def __init__(self, host_ip: str, port: int = 9877, hotkey: str = "f9"):
        self.host_ip = host_ip
        self.port = port
        self.hotkey = hotkey
        self.websocket = None
        self._running = False
        self._reconnect_delay = 1
        self._loop: asyncio.AbstractEventLoop | None = None
        self._injector = KeystrokeInjector()
        self._listener = HotkeyListener(
            hotkey=hotkey,
            on_press_start=self._on_hold_start,
            on_press_stop=self._on_hold_stop,
            mode="push-to-talk",
        )

    @property
    def uri(self) -> str:
        return f"ws://{self.host_ip}:{self.port}"

    # -- hotkey callbacks (run in pynput's thread) ----------------------
    def _send_threadsafe(self, action: str) -> None:
        if not self._loop or not self.websocket:
            logger.warning("Not connected to host — hotkey '%s' ignored", action)
            return
        asyncio.run_coroutine_threadsafe(self._send_hotkey(action), self._loop)

    def _on_hold_start(self) -> None:
        print("⏺  recording (speak now)...")
        self._send_threadsafe("start")

    def _on_hold_stop(self) -> None:
        print("⏹  released — transcribing...")
        self._send_threadsafe("stop")

    async def _send_hotkey(self, action: str) -> None:
        try:
            await self.websocket.send(json.dumps({"type": "hotkey", "action": action}))
        except Exception as exc:
            logger.warning("could not send '%s': %s", action, exc)

    # -- networking -----------------------------------------------------
    async def connect(self) -> None:
        self._loop = asyncio.get_running_loop()
        while self._running:
            try:
                async with websockets.connect(self.uri) as ws:
                    self.websocket = ws
                    self._reconnect_delay = 1
                    logger.info("Connected to host at %s", self.uri)
                    print(f"✓  Connected to TalkFlow Host ({self.uri}). "
                          f"Hold {self.hotkey} to dictate.")
                    await self.receive_loop()
            except (ConnectionRefusedError, OSError) as e:
                self.websocket = None
                logger.warning("Connect failed: %s — retrying in %ss",
                               e, self._reconnect_delay)
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, 30)
            except websockets.exceptions.ConnectionClosed:
                self.websocket = None
                logger.warning("Connection closed — reconnecting...")
                await asyncio.sleep(1)

    async def receive_loop(self) -> None:
        async for message in self.websocket:
            await self.process_message(message)

    async def process_message(self, message: str) -> None:
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            return
        mtype = data.get("type")
        if mtype == "text":
            text = data.get("data", "")
            if text:
                logger.info("Injecting: %s", text[:60])
                # Run injection off the event loop (it can block on subprocess).
                await asyncio.get_running_loop().run_in_executor(
                    None, self._injector.type_text, text + " ")
                print(f"✓  {text}")
            else:
                print("⚠  (no speech detected)")
        elif mtype == "error":
            print(f"✗  Host error: {data.get('message', '')}")

    # -- lifecycle ------------------------------------------------------
    async def start(self) -> None:
        self._running = True
        self._listener.start()
        print(f"\n{'='*56}")
        print("  TalkFlow Agent — remote dictation")
        print(f"  Host  : {self.uri}")
        print(f"  Hotkey: {self.hotkey} (push-to-talk)")
        print(f"{'='*56}")
        await self.connect()

    async def stop(self) -> None:
        self._running = False
        try:
            self._listener.stop()
        except Exception:
            pass
        if self.websocket:
            await self.websocket.close()


def main() -> None:
    import argparse

    p = argparse.ArgumentParser(description="TalkFlow Agent (runs on a remote DeskFlow screen)")
    p.add_argument("--host", required=True, metavar="IP[:PORT]",
                   help="TalkFlow Host address, e.g. 192.168.1.50:9877 (the PC)")
    p.add_argument("--hotkey", default="f9", help="Push-to-talk hotkey (default: f9)")
    args = p.parse_args()

    if ":" in args.host:
        ip, port = args.host.rsplit(":", 1)
        port = int(port)
    else:
        ip, port = args.host, 9877

    agent = TalkFlowAgent(ip, port, hotkey=args.hotkey)
    try:
        asyncio.run(agent.start())
    except KeyboardInterrupt:
        print("\nShutting down.")


if __name__ == "__main__":
    main()
