from app.models.db_models import Space, SpaceMember
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
