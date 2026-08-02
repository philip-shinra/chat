from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from pydantic import ValidationError
from app.core.database import get_db
from app.services.user_service import get_current_user_ws
from app.services.messages import create_messages, _assert_is_mem, serialize_message
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

            await manager.broadcast(
                space_id,
                serialize_message(message, current_user.name),
            )
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(space_id, websocket)
