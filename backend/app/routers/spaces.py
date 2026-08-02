from fastapi import APIRouter, Depends
from app.models.response import SpaceCreate, SpaceJoin
from app.core.database import get_db
from app.services.user_service import get_current_user
from app.services.spaces import create_space_service, join_space_invite_code
router = APIRouter()

@router.post("/create")
async def create_space(space_detail:SpaceCreate,
                 user_detail=Depends(get_current_user),
                 db=Depends(get_db)):
    return await create_space_service(db,space_detail,user_detail)
    

@router.post("/edit")
async def edit_space():
    pass

@router.post("/join")
async def join_space(invite_payload:SpaceJoin,
                     user_detail=Depends(get_current_user),
                     db=Depends(get_db)):
    
    return await join_space_invite_code(db,invite_payload.invite_code,user_detail)


