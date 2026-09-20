"""Fan-out WebSocket hub for IMU + session broadcasts."""

from __future__ import annotations

import json
from typing import Any

from fastapi import WebSocket


class WebSocketManager:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._clients.discard(ws)

    async def broadcast(self, payload: dict[str, Any]) -> None:
        if not self._clients:
            return
        message = json.dumps(payload, default=str)
        stale: list[WebSocket] = []
        for client in list(self._clients):
            try:
                await client.send_text(message)
            except Exception:
                stale.append(client)
        for client in stale:
            self.disconnect(client)

    @property
    def client_count(self) -> int:
        return len(self._clients)
