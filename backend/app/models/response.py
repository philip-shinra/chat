from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr

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
