import os

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.auth import (
    create_token,
    decode_token,
    hash_password,
    seed_default_users,
    verify_password,
)


def test_password_hash_roundtrip():
    h = hash_password("s3cret")
    assert h != "s3cret"
    assert verify_password("s3cret", h)
    assert not verify_password("wrong", h)


def test_token_roundtrip_carries_role():
    tok = create_token(username="alice", role="admin")
    claims = decode_token(tok)
    assert claims["sub"] == "alice"
    assert claims["role"] == "admin"


def test_decode_rejects_tampered_token():
    tok = create_token(username="bob", role="analyst")
    with pytest.raises(Exception):
        decode_token(tok + "tamper")


def test_login_returns_token():
    if not os.getenv("SENTINEL_TEST_DB"):
        pytest.skip("needs live DB")
    from pipeline.db import get_pooled_connection
    conn, pool = get_pooled_connection()
    try:
        seed_default_users(conn)
    finally:
        pool.return_connection(conn)
    c = TestClient(create_app())
    r = c.post("/auth/login", json={"username": "admin", "password": "admin"})
    assert r.status_code == 200 and r.json()["role"] == "admin"
    assert c.post("/auth/login", json={"username": "admin", "password": "no"}).status_code == 401
