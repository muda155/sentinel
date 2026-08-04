from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import create_token, verify_password
from api.ratelimit import limit_auth
from api.schemas import LoginResponse
from pipeline.db import get_pooled_connection

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/auth/login", response_model=LoginResponse)
def login(body: LoginRequest, _rate_limit: None = Depends(limit_auth)):
    conn, pool = get_pooled_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT password_hash, role FROM users WHERE username=%s", (body.username,))
            row = cur.fetchone()
    finally:
        pool.return_connection(conn)
    if not row or not verify_password(body.password, row[0]):
        raise HTTPException(status_code=401, detail="invalid credentials")
    return LoginResponse(access_token=create_token(username=body.username, role=row[1]), role=row[1])
