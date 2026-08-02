from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr
import uuid

class UserCreate(BaseModel):
    username:str
    password:str
    email:EmailStr

class UserLogin(BaseModel):
    username:str
    password:str

class SpaceCreate(BaseModel):
    name:str
    agent_instruction:Optional[str]

class SpaceJoin(BaseModel):
    invite_code:str

class MessageCreate(BaseModel):
    content: str
    message_type: str = "text"
    reply_to_message_id: Optional[uuid.UUID] = None

class MessageFilter(BaseModel):
    after: Optional[datetime] = None
    before: Optional[datetime] = None
    sender_user_id: Optional[int] = None
    message_type: Optional[str] = None
    limit: int = 50

class UserOut(BaseModel):
    id: int
    name: str
    email: EmailStr

    class Config:
        from_attributes = True