"""JWT issue/verify + password hashing + FastAPI auth dependencies (NFR-5)."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request


_DEFAULT_SECRET = "change_me_in_production_32_bytes__xxxx!"


def _secret() -> str:
    secret = os.getenv("SENTINEL_JWT_SECRET", _DEFAULT_SECRET)
    if os.getenv("SENTINEL_ENV") == "production" and secret == _DEFAULT_SECRET:
        raise RuntimeError(
            "SENTINEL_JWT_SECRET must be overridden in production — "
            "inject via secrets manager, never use the default."
        )
    return secret


def _alg() -> str:
    return os.getenv("SENTINEL_JWT_ALG", "HS256")


def hash_password(raw: str) -> str:
    return bcrypt.hashpw(raw.encode(), bcrypt.gensalt()).decode()


def verify_password(raw: str, hashed: str) -> bool:
    return bcrypt.checkpw(raw.encode(), hashed.encode())


def create_token(*, username: str, role: str) -> str:
    ttl = int(os.getenv("SENTINEL_JWT_TTL_MIN", "720"))
    payload = {
        "sub": username,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=ttl),
    }
    return jwt.encode(payload, _secret(), algorithm=_alg())


def decode_token(token: str) -> dict:
    return jwt.decode(token, _secret(), algorithms=[_alg()])


def _token_from_request(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return request.query_params.get("token")


def get_current_user(request: Request) -> dict:
    token = _token_from_request(request)
    if not token:
        raise HTTPException(status_code=401, detail="missing bearer token")
    try:
        return decode_token(token)
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="invalid token")


def require_role(role: str):
    def _dep(user: dict = Depends(get_current_user)) -> dict:
        if user.get("role") != role:
            raise HTTPException(status_code=403, detail=f"requires {role} role")
        return user
    return _dep


def seed_default_users(conn) -> None:
    rows = [("admin", "admin", "admin"), ("analyst", "analyst", "analyst")]
    with conn.cursor() as cur:
        for username, pw, role in rows:
            cur.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (%s,%s,%s) "
                "ON CONFLICT (username) DO NOTHING",
                (username, hash_password(pw), role),
            )
    conn.commit()
