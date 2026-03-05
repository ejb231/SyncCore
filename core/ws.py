"""WebSocket connection manager for real-time dashboard updates."""

from __future__ import annotations

import asyncio
import json

from fastapi import WebSocket

from utils.logging import get_logger

log = get_logger("ws")


class ConnectionManager:
    """Tracks active WebSocket connections and broadcasts JSON events."""

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.append(ws)
        log.debug("WebSocket client connected (%d total)", len(self._connections))

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self._connections:
            self._connections.remove(ws)
        log.debug(
            "WebSocket client disconnected (%d remaining)", len(self._connections)
        )

    async def broadcast(self, event: dict) -> None:
        """Send *event* to every connected client; prune dead sockets."""
        payload = json.dumps(event)
        dead: list[WebSocket] = []
        for ws in self._connections:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    def broadcast_sync(self, event: dict) -> None:
        """Fire-and-forget broadcast from synchronous (non-async) code."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.broadcast(event))
        except RuntimeError:
            pass


ws_manager = ConnectionManager()
