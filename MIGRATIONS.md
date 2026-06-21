# Production-Grade Database Migrations with Alembic

Stack: **FastAPI + PostgreSQL + SQLAlchemy + Alembic**, run entirely through **Docker Compose**.

---

## Overview of the Flow

```
Define Model → Generate Migration → Review SQL → docker compose up (migrations apply automatically)
```

Never write raw SQL to create tables in production. Alembic tracks every schema change in versioned files, so the database can be upgraded or rolled back reliably.

---

## Requirements

**`backend/requirements.txt`**
```
fastapi
uvicorn[standard]
sqlalchemy
alembic
psycopg2-binary
python-dotenv
```

- `uvicorn[standard]` — includes `websockets` and `httptools` for better performance
- `sqlalchemy` — ORM and database engine
- `alembic` — migration tool
- `psycopg2-binary` — PostgreSQL driver that SQLAlchemy uses to talk to Postgres

---

## Environment Variables

Credentials are never hardcoded. They live in a `.env` file that is gitignored. Docker Compose reads `.env` automatically from the project root and substitutes `${VAR}` references in `docker-compose.yml`.

**`.env.example`** (commit this):
```
POSTGRES_USER=
POSTGRES_PASSWORD=
POSTGRES_DB=
DATABASE_URL=postgresql://<user>:<password>@db:5432/<db>
DB_HOST=db
DB_PORT=5432
DB_USER=
```

**`.env`** (gitignored, fill in your values):
```
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=postgres
DATABASE_URL=postgresql://postgres:postgres@db:5432/postgres
DB_HOST=db
DB_PORT=5432
DB_USER=postgres
```

Add to `.gitignore`:
```
.env
```

---

## Step 1 — Set Up SQLAlchemy Base and Database Session

**`app/core/database.py`**
```python
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

DATABASE_URL = os.environ["DATABASE_URL"]

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Base(DeclarativeBase):
    pass
```

`DATABASE_URL` is injected by Docker Compose from `.env` — no hardcoding needed. `Base` is the parent class every model inherits from; Alembic inspects it to detect schema changes.

---

## Step 2 — Alembic Layout

All Alembic config files are now in place:

```
backend/
  alembic/
    versions/       ← generated migration files land here (currently empty)
    env.py          ← configured (Step 4)
    script.py.mako  ← migration template
  alembic.ini       ← configured (Step 3)
```

> These were created manually rather than via `alembic init alembic`, because `init` refuses to write into the non-empty `alembic/` directory (which already contained `versions/`).

---

## Step 3 — Configure `alembic.ini`

Leave `sqlalchemy.url` blank — it is overridden by `env.py` at runtime from the environment:

```ini
sqlalchemy.url =
```

Never put credentials here.

---

## Step 4 — Configure `alembic/env.py`

```python
import os
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context

# Import your Base and ALL models so Alembic can see them
from app.core.database import Base
import app.models  # ensures all model files are imported

config = context.config
fileConfig(config.config_file_name)

# Read DATABASE_URL from the environment — never from alembic.ini
config.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

---

## Step 5 — Define a Model

Create a file in `app/models/`. Example: `app/models/user.py`

```python
from sqlalchemy import String, Boolean, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), onupdate=func.now())
```

Then register it in `app/models/__init__.py`:

```python
from app.models.user import User  # noqa: F401
```

The `noqa` comment prevents linters from removing the import (which looks unused but is required for Alembic).

---

## Step 6 — Generate a Migration

Generating a new migration file is the one step that needs an explicit command. Run it through Docker Compose so it uses the same image and `.env` as everything else:

```bash
docker compose run --rm migrate alembic revision --autogenerate -m "create_users_table"
```

This generates a file in `alembic/versions/`:

```
alembic/versions/3a1b2c3d4e5f_create_users_table.py
```

**Always open and review the generated file before applying it.** Check that:
- `upgrade()` creates the right tables/columns/indexes
- `downgrade()` correctly reverses the change
- No unexpected drops are included

---

## Step 7 — Docker Compose Setup (applies migrations automatically)

The `migrate` service runs `alembic upgrade head` and exits before `api` starts. You never run `alembic upgrade` by hand — `docker compose up` does it. This means:
- Migrations run exactly once per `docker compose up`, not once per app replica
- If a migration fails, `api` never starts — no crash loop, no partial state
- Migration logs are separate and easy to read

**`docker-compose.yml`**:
```yaml
services:
  migrate:
    build: ./backend
    command: alembic upgrade head
    environment:
      DATABASE_URL: ${DATABASE_URL}
    depends_on:
      db:
        condition: service_healthy

  api:
    build: ./backend
    ports:
      - "8080:8080"
    environment:
      DATABASE_URL: ${DATABASE_URL}
      DB_HOST: ${DB_HOST}
      DB_PORT: ${DB_PORT}
      DB_USER: ${DB_USER}
    depends_on:
      migrate:
        condition: service_completed_successfully
      db:
        condition: service_healthy

  db:
    image: postgres:16
    env_file: .env
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER}"]
      interval: 5s
      timeout: 5s
      retries: 5
```

- `db` passes `POSTGRES_USER/PASSWORD/DB` via `env_file: .env` — the Postgres image uses these to initialize the database
- `api` and `migrate` receive `DATABASE_URL` via `${VAR}` substitution from `.env`
- `condition: service_healthy` ensures Postgres is ready to accept connections before migrations run (a plain `depends_on` only waits for the container to *start*, not to be *ready*)
- `condition: service_completed_successfully` ensures migrations finished with exit code 0 before the app starts

**Start everything:**
```bash
docker compose up --build
```

**Expected startup order in the logs:**
1. `db` starts and passes its healthcheck
2. `migrate` runs `alembic upgrade head` and exits with code 0
3. `api` starts

**If migrations fail, inspect the logs:**
```bash
docker compose logs migrate
```

---

## Step 8 — Workflow Summary (Every Time You Change the Schema)

```
1. Edit or create a model in app/models/
2. Register it in app/models/__init__.py
3. docker compose run --rm migrate alembic revision --autogenerate -m "describe_change"
4. Review the generated file in alembic/versions/
5. docker compose up --build      (the migrate service applies it automatically)
6. Commit the migration file to git
```

---

## Production Hardening

### Never hardcode credentials
All credentials come from `.env` (local) or injected environment variables (CI/CD). Neither `alembic.ini` nor `database.py` should contain literal passwords.

### Migrations live in their own service
The separate `migrate` service is what makes this production-safe with multiple `api` replicas — migrations run once, before any replica starts, instead of every replica racing to alter the same tables.

### Never edit a migration file after it has been applied
Once a migration has run on any environment (staging, prod), treat it as immutable. Create a new migration to fix it.

### Add migrations to version control
The `alembic/versions/` directory must be committed to git. It is the source of truth for your schema history.

---

## Common Mistakes to Avoid

| Mistake | Why it's a problem |
|---|---|
| Hardcoding credentials in `docker-compose.yml` or `alembic.ini` | Credentials leak into git history |
| Running `Base.metadata.create_all()` in production | Bypasses Alembic — schema drifts, no rollback |
| Not importing models in `env.py` | Alembic sees an empty schema and generates DROP statements |
| Editing an applied migration | Other developers and environments get out of sync |
| Not reviewing autogenerated migrations | Alembic sometimes generates incorrect or destructive SQL |
| Running migrations inside the `api` container | Multiple replicas race to alter the same tables — use the separate `migrate` service |
| Using plain `depends_on: db` without a healthcheck | Migrations run before Postgres is ready and fail with connection refused |
