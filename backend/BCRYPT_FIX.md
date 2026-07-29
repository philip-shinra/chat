# Fix — "password cannot be longer than 72 bytes" on register

## Root cause

`passlib` 1.7.4 (unmaintained since 2020) detects the installed `bcrypt`
version to decide whether *it* needs to truncate passwords to 72 bytes before
hashing. `bcrypt` 4.1+ removed the attribute passlib used for that detection,
so passlib silently skips its own truncation step and forwards the raw
password straight to `bcrypt.hashpw()` — which now raises instead of quietly
truncating like older `bcrypt` did.

Installed in this project's venv: `passlib==1.7.4`, `bcrypt==5.0.0` — the
exact broken combo.

## Fix — pin `bcrypt` to a version passlib understands

**`backend/requirements.txt`** — change:
```
passlib[bcrypt]
```
to:
```
passlib[bcrypt]
bcrypt==4.0.1
```
(`bcrypt==4.0.1` is the last release before the attribute passlib relies on
was removed.)

## Apply it

```bash
docker compose build api migrate
docker compose up -d
```

Rebuild is required (not just restart) since `requirements.txt` changed and
gets installed at image build time.

## Verify

```bash
docker compose exec api curl -X POST http://localhost:8080/register \
  -H "Content-Type: application/json" \
  -d '{"username":"test2","email":"test2@example.com","password":"secret123"}'
```

Expect `{"message": "user created"}`, not a 400.

## Longer-term note

`passlib` itself hasn't been released since 2020 and has no fix planned for
this. Pinning `bcrypt` back is a stopgap. If this keeps causing friction,
consider dropping `passlib` and calling `bcrypt.hashpw()` /
`bcrypt.checkpw()` directly in `user_service.py` — it's the actively
maintained library and removes the version-detection problem entirely.
