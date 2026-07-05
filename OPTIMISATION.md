# Performance & Optimisation Notes

Guidance on making the app fast, organized from highest-impact/architectural down to smaller code-level tweaks. Not urgent to do all of this now — see "Priority" at the bottom.

---

## 1. Plan-level architecture decisions

### Async SQLAlchemy + asyncpg (the biggest one)

`plan.md` already specifies "SQLAlchemy 2.0 (async)," but what's actually built in `backend/app/core/database.py` is sync (`create_engine` + `psycopg2`).

This matters most for a WebSocket-heavy app: with sync DB calls, a slow query blocks that worker's entire event loop — no other requests or WebSocket messages get processed until it returns. An async engine (`create_async_engine` + `asyncpg` driver instead of `psycopg2`) lets FastAPI keep serving other connections while a query is in flight.

This is a decision to make deliberately **now**, before more routes/sessions are built on top of the sync pattern — retrofitting later means touching every route and dependency (`get_db` becomes `async def`, all route handlers become `async def`, all `db.scalar(...)` calls become `await db.scalar(...)`, etc).

### Redis for WebSocket pub/sub

Already in `plan.md`'s tech stack — don't skip it once WebSockets are built. If you ever run more than one `api` container/worker, in-memory broadcasting only reaches clients connected to *that* worker. Redis pub/sub lets a message from one worker reach WebSocket clients connected to another. Worth building the pub/sub abstraction from day one even at 1 worker, to avoid a rewrite later.

### Multiple Uvicorn workers behind Nginx

Run Gunicorn managing multiple Uvicorn workers (or `uvicorn --workers N`), so multiple CPU cores actually get used. This is what makes Redis pub/sub necessary — without it, workers can't be split for WebSocket traffic.

### Background jobs for anything slow

`plan.md` already lists Celery + Redis as optional. Anything that isn't instant — AI-assisted suggestions calling out to Claude, notification emails — should never block a request. Queue it, return immediately, push the result to the client over the WebSocket when it's done.

---

## 2. Database

- **Indexes** — currently only `email` has one (via `unique=True`). Once `spaces`, `issues`, `messages` exist, index anything used in `WHERE`/`JOIN`: `space_id` on `issues` and `messages`, `user_id` + `space_id` on `space_members`, `status` on `issues` if dashboards filter by status often.
- **Avoid N+1 queries** — e.g. loading an issue plus all its messages plus each message's sender in separate round-trips. Use `selectinload`/`joinedload` in SQLAlchemy queries to batch related rows into one or two queries instead of one per row.
- **Pagination** — general chat history and issue lists grow unbounded. Never query messages/issues with no `LIMIT`; use cursor-based pagination (ordered by `created_at`/`id`) rather than offset-based, especially for chat scroll-back.
- **Connection pool sizing** — pool size is *per engine instance*, i.e. per worker process. With multiple Uvicorn workers, total real Postgres connections = `workers × pool_size` (+ overflow) — keep this within Postgres's `max_connections`.

---

## 3. Application code

- **Narrow response models** — already doing this correctly with `UserOut`. Keep returning narrow Pydantic response models instead of full ORM objects: less serialization overhead per response, and it prevents leaking fields like `password_hash`.
- **bcrypt cost factor** — `passlib`'s default bcrypt rounds are deliberately slow (that's the point — resists brute force). Only call `verify_password`/`hash_password` in register/login, never in a hot path like "check password on every request."
- **JWT over DB session lookups** — already doing this right: `get_current_user` decodes the JWT locally instead of hitting the DB for a session table on every request. Keep it that way; no server-side session store needed for now.
- **Don't over-fetch** — endpoints like `/admin/users` returning full lists should get pagination once real growth is expected; fine as-is at this stage.

---

## 4. Infra

- **Nginx** — enable gzip/brotli compression for API responses and the frontend bundle; use `keepalive` connections upstream to `api` so Nginx doesn't re-open a TCP connection to the backend per request.
- **Frontend** — served as a static build via Nginx already, which is the fast path (no SSR overhead). Ensure cache headers are set for hashed static assets (Vite content-hashes filenames by default, so `Cache-Control: max-age=1y, immutable` is safe).

---

## Priority

Don't optimize prematurely — there's no real load yet. The one thing worth deciding **now**, before more code piles on top of the sync pattern, is **sync vs. async SQLAlchemy** — that's the expensive one to change later. Indexes and pagination can be added incrementally as tables grow. Multi-worker setup, Redis pub/sub, and Celery matter once there's real concurrent usage, not before.
