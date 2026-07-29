# Auth fixes — remaining issues

Three things left to fix from the review. Do them in this order.

## 1. `app/models/response.py` — add `email` to `UserLogin`

Login is looking up the user by email, but `UserLogin` never collects one. Add it:

```python
class UserLogin(BaseModel):
    email: EmailStr
    password: str
```

(You can drop `username` from this schema, or keep it if you also want to support username login later — but right now nothing uses it.)

Add the `EmailStr` import if not already there (it already is, from `UserCreate`).

## 2. `app/routers/user.py` — fix the login error response

Line 28 currently does:

```python
except ValueError as e:
    return HTTPException(
        status_code=401,
        detail=str(e)
    )
```

`return` just serializes the `HTTPException` object as a normal 200 response body. Change `return` to `raise`:

```python
except ValueError as e:
    raise HTTPException(
        status_code=401,
        detail=str(e)
    )
```

## 3. `app/routers/user.py` — return the register result

Line 14 currently discards the result:

```python
try:
    await create_user(db, user)
except ValueError as e:
    ...
```

Capture and return it so the client gets the success message:

```python
try:
    result = await create_user(db, user)
    return result
except ValueError as e:
    ...
```

## Optional cleanup

`app/routers/auth.py` is a stub (one unused import, no router) and isn't included in `main.py`. Either flesh it out or delete it — it's currently just dead code.

## After making these changes

Restart via Docker Compose and hit both endpoints to confirm:

```
docker compose up -d --build
docker compose exec backend curl -X POST http://localhost:8080/register -H "Content-Type: application/json" -d '{"username":"test","email":"test@example.com","password":"secret123"}'
docker compose exec backend curl -X POST http://localhost:8080/login -H "Content-Type: application/json" -d '{"email":"test@example.com","password":"secret123"}'
```

Expect: register → `{"message": "user created successfuly"}`; login → `{"access_token": "..."}`.
Try a wrong password too — expect a `401`, not a `200`.
