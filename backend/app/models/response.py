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