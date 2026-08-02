from fastapi import APIRouter, Depends, HTTPException
from app.models.response import SpaceCreate, SpaceJoin, MessageFilter
from app.core.database import get_db
from app.services.user_service import get_current_user
from app.services.spaces import create_space_service, join_space_invite_code, get_spaces_by_user
from app.services.messages import filter_messages
from app.models.exceptions import NotSpaceMemberError
router = APIRouter()

@router.post("/create")
async def create_space(space_detail:SpaceCreate,
                 user_detail=Depends(get_current_user),
                 db=Depends(get_db)):
    return await create_space_service(db,space_detail,user_detail)
    
@router.get("/list_spaces")
async def list_spaces_by_user(user_detail=Depends(get_current_user),
                    db=Depends(get_db)):
    return await get_spaces_by_user(user_detail,db)

@router.post("/edit")
async def edit_space():
    pass

@router.post("/join")
async def join_space(invite_payload:SpaceJoin,
                     user_detail=Depends(get_current_user),
                     db=Depends(get_db)):
    
    return await join_space_invite_code(db,invite_payload.invite_code,user_detail)


@router.post("/spaces/{space_id}/messages/filter")
async def get_message_history(space_id: int,
                              filters: MessageFilter,
                              user_detail=Depends(get_current_user),
                              db=Depends(get_db)):
    try:
        return await filter_messages(db, space_id, filters, user_detail)
    except NotSpaceMemberError:
        raise HTTPException(status_code=403, detail="Not a member of this space")


