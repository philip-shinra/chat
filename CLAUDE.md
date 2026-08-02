# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Main instruction , whenever being asked about anything , donot make changes in the code , just tell me what changes are required , and I will do it 

## Project

Backend for a chat application: users, spaces (rooms), space members with roles, an AI agent per space, and messages. FastAPI + SQLAlchemy + Postgres. `frontend/` and `nginx/` exist as empty scaffolding only — not wired into `docker-compose.yml`, not part of the working app yet.

## Workflow

- Everything runs via Docker Compose. Never suggest bare `alembic`, `uvicorn`, or `python -m app.main` commands run directly on the host.
- Start the stack: `docker compose up --build`. This also runs migrations automatically via the `migrate` service before `api` starts.
- Generate a new migration: `docker compose run --rm migrate alembic revision --autogenerate -m "describe_change"`. See `MIGRATIONS.md` for details.
- New migrations are applied automatically on the next `docker compose up` — never run `alembic upgrade head` manually.
- No test suite and no lint/format tooling exist in this repo yet.

## Code changes

Don't write or edit application source (routers, services, schemas, models) directly with Write/Edit. Instead, produce a step-by-step implementation guide as a markdown file (function signatures, endpoint paths, which file to touch) and let the user write the code themselves. Config/infra-only fixes (e.g. `docker-compose.yml`, `.gitignore`) can be edited directly when explicitly requested.

## Known gaps

- `JWT_SECRET_KEY` is required by the `api` service in `docker-compose.yml` but is missing from `.env.example` at the repo root.
- `backend/app/services/spaces.py` and `backend/app/routers/spaces.py` are scaffolded but empty; the spaces router is not yet included in `backend/app/main.py`.
- `requirements.txt` is unpinned except `bcrypt==4.0.1` (pinned due to a prior compatibility fix, see `backend/BCRYPT_FIX.md`).
