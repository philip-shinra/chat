from app.core.config import SECRET_KEY, JWT_HASH_ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES
from datetime import datetime, timedelta
from jose import jwt, JWTError
from fastapi import HTTPException, status

def create_access_token(data:dict):
    payload = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload["exp"] = expire

    return jwt.encode(
        payload,
        SECRET_KEY,
        algorithm=JWT_HASH_ALGORITHM
    )

def decode_token(token:str):
    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[JWT_HASH_ALGORITHM]
        )
        return payload

    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or Expired token"
        )


