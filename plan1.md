# Chat App — V1 Plan: AI in the Chat + Writing Space

## Overview

A private, self-hosted chat application where people collaborate inside
**spaces**, with an **AI agent as a full member of each space**. Members chat
in real time; the agent is a full general assistant with complete
conversational context, and it maintains a **writing space** — a side panel
of markdown documents it creates and edits (notes, plans, summaries, todos),
persisted in Postgres and mirrored to disk as real `.md` files. The agent's
memory is itself a pinned document it keeps up to date and members can read
and correct. Runs locally via Docker; access controlled by IP whitelisting.

---

## Table of Contents

- **Part 1 — Foundation**: tech stack (1.1), folder structure (1.2), deps/config/DB (1.3–1.5), models (1.6), auth (1.7), WebSockets (1.8), job queue (1.9), agent loop (1.10), security (1.11), Nginx (1.12), Docker (1.13–1.14)
- **Part 2 — The product**: scope (2.1), data model (2.2), agent tools (2.3), memory (2.4), UI (2.5), build order (2.6), exclusions (2.7)

Read linearly: Part 1 is the plumbing, Part 2 is the product.

---

# Part 1 — Foundation

Everything here is buildable as written. Python 3.12, SQLAlchemy 2.0 style.

## 1.1 Tech Stack

### Backend — Python
| Layer | Choice | Reason |
|---|---|---|
| Framework | **FastAPI** | Async, fast, great WebSocket support |
| WebSockets | FastAPI + **python-socketio** | Real-time chat & issue threads |
| Auth | **JWT** (python-jose) + bcrypt | Simple, stateless |
| ORM | **SQLAlchemy 2.0** (async) | Clean, well-supported |
| DB | **PostgreSQL** | Reliable; JSONB for audit logs |
| Migrations | **Alembic** | Works with SQLAlchemy |
| **LLM** | **Anthropic Claude API (tool use)** | Agentic loop with function calling |
| Agent jobs | **`asyncio.Queue`** + in-process worker task | Decouple LLM latency from sockets, no extra service |

### Frontend — Web UI
| Layer | Choice | Reason |
|---|---|---|
| Framework | **React** (Vite) | Fast dev, component-friendly chat UI |
| State | **Zustand** | Lightweight, no boilerplate |
| Styling | **Tailwind CSS** | Quick, clean UI |
| Real-time | **Socket.IO client** | Pairs with backend |
| HTTP client | **Axios** | Simple REST calls |

### Infrastructure (Local Docker)
| Service | Docker Image |
|---|---|
| Backend API | Custom Python image |
| Agent worker | Same image, worker entrypoint (or in-process for MVP) |
| Frontend | Nginx serving React build |
| PostgreSQL | `postgres:16` (later: `pgvector/pgvector:pg16`) |
| Reverse Proxy | **Nginx** (with IP whitelist) |

---

## 1.2 Project Folder Structure

```
app/
├── backend/
│   ├── app/
│   │   ├── api/            — route handlers
│   │   ├── core/           — config, auth, middleware
│   │   ├── models/         — SQLAlchemy models
│   │   ├── schemas/        — Pydantic schemas
│   │   ├── services/       — business logic
│   │   │   ├── documents.py    — document CRUD + disk mirror
│   │   │   └── messages.py
│   │   ├── agent/          — agent runtime
│   │   │   ├── runner.py       — agentic loop (Claude API, tool dispatch)
│   │   │   ├── tools.py        — generic tool schemas + executors (wrap services)
│   │   │   ├── context.py      — context builder (messages, documents)
│   │   │   ├── prompts.py      — system prompt templates
│   │   │   └── queue.py        — job enqueue/consume
│   │   └── websockets/     — socket handlers
│   ├── alembic/            — migrations
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── chat/
│   │   │   └── documents/      — doc list, markdown reader, editor
│   │   ├── pages/
│   │   ├── store/          — Zustand stores
│   │   └── api/            — Axios clients
│   ├── Dockerfile
│   └── package.json
├── nginx/
│   ├── nginx.conf
│   └── ip_whitelist.conf
└── docker-compose.yml
```

---

## 1.3 Backend dependencies

```
# requirements.txt
fastapi==0.115.*
uvicorn[standard]==0.34.*
python-socketio==5.11.*
sqlalchemy[asyncio]==2.0.*
asyncpg==0.29.*
alembic==1.13.*
pydantic==2.*
pydantic-settings==2.*
python-jose[cryptography]==3.3.*
passlib[bcrypt]==1.7.*
anthropic==0.*        # pin latest at build time
httpx
```

## 1.4 Config (`app/core/config.py`)

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://app:app@postgres:5432/chatapp"
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 30
    refresh_token_days: int = 14
    anthropic_api_key: str
    agent_model: str = "claude-sonnet-4-6"
    agent_max_tool_calls: int = 8
    agent_context_messages: int = 50

settings = Settings()
```

## 1.5 Database layer (`app/core/db.py`)

```python
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

engine = create_async_engine(settings.database_url, pool_size=10, max_overflow=5)
SessionFactory = async_sessionmaker(engine, expire_on_commit=False)

async def get_db():                      # FastAPI dependency
    async with SessionFactory() as session:
        async with session.begin():      # commit on success, rollback on error
            yield session
```

Note `expire_on_commit=False` — objects stay usable after commit (you already know why from SQE). The agent worker uses `SessionFactory` directly, one short transaction per tool call.

## 1.6 Models (`app/models/`)

```python
import uuid
from datetime import datetime
from sqlalchemy import CheckConstraint, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

def pk():
    return mapped_column(default=uuid.uuid4, primary_key=True)

class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = pk()
    email: Mapped[str] = mapped_column(unique=True, index=True)
    password_hash: Mapped[str]
    name: Mapped[str]
    role: Mapped[str] = mapped_column(default="member")   # admin|member
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

class Agent(Base):
    __tablename__ = "agents"
    id: Mapped[uuid.UUID] = pk()
    name: Mapped[str] = mapped_column(default="AI")
    persona: Mapped[str | None]      # optional standing personality
    model: Mapped[str | None]        # overrides settings.agent_model if set
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

class Space(Base):
    __tablename__ = "spaces"
    id: Mapped[uuid.UUID] = pk()
    name: Mapped[str]
    agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id"))
    # set = agent enabled in this space; null = no agent
    agent_instructions: Mapped[str | None]
    invite_code: Mapped[str] = mapped_column(unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

class SpaceMember(Base):
    __tablename__ = "space_members"
    space_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("spaces.id"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    role: Mapped[str] = mapped_column(default="member")   # owner|member — humans only;
    # the agent's presence in a space is spaces.agent_id, not a membership row
    joined_at: Mapped[datetime] = mapped_column(server_default=func.now())

class Message(Base):
    __tablename__ = "messages"
    id: Mapped[uuid.UUID] = pk()
    space_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("spaces.id"))
    sender_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    sender_agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id"))
    content: Mapped[str]
    message_type: Mapped[str] = mapped_column(default="text")  # text|system|agent_action
    reply_to_message_id: Mapped[uuid.UUID | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    __table_args__ = (
        Index("ix_messages_space_created", "space_id", "created_at"),
        CheckConstraint(
            "(sender_user_id IS NULL) != (sender_agent_id IS NULL)",
            name="ck_messages_exactly_one_sender"),
    )

class AgentAction(Base):
    __tablename__ = "agent_actions"
    id: Mapped[uuid.UUID] = pk()
    space_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("spaces.id"))
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id"))
    triggered_by_message_id: Mapped[uuid.UUID | None]
    tool_name: Mapped[str]
    tool_input: Mapped[dict] = mapped_column(JSONB)
    tool_result: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(default="success")  # success|error
    error_detail: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    __table_args__ = (Index("ix_agent_actions_space_created", "space_id", "created_at"),)
```

All `DateTime` columns should be `DateTime(timezone=True)` — declare via `type_annotation_map` on `Base` so you never repeat the naive/aware bug:

```python
class Base(DeclarativeBase):
    type_annotation_map = {datetime: DateTime(timezone=True), dict: JSONB}
```

> One product table is intentionally NOT listed here: `space_documents` —
> the writing space's storage, where the agent's notes and memory persist.
> It's defined with the product in 2.2 (model + disk mirror).

Why a separate `agents` table: users stay purely human (auth never needs an
`is_agent` check), agent-specific fields (persona, model) have a home, and
multiple named agents later cost nothing. The price is sender polymorphism
on `messages` — solved with the dual nullable FKs plus the CHECK constraint —
and for document attribution, the convention that a NULL `created_by` means
"the space's agent" (agent_actions holds the precise record).

## 1.7 Auth (`app/core/auth.py`)

```python
from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from passlib.context import CryptContext

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer = HTTPBearer()

def make_token(user_id: uuid.UUID, minutes: int, token_type: str = "access") -> str:
    now = datetime.now(timezone.utc)
    claims = {"sub": str(user_id), "type": token_type,
              "iat": now, "exp": now + timedelta(minutes=minutes)}
    return jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)

async def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(bearer),
    db=Depends(get_db),
) -> User:
    try:
        payload = jwt.decode(creds.credentials, settings.jwt_secret,
                             algorithms=[settings.jwt_algorithm])
        if payload.get("type") != "access":
            raise JWTError()
        user_id = uuid.UUID(payload["sub"])
    except (JWTError, ValueError, KeyError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")
    return user

def require_space_member(param: str = "space_id"):
    async def dep(request: Request, user: User = Depends(get_current_user),
                  db=Depends(get_db)) -> SpaceMember:
        space_id = uuid.UUID(request.path_params[param])
        m = await db.get(SpaceMember, (space_id, user.id))
        if m is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND)   # 404, not 403
        return m
    return dep
```

Same 404-not-403 convention as your agent-platform auth work: don't leak the existence of spaces the caller doesn't belong to.

## 1.8 WebSockets (`app/websockets/chat.py`)

Single backend process, so no client manager is needed — `sio.emit()` reaches
every connected client directly. (A client manager is only required when two
or more processes must broadcast to each other's clients; if you ever split
the agent into its own container or run multiple uvicorn workers, add
`client_manager=socketio.AsyncRedisManager(url)` here and a `write_only=True`
manager in the worker — nothing else changes.)

**V1 runs as a single process. That is a hard constraint, not a default** —
with `uvicorn --workers 2` you get two independent job queues and two socket
servers that cannot see each other, so messages appear for some members and
not others. Run one worker.

```python
import socketio

sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins=[])

@sio.event
async def connect(sid, environ, auth):
    user = await user_from_token(auth.get("token"))     # same JWT decode
    if user is None:
        raise socketio.exceptions.ConnectionRefusedError("unauthorized")
    await sio.save_session(sid, {"user_id": str(user.id), "name": user.name})

@sio.event
async def join_space(sid, data):
    sess = await sio.get_session(sid)
    space_id = uuid.UUID(data["space_id"])
    async with SessionFactory() as db:
        m = await db.get(SpaceMember, (space_id, uuid.UUID(sess["user_id"])))
    if m is None:
        return {"error": "not a member"}
    await sio.enter_room(sid, f"space:{space_id}")
    return {"ok": True}

@sio.event
async def chat_message(sid, data):
    sess = await sio.get_session(sid)
    space_id = uuid.UUID(data["space_id"])
    if f"space:{space_id}" not in sio.rooms(sid):
        return {"error": "join first"}
    async with SessionFactory() as db, db.begin():
        msg = Message(space_id=space_id,
                      sender_user_id=uuid.UUID(sess["user_id"]),
                      content=data["content"][:4000])
        db.add(msg)
        space = await db.get(Space, space_id)
        mentioned = (space.agent_id is not None
                     and "@ai" in data["content"].lower())
    await sio.emit("message", serialize_message(msg, sess["name"]),
                   room=f"space:{space_id}")
    if mentioned:
        await enqueue_agent_job(space_id=space_id,
                                message_id=msg.id, agent_id=space.agent_id)

# Mount alongside FastAPI:
app_asgi = socketio.ASGIApp(sio, other_asgi_app=fastapi_app)
```

The socket handler does exactly three cheap things on a mention — persist, broadcast, enqueue — then returns. All LLM latency lives in the worker. (This is the same lesson as your liveness-probe incident: never let slow CPU/IO-bound work sit inside the request path.)

## 1.9 Job queue (`app/agent/queue.py`)

An in-process `asyncio.Queue` — no broker, no extra service. The socket
handler enqueues and returns immediately; a background task drains the queue
and runs agent turns, so LLM latency never blocks a message send.

```python
import asyncio, logging

log = logging.getLogger(__name__)
job_queue: asyncio.Queue[dict] = asyncio.Queue()
_busy: set[uuid.UUID] = set()          # per-space debounce

async def enqueue_agent_job(*, space_id, message_id, agent_id) -> None:
    if space_id in _busy:              # a turn is already running for this space
        return
    _busy.add(space_id)
    await job_queue.put({"space_id": space_id, "message_id": message_id,
                         "agent_id": agent_id})

async def worker_loop() -> None:
    while True:
        job = await job_queue.get()
        try:
            await run_agent_turn(job)
        except Exception:
            log.exception("agent job failed: %s", job)
        finally:
            _busy.discard(job["space_id"])
            job_queue.task_done()
```

Start it in the FastAPI lifespan, in the same process as the socket server —
that is what lets the runner emit through `sio` directly (1.10):

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(worker_loop())
    yield
    task.cancel()
```

Known limits, accepted for V1: the queue is in memory, so agent jobs pending
during a restart are lost (the member simply asks again), and it cannot be
shared across processes — hence the single-process constraint in 1.8. If
either becomes a real problem, swap this file for a Redis list (`lpush` /
`brpop`) and add a `write_only` Redis client manager to Socket.IO; no other
code changes.

## 1.10 The agentic loop (`app/agent/runner.py`)

```python
from anthropic import AsyncAnthropic

client = AsyncAnthropic(api_key=settings.anthropic_api_key)

async def run_agent_turn(job: dict) -> None:
    space_id = uuid.UUID(job["space_id"])
    trigger_id = uuid.UUID(job["message_id"])
    agent_id = uuid.UUID(job["agent_id"])

    async with SessionFactory() as db:
        ctx = await build_context(db, space_id)
    tools = V1_TOOL_SCHEMAS

    await sio.emit("agent_typing", {"state": "start"}, room=f"space:{space_id}")

    messages = [{"role": "user", "content":
                 f"<recent_conversation>\n{ctx.transcript}\n</recent_conversation>\n\n"
                 f"Respond to the latest message that mentioned you."}]
    final_text = "I wasn't able to finish that — try asking again."

    try:
        for _ in range(settings.agent_max_tool_calls):
            resp = await client.messages.create(
                model=settings.agent_model, max_tokens=2000,
                system=ctx.system_prompt, tools=tools, messages=messages)
            messages.append({"role": "assistant", "content": resp.content})

            if resp.stop_reason != "tool_use":
                final_text = "".join(b.text for b in resp.content if b.type == "text")
                break

            tool_results = []
            for block in resp.content:
                if block.type != "tool_use":
                    continue
                result = await execute_tool(
                    space_id=space_id, agent_id=agent_id,
                    trigger_message_id=trigger_id,
                    name=block.name, args=block.input)
                tool_results.append({
                    "type": "tool_result", "tool_use_id": block.id,
                    "content": json.dumps(result.payload),
                    "is_error": result.is_error})
            messages.append({"role": "user", "content": tool_results})
        else:
            final_text = "I hit my action limit for one request — ask me to continue."
    finally:
        await sio.emit("agent_typing", {"state": "stop"},
                       room=f"space:{space_id}")

    async with SessionFactory() as db, db.begin():
        msg = Message(space_id=space_id, sender_agent_id=agent_id,
                      content=final_text, message_type="text")
        db.add(msg)
    await sio.emit("message", serialize_message(msg),
                   room=f"space:{space_id}")
```

Notes:
- The loop cap uses `for/else` — the `else` fires only if the model never produced a final text response within the budget.
- Validation failures come back as `is_error` tool results; Claude reads the error text and retries with corrected input inside the same loop. This is why `ObjectServiceError` messages are written to be instructive.
- Parallel `tool_use` blocks in one response are all answered before the next API call (required by the API contract).

## 1.11 Security & Access Control

### IP Whitelisting
- Nginx checks `$remote_addr` against an allowlist before requests reach the app
- Admin panel adds/removes IPs (DB-backed; Nginx conf regenerated on change)
- Alternative: FastAPI middleware IP check (simpler, no Nginx reload)

### Auth
- JWT (access + refresh), bcrypt password hashing
- HTTPS optional locally (self-signed cert via Nginx)

### Agent-Specific Safety
- **Space scoping enforced server-side** — `space_id` never accepted from LLM tool args; it comes from the job payload built when the mention arrived
- **Fixed tool set, no code execution** — the agent can only read/write this space's documents and search its messages
- Full audit trail in `agent_actions`, visible to all space members; every document save appears as a system line in chat
- Rate limit agent invocations per space; cap agentic loop iterations (~8 tool calls); size caps on document content
- Members can edit or delete anything the agent writes — human edits are authoritative

---

## 1.12 Nginx with IP whitelist (`nginx/nginx.conf`)

```nginx
events {}
http {
  include /etc/nginx/ip_whitelist.conf;   # geo block below

  server {
    listen 80;

    if ($ip_allowed = 0) { return 403; }

    location /api/ {
      proxy_pass http://backend:8000/;
      proxy_set_header X-Real-IP $remote_addr;
    }
    location /socket.io/ {
      proxy_pass http://backend:8000/socket.io/;
      proxy_http_version 1.1;
      proxy_set_header Upgrade $http_upgrade;
      proxy_set_header Connection "upgrade";
      proxy_read_timeout 86400;
    }
    location / {
      root /usr/share/nginx/html;
      try_files $uri /index.html;
    }
  }
}
```

```nginx
# nginx/ip_whitelist.conf  — regenerated by the backend on admin changes
geo $ip_allowed {
  default        0;
  127.0.0.1      1;
  192.168.1.0/24 1;
}
```

Regeneration flow: admin endpoint writes the DB row → renders this file to a shared volume → `docker exec nginx nginx -s reload` (or an inotify sidecar). MVP alternative: skip Nginx-level filtering and use a FastAPI middleware that checks `X-Real-IP` against the `ip_whitelist` table (cached in memory, 30s TTL) — simpler, no reloads, good enough for a LAN app.

## 1.13 Docker Compose Layout

```
docker-compose.yml
services:
  nginx        → port 80/443, IP whitelist, reverse proxy
  frontend     → React build served by Nginx (internal)
  backend      → FastAPI on port 8000 (internal)
  postgres     → 5432 (internal)
```

All services on an internal Docker network. Only Nginx exposed externally.
`ANTHROPIC_API_KEY` provided via env/secret. The agent worker is an asyncio
task inside `backend`, not a separate service — run backend with a single
uvicorn worker (see 1.8).

---

## 1.14 docker-compose.yml

```yaml
services:
  nginx:
    image: nginx:1.27-alpine
    ports: ["80:80"]
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - whitelist:/etc/nginx/whitelist
      - frontend_dist:/usr/share/nginx/html:ro
    depends_on: [backend]

  backend:
    build: ./backend
    environment:
      DATABASE_URL: postgresql+asyncpg://app:app@postgres:5432/chatapp
      JWT_SECRET: ${JWT_SECRET}
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY}
    volumes: [whitelist:/whitelist]
    depends_on:
      postgres: { condition: service_healthy }

  frontend:
    build: ./frontend            # multi-stage: node build → copy dist
    volumes: [frontend_dist:/dist]
    command: sh -c "cp -r /app/dist/* /dist/"

  postgres:
    image: postgres:16
    environment: { POSTGRES_USER: app, POSTGRES_PASSWORD: app, POSTGRES_DB: chatapp }
    volumes: [pgdata:/var/lib/postgresql/data]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U app"]
      interval: 5s
      retries: 10

volumes: { pgdata: {}, whitelist: {}, frontend_dist: {} }
```

Backend Dockerfile: `python:3.12-slim`, `pip install -r requirements.txt`, `alembic upgrade head && uvicorn app.main:app_asgi --host 0.0.0.0 --port 8000`. Behind your Zscaler proxy, remember the usual `PIP_CERT`/`REQUESTS_CA_BUNDLE` build args for local image builds.


---

# Part 2 — The Product: AI in the chat + the writing space

Real-time chat, the agent as a full general assistant, and a side panel of
markdown documents it writes and maintains — including its own memory. Runs
entirely on Part 1.

## 2.1 Scope

**In:** auth (JWT), spaces + invites, IP whitelisting, real-time general chat, the AI agent as a space member (mention-triggered, full general assistant), a **writing space**: per-space markdown documents the agent creates and edits via tools, humans can read and edit too, persisted in Postgres AND mirrored to disk as `.md` files, memory via a pinned "Space notes" document, message search, agent audit log.

**Out of scope for now:** kanban boards or issue trackers, per-document discussion threads, scheduled/automatic agent behavior, external tools (web search, code execution), summary pipelines, semantic search.

## 2.2 V1 data model

All models from 1.6, plus one more table:

```
space_documents
  id, space_id (FK, indexed), title
  content (text, markdown)
  pinned (bool), archived (bool)
  created_by, updated_by, created_at, updated_at
```

```python
class SpaceDocument(Base):
    __tablename__ = "space_documents"
    id: Mapped[uuid.UUID] = pk()
    space_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("spaces.id"), index=True)
    title: Mapped[str]
    content: Mapped[str] = mapped_column(default="")
    pinned: Mapped[bool] = mapped_column(default=False)
    archived: Mapped[bool] = mapped_column(default=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    # created_by/updated_by: null = the space's agent (exact attribution
    # is in agent_actions); non-null = the human member who wrote/edited it
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(),
                                                 onupdate=func.now())
```

**Disk mirror** — every save also writes a real file, so a self-hoster can
browse/backup space knowledge with `ls`:

```python
DOCS_ROOT = Path("/data/spaces")          # docker volume

def _slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60]

async def mirror_to_disk(doc: SpaceDocument) -> None:
    d = DOCS_ROOT / str(doc.space_id) / "docs"
    await asyncio.to_thread(d.mkdir, parents=True, exist_ok=True)
    path = d / f"{_slug(doc.title)}-{str(doc.id)[:8]}.md"
    await asyncio.to_thread(path.write_text,
        f"# {doc.title}

{doc.content}
", "utf-8")
```

Postgres is the source of truth (transactional, concurrent-safe); the mirror is
write-only convenience. Called after commit in the document service.

## 2.3 V1 agent tools (the whole set)

```python
V1_TOOL_SCHEMAS = [
  {"name": "write_document",
   "description": ("Create a new markdown document in the space's writing "
                   "panel. Use for notes, plans, summaries, drafts — anything "
                   "worth keeping outside the chat scroll."),
   "input_schema": {"type": "object", "required": ["title", "content"],
     "properties": {"title": {"type": "string"},
                    "content": {"type": "string"},
                    "pinned": {"type": "boolean", "default": False}}}},

  {"name": "update_document",
   "description": ("Replace a document's content (and/or title/pinned). "
                   "Read it first with read_document, then write the full "
                   "revised content."),
   "input_schema": {"type": "object", "required": ["document_id"],
     "properties": {"document_id": {"type": "string"},
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "pinned": {"type": "boolean"},
                    "archived": {"type": "boolean"}}}},

  {"name": "read_document",
   "description": "Read one document's full content.",
   "input_schema": {"type": "object", "required": ["document_id"],
     "properties": {"document_id": {"type": "string"}}}},

  {"name": "list_documents",
   "description": "List the space's documents (id, title, pinned, updated).",
   "input_schema": {"type": "object", "properties": {}}},

  {"name": "search_messages",
   "description": ("Search this space's chat history for evidence or "
                   "context older than the recent transcript."),
   "input_schema": {"type": "object", "required": ["query"],
     "properties": {"query": {"type": "string"},
                    "sender_name": {"type": "string"},
                    "from_date": {"type": "string", "format": "date"},
                    "to_date": {"type": "string", "format": "date"},
                    "limit": {"type": "integer", "default": 20, "maximum": 50}}}},
]
```

Dispatch is a plain `match` on tool name calling the documents/messages
services, wrapped in `execute_tool` exactly as the runner (1.10) expects:
one short transaction per call, an `agent_actions` audit row always written,
errors returned as instructive `is_error` tool results the model can
self-correct from, and a WS broadcast on every mutation. `space_id` and
`agent_id` come from the job payload — never from tool arguments.

## 2.4 Memory = a document (the V1 memory system)

Convention, not code: the agent maintains a pinned document titled
**"Space notes"** — durable facts, decisions, preferences, running state.
The context builder injects it wholesale:

```
System prompt = template
  + members
  + FULL content of all pinned documents (Space notes first)
  + titles of unpinned documents
  + last N (~50) chat messages as transcript
```

Prompt rules:
```
- Maintain a pinned document "Space notes". When you learn a durable fact
  ("Ravi is vegetarian", "rent due on the 5th", "we chose Coorg over Goa"),
  update it. Keep it terse and organized with headings.
- When asked to "remember" something, that means: update Space notes.
- Members can edit any document, including Space notes — their edits are
  authoritative. Never fight a human edit.
```

Properties this buys cheaply: memory is **visible** (open the doc),
**correctable** (edit it), **portable** (it's a .md file on disk), and
**bounded** (one doc in the prompt, not a summary pipeline).

## 2.5 V1 UI

Two panes (the simple mockup from design review): chat left, writing panel
right. Panel = pinned docs as cards showing rendered markdown, unpinned as a
title list; tap opens full-width reader with an Edit toggle (plain textarea →
save = same PATCH endpoint the agent uses). "AI is writing…" indicator while
an agent job runs; every agent save appears as a system line in chat
("AI updated Space notes"). Mobile: Chat | Docs tabs.

Endpoints:
```
GET    /spaces/:id/documents            — list (pinned first)
POST   /spaces/:id/documents            — create (humans can too)
GET    /spaces/:id/documents/:did       — read
PATCH  /spaces/:id/documents/:did       — update content/title/pinned/archived
```
WS events: `document_created`, `document_updated`, `agent_typing`, `message`.

## 2.6 V1 build order (~2–3 weeks of evenings)

1. Compose: postgres + backend skeleton; alembic; models (2.2 subset)
2. Auth + spaces + invites (1.7 as written)
3. Socket.IO chat: persist → broadcast; two-tab test (1.8 minus mention logic)
4. Documents service + REST + disk mirror + unit tests
5. Agent: queue (1.9) + runner (1.10) + V1 tools + context (2.4); golden test
   with faked client; live smoke: "@ai summarize today into a doc"
6. Frontend: auth → chat → docs panel → markdown reader/editor → live WS
7. @ai mention wiring + "AI is writing…" + system lines; IP whitelist; polish

Definition of done: two phones on your LAN, one "@ai remember we play
badminton Saturdays" → Space notes updates in the panel on both screens.

## 2.7 What V1 deliberately excludes (and the cheap substitutes)

- No todo/checklist widgets → the agent keeps a "Todos" *document* with
  markdown checkboxes it edits on request. Ugly but functional — and the
  pain of editing-a-doc-to-tick-a-box tells you what to build next.
- No issues → a pinned "Open questions" document, same idea.
- No automations → none; the agent only acts when mentioned.
- No summaries pipeline → Space notes + search_messages cover it at V1 scale.