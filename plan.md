# RelationshipChat App — Architecture & Product Plan

## Overview

A private, self-hosted chat application designed primarily for people to resolve  issues through structured conversations, with support for general chat as well. Runs locally via Docker, access controlled via IP whitelisting.

---

## Core Concept

Two modes of interaction:
1. **Issue Resolution Mode** — structured flow: raise issue → discuss → resolve/close
2. **General Chat Mode** — normal real-time messaging between users/couples

---

## User Flows

### Couple / User Setup
- Register with name + email
- Create or join a "relationship space" (a private room linking two users)
- Only whitelisted IPs can access the app

### Issue Flow
```
One partner raises an issue
        ↓
Issue listed on shared dashboard (title, category, priority, date)
        ↓
Both partners enter the issue's conversation thread
        ↓
They discuss, optionally get AI-assisted mediation prompts
        ↓
Either partner marks issue as Resolved / Needs More Time / Escalated
        ↓
Issue archived with resolution summary
```

### General Chat Flow
- Standard real-time messaging within their relationship space
- Supports text, emoji, images (optional)

---

## Features

### Must-Have (MVP)
- [ ] User auth (email + password, JWT)
- [ ] Couple pairing (invite via link or code)
- [ ] Issue tracker: create, list, filter by status (Open / In Progress / Resolved)
- [ ] Per-issue conversation thread (real-time chat)
- [ ] General chat channel per relationship space
- [ ] Issue resolution: mark resolved with a short summary note
- [ ] IP whitelisting middleware

### Nice-to-Have (Post-MVP)
- [ ] AI mediation suggestions inside issue threads (using Claude API)
- [ ] Mood check-in (daily prompt: "How are you feeling today?")
- [ ] Issue categories (Communication, Trust, Finance, Intimacy, etc.)
- [ ] Resolution history & stats ("12 issues resolved this month")
- [ ] Notifications (in-app or email)
- [ ] Image/file sharing in chat

---

## Tech Stack

### Backend — Python
| Layer | Choice | Reason |
|---|---|---|
| Framework | **FastAPI** | Async, fast, great WebSocket support |
| WebSockets | FastAPI + **python-socketio** | Real-time chat & issue threads |
| Auth | **JWT** (python-jose) + bcrypt | Simple, stateless |
| ORM | **SQLAlchemy 2.0** (async) | Clean, well-supported |
| DB | **PostgreSQL** | Reliable, supports JSONB for flexible data |
| Migrations | **Alembic** | Works with SQLAlchemy |
| Background jobs | **Celery + Redis** (optional for notifications) | Async tasks |
| Cache / Pub-Sub | **Redis** | WebSocket message broadcasting across workers |

### Frontend — Web UI
| Layer | Choice | Reason |
|---|---|---|
| Framework | **React** (Vite) | Fast dev, component-friendly for chat UI |
| State | **Zustand** | Lightweight, no boilerplate |
| Styling | **Tailwind CSS** | Quick, clean UI |
| Real-time | **Socket.IO client** | Pairs with backend |
| HTTP client | **Axios** | Simple REST calls |

### Infrastructure (Local Docker)
| Service | Docker Image |
|---|---|
| Backend API | Custom Python image |
| Frontend | Nginx serving React build |
| PostgreSQL | `postgres:16` |
| Redis | `redis:7-alpine` |
| Reverse Proxy | **Nginx** (with IP whitelist) |

---

## Database Schema (High Level)

```
users
  id, email, password_hash, name, created_at

relationship_spaces
  id, name, created_at

space_members
  space_id, user_id, role (owner/partner), joined_at

issues
  id, space_id, raised_by, title, description
  category, priority, status (open/in_progress/resolved)
  resolution_note, created_at, resolved_at

messages
  id, space_id, issue_id (nullable — null = general chat)
  sender_id, content, message_type (text/image/system)
  created_at

ip_whitelist
  id, ip_address, label, added_at
```

---

## API Structure

```
POST   /auth/register
POST   /auth/login
GET    /auth/me

POST   /spaces                    — create relationship space
GET    /spaces/:id                — get space details
POST   /spaces/:id/invite         — generate invite link

GET    /spaces/:id/issues         — list issues (filterable by status)
POST   /spaces/:id/issues         — raise new issue
GET    /spaces/:id/issues/:iid    — get issue detail + messages
PATCH  /spaces/:id/issues/:iid    — update status / add resolution note

GET    /spaces/:id/messages       — general chat history
WS     /ws/spaces/:id             — general chat socket
WS     /ws/issues/:iid            — issue thread socket

GET    /admin/ip-whitelist        — list whitelisted IPs
POST   /admin/ip-whitelist        — add IP
DELETE /admin/ip-whitelist/:id    — remove IP
```

---

## UI/UX Structure

### Layout
```
┌─────────────────────────────────────────────────┐
│  Header: Space name | Partner online indicator  │
├──────────────┬──────────────────────────────────┤
│              │                                  │
│  Sidebar     │   Main Content Area              │
│              │                                  │
│  > General   │   (Chat / Issue Thread /         │
│    Chat      │    Issue List / Issue Detail)    │
│              │                                  │
│  > Issues    │                                  │
│    (list)    │                                  │
│              │                                  │
│  + New Issue │                                  │
│              │                                  │
└──────────────┴──────────────────────────────────┘
```

### Key Screens
1. **Login / Register** — minimal, clean
2. **Home / General Chat** — familiar messaging UI (WhatsApp-like)
3. **Issue Dashboard** — kanban-style or list view with status columns
   - Open | In Progress | Resolved
4. **Issue Thread** — chat thread with issue header showing title, status, priority
   - "Mark Resolved" button with a resolution note input
5. **Issue Creation Modal** — title, description, category, priority
6. **Settings** — profile, partner info, IP whitelist (admin)

### UX Principles
- Calm, neutral color palette — this is an emotionally sensitive app
- No aggressive colors or gamification
- Resolution feels like a shared achievement (subtle confirmation animation)
- Mobile-responsive (even though it's local, could be on phone via local network)

---

## Security & Access Control

### IP Whitelisting
- Nginx checks `$remote_addr` against an allowlist before any request reaches the app
- Admin panel to add/remove IPs at runtime (stored in DB, Nginx reads from file regenerated on change)
- Alternative: FastAPI middleware for IP check (simpler, no Nginx config reload needed)

### Auth
- JWT tokens (access + refresh)
- Passwords hashed with bcrypt
- HTTPS optional locally (can use self-signed cert via Nginx)

---

## Docker Compose Layout

```
docker-compose.yml
services:
  nginx        → port 80/443, IP whitelist, reverse proxy
  frontend     → React build served by Nginx (internal)
  backend      → FastAPI on port 8000 (internal)
  postgres     → port 5432 (internal)
  redis        → port 6379 (internal)
```

All services on an internal Docker network. Only Nginx exposed externally.

---

## Project Folder Structure

```
app/
├── backend/
│   ├── app/
│   │   ├── api/          — route handlers
│   │   ├── core/         — config, auth, middleware
│   │   ├── models/       — SQLAlchemy models
│   │   ├── schemas/      — Pydantic schemas
│   │   ├── services/     — business logic
│   │   └── websockets/   — socket handlers
│   ├── alembic/          — migrations
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   ├── store/        — Zustand stores
│   │   └── api/          — Axios clients
│   ├── Dockerfile
│   └── package.json
├── nginx/
│   ├── nginx.conf
│   └── ip_whitelist.conf
└── docker-compose.yml
```

---

## Build Order (Recommended)

1. ✅ Folder structure created
2. ⬜ Docker Compose skeleton + Postgres + Redis running
3. ⬜ Backend: auth (register/login/JWT)
4. ⬜ Backend: relationship spaces + pairing
5. ⬜ Backend: issue CRUD
6. ⬜ Backend: WebSocket for general chat
7. ⬜ Backend: WebSocket for issue threads
8. ⬜ Frontend: auth screens
9. ⬜ Frontend: general chat UI
10. ⬜ Frontend: issue dashboard + thread UI
11. ⬜ IP whitelist middleware
12. ⬜ Polish + mobile responsiveness
13. ⬜ (Optional) AI mediation via Claude API in issue threads

---

## Estimated Complexity

| Area | Effort |
|---|---|
| Backend API + Auth | Medium |
| WebSocket real-time chat | Medium |
| Issue tracker logic | Low–Medium |
| Frontend UI | Medium–High |
| Docker setup | Low |
| IP whitelisting | Low |
| AI mediation (optional) | Low (API call) |
