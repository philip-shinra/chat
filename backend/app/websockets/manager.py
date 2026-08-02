from collections import defaultdict
from fastapi import WebSocket

class ConnectionManager:
    def __init__(self):
        self.active = defaultdict(list)

    async def connect(self, space_id, websocket):
        await websocket.accept()
        self.active[space_id].append(websocket)

    def disconnect(self, space_id, websocket):
        if websocket in self.active[space_id]:
            self.active[space_id].remove(websocket)

        if not self.active[space_id]:
            del self.active[space_id]

    async def broadcast(self, space_id, message):
        dead_conn =[]
        for ws in self.active[space_id]:
            try:
                await ws.send_json(message)
            except Exception:
                dead_conn.append(ws)

        for ws in dead_conn:
            self.disconnect(space_id,ws)

manager = ConnectionManager()