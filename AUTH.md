# Auth Implementation — Step by Step

Goal: `POST /auth/register`, `POST /auth/login`, `GET /auth/me`, backed by the `users` table that already exists (`id`, `name`, `email`, `password_hash`, `created_at`). Also covers a global `role` (admin/member) on `users`, plus admin-only endpoints to list and remove users (Step 10).

Note: this `role` is global (platform-wide admin vs. member) — different from the per-space `owner`/`member` role planned for `space_members` later. Don't conflate the two.

---

## Step 1 — Add dependencies

**`backend/requirements.txt`** — add these lines:
```
passlib[bcrypt]
python-jose[cryptography]
pydantic[email]
```
- `passlib[bcrypt]` — hashing/verifying passwords
- `python-jose[cryptography]` — encoding/decoding JWTs
- `pydantic[email]` — gives you `EmailStr` for validating email fields in schemas

**Also keep both Postgres drivers**, since the project uses an async engine for the app but Alembic migrations stay sync (see Step 2 note below):
```
asyncpg
psycopg2-binary
```
`asyncpg` — used by the app's async engine. `psycopg2-binary` — used by Alembic (`alembic/env.py`), which runs migrations synchronously even in an async app.

After adding, rebuild so the container picks them up:
```bash
docker compose build api migrate
```

---

## Step 2 — Async engine, session dependency, and the Alembic split

The project uses `create_async_engine` + `asyncpg` for the running app (not `create_engine`/`psycopg2`), so the DB layer and every route touching it needs to follow the async pattern consistently.

**`backend/app/core/database.py`** — full corrected content:

```python
import os
import logging

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL", "")

if not DATABASE_URL:
    logger.info("DATABASE URL not found or not loaded")

engine = create_async_engine(DATABASE_URL)
SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with SessionLocal() as db:
        yield db
```

Key differences from a sync setup, and from what's currently in the file:
- `create_async_engine` is imported from `sqlalchemy.ext.asyncio`, **not** top-level `sqlalchemy` — importing it from `sqlalchemy` directly will raise `ImportError`.
- `async_sessionmaker` (also from `sqlalchemy.ext.asyncio`) replaces `sessionmaker` — this is the actual session factory; without it there's no `SessionLocal` to use in `get_db`.
- `get_db` is `async def`, and uses `async with SessionLocal() as db: yield db` — this handles closing the session automatically, no manual `try/finally` + `db.close()` needed (that pattern is sync-only).
- `Base` stays exactly as-is — table definitions don't change between sync/async.

**`.env` / `.env.example`** — `DATABASE_URL` needs the `+asyncpg` driver scheme:
```
DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/postgres
```

**`backend/alembic/env.py`** — Alembic keeps using a **sync** connection (via `psycopg2`) even though the app is async; don't try to make Alembic itself async. Since it reads the same `DATABASE_URL`, strip the `+asyncpg` back out before handing the URL to Alembic:

```python
db_url = os.environ["DATABASE_URL"].replace("+asyncpg", "")
config.set_main_option("sqlalchemy.url", db_url)
```
(replaces the existing `config.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])` line). Without this, Alembic's sync `engine_from_config` will fail trying to load an async dialect.

This `get_db` is what your routes will use via `Depends(get_db)` to get a DB session per-request.

---

## Step 3 — Config for JWT secret

**`backend/app/core/config.py`** (new file) — centralize settings read from env:

```python
import os

SECRET_KEY = os.environ["JWT_SECRET_KEY"]
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
```

Add `JWT_SECRET_KEY=<some long random string>` to `.env` and `.env.example` (blank value in the example, like the other secrets). Generate a real value for `.env` with e.g. `openssl rand -hex 32`.

Also add `JWT_SECRET_KEY: ${JWT_SECRET_KEY}` to the `api` service's `environment:` block in `docker-compose.yml` (it's the only service that needs it — `migrate` doesn't touch auth).

---

## Step 4 — Pydantic schemas

**`backend/app/schemas/user.py`** (new file):

```python
from datetime import datetime
from pydantic import BaseModel, EmailStr

class UserCreate(BaseModel):
    name: str
    email: EmailStr
    password: str

class UserOut(BaseModel):
    id: int
    name: str
    email: EmailStr
    created_at: datetime

    class Config:
        from_attributes = True  # lets this build directly from a SQLAlchemy User object

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

class LoginRequest(BaseModel):
    email: EmailStr
    password: str
```

Register in **`backend/app/schemas/__init__.py`**:
```python
from .user import UserCreate, UserOut, Token, LoginRequest  # noqa: F401
```

Note: `UserCreate`/`UserOut` are Pydantic (API request/response shapes) — separate from your SQLAlchemy `User` in `models/models.py` (the DB table). Don't merge these; that separation is intentional and standard for FastAPI + SQLAlchemy.

---

## Step 5 — Password hashing service

**`backend/app/services/security.py`** (new file):

```python
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)
```

---

## Step 6 — JWT service

**`backend/app/services/auth.py`** (new file):

```python
from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError
from app.core.config import SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None
```

Convention: put the user's id in the token payload as `{"sub": str(user.id)}` when you call `create_access_token` in the login route — `sub` (subject) is the standard JWT claim for "who this token is about."

---

## Step 7 — User service (DB access + business logic, kept out of the router)

Routers should stay thin: parse the request, call a service function, shape the response. All DB queries and rules like "email already registered" belong here instead, in `services/`, so they're reusable later from WebSocket handlers and testable without spinning up HTTP.

**`backend/app/services/user_service.py`** (new file):

```python
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import User
from app.schemas.user import UserCreate
from app.services.security import hash_password, verify_password


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    return await db.scalar(select(User).where(User.email == email))


async def get_user_by_id(db: AsyncSession, user_id: int) -> User | None:
    return await db.get(User, user_id)


async def create_user(db: AsyncSession, payload: UserCreate) -> User:
    existing = await get_user_by_email(db, payload.email)
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        name=payload.name,
        email=payload.email,
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def authenticate_user(db: AsyncSession, email: str, password: str) -> User:
    user = await get_user_by_email(db, email)
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return user


async def list_users(db: AsyncSession) -> list[User]:
    result = await db.scalars(select(User))
    return list(result.all())


async def delete_user(db: AsyncSession, user_id: int, requesting_admin: User) -> None:
    user = await get_user_by_id(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == requesting_admin.id:
        raise HTTPException(status_code=400, detail="Cannot delete your own admin account")
    await db.delete(user)
    await db.commit()
```

Note: raising `HTTPException` directly from the service (rather than a custom domain exception the router translates) is a pragmatic middle ground — it keeps this app simple while still moving the *logic* out of routers. If this grows into a large codebase later, custom exceptions + router-level translation is the more decoupled version; not needed at this size.

---

## Step 8 — Auth router (thin — calls the service)

**`backend/app/routers/auth.py`** (new file):

Note: the app uses an async DB engine (Step 2), so every route/dependency touching `db` must be `async def` with `db: AsyncSession`, and every DB call must be `await`ed.

```python
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.models import User
from app.schemas.user import UserCreate, UserOut, Token, LoginRequest
from app.services import user_service
from app.services.auth import create_access_token, decode_access_token

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(payload: UserCreate, db: AsyncSession = Depends(get_db)):
    return await user_service.create_user(db, payload)

@router.post("/login", response_model=Token)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    user = await user_service.authenticate_user(db, payload.email, payload.password)
    token = create_access_token({"sub": str(user.id)})
    return Token(access_token=token)
```

`GET /auth/me` needs a reusable "get current user from token" dependency — add this in the same file:

```python
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

async def get_current_user(token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)) -> User:
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user = await user_service.get_user_by_id(db, int(payload["sub"]))
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user

@router.get("/me", response_model=UserOut)
async def me(current_user: User = Depends(get_current_user)):
    return current_user
```

Notice the router no longer imports `select`, touches `User` only as a type hint, and never calls `db.scalar`/`db.commit` directly — that's all in `user_service.py` now.

---

## Step 9 — Wire the router into the app

**`backend/app/main.py`** — add alongside the existing `health_router` include:

```python
from app.routers.auth import router as auth_router
...
app.include_router(auth_router)
```

---

## Step 10 — Rebuild and test

```bash
docker compose up --build
```

Test with curl (or import into Postman/Insomnia):

```bash
# register
curl -X POST http://localhost:8080/auth/register \
  -H "Content-Type: application/json" \
  -d '{"name":"Alice","email":"alice@example.com","password":"secret123"}'

# login
curl -X POST http://localhost:8080/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"alice@example.com","password":"secret123"}'

# me (replace TOKEN with the access_token from login)
curl http://localhost:8080/auth/me -H "Authorization: Bearer TOKEN"
```

---

## Step 11 — Global admin role + admin user-management endpoints

### 10a. Add `role` to the `User` model

**`backend/app/models/models.py`** — add a `role` column, defaulting new users to `"member"`:

```python
role: Mapped[str] = mapped_column(String(20), server_default="member", nullable=False)
```

### 10b. Generate + apply the migration

```bash
docker compose run --rm migrate alembic revision --autogenerate -m "add role to users"
```

Open the generated file and check it only adds the `role` column (with the server default) — nothing else. Then apply:

```bash
docker compose run --rm migrate alembic upgrade head
```

### 10c. Update schemas

**`backend/app/schemas/user.py`** — add `role` to `UserOut` so it's visible in responses (never add it to `UserCreate` — a user should never be able to set their own role at registration):

```python
class UserOut(BaseModel):
    id: int
    name: str
    email: EmailStr
    role: str
    created_at: datetime

    class Config:
        from_attributes = True
```

### 10d. Admin-only dependency

**`backend/app/routers/auth.py`** — add this below `get_current_user` (reuses it):

```python
async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user
```

### 10e. Admin router

**`backend/app/routers/admin.py`** (new file) — thin again, calls `user_service.list_users`/`user_service.delete_user` from Step 7 (which already handles the "can't delete yourself" rule):

```python
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.models import User
from app.schemas.user import UserOut
from app.services import user_service
from app.routers.auth import require_admin

router = APIRouter(prefix="/admin", tags=["admin"])

@router.get("/users", response_model=list[UserOut])
async def list_all_users(db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    return await user_service.list_users(db)

@router.delete("/users/{user_id}", status_code=204)
async def remove_user(user_id: int, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    await user_service.delete_user(db, user_id, requesting_admin=admin)
```

Wire it into **`backend/app/main.py`** alongside `auth_router`:

```python
from app.routers.admin import router as admin_router
...
app.include_router(admin_router)
```

### 10f. Promote your first admin manually

There's no endpoint to self-promote to admin (by design — an unauthenticated user shouldn't be able to grant themselves admin). After registering your first user, promote it directly in Postgres:

```bash
psql -h localhost -p 5432 -U postgres -d postgres \
  -c "UPDATE users SET role = 'admin' WHERE email = 'alice@example.com';"
```

### 10g. Test

```bash
# login as the admin user to get a token, then:
curl http://localhost:8080/admin/users -H "Authorization: Bearer TOKEN"

curl -X DELETE http://localhost:8080/admin/users/2 -H "Authorization: Bearer TOKEN"

# as a non-admin token, both should return 403
```

---

## Things to double check as you go

- `password_hash` should never appear in `UserOut` or any response — it doesn't, since `UserOut` simply doesn't declare that field.
- `JWT_SECRET_KEY` must be a real secret in `.env` (not committed) — never reuse `postgres`/`postgres` style placeholder values for this one, it's what signs your tokens.
- No new Alembic migration needed for Steps 1-9 — you're not changing the `users` table there, only adding application code around it. Step 10 does need one, for the new `role` column.
- `role` must never be settable via `UserCreate` — only change it through direct DB access (10f) or, later, an existing-admin-only endpoint if you build one.
- An admin should not be able to delete their own account via the API (handled in 10e) — otherwise a single admin could lock everyone (including themselves) out.
- Everything touching `db` must be async end-to-end: `async def` route/dependency, `AsyncSession` type hint, `await` on every `db.scalar/get/commit/refresh/delete` call. Mixing a sync call into an async session (or vice versa) raises an error immediately — there's no silent partial-async state.
- `alembic/env.py` intentionally stays on the sync driver (`psycopg2`, with `+asyncpg` stripped from the URL) — don't try to make Alembic async too; the `migrate` service runs independently from the app and doesn't need it.
- Routers (`auth.py`, `admin.py`) should never call `db.scalar`/`db.get`/`db.commit` directly — that logic lives in `services/user_service.py` (Step 7). If a route starts writing SQL/ORM queries directly, that's a signal it belongs in the service layer instead.
