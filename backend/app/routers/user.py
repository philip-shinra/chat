from fastapi import APIRouter, Depends
from ..core.database import get_db

router =APIRouter()

@router.post("/register")
async def register(
    db=Depends(get_db),
):
    pass

    
    
    