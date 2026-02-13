from typing import Dict, Set
from fastapi import WebSocket


class ChannelConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, Set[WebSocket]] = {}

    async def connect(self, channel_id: str, ws: WebSocket):
        if channel_id not in self.active_connections:
            self.active_connections[channel_id] = set()

        self.active_connections[channel_id].add(ws)

        print(
            "[MANAGER] connect:",
            "channel_id=",
            channel_id,
            "total=",
            len(self.active_connections[channel_id]),
        )

    def disconnect(self, channel_id: str, ws: WebSocket):
        if channel_id in self.active_connections:
            self.active_connections[channel_id].discard(ws)

            print(
                "[MANAGER] disconnect:",
                "channel_id=",
                channel_id,
                "remaining=",
                len(self.active_connections[channel_id]),
            )

            if not self.active_connections[channel_id]:
                del self.active_connections[channel_id]
                print("[MANAGER] channel removed:", channel_id)

    async def broadcast(self, channel_id: str, message: dict):
        conns = list(self.active_connections.get(channel_id, []))

        print(
            "[MANAGER] broadcast:",
            "channel_id=",
            channel_id,
            "connections=",
            len(conns),
        )

        for ws in conns:
            try:
                await ws.send_json(message)
            except Exception as e:
                print("[MANAGER][ERROR] send failed:", repr(e))


manager = ChannelConnectionManager()
