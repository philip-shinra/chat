# Websocket chat implementation guide

## 1. Auth helper for websockets — `backend/app/services/user_service.py`

Browsers' native `WebSocket` API can't set an `Authorization` header, so the
token comes in as a query param instead. Add alongside `get_current_user`:

```python
async def get_current_user_ws(token: str, db: AsyncSession) -> User:
    payload = decode_token(token)
    user_id = payload.get("sub")
    if user_id is None:
        raise ValueError("Invalid token")

    user = await db.get(User, int(user_id))
    if user is None:
        raise ValueError("User not found")
    return user
```

## 2. Connection manager — `backend/app/websockets/manager.py` (new file)

```python
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
        dead_connections = []

        for ws in self.active[space_id]:
            try:
                await ws.send_json(message)
            except Exception:
                dead_connections.append(ws)

        for ws in dead_connections:
            self.disconnect(space_id, ws)

manager = ConnectionManager()
```

## 3. Websocket route — `backend/app/websockets/chat.py` (new file)

```python
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from pydantic import ValidationError
from app.core.database import get_db
from app.services.user_service import get_current_user_ws
from app.services.messages import create_messages, _assert_is_mem
from app.models.exceptions import NotSpaceMemberError
from app.websockets.manager import manager
from app.models.response import MessageCreate

router = APIRouter()

@router.websocket("/ws/spaces/{space_id}")
async def space_chat(websocket: WebSocket, space_id: int, token: str, db=Depends(get_db)):
    try:
        current_user = await get_current_user_ws(token, db)
        await _assert_is_mem(db, current_user.id, space_id)
    except (ValueError, NotSpaceMemberError):
        await websocket.close(code=4401)
        return

    await manager.connect(space_id, websocket)
    try:
        while True:
            data = await websocket.receive_json()

            try:
                payload = MessageCreate(**data)
                message = await create_messages(db, payload, space_id, current_user)
            except ValidationError as e:
                await websocket.send_json({"error": str(e)})
                continue
            except NotSpaceMemberError:
                await websocket.close(code=4403)
                break

            await manager.broadcast(space_id, {
                "id": str(message.id),
                "space_id": message.space_id,
                "sender_user_id": message.sender_user_id,
                "content": message.content,
                "message_type": message.message_type,
                "reply_to_message_id": str(message.reply_to_message_id) if message.reply_to_message_id else None,
                "created_at": message.created_at.isoformat(),
            })
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(space_id, websocket)
```

Notes:
- Auth + membership check happens **before** `manager.connect`/`accept()` —
  reject bad tokens/non-members with a close code rather than accepting
  then closing.
- The inner `try/except ValidationError` means one malformed message from a
  client sends an error frame back and keeps the connection alive, instead
  of killing the loop.
- `manager.disconnect` is in a `finally` block so it runs whether the loop
  exits via `WebSocketDisconnect`, a `break`, or any other path.

## 4. Wire into `main.py`

```python
from app.websockets.chat import router as chat_ws_router
app.include_router(chat_ws_router)
```

## Client-side connect (for testing)

```
ws://localhost:8080/ws/spaces/3?token=<jwt>
```
