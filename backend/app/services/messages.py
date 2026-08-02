from app.models.db_models import Message, Space, SpaceMember
from app.models.response import MessageCreate
from sqlalchemy import select
from app.models.exceptions import NotSpaceMemberError

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

