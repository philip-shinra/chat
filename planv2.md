# Chat App — V2 Plan: The Dynamic Object System

Companion to `v1-plan.md`. This file specifies V2 only — the generalization
of V1 into agent-defined object types, generic renderers, object threads,
automations-ready state, and layered capabilities (per-space tools + MCP).

**Prerequisites:** V1 shipped and in daily use. All `1.x` and `2.x`
references below (models 1.6, auth 1.7, WebSockets 1.8, queue 1.9, agent
loop 1.10, Nginx 1.12, compose 1.14; V1 data model 2.2, tools 2.3) point
into `v1-plan.md` — the foundation and V1 spec live there and are reused
unchanged.

## Migration from V1 (additive only)

1. Ship the V2 tables alongside V1's — additive migrations, nothing dropped:
   `space_object_types` and `space_objects` (below), a nullable
   `messages.object_id` column, and `spaces.agent_capabilities` (JSONB).

```python
class SpaceObjectType(Base):
    __tablename__ = "space_object_types"
    id: Mapped[uuid.UUID] = pk()
    space_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("spaces.id"), index=True)
    name: Mapped[str]
    version: Mapped[int] = mapped_column(default=1)
    description: Mapped[str | None]
    json_schema: Mapped[dict] = mapped_column(JSONB)
    render_hint: Mapped[str] = mapped_column(default="keyvalue")
    widget_html: Mapped[str | None]      # 4.6: agent-written renderer
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    __table_args__ = (UniqueConstraint("space_id", "name", "version"),)

class SpaceObject(Base):
    __tablename__ = "space_objects"
    id: Mapped[uuid.UUID] = pk()
    space_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("spaces.id"))
    type_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("space_object_types.id"))
    title: Mapped[str]
    data: Mapped[dict] = mapped_column(JSONB, default=dict)
    pinned: Mapped[bool] = mapped_column(default=False)
    archived: Mapped[bool] = mapped_column(default=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    # created_by/updated_by: null = the space's agent (see agent_actions)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(),
                                                 onupdate=func.now())
    __table_args__ = (
        Index("ix_objects_space_type_live", "space_id", "type_id",
              postgresql_where=text("NOT archived")),
        Index("ix_objects_data_gin", "data", postgresql_using="gin"),
    )
```
2. Data migration: for each space, define a `document` type (render_hint
   `markdown`, schema `{body: string}`); copy each `space_documents` row into
   `space_objects` (`title` → title, `content` → `data.body`, pinned/archived
   carried over). The disk mirror keeps working against objects of this type.
3. Swap agent tools: V1's document tools retire; `define_object_type` /
   `create_object` / `update_object` / `query_objects` / `get_object_thread`
   arrive (4.2). Prompt exemplars replace the hardcoded document convention —
   the pinned "Space notes" memory document keeps working, unchanged, as a
   pinned `document` object.
4. Frontend: the markdown renderer joins the registry as one renderer among
   several; the docs panel becomes the objects panel.
5. Drop `space_documents` after one release of parallel running.

## Table of Contents

- **Part 3 — V2 Design**: concept (3.1), flows (3.2), features (3.3), architecture (3.4), schema (3.5), API (3.6), UI (3.7), complexity (3.8), open questions (3.9)
- **Part 4 — V2 Implementation**: object service (4.1), tools (4.2), context (4.3), REST (4.4), frontend (4.5), widgets (4.6), capabilities/MCP (4.7), testing (4.8), build orders (4.9–4.10)

---

# Part 3 — V2 Design: the dynamic object system

The generalization of V1: agent-defined types, generic renderers, object
threads, and layered capabilities. Read this before Part 4.

## 3.1 Core Concept

A space is a shared room. Inside a space:

1. **General Chat** — real-time messaging between members
2. **Object Threads** — every object can carry its own discussion thread (issues are just an agent-defined object type with a status workflow)
3. **AI Space Agent** — an AI member with agency inside the space:
   - **A full general assistant first**: members can ask it anything — questions,
     explanations, drafting, planning, math, mediation. Most requests are pure
     conversation and touch no tools at all. Tools gate what it can CHANGE,
     never what it can discuss.
   - Full conversational context (recent messages + rolling summaries + on-demand search)
   - **Generic tools over a dynamic object store** — it can invent and manage any structure the space needs, on demand
   - **Extensible capabilities**: per-space toggles (web search, code sandbox)
     and MCP servers extend what "doing" means, without changing the architecture
   - Can **arbitrate disagreements** by citing actual messages as evidence
   - Responds when mentioned (`@ai`); optionally proactive later

Key principles:
- **Conversation is unrestricted; only side effects are gated.** The tool list is not the limit of the agent's abilities — a message that needs no state change is answered directly, on any topic.
- **Space tools are fixed and generic; the data model is dynamic.** The LLM defines new *object types* (with JSON Schemas), never new tools — flexibility stays high, the trusted surface stays small.
- **Capabilities are layered, not baked in.** Core space tools are always present; capability tools (web search, sandboxed code) are per-space toggles; MCP servers make the tool surface arbitrarily extensible under the same audit and scoping rules.

---

## 3.2 User Flows

### User Setup
- Register with name + email
- Create or join a space (invite link / code)
- Space owner can **add the AI agent to the space** (toggle + optional persona/instructions)
- Only whitelisted IPs can access the app

### Agent Interaction Flow
```
Member sends a message mentioning @ai
        ↓
Message persisted + broadcast as normal
        ↓
Agent job enqueued (async, non-blocking)
        ↓
Agent service builds context:
  system prompt + space state (existing object types, pinned objects,
  open issues, members) + last N messages + rolling summaries
        ↓
Claude API call with generic tool definitions
        ↓
Agentic loop: tool_use → validate + execute (space-scoped) → tool_result → repeat
        ↓
Final response persisted as agent message → broadcast to space
        ↓
All tool calls logged to agent_actions (audit trail)
```

### Example Agent Interactions (all through the same generic tools)
Pure conversation — no tools involved (most requests look like this):
- "@ai explain this error message" / "@ai draft a polite reply to the landlord"
- "@ai what's a fair rent split for unequal room sizes?" → reasoned answer
- "@ai summarize what we discussed this morning" → uses context, changes nothing

State-changing — through the generic tools. A new space contains ZERO types;
everything below is agent-defined on first use:
- "@ai make a todo list for the weekend trip"
  → no matching type exists → `define_object_type("todo_list", {items:[{text,done}]},
    render_hint="checklist")` → `create_object` → next time, the type is reused
- "@ai let's track who owes what for dinner"
  → `define_object_type("expense", {...}, render_hint="table")` → creates rows
- "@ai poll: movie on Friday or Saturday?"
  → defines a `poll` type (render_hint="poll"), members vote in UI
- "@ai checkpoint today's discussion"
  → defines/reuses a `checkpoint` type (render_hint="markdown"), creates + pins
- "@ai track this as an issue"
  → defines/reuses an `issue` type (render_hint="kanban", status enum,
    if/then conditional for resolution_note — pattern from the prompt exemplars)
- "@ai who was right about the deployment date?"
  → `search_messages`, cites evidence, answers neutrally

### Issue Flow (issues are an agent-defined object type, not special code)
```
A member asks; agent defines `issue` on first use (exemplar in prompt):
  → {description, category, priority,
     status: open|in_progress|resolved, resolution_note}
  → render_hint: kanban → the "dashboard" is just the kanban renderer
        ↓
Members discuss in the object's thread (any object can have a thread)
        ↓
Status updated via update_object; JSON Schema conditional enforces
  "resolved requires resolution_note" (if/then)
        ↓
Archived like any object; resolution lives in its data + thread
```

---

## 3.3 Features

### Must-Have (MVP)
- [ ] User auth (email + password, JWT)
- [ ] Spaces: create, invite via link/code, join
- [ ] General chat channel per space (real-time)
- [ ] **Per-object discussion threads** (messages.object_id — general chat when null)
- [ ] **Dynamic object system: object types (JSON Schema) + objects (JSONB)**
- [ ] **Generic renderers: checklist, table, markdown, key-value (kanban/timeline/poll later)**
- [ ] **Zero pre-defined types — every structure is agent-defined via `define_object_type`; exemplar schemas live in the system prompt, not the database**
- [ ] **AI agent as space member (mention-triggered) with generic object tools**
- [ ] Humans can also edit objects directly in the UI (check off items, edit cells)
- [ ] Agent action audit log (`agent_actions`)
- [ ] IP whitelisting middleware

### Nice-to-Have (Post-MVP)
- [ ] More renderers: kanban, timeline, poll with live votes
- [ ] Agent-generated custom widgets per type (sandboxed iframe) — fully dynamic UI
- [ ] Streaming agent responses over WebSocket + "agent is thinking" indicator
- [ ] Rolling conversation summaries (background job)
- [ ] Semantic search over history (pgvector) as an agent tool
- [ ] Proactive agent behaviors (nudge stale issues, surface unfinished lists) — opt-in
- [ ] Per-space agent persona / custom instructions
- [ ] Notifications; image/file sharing in chat

---

## 3.4 Architecture

### High-Level Components
```
┌────────────────────────────────────────────────────────────┐
│                        Nginx (IP whitelist)                │
└──────────────┬─────────────────────────────┬───────────────┘
               │                             │
        ┌──────▼──────┐               ┌──────▼──────┐
        │  Frontend   │               │  FastAPI    │
        │  (React)    │◄─ WebSocket ─►│  Backend    │
        └─────────────┘               └──┬───────┬──┘
                                         │       │
                          ┌──────────────▼─┐   ┌─▼──────────────────┐
                          │  Agent Service │   │ Service Layer      │
                          │  (async worker)│──►│ objects, types,    │
                          │  Claude API +  │   │ threads, messages  │
                          │  tool executor │   │ (+ JSON Schema     │
                          └──────┬─────────┘   │   validation)      │
                                 │             └─┬──────────────────┘
                                 │        ┌──────▼──────┐  ┌────────┐
                                 └───────►│ PostgreSQL  │  │ Redis  │
                                          │ (JSONB+GIN) │  │        │
                                          └─────────────┘  └────────┘
```

### Key Design Decisions

**1. Agent = virtual member.**
The agent is a row in the dedicated `agents` table (see `v1-plan.md` 1.6), attached to a space via `spaces.agent_id`. Its messages are normal rows in `messages` (via `sender_agent_id`); the frontend renders them with an agent badge. Context is always scoped per space.

**2. Decoupled agent execution.**
WebSocket handlers never call the LLM inline. On an `@ai` mention, the handler persists the message and pushes a job (Redis list / `asyncio.create_task` for MVP). The agent worker does the slow work and publishes the reply through the normal Redis pub/sub → WebSocket broadcast path.

**3. Fixed generic tools + dynamic object model (the core idea).**
The agent cannot add tools or execute code. It gets a small, stable set of generic tools that operate on a schema-flexible store:
- `define_object_type` lets it invent new structures (a JSON Schema + a render hint)
- `create_object` / `update_object` / `query_objects` manage instances (pinning and archiving are just fields in an `update_object` patch)
- Server validates every `data` payload against the type's JSON Schema before writing
- Nothing is pre-defined: the first todo list, checkpoint, or issue in a space is born from `define_object_type` — exemplar schemas in the prompt guide the agent toward good patterns, but they're suggestions, not rows

This gives "the agent can build anything the space needs" while the backend surface stays tiny, testable, and safe.

**4. Rendering by hint, not by feature.**
Render hints are presentation primitives, not features — the moral equivalent of
HTML tags. `checklist` no more pre-defines "todo lists" than `<table>` pre-defines
spreadsheets: meaning lives in the agent's schema, the hint only picks the drawing
primitive. The frontend ships a handful of generic renderers keyed by `render_hint`:
`checklist`, `table`, `markdown`, `keyvalue` (MVP) → `kanban`, `timeline`, `poll` (later).
Every agent-invented type maps to one. Unknown/missing hint → key-value fallback. Humans interact directly (toggle a checklist item = `PATCH /objects/:id`), so objects are shared artifacts, not chat-only.
Post-MVP escape hatch: agent-generated widget (sanitized HTML in a sandboxed iframe) per type for truly custom UI.

**5. Server-side scoping (security-critical).**
Tool schemas exposed to the LLM contain **no** `space_id` — it is injected from the agent's execution context. The model cannot read or write outside its space regardless of what it generates. Same principle as multi-tenant RBAC: authorization lives in the executing layer, never trusted from the caller.

**6. Everything the agent does is audited.**
Every tool invocation → `agent_actions` row (tool name, input, result, triggering message), surfaced in chat as system lines ("AI created list: Trip Todos") so members always see what changed.

**7. Context strategy (tiered).**
- Tier 1: last N (~50) messages verbatim
- Tier 2: rolling per-day summaries from `conversation_summaries` (post-MVP)
- Tier 3: `search_messages` tool for on-demand retrieval (ILIKE/FTS first, pgvector later)
- Plus space state snapshot: **existing object types + recent/pinned objects**, open issues, member names — critical so the agent reuses types instead of redefining them

**8. Arbitration ("who is correct") = prompt + evidence, not a component.**
For dispute questions the system prompt requires: search the history, cite specific messages (sender + time + quote), answer factual disputes with evidence, mediate opinion disputes without declaring winners, stay neutral in tone.

### Agent Tool Definitions (fixed, generic; exposed to the LLM)
```
define_object_type(name, description, json_schema, render_hint)
   # creates a new type or a NEW VERSION of an existing name (no mutation);
   # render_hint ∈ checklist|table|markdown|keyvalue|kanban|timeline|poll

create_object(type_name, title, data)          # data validated vs JSON Schema
update_object(object_id, json_patch)           # RFC 7386 merge patch, re-validated
query_objects(type_name?, filter?, limit?)     # filter on data via JSONB containment
# pin/unpin/archive = update_object with {"pinned": true} / {"archived": true}

search_messages(query, from_date?, to_date?, sender_name?, limit?)
get_object_thread(object_id, limit?)   # read an object's discussion thread
```
(`space_id` and actor identity injected server-side; member references resolved by name against `space_members`.)

### Agent System Prompt (sketch)
```
You are the AI member of the space "{space_name}".
Members: {names}. Open issue objects: {snapshot}. Pinned objects: {snapshot}.
Object types already defined in this space: {name, description, schema summary}.
Rolling summary of earlier conversation: {summaries}.

- You are a general assistant: answer any question or request directly.
  Use tools ONLY when the space's shared state should change or you need
  evidence/history — plain questions get plain answers.
- REUSE an existing object type whenever it fits; define a new type only
  when nothing matches. Prefer simple schemas.
- Act only within this space using your tools.
- When asked to settle a disagreement, find evidence with search_messages
  and cite it; be neutral; don't declare winners on matters of opinion.
- Confirm actions in plain language ("Created list 'Trip Todos' with 4 items").
- Keep replies conversational and short — this is a chat, not a report.
```

### Guardrails for the Dynamic Model
- **Schema validation server-side** (`jsonschema`) on every create/update; reject with a clear error the agent can self-correct from in the loop
- **Type versioning, not mutation**: redefining a name creates `version+1`; old objects keep their version's schema (agent-driven, application-level migrations)
- **Anti-sprawl**: existing types injected into context + prompt to reuse; soft cap on types per space (e.g., 30) and objects per space
- **Loop caps**: max ~8 tool calls per invocation; per-space rate limit on agent invocations (protects API spend and against loops)
- **Schema complexity limits**: max nesting depth / property count; no remote $refs
- Optional confirm-in-chat before destructive actions (archive many objects, close issues)

---

## 3.5 Database Schema (High Level)

```
users
  id, email, password_hash, name, role (admin/member), created_at

agents
  id, name, persona (nullable), model (nullable), created_at
  # the AI's identity; attached to spaces via spaces.agent_id

spaces
  id, name, invite_code (unique)
  agent_id (FK agents, nullable — set = agent enabled)
  agent_instructions (text, nullable)
  agent_capabilities (jsonb) — {"web_search": bool, "run_python": bool,
                                "mcp_servers": [...]}
  created_at

space_members
  space_id, user_id, role (owner/member), joined_at
  # humans only — the agent's presence is spaces.agent_id
  # per-space role, distinct from users.role (global)

messages
  id, space_id, object_id (nullable — null = general chat; else the
                            object whose thread this message belongs to)
  sender_user_id (nullable), sender_agent_id (nullable) — exactly one set
  content, message_type (text/image/system/agent_action)
  reply_to_message_id (nullable), created_at

space_object_types
  id, space_id, name, version (int), description
  json_schema (jsonb), render_hint (text)
  widget_html (text, nullable)   # post-MVP: agent-written custom renderer
  created_by, created_at
  UNIQUE (space_id, name, version)
  # NO seeds — types exist only once the agent (or a human) defines them

space_objects
  id, space_id, type_id (FK space_object_types)
  title, data (jsonb), pinned (bool), archived (bool)
  created_by, updated_by, created_at, updated_at
  # GIN index on data for JSONB containment queries

# NOTE: no issues table — `issue` is an agent-defined object type
# (kanban render_hint, status enum, if/then schema conditional
#  requiring resolution_note when status = resolved)

agent_actions
  id, space_id, agent_id, triggered_by_message_id (nullable)
  tool_name, tool_input (jsonb), tool_result (jsonb)
  status (success/error), error_detail (nullable), created_at

conversation_summaries              # post-MVP
  id, space_id, period_start, period_end,
  summary (text), message_count, created_at

ip_whitelist
  id, ip_address, label, added_at
```

Useful indexes: `messages (space_id, created_at)`, `messages (space_id, object_id, created_at)`,
`space_objects (space_id, type_id) WHERE NOT archived`, GIN on `space_objects.data`
(the GIN index also serves status filters like `data @> '{"status": "open"}'`),
`agent_actions (space_id, created_at)`.

---

## 3.6 API Structure

```
POST   /auth/register
POST   /auth/login
GET    /auth/me

POST   /spaces                          — create space
GET    /spaces/:id                      — space details (members, agent status)
POST   /spaces/:id/invite               — generate invite link
POST   /spaces/:id/agent                — enable/disable agent, set instructions
                                          and capabilities (owner only)
GET    /spaces/:id/agent/actions        — agent audit log

GET    /spaces/:id/object-types         — list types (with schemas, hints)
POST   /spaces/:id/object-types         — define type (humans can too)
GET    /spaces/:id/objects              — list/query objects (?type=&pinned=&filter=)
POST   /spaces/:id/objects              — create object (validated vs schema)
PATCH  /spaces/:id/objects/:oid         — merge-patch data / pin / archive
GET    /spaces/:id/objects/:oid         — object detail

GET    /spaces/:id/objects/:oid/messages — object thread history (issues etc.)
GET    /spaces/:id/messages             — general chat history (paginated)
GET    /spaces/:id/messages/search      — search history
WS     /ws/spaces/:id                   — one socket; thread messages carry
                                          object_id and route client-side

GET    /admin/ip-whitelist              — list whitelisted IPs
POST   /admin/ip-whitelist              — add IP
DELETE /admin/ip-whitelist/:id          — remove IP
GET    /admin/users                     — list all users (admin only)
DELETE /admin/users/:id                 — remove a user (admin only)
```

WebSocket events (server → client): `message`, `agent_typing`, `agent_action`,
`object_created`, `object_updated`, `object_type_defined`.
(Human edits to objects broadcast too — everyone's panel stays live.)

---

## 3.7 UI/UX Structure

### Layout
```
┌───────────────────────────────────────────────────────────┐
│ Header: Space name | Members online | AI badge if enabled │
├──────────────┬────────────────────────────┬───────────────┤
│              │                            │               │
│  Sidebar     │   Main Content Area        │  Space Panel  │
│              │                            │  (collapsible)│
│  > General   │   (Chat / Object Thread /  │               │
│    Chat      │    Kanban board)           │  Objects,     │
│  > Boards    │                            │  grouped by   │
│  > Objects   │   @ai messages render      │  type; pinned │
│              │   with agent avatar +      │  on top; each │
│  + New Object│   action confirmations     │  rendered by  │
│              │                            │  render_hint  │
└──────────────┴────────────────────────────┴───────────────┘
```

### Key Screens
1. **Login / Register** — minimal, clean
2. **Home / General Chat** — WhatsApp-like; `@ai` autocompletes; agent messages badged; "AI is thinking…" indicator; system lines for agent actions
3. **Space Panel** — live objects grouped by type; checklist items toggleable, table cells editable, markdown checkpoints expandable; pinned objects float to top
4. **Object Detail** — full view of one object with edit + history
5. **Kanban board** — the kanban renderer, full-page: any type with a status
   enum gets one (issues by default); columns derived from the schema's enum
6. **Object Thread** — chat thread with the object rendered as its header;
   for issues, "Mark Resolved" is just a status patch + note field
7. **Agent Settings (per space)** — enable/disable, custom instructions, type list, audit log viewer
8. **Settings** — profile, member info, IP whitelist (admin)

### UX Principles
- Clean, neutral palette
- Every agent action is visible in-chat as a system line (no silent changes)
- Objects are shared, directly editable artifacts — chat is one way to change them, not the only way
- Mobile-responsive (usable on phones over the local network)

---

## 3.8 Estimated Complexity

| Area | Effort |
|---|---|
| Backend API + Auth | Medium |
| WebSocket real-time chat | Medium |
| **Object system (types, validation, versioning)** | **Medium** |
| Object threads + kanban renderer | Low–Medium |
| **Agent runtime (loop, generic tools, context)** | **Medium–High** |
| **Frontend renderer registry + live objects** | **High** |
| Context management (summaries, search) | Medium (post-MVP) |
| Docker setup | Low |
| IP whitelisting | Low |

---

## 3.9 Open Questions / Later Decisions

- How far to take dynamic UI: renderer registry only, or agent-generated sandboxed widgets per type?
- Should humans be able to define types via a UI form too, or only the agent?
- Proactivity: agent speaking unprompted (idle issues, unfinished lists) — opt-in per space?
- One shared agent identity vs. named per-space personas
- Model choice per space (fast/cheap vs. deep) and per-space token budget
- Undo for agent actions (soft-archive + one-click restore already gets most of the way)
- Privacy: agent reads all space messages by design — make explicit in UI when enabling

---
---


---

# Part 4 — V2 Implementation Detail

Buildable as written, on top of Parts 1–2.

## 4.1 Object service — the heart of the dynamic model (`app/services/objects.py`)

```python
import jsonschema
from sqlalchemy import select, func

class ObjectServiceError(Exception):
    """Message is safe to show to humans AND to feed back to the agent."""

MAX_SCHEMA_BYTES = 8_000
MAX_DATA_BYTES = 50_000
ALLOWED_HINTS = {"checklist", "table", "markdown", "keyvalue", "kanban", "timeline", "poll"}

def _validate_schema_itself(schema: dict) -> None:
    if len(json.dumps(schema)) > MAX_SCHEMA_BYTES:
        raise ObjectServiceError("Schema too large; simplify it.")
    if "$ref" in json.dumps(schema):
        raise ObjectServiceError("$ref is not allowed in schemas.")
    try:
        jsonschema.Draft202012Validator.check_schema(schema)
    except jsonschema.SchemaError as e:
        raise ObjectServiceError(f"Invalid JSON Schema: {e.message}")

async def latest_type(db, space_id: uuid.UUID, name: str) -> SpaceObjectType | None:
    stmt = (select(SpaceObjectType)
            .where(SpaceObjectType.space_id == space_id, SpaceObjectType.name == name)
            .order_by(SpaceObjectType.version.desc()).limit(1))
    return await db.scalar(stmt)

async def define_type(db, *, space_id, name, description, json_schema,
                      render_hint, actor_id) -> SpaceObjectType:
    if render_hint not in ALLOWED_HINTS:
        raise ObjectServiceError(f"render_hint must be one of {sorted(ALLOWED_HINTS)}")
    _validate_schema_itself(json_schema)
    count = await db.scalar(select(func.count(func.distinct(SpaceObjectType.name)))
                            .where(SpaceObjectType.space_id == space_id))
    existing = await latest_type(db, space_id, name)
    if existing is None and count >= settings.agent_max_types_per_space:
        raise ObjectServiceError("Type limit reached for this space; reuse an existing type.")
    t = SpaceObjectType(
        space_id=space_id, name=name, description=description,
        json_schema=json_schema, render_hint=render_hint,
        version=(existing.version + 1 if existing else 1), created_by=actor_id)
    db.add(t)
    await db.flush()
    return t

async def create_object(db, *, space_id, type_name, title, data, actor_id) -> SpaceObject:
    t = await latest_type(db, space_id, type_name)
    if t is None:
        available = await db.scalars(select(func.distinct(SpaceObjectType.name))
                                     .where(SpaceObjectType.space_id == space_id))
        raise ObjectServiceError(
            f"No type '{type_name}'. Available: {sorted(available.all())}. "
            f"Use define_object_type to create a new one.")
    _validate_data(data, t.json_schema)
    obj = SpaceObject(space_id=space_id, type_id=t.id, title=title,
                      data=data, created_by=actor_id)
    db.add(obj)
    await db.flush()
    return obj

def merge_patch(target, patch):
    """RFC 7386 JSON Merge Patch."""
    if not isinstance(patch, dict):
        return patch
    result = dict(target) if isinstance(target, dict) else {}
    for k, v in patch.items():
        if v is None:
            result.pop(k, None)
        else:
            result[k] = merge_patch(result.get(k), v)
    return result

async def update_object(db, *, space_id, object_id, patch, actor_id) -> SpaceObject:
    obj = await db.get(SpaceObject, object_id)
    if obj is None or obj.space_id != space_id or obj.archived:
        raise ObjectServiceError("Object not found in this space.")
    t = await db.get(SpaceObjectType, obj.type_id)
    new_data = merge_patch(obj.data, patch.get("data", {})) if "data" in patch else obj.data
    _validate_data(new_data, t.json_schema)
    obj.data = new_data                      # reassign — JSONB mutation isn't tracked
    for field in ("title", "pinned", "archived"):
        if field in patch:
            setattr(obj, field, patch[field])
    obj.updated_by = actor_id
    await db.flush()
    return obj

async def query(db, *, space_id, type_name=None, pinned_only=False, limit=20):
    stmt = (select(SpaceObject, SpaceObjectType.name)
            .join(SpaceObjectType, SpaceObject.type_id == SpaceObjectType.id)
            .where(SpaceObject.space_id == space_id, ~SpaceObject.archived))
    if type_name:
        stmt = stmt.where(SpaceObjectType.name == type_name)
    if pinned_only:
        stmt = stmt.where(SpaceObject.pinned)
    rows = await db.execute(
        stmt.order_by(SpaceObject.updated_at.desc()).limit(min(limit, 50)))
    return rows.all()          # [(SpaceObject, type_name), ...]

def _validate_data(data: dict, schema: dict) -> None:
    if len(json.dumps(data)) > MAX_DATA_BYTES:
        raise ObjectServiceError("Object data too large.")
    try:
        jsonschema.validate(data, schema)
    except jsonschema.ValidationError as e:
        raise ObjectServiceError(
            f"Data does not match schema at {list(e.absolute_path)}: {e.message}")
```

Three deliberate details here:

1. **Errors are agent-food.** `ObjectServiceError` messages are written so that, fed back as a `tool_result` with `is_error=True`, the model can self-correct in the next loop iteration ("No type 'expenses'. Available: ['expense', ...]").
2. **`obj.data = new_data` reassigns** the JSONB attribute instead of mutating in place — SQLAlchemy doesn't track in-place dict mutation without `MutableDict`, and reassignment is the cleaner habit.
3. **Merge patch can't address array elements** (RFC 7386 limitation). For a checklist toggle, the client/agent sends the full `items` array back. At these object sizes that's fine; if it ever isn't, add a tiny JSON-Pointer op later.

**Exemplar schemas** — these live in `prompts.py` and are injected into the
agent's system prompt as reference patterns. They are NOT written to the
database; the agent adapts them via `define_object_type` when a space first
needs that kind of structure:

```python
EXEMPLAR_SCHEMAS = [
    dict(name="task_list", render_hint="checklist",
         description="A checklist of items",
         json_schema={"type": "object", "required": ["items"], "properties": {
             "items": {"type": "array", "items": {"type": "object",
                 "required": ["text", "done"], "properties": {
                     "text": {"type": "string"},
                     "done": {"type": "boolean"},
                     "assignee": {"type": "string"}},
                 "additionalProperties": False}}},
         "additionalProperties": False}),
    dict(name="checkpoint", render_hint="markdown",
         description="A pinned summary of a discussion or period",
         json_schema={"type": "object", "required": ["body"], "properties": {
             "body": {"type": "string"},
             "period_start": {"type": "string", "format": "date"},
             "period_end": {"type": "string", "format": "date"}},
         "additionalProperties": False}),
    dict(name="note", render_hint="keyvalue",
         description="Free-form pinned note",
         json_schema={"type": "object", "additionalProperties": True}),
    dict(name="issue", render_hint="kanban",
         description="A tracked issue with a status workflow; discuss in its thread",
         json_schema={"type": "object", "required": ["description", "status"],
             "properties": {
                 "description": {"type": "string"},
                 "category": {"type": "string"},
                 "priority": {"type": "string", "enum": ["low", "medium", "high"]},
                 "status": {"type": "string",
                            "enum": ["open", "in_progress", "resolved"]},
                 "resolution_note": {"type": "string"},
                 "resolved_on": {"type": "string", "format": "date"}},
             "if": {"properties": {"status": {"const": "resolved"}}},
             "then": {"required": ["resolution_note"]},
             "additionalProperties": False}),
]

# Injected into SYSTEM_TEMPLATE as:
#   "Reference patterns you may adapt when defining types (do not treat
#    these as existing — check the space's actual type list): {exemplars}"
#
# The kanban renderer discovers its columns from the schema: the first
# property with an "enum" is the grouping field. Works for any
# status-bearing type the agent defines.
```

## 4.2 Agent tool schemas (`app/agent/tools.py`)

Fixed, generic, no `space_id` anywhere:

```python
CORE_TOOL_SCHEMAS = [
    {
        "name": "define_object_type",
        "description": ("Define a NEW kind of structured object for this space "
                        "(e.g. expense, poll, itinerary). Redefining an existing "
                        "name creates a new version. REUSE existing types when "
                        "one fits — check the type list in your context first."),
        "input_schema": {
            "type": "object",
            "required": ["name", "description", "json_schema", "render_hint"],
            "properties": {
                "name": {"type": "string", "pattern": "^[a-z][a-z0-9_]{1,30}$"},
                "description": {"type": "string"},
                "json_schema": {"type": "object",
                    "description": "JSON Schema (draft 2020-12) for the object's data field. Keep it flat and simple. No $ref."},
                "render_hint": {"type": "string",
                    "enum": ["checklist", "table", "markdown", "keyvalue",
                             "kanban", "timeline", "poll"]},
            },
        },
    },
    {
        "name": "create_object",
        "description": "Create an object of an existing type in this space.",
        "input_schema": {
            "type": "object",
            "required": ["type_name", "title", "data"],
            "properties": {
                "type_name": {"type": "string"},
                "title": {"type": "string"},
                "data": {"type": "object"},
                "pinned": {"type": "boolean", "default": False},
            },
        },
    },
    {
        "name": "update_object",
        "description": ("Update an object with an RFC 7386 merge patch on its data, "
                        "and/or change title/pinned/archived. To edit array fields "
                        "(like checklist items), send the FULL new array."),
        "input_schema": {
            "type": "object",
            "required": ["object_id", "patch"],
            "properties": {
                "object_id": {"type": "string"},
                "patch": {"type": "object", "properties": {
                    "title": {"type": "string"},
                    "data": {"type": "object"},
                    "pinned": {"type": "boolean"},
                    "archived": {"type": "boolean"}}},
            },
        },
    },
    {
        "name": "query_objects",
        "description": "List objects in this space, optionally by type, with data included.",
        "input_schema": {
            "type": "object",
            "properties": {
                "type_name": {"type": "string"},
                "pinned_only": {"type": "boolean"},
                "limit": {"type": "integer", "default": 20, "maximum": 50},
            },
        },
    },
    {
        "name": "search_messages",
        "description": "Search this space's chat history. Use when you need evidence of what was said, or context older than the recent transcript.",
        "input_schema": {
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {"type": "string"},
                "sender_name": {"type": "string"},
                "from_date": {"type": "string", "format": "date"},
                "to_date": {"type": "string", "format": "date"},
                "limit": {"type": "integer", "default": 20, "maximum": 50},
            },
        },
    },
    {
        "name": "get_object_thread",
        "description": ("Read the discussion thread attached to an object "
                        "(e.g. an issue). Use for evidence about a specific "
                        "object's discussion."),
        "input_schema": {
            "type": "object",
            "required": ["object_id"],
            "properties": {
                "object_id": {"type": "string"},
                "limit": {"type": "integer", "default": 30, "maximum": 100},
            },
        },
    },
]

# Note: no issue-specific tools. Issues are created with
# create_object(type_name="issue", ...) and resolved with update_object —
# the agent-defined schema's if/then conditional enforces the resolution note.
```

**Tool executor** — one short transaction per call, audit row always written, WS event broadcast on mutation:

```python
@dataclass
class ToolResult:
    payload: dict
    is_error: bool = False

async def execute_tool(*, space_id, agent_id, trigger_message_id,
                       name: str, args: dict) -> ToolResult:
    async with SessionFactory() as db:
        try:
            async with db.begin():
                result = await _dispatch(db, space_id, agent_id, name, args)
                db.add(AgentAction(space_id=space_id, agent_id=agent_id,
                                   triggered_by_message_id=trigger_message_id,
                                   tool_name=name, tool_input=args,
                                   tool_result=result, status="success"))
        except ObjectServiceError as e:
            async with SessionFactory() as db2, db2.begin():
                db2.add(AgentAction(space_id=space_id, agent_id=agent_id,
                                    triggered_by_message_id=trigger_message_id,
                                    tool_name=name, tool_input=args,
                                    status="error", error_detail=str(e)))
            return ToolResult({"error": str(e)}, is_error=True)
    await broadcast_side_effects(space_id, name, result)   # object_created etc.
    return ToolResult(result)

async def _dispatch(db, space_id, agent_id, name, args) -> dict:
    match name:
        case "define_object_type":
            t = await objects.define_type(db, space_id=space_id, actor_id=None, **args)  # null actor = agent
            return {"type_id": str(t.id), "name": t.name, "version": t.version}
        case "create_object":
            pinned = args.pop("pinned", False)
            o = await objects.create_object(db, space_id=space_id, actor_id=None, **args)  # null actor = agent
            if pinned:
                o.pinned = True
            return {"object_id": str(o.id), "title": o.title}
        case "update_object":
            o = await objects.update_object(
                db, space_id=space_id, actor_id=None,   # null actor = agent
                object_id=uuid.UUID(args["object_id"]), patch=args["patch"])
            return {"object_id": str(o.id), "title": o.title, "data": o.data}
        case "query_objects":
            rows = await objects.query(db, space_id=space_id, **args)
            return {"objects": [{"object_id": str(o.id), "type": tname,
                                 "title": o.title, "pinned": o.pinned,
                                 "data": o.data} for o, tname in rows]}
        case "search_messages":
            rows = await messages_svc.search(db, space_id=space_id, **args)
            return {"messages": [{"sender": r.sender_name,
                                  "at": r.created_at.isoformat(),
                                  "text": r.content} for r in rows]}
        case "get_object_thread":
            rows = await messages_svc.thread(
                db, space_id=space_id,
                object_id=uuid.UUID(args["object_id"]),
                limit=args.get("limit", 30))
            return {"messages": [{"sender": r.sender_name,
                                  "at": r.created_at.isoformat(),
                                  "text": r.content} for r in rows]}
        case _:
            raise ObjectServiceError(f"Unknown tool {name}")
```

`space_id` and `agent_id` come from the job payload built by *your* code when the mention arrived — never from `args`. That's the entire tenant-isolation story, enforced in one place.

## 4.3 Context builder (`app/agent/context.py`)

```python
@dataclass
class AgentContext:
    system_prompt: str
    transcript: str

async def build_context(db, space_id: uuid.UUID) -> AgentContext:
    space = await db.get(Space, space_id)
    members = await db.execute(
        select(User.name, SpaceMember.role).join(SpaceMember)
        .where(SpaceMember.space_id == space_id))
    types = await db.execute(         # latest version per name (DISTINCT ON)
        select(SpaceObjectType)
        .where(SpaceObjectType.space_id == space_id)
        .distinct(SpaceObjectType.name)
        .order_by(SpaceObjectType.name, SpaceObjectType.version.desc()))
    pinned = await db.scalars(
        select(SpaceObject).where(SpaceObject.space_id == space_id,
                                  SpaceObject.pinned, ~SpaceObject.archived)
        .order_by(SpaceObject.updated_at.desc()).limit(10))
    issue_type = await objects.latest_type(db, space_id, "issue")
    open_issues = []
    if issue_type is not None:            # nothing exists until defined
        open_issues = (await db.scalars(
            select(SpaceObject)
            .where(SpaceObject.space_id == space_id, ~SpaceObject.archived,
                   SpaceObject.type_id == issue_type.id,
                   ~SpaceObject.data.contains({"status": "resolved"}))
            .order_by(SpaceObject.created_at.desc()).limit(10))).all()
    recent = await db.execute(
        select(Message,
               func.coalesce(User.name, Agent.name).label("sender"))
        .outerjoin(User, Message.sender_user_id == User.id)
        .outerjoin(Agent, Message.sender_agent_id == Agent.id)
        .where(Message.space_id == space_id, Message.object_id.is_(None),
               Message.message_type.in_(("text", "agent_action")))
        .order_by(Message.created_at.desc())
        .limit(settings.agent_context_messages))

    transcript = "\n".join(
        f"{name} [{m.created_at:%Y-%m-%d %H:%M}]: {m.content}"
        for m, name in reversed(recent.all()))

    type_lines = "\n".join(
        f"- {t.name} (v{t.version}, render: {t.render_hint}): {t.description}\n"
        f"  schema: {json.dumps(t.json_schema)}"
        for t in types.scalars())

    system_prompt = SYSTEM_TEMPLATE.format(
        space_name=space.name,
        custom_instructions=space.agent_instructions or "None.",
        members=", ".join(f"{n} ({r})" for n, r in members),
        types=type_lines or "None yet.",
        pinned="\n".join(f"- [{o.id}] {o.title}" for o in pinned) or "None.",
        issues="\n".join(f"- [{o.id}] {o.title} ({o.data.get('status')})"
                         for o in open_issues) or "None.",
        today=date.today().isoformat())
    return AgentContext(system_prompt=system_prompt, transcript=transcript)
```

`SYSTEM_TEMPLATE` (in `prompts.py`) is the sketch from 3.4, plus:

```
Today is {today}.
Space-specific instructions from the owner: {custom_instructions}

Dispute-resolution rules:
- Before saying who is correct, use search_messages to find what was
  actually said. Quote the message with sender and time as evidence.
- Factual disputes: answer directly, citing evidence.
- Preference/opinion disputes: summarize both positions fairly and help
  the group decide. Do not declare a winner.
- Never mock or pile on a member. You serve the space, not one person.

General-assistant rule:
- Members may ask you anything. If no shared state needs to change and no
  history lookup is needed, just answer — do not force a tool call.

Object rules:
- Reuse an existing type if it fits. Only define_object_type when nothing matches.
- To toggle a checklist item, send update_object with the FULL items array.
- After actions, confirm briefly ("Created 'Trip Todos' with 4 items").
```

## 4.4 REST routes (thin wrappers)

Objects endpoints call the same service functions as the agent tools:

```python
@router.post("/spaces/{space_id}/objects", status_code=201)
async def create_obj(space_id: uuid.UUID, body: CreateObjectIn,
                     m: SpaceMember = Depends(require_space_member()),
                     db=Depends(get_db)):
    o = await objects.create_object(db, space_id=space_id, actor_id=m.user_id,
                                    type_name=body.type_name,
                                    title=body.title, data=body.data)
    await broadcast_object_created(space_id, o)
    return serialize_object(o)

@router.patch("/spaces/{space_id}/objects/{object_id}")
async def patch_obj(space_id: uuid.UUID, object_id: uuid.UUID, body: dict,
                    m: SpaceMember = Depends(require_space_member()),
                    db=Depends(get_db)):
    o = await objects.update_object(db, space_id=space_id, object_id=object_id,
                                    patch=body, actor_id=m.user_id)
    await broadcast_object_updated(space_id, o)
    return serialize_object(o)
```

Message search (used by both the REST endpoint and the agent tool) — start with ILIKE, upgrade to `to_tsvector` FTS when needed:

```python
async def search(db, *, space_id, query, sender_name=None,
                 from_date=None, to_date=None, limit=20):
    who = func.coalesce(User.name, Agent.name)
    stmt = (select(Message, who.label("sender_name"))
            .outerjoin(User, Message.sender_user_id == User.id)
            .outerjoin(Agent, Message.sender_agent_id == Agent.id)
            .where(Message.space_id == space_id,
                   Message.content.ilike(f"%{query}%")))
    if sender_name:
        stmt = stmt.where(who.ilike(sender_name))
    if from_date:
        stmt = stmt.where(Message.created_at >= from_date)
    if to_date:
        stmt = stmt.where(Message.created_at < to_date)
    rows = await db.execute(stmt.order_by(Message.created_at.desc()).limit(limit))
    return rows.all()

async def thread(db, *, space_id, object_id, limit=30):
    """Messages attached to one object, oldest first (used by the
    get_object_thread tool and GET /spaces/:id/objects/:oid/messages)."""
    stmt = (select(Message,
                   func.coalesce(User.name, Agent.name).label("sender_name"))
            .outerjoin(User, Message.sender_user_id == User.id)
            .outerjoin(Agent, Message.sender_agent_id == Agent.id)
            .where(Message.space_id == space_id,
                   Message.object_id == object_id)
            .order_by(Message.created_at.asc()).limit(min(limit, 100)))
    rows = await db.execute(stmt)
    return rows.all()
```

## 4.5 Frontend implementation

**Renderer registry** — the one pattern that makes dynamic types renderable:

```jsx
// src/components/objects/registry.jsx
import Checklist from "./Checklist";
import TableCard from "./TableCard";
import MarkdownCard from "./MarkdownCard";
import KeyValueCard from "./KeyValueCard";

const RENDERERS = {
  checklist: Checklist,
  table: TableCard,
  markdown: MarkdownCard,
  keyvalue: KeyValueCard,
};

export function ObjectCard({ obj, type }) {
  const Renderer = RENDERERS[type.render_hint] ?? KeyValueCard;
  return (
    <div className="rounded-xl border bg-white p-4">
      <header className="flex items-center justify-between mb-2">
        <span className="font-medium text-sm">{obj.title}</span>
        <span className="text-xs text-gray-500">{type.name}</span>
      </header>
      <Renderer obj={obj} type={type} />
    </div>
  );
}
```

**Checklist renderer** — human edits go through the same PATCH the agent uses:

```jsx
export default function Checklist({ obj }) {
  const patchObject = useSpaceStore((s) => s.patchObject);
  const toggle = (i) => {
    const items = obj.data.items.map((it, idx) =>
      idx === i ? { ...it, done: !it.done } : it);
    patchObject(obj.id, { data: { items } });   // full array — RFC 7386
  };
  return obj.data.items.map((it, i) => (
    <label key={i} className="flex items-center gap-2 py-1 text-sm">
      <input type="checkbox" checked={it.done} onChange={() => toggle(i)} />
      <span className={it.done ? "line-through text-gray-400" : ""}>{it.text}</span>
    </label>
  ));
}
```

**TableCard** derives columns from the type's schema — no hardcoding:

```jsx
export default function TableCard({ obj, type }) {
  const rows = obj.data.rows ?? [obj.data];          // single-record or rows[]
  const cols = Object.keys(type.json_schema.properties?.rows?.items?.properties
                           ?? type.json_schema.properties ?? rows[0] ?? {});
  ...
}
```

**Zustand store + socket wiring**:

```js
// src/store/space.js
export const useSpaceStore = create((set, get) => ({
  messages: [], objects: {}, types: {}, agentTyping: false,

  patchObject: async (id, patch) => {
    const { data } = await api.patch(
      `/spaces/${get().spaceId}/objects/${id}`, patch);
    set((s) => ({ objects: { ...s.objects, [id]: data } }));  // optimistic-ish
  },

  bindSocket: (socket) => {
    socket.on("message", (m) =>
      set((s) => ({ messages: [...s.messages, m] })));
    socket.on("agent_typing", ({ state }) =>
      set({ agentTyping: state === "start" }));
    socket.on("object_created", (o) =>
      set((s) => ({ objects: { ...s.objects, [o.id]: o } })));
    socket.on("object_updated", (o) =>
      set((s) => ({ objects: { ...s.objects, [o.id]: o } })));
    socket.on("object_type_defined", (t) =>
      set((s) => ({ types: { ...s.types, [t.id]: t } })));
  },
}));
```

```js
// src/api/socket.js
import { io } from "socket.io-client";
export const socket = io("/", {
  path: "/socket.io",
  auth: { token: localStorage.getItem("access_token") },
});
```

(Note: token in localStorage is fine for a LAN-only self-hosted app; switch to httpOnly-cookie + socket cookie auth if you ever expose it.)

## 4.6 Fully dynamic rendering (post-MVP level 2): agent-written widgets

The renderer registry (level 1) fixes only the presentation primitives. If a
type outgrows them, the agent can write the renderer itself:

- New tool: `set_type_widget(type_name, html)` — stores `widget_html` on the
  latest type version (size cap ~30KB, server strips `<script src>` to
  disallow external loads if you want it stricter).
- Frontend: if `type.widget_html` is set, render it in a sandboxed iframe
  instead of the registry renderer:

```jsx
function CustomWidget({ obj, type }) {
  const ref = useRef();
  useEffect(() => {
    const onMsg = (e) => {
      if (e.source !== ref.current?.contentWindow) return;
      if (e.data?.kind === "patch")           // widget proposes a change
        useSpaceStore.getState().patchObject(obj.id, { data: e.data.patch });
    };
    window.addEventListener("message", onMsg);
    return () => window.removeEventListener("message", onMsg);
  }, [obj.id]);

  useEffect(() => {                            // push data into the widget
    ref.current?.contentWindow?.postMessage(
      { kind: "data", data: obj.data, title: obj.title }, "*");
  }, [obj.data]);

  return <iframe ref={ref} sandbox="allow-scripts" srcDoc={type.widget_html}
                 style={{ width: "100%", border: 0 }} />;
}
```

Security containment, in order of importance:
1. `sandbox="allow-scripts"` WITHOUT `allow-same-origin` — the widget runs in
   an opaque origin: no cookies, no localStorage, no parent DOM, no app JWT.
2. All writes flow parent-side through the same `PATCH` endpoint → same JSON
   Schema validation → same audit trail. The widget can only *propose* patches.
3. CSP on the iframe document (`default-src 'none'; script-src 'unsafe-inline'`)
   blocks network exfiltration.
4. Registry renderer remains the fallback: widget errors or fails to
   handshake within 2s → fall back to `render_hint`, log a system message.

This is the full spectrum, explicitly:
| Level | What's dynamic | What's fixed |
|---|---|---|
| 0 (v1 plan) | nothing | features hardcoded |
| 1 (MVP) | meaning: types, schemas, workflows | ~7 presentation primitives |
| 2 (this) | meaning AND presentation | the storage/validation/audit substrate |

The substrate never becomes dynamic — generic CRUD, schema validation,
scoping, and audit are the trusted computing base that makes the rest safe
to leave to the model.

## 4.7 Extensible capabilities: per-space tools and MCP (the "anything" layer)

The agent's tool list is assembled per space, per invocation — core tools are
constant, everything else comes from the space's `agent_capabilities` config:

```python
# app/agent/capabilities.py
CAPABILITY_TOOLS = {
    "web_search": {
        "name": "web_search",
        "description": "Search the web for current information.",
        "input_schema": {"type": "object", "required": ["query"],
                         "properties": {"query": {"type": "string"}}},
    },
    "fetch_url": {
        "name": "fetch_url",
        "description": "Fetch a public web page and return its text.",
        "input_schema": {"type": "object", "required": ["url"],
                         "properties": {"url": {"type": "string"}}},
    },
    "run_python": {
        "name": "run_python",
        "description": ("Run a short Python snippet in a sandbox and return "
                        "stdout. Use for exact arithmetic (expense splits, "
                        "date math) instead of computing in your head."),
        "input_schema": {"type": "object", "required": ["code"],
                         "properties": {"code": {"type": "string"}}},
    },
}

async def assemble_tools(space: Space) -> tuple[list[dict], dict]:
    tools = list(CORE_TOOL_SCHEMAS)
    caps = space.agent_capabilities or {}
    for key, schema in CAPABILITY_TOOLS.items():
        if caps.get(key):
            tools.append(schema)
    mcp_routes = {}
    for server in caps.get("mcp_servers", []):
        for t in await mcp_list_tools(server):          # MCP tools/list
            name = f"mcp_{server['name']}_{t['name']}"
            tools.append({"name": name, "description": t["description"],
                          "input_schema": t["inputSchema"]})
            mcp_routes[name] = (server, t["name"])
    return tools, mcp_routes
```

Dispatch grows one branch — MCP calls route to their server, everything else
is unchanged, and ALL of it still lands in `agent_actions`:

```python
    if name in mcp_routes:
        server, remote_name = mcp_routes[name]
        return await mcp_call_tool(server, remote_name, args)   # MCP tools/call
    if name == "run_python":
        return await sandbox_run(args["code"], timeout=5)
    if name == "web_search":
        return await search_provider(args["query"])
    ...
```

Implementation notes:
- `runner.py` changes one line: `tools, mcp_routes = await assemble_tools(space)`
  is already wired in `run_agent_turn` (see 1.10); with no capabilities
  enabled it returns exactly `CORE_TOOL_SCHEMAS`.
- **run_python sandbox**: a dedicated container with no network
  (`network_mode: none`), read-only FS, 128MB/5s limits, communicating over a
  Redis request/response pair. Never exec in the backend process. This also
  fixes the "LLM arithmetic" caveat from the expense-split example — the
  agent computes settlements in real code.
- **fetch_url**: block private ranges (10/8, 172.16/12, 192.168/16, 169.254/16,
  localhost) unless the owner explicitly allows LAN fetches — this app lives
  ON the LAN, so SSRF is the first thing to close.
- **MCP secrets**: `token_ref` points at an env/secret name, never the token
  itself in the DB row.
- Capability config is owner-only (`role == "owner"` check on
  `POST /spaces/:id/agent`), and every capability/MCP call is visible to all
  members through the audit log — same transparency rule as space tools.

The mental model, final form:
- **Say anything**: free, always on — it's just the model talking.
- **Change the space**: core generic tools, always on, schema-validated, audited.
- **Act on the world**: capability tools + MCP, owner-enabled per space, audited.

## 4.8 Testing the agent loop (worth doing early)

- **Unit-test the executor without an LLM**: call `execute_tool` directly with crafted args; assert audit rows, validation rejections, and that a bad `type_name` returns an instructive error payload.
- **Golden-transcript test for the loop**: fake the Anthropic client with a scripted sequence (`tool_use create_object` → final text) and assert the DB side effects. Keeps loop-plumbing bugs out of LLM-land.
- **One live smoke test** behind an env flag: "make a todo list with 3 items" → assert one `task_list` object exists with 3 items. Run manually, not in CI.
- **Merge-patch property test**: `merge_patch(merge_patch(a, p1), p2)` invariants + round-trips against the RFC 7386 examples (there are 15 canonical cases in the RFC — encode them all, it's 20 lines).

## 4.9 V2 build order (high level; assumes V1 shipped — its steps 1–5 overlap V1)

1. ✅ Folder structure created
2. ⬜ Docker Compose skeleton + Postgres + Redis running
3. ⬜ Backend: auth (register/login/JWT)
4. ⬜ Backend: spaces + invite/join
5. ⬜ Backend: WebSocket general chat (persist + Redis pub/sub broadcast)
6. ⬜ **Backend: object system — types + objects CRUD, JSON Schema validation (human-usable via API first; starts empty)**
7. ⬜ Backend: object threads (messages.object_id) + thread history endpoint
8. ⬜ **Agent v1: mention detection → job → context (last N messages + type list + exemplars) → Claude tool loop with `define_object_type` / `create_object` / `query_objects` / `update_object`** (define must be in v1 — nothing exists without it)
9. ⬜ **Agent v2: remaining tools (`get_object_thread`, `search_messages`) + audit log + system events in chat**
10. ⬜ Frontend: auth screens
11. ⬜ Frontend: general chat UI + @ai mention + agent message rendering
12. ⬜ **Frontend: space panel with renderer registry (checklist, table, markdown, keyvalue) + live object updates over WS**
13. ⬜ Frontend: kanban board renderer (issues) + object thread view
14. ⬜ IP whitelist middleware
15. ⬜ Polish + mobile responsiveness
16. ⬜ Post-MVP: more renderers (kanban/poll/timeline), streaming replies,
      rolling summaries, FTS/pgvector search, proactive behaviors,
      sandboxed custom widgets per type

---

## 4.10 V2 implementation order (fine-grained)

1. Compose up postgres+redis; alembic init; models + first migration (no seeds)
2. Auth endpoints + `get_current_user` + `require_space_member` (tests)
3. Spaces create/join; default agent row seeded in `agents`; enabling the agent sets `spaces.agent_id`
4. Objects service + REST + unit tests (validation, merge patch, versioning)
5. Socket.IO mount + join/chat/broadcast; verify two browser tabs sync
6. Queue + worker loop + fake-client golden test
7. `tools.py` + `execute_tool` + context builder with exemplars; live smoke test: cold space → "make a todo list" must define + create in one turn
8. Add `define_object_type` + remaining tools; anti-sprawl caps
9. Frontend: auth → chat → panel with registry renderers → live WS updates
10. Object thread endpoint + kanban board UI; IP whitelist middleware; polish