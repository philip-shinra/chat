from app.models.db_models import Space, SpaceMember, User
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

import secrets

async def create_space_service(db,payload,current_user):
    space = Space(
        name = payload.name,
        agent_instruction =payload.agent_instruction,
        invite_code=secrets.token_urlsafe(8)
    )

    db.add(space)
    await db.flush()

    member = SpaceMember(
        space_id=space.id,
        user_id =current_user.id,
        role="admin"
    )
    db.add(member)
    await db.commit()
    await db.refresh(space)

    return {
        "id":space.id,
        "name":space.name,
        "invite_code":space.invite_code
    }


async def join_space_invite_code(db:AsyncSession,invite_code:str,current_user:User):
    """
    add users using invite code
    """
    stmt = select(Space).where(Space.invite_code==invite_code)
    result = await db.execute(stmt)

    space = result.scalar_one_or_none()

    if space is None:
        raise HTTPException(
            status_code=404,
            detail="Invalid invite code",
        )

    new_member = SpaceMember(
        space_id=space.id,
        user_id=current_user.id,
        role="member"
    )

    try:
        db.add(new_member)
        await db.commit()

    except IntegrityError as e:
        await db.rollback()
        raise HTTPException(
            status_code=400,
            detail="User is already a member of this space"
        )

    return {
        "message": "Successfully joined the space",
        "space_id": space.id,
    }

async def get_spaces_by_user(user: User, db: AsyncSession):
    stmt = (
        select(Space)
        .join(SpaceMember, SpaceMember.space_id == Space.id)
        .where(SpaceMember.user_id == user.id)
        .order_by(Space.created_at.desc())
    )
    result = await db.execute(stmt)
    spaces = result.scalars().all()

    return [
        {
            "id": space.id,
            "name": space.name,
            "invite_code": space.invite_code,
            "created_at": space.created_at,
        }
        for space in spaces
    ]


