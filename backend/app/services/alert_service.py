"""WebSocket alert broadcast service."""
from __future__ import annotations

import asyncio
import logging
from typing import Any
from fastapi import WebSocket

logger = logging.getLogger("traffic_ai.alerts")


class AlertBroadcaster:
    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self.active_connections.append(websocket)
        logger.info("WebSocket client connected. Total clients: %d", len(self.active_connections))

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)
        logger.info("WebSocket client disconnected. Total clients: %d", len(self.active_connections))

    async def broadcast(self, message: dict[str, Any]) -> None:
        async with self._lock:
            disconnected = []
            for connection in self.active_connections:
                try:
                    await connection.send_json(message)
                except Exception:
                    disconnected.append(connection)
            for dead in disconnected:
                if dead in self.active_connections:
                    self.active_connections.remove(dead)


alert_broadcaster = AlertBroadcaster()
