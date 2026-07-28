from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.response import UserCreate
from app.models.db_models import User
from app.services.auth import create_access_token
from sqlalchemy import select

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

async def get_user_by_email(db:AsyncSession,email:str)->User:
   return await db.scalar(select(User).where(User.email==email))

async def login_token(payload,db):
    user = await get_user_by_email(db,payload.email)

    if not user:
        raise ValueError("Email doesnt exist")

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

