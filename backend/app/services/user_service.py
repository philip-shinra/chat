from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession
from ..schemas.user import UserCreate
from app.models.models import User
from sqlalchemy import select
from fastapi import HTTPException

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

async def get_user_by_email(db:AsyncSession,email:str)->User:
   return await db.scaler(select(User).where(User.email==email))

async def create_user(db:AsyncSession, payload:UserCreate):
    existing = await get_user_by_email(db,email=payload.email)
    if existing:
        raise HTTPException(status_code=400, detail="Email already exists")
    user =User(
        name = payload.name,
        email = payload.email,
        password_hash = hash_password(payload.password)
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user

