# Running the App Locally — Options

Stack: **FastAPI + PostgreSQL + SQLAlchemy + Alembic + React**, orchestrated with **Docker Compose**.

---

## Option 1 — Full Docker Compose, no bind mounts (current setup)

```bash
docker compose up --build
```

Everything runs in containers built from `backend/Dockerfile` / `frontend/Dockerfile`. The image only contains a *copy* of your code taken at build time (`COPY . .`).

**Pros**
- Clean, production-like — what runs locally closely matches what would run in prod
- Single command, no host dependencies (no local Python venv, no local Node)

**Cons**
- Every code change requires `--build` to take effect — no live reload
- Generated files (e.g. Alembic migrations from `alembic revision --autogenerate`) are written to the container's ephemeral filesystem and are lost when the container exits — see `MIGRATIONS.md`

---

## Option 2 — Docker Compose + bind mounts + auto-reload (recommended)

Same one-command workflow, but mount source directories into the containers so the container sees host file changes instantly:

```yaml
services:
  api:
    build: ./backend
    volumes:
      - ./backend:/app
    command: uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
    ...

  migrate:
    build: ./backend
    volumes:
      - ./backend:/app
    command: alembic upgrade head
    ...
```

(Frontend gets the same treatment later: mount `./frontend/src` and run the Vite dev server inside the container instead of building a static bundle.)

**Pros**
- Edit code on host → container sees it immediately → uvicorn `--reload` restarts itself, no rebuild
- Alembic-generated migration files land directly in `backend/alembic/versions/` on the host (fixes the issue described in `MIGRATIONS.md`)
- Still a single command: `docker compose up`
- You only rebuild when `requirements.txt`/`package.json` or a Dockerfile changes

**Cons**
- Slightly more compose config to maintain
- Container now depends on host filesystem state, which is a minor departure from "prod-identical" — acceptable tradeoff for local dev

**Variant:** Compose v2.22+ has `develop: watch:`, which syncs/rebuilds on file changes without a classic bind mount. More setup for marginal benefit here — plain bind mounts are simpler and sufficient.

---

## Option 3 — Hybrid: infra in Docker, app on host

Run only `db` (and `redis`, once added) via Docker Compose, with the Postgres port exposed:

```yaml
db:
  image: postgres:16
  ports:
    - "5432:5432"
  ...
```

Run FastAPI directly on the host in a local venv:

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres uvicorn app.main:app --reload
```

**Pros**
- Fastest feedback loop
- Full IDE integration — breakpoints, debugger, linting, etc. work directly against the running process

**Cons**
- Needs a local Python venv and a second `DATABASE_URL` (using `localhost` instead of the Docker network hostname `db`)
- Local dev environment can drift from the containerized one (different Python patch version, missing system deps, etc.)
- Breaks the "everything through Docker Compose" workflow

---

## Recommendation

**Option 2** — Docker Compose with bind mounts and `--reload`. It keeps the single-command workflow, fixes the migration-file-vanishing problem, and gives live reload without needing a local Python/Node environment.

Concrete changes needed in `docker-compose.yml`:
- Add `volumes: - ./backend:/app` to the `api` and `migrate` services
- Change `api`'s command to `uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload`
- Later: add an equivalent mount + dev server command for `frontend`

See `MIGRATIONS.md` for how this interacts with the Alembic migration workflow.
