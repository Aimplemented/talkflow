"""WebSocket client for TalkFlow network STT.

Receives transcribed text from server and injects keystrokes.
Sends hotkey signals to server.
"""

import asyncio
import json
import logging

try:
    import websockets
except ImportError:
    print("websockets package required: pip install websockets")
    raise

from client import keystroke_injector

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TalkFlowClient:
    """WebSocket client for receiving transcribed text."""

    def __init__(self, server_ip: str = "127.0.0.1", port: int = 9877):
        self.server_ip = server_ip
        self.port = port
        self.websocket = None
        self._running = False
        self._reconnect_delay = 1

    @property
    def uri(self) -> str:
        return f"ws://{self.server_ip}:{self.port}"

    async def connect(self) -> None:
        """Connect to the TalkFlow server."""
        while self._running:
            try:
                async with websockets.connect(self.uri) as websocket:
                    self.websocket = websocket
                    self._reconnect_delay = 1
                    logger.info(f"Connected to server at {self.uri}")
                    await self.receive_loop()
            except (ConnectionRefusedError, OSError) as e:
                logger.warning(f"Connection failed: {e}. Retrying in {self._reconnect_delay}s...")
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, 30)
            except websockets.exceptions.ConnectionClosed:
                logger.warning("Connection closed. Reconnecting...")
                await asyncio.sleep(1)

    async def receive_loop(self) -> None:
        """Receive and process messages from server."""
        async for message in self.websocket:
            await self.process_message(message)

    async def process_message(self, message: str) -> None:
        """Process incoming message from server."""
        try:
            data = json.loads(message)
            msg_type = data.get("type")

            if msg_type == "text":
                text = data.get("data", "")
                logger.info(f"Received text: {text[:50]}...")
                keystroke_injector.inject_text(text)

        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON message: {message}")

    async def send_hotkey(self, action: str) -> None:
        """Send hotkey signal to server."""
        if self.websocket:
            message = json.dumps({"type": "hotkey", "action": action})
            try:
                await self.websocket.send(message)
                logger.info(f"Sent hotkey signal: {action}")
            except websockets.exceptions.ConnectionClosed:
                logger.warning("Cannot send hotkey: not connected")

    async def start(self) -> None:
        """Start the client."""
        self._running = True
        await self.connect()

    async def stop(self) -> None:
        """Stop the client."""
        self._running = False
        if self.websocket:
            await self.websocket.close()


async def main():
    """Run the client standalone for testing."""
    client = TalkFlowClient()

    # Demo: send hotkey after connection
    async def demo_hotkey():
        await asyncio.sleep(3)
        await client.send_hotkey("toggle")

    asyncio.create_task(demo_hotkey())
    await client.start()


if __name__ == "__main__":
    asyncio.run(main())
