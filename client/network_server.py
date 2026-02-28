"""WebSocket server for TalkFlow network STT.

Broadcasts transcribed text to all connected clients.
Accepts hotkey signals from clients.
"""

import asyncio
import json
import logging
from typing import Set

try:
    import websockets
    from websockets.server import WebSocketServerProtocol
except ImportError:
    print("websockets package required: pip install websockets")
    raise

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TalkFlowServer:
    """WebSocket server for distributing transcribed text."""

    def __init__(self, host: str = "0.0.0.0", port: int = 9877):
        self.host = host
        self.port = port
        self.clients: Set[WebSocketServerProtocol] = set()
        self.hotkey_callback = None
        self._server = None

    async def register(self, websocket: WebSocketServerProtocol) -> None:
        """Register a new client connection."""
        self.clients.add(websocket)
        logger.info(f"Client connected: {websocket.remote_address}. Total: {len(self.clients)}")

    async def unregister(self, websocket: WebSocketServerProtocol) -> None:
        """Unregister a client connection."""
        self.clients.discard(websocket)
        logger.info(f"Client disconnected: {websocket.remote_address}. Total: {len(self.clients)}")

    async def broadcast_text(self, text: str) -> None:
        """Broadcast transcribed text to all connected clients."""
        if not self.clients:
            return

        message = json.dumps({"type": "text", "data": text})
        disconnected = set()

        for client in self.clients:
            try:
                await client.send(message)
            except websockets.exceptions.ConnectionClosed:
                disconnected.add(client)

        for client in disconnected:
            await self.unregister(client)

    async def handle_client(self, websocket: WebSocketServerProtocol) -> None:
        """Handle messages from a connected client."""
        await self.register(websocket)
        try:
            async for message in websocket:
                await self.process_message(message)
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            await self.unregister(websocket)

    async def process_message(self, message: str) -> None:
        """Process incoming message from client."""
        try:
            data = json.loads(message)
            msg_type = data.get("type")

            if msg_type == "hotkey":
                action = data.get("action")
                logger.info(f"Received hotkey signal: {action}")
                if self.hotkey_callback:
                    await self.hotkey_callback(action)

        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON message: {message}")

    def set_hotkey_callback(self, callback) -> None:
        """Set callback for hotkey signals."""
        self.hotkey_callback = callback

    async def start(self) -> None:
        """Start the WebSocket server."""
        self._server = await websockets.serve(
            self.handle_client,
            self.host,
            self.port,
        )
        logger.info(f"TalkFlow server started on ws://{self.host}:{self.port}")
        await self._server.wait_closed()

    async def stop(self) -> None:
        """Stop the WebSocket server."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            logger.info("TalkFlow server stopped")


async def main():
    """Run the server standalone for testing."""
    server = TalkFlowServer()

    async def test_hotkey(action):
        print(f"Hotkey action: {action}")

    server.set_hotkey_callback(test_hotkey)

    # Demo: broadcast test messages periodically
    async def demo_broadcast():
        await asyncio.sleep(2)
        while True:
            await server.broadcast_text("Test transcription message")
            await asyncio.sleep(5)

    asyncio.create_task(demo_broadcast())
    await server.start()


if __name__ == "__main__":
    asyncio.run(main())
