from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator

from api import queries
from api.auth import create_token, hash_password, require_role, verify_password
from api.ratelimit import limit_auth
from api.schemas import LoginResponse, UserRow
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


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    # bcrypt truncates at 72 BYTES. A longer password would authenticate
    # against its own first 72 bytes, which is not the string the admin typed.
    password: str = Field(min_length=8, max_length=72)
    role: Literal["analyst", "admin"] = "analyst"

    @field_validator("password")
    @classmethod
    def _fits_bcrypt(cls, v: str) -> str:
        if len(v.encode()) > 72:
            raise ValueError("password must be at most 72 bytes")
        return v

    @field_validator("username")
    @classmethod
    def _no_whitespace(cls, v: str) -> str:
        stripped = v.strip()
        if stripped != v or not stripped:
            raise ValueError("username must not have leading or trailing whitespace")
        return stripped


@router.get("/auth/users", response_model=list[UserRow])
def list_users(_admin: dict = Depends(require_role("admin"))):
    conn, pool = get_pooled_connection()
    try:
        return queries.fetch_users(conn)
    finally:
        pool.return_connection(conn)


@router.post("/auth/users", response_model=UserRow, status_code=201)
def create_user(body: CreateUserRequest, _admin: dict = Depends(require_role("admin"))):
    conn, pool = get_pooled_connection()
    try:
        row = queries.insert_user(
            conn,
            username=body.username,
            password_hash=hash_password(body.password),
            role=body.role,
        )
    finally:
        pool.return_connection(conn)
    if row is None:
        raise HTTPException(status_code=409, detail="username already exists")
    return row


@router.delete("/auth/users/{user_id}", status_code=204)
def remove_user(user_id: int, admin: dict = Depends(require_role("admin"))):
    conn, pool = get_pooled_connection()
    try:
        target = queries.fetch_user_by_id(conn, user_id)
        if target is None:
            raise HTTPException(status_code=404, detail="user not found")
        if target["username"] == admin.get("sub"):
            raise HTTPException(status_code=400, detail="cannot delete your own account")
        if not queries.delete_user(conn, user_id):
            # rowcount 0 means either the row vanished between the fetch above
            # and this delete, or the last-admin guard blocked it — re-fetch to
            # tell them apart (a vanished row is a 404, not a last-admin 400).
            if queries.fetch_user_by_id(conn, user_id) is None:
                raise HTTPException(status_code=404, detail="user not found")
            raise HTTPException(status_code=400, detail="cannot delete the last admin")
    finally:
        pool.return_connection(conn)
    return Response(status_code=204)
