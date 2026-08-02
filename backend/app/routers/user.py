from fastapi import APIRouter, Depends
from ..core.database import get_db
from app.models.response import UserCreate, UserLogin, UserOut
from app.services.user_service import create_user, login_token, get_current_user
from fastapi import HTTPException

router =APIRouter()

@router.post("/register")
async def register(user:UserCreate,
                db=Depends(get_db)):
    
    try:
        await create_user(db,user)
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )
    return {
        "message":"user created"
    }

@router.post("/login")
async def login(login_cred:UserLogin,db=Depends(get_db)):

    try:
        token = await login_token(payload=login_cred,db=db)
        return token
    except ValueError as e:
        raise HTTPException(
            status_code=401,
            detail=str(e)
        )

@router.get("/me", response_model=UserOut)
async def me(user_detail=Depends(get_current_user)):
    return user_detail



    
    
