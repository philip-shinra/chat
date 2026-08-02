from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.response import UserCreate
from app.models.db_models import User
from app.services.auth import create_access_token, decode_token
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi import Depends, HTTPException, status
from app.core.database import get_db
from sqlalchemy import select

bearer_scheme = HTTPBearer()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

async def get_user_by_email(db:AsyncSession,email:str)->User:
   return await db.scalar(select(User).where(User.email==email))

async def get_user_by_username(db:AsyncSession,username:str)->User:
   return await db.scalar(select(User).where(User.name==username))

async def login_token(payload,db):
    user = await get_user_by_username(db,payload.username)

    if not user:
        raise ValueError("Username doesnt exist")

    if not verify_password(plain_password=payload.password, hashed_password=user.password_hash):
        raise ValueError("Invalid password")
    
    acces_token = create_access_token({
        "sub": str(user.id),
        "role": user.role
    })

    return {
        "access_token":acces_token
    }


async def create_user(db:AsyncSession, payload:UserCreate):
    existing = await get_user_by_email(db,email=payload.email)
    if existing:
        raise ValueError("Email already exsits")
    existing_username = await get_user_by_username(db,username=payload.username)
    if existing_username:
        raise ValueError("Username already exists")
    user =User(
        name = payload.username,
        email = payload.email,
        password_hash = hash_password(payload.password)
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return {
        "message":"user created successfuly"
    }

async def get_current_user(db:AsyncSession=Depends(get_db), credentials:HTTPAuthorizationCredentials = Depends(bearer_scheme)):
    token = credentials.credentials
    payload = decode_token(token)
    user_id = payload.get("sub")

    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )

    user = await db.get(User, int(user_id))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    return user
