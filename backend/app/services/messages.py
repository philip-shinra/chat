from app.models.db_models import Message, Space, SpaceMember, User
from app.models.response import MessageCreate
from sqlalchemy import select
from app.models.exceptions import NotSpaceMemberError


def serialize_message(message, sender_name=None):
    """Single source of truth for the message shape sent to clients.

    Used by both the history endpoint and the websocket broadcast so the two
    can never drift apart.
    """
    return {
        "id": str(message.id),
        "space_id": message.space_id,
        "sender_user_id": message.sender_user_id,
        "sender_agent_id": message.sender_agent_id,
        "sender_name": sender_name,
        "content": message.content,
        "message_type": message.message_type,
        "reply_to_message_id": (
            str(message.reply_to_message_id) if message.reply_to_message_id else None
        ),
        "created_at": message.created_at.isoformat(),
    }

async def _assert_is_mem(db, user_id, space_id):
    stmt = select(SpaceMember).where(
        SpaceMember.space_id==space_id,
        SpaceMember.user_id==user_id
    )
    result = await db.execute(stmt)
    if result.scalar_one_or_none() is None:
        raise NotSpaceMemberError("Not a member of this space")

async def create_messages(db, payload, space_id, user):
    await _assert_is_mem(db,user.id,space_id)

    message_row = Message(
        space_id = space_id,
        sender_user_id=user.id,
        content= payload.content,
        reply_to_message_id=payload.reply_to_message_id
    )

    db.add(message_row)
    await db.commit()
    await db.refresh(message_row)
    return message_row


async def filter_messages(db, space_id, filters, user):
    """Message history for a space, newest-last (chronological)."""
    await _assert_is_mem(db, user.id, space_id)

    stmt = (
        select(Message, User.name)
        .join(User, User.id == Message.sender_user_id, isouter=True)
        .where(Message.space_id == space_id)
    )

    if filters.after is not None:
        stmt = stmt.where(Message.created_at >= filters.after)
    if filters.before is not None:
        stmt = stmt.where(Message.created_at <= filters.before)
    if filters.sender_user_id is not None:
        stmt = stmt.where(Message.sender_user_id == filters.sender_user_id)
    if filters.message_type is not None:
        stmt = stmt.where(Message.message_type == filters.message_type)

    # newest-first + limit gets the most RECENT n rows, then reverse so the
    # client can render top-to-bottom without re-sorting
    stmt = stmt.order_by(Message.created_at.desc()).limit(filters.limit)

    result = await db.execute(stmt)
    rows = result.all()

    return [serialize_message(message, sender_name) for message, sender_name in reversed(rows)]

