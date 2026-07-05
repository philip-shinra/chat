from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
import os
import logging

logger = logging.getLogger(__name__)

DATABASE_URL=os.environ.get("DATABASE_URL","")

if not DATABASE_URL:
    logger.info ("DATABASE URL not found or not loaded")

engine = create_async_engine(DATABASE_URL)
SessionLocal = async_sessionmaker(bind=engine,expire_on_commit=False)

class Base(DeclarativeBase):
    pass

async def get_db():
    async with SessionLocal() as db:
        yield db




