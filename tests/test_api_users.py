import os
import uuid

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.auth import create_token

pytestmark = pytest.mark.skipif(
    not os.getenv("SENTINEL_TEST_DB"), reason="needs live DB"
)


def _auth(role="admin", username="admin"):
    return {"Authorization": f"Bearer {create_token(username=username, role=role)}"}


def _cleanup(username):
    from pipeline.db import get_pooled_connection

    conn, pool = get_pooled_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE username = %s", (username,))
        conn.commit()
    finally:
        pool.return_connection(conn)


def test_analyst_cannot_list_users():
    c = TestClient(create_app())
    assert c.get("/auth/users", headers=_auth("analyst")).status_code == 403


def test_analyst_cannot_create_users():
    c = TestClient(create_app())
    r = c.post("/auth/users", json={"username": "x", "password": "password123", "role": "admin"},
               headers=_auth("analyst"))
    assert r.status_code == 403


def test_unauthenticated_cannot_create_users():
    """No public signup: this is the whole product decision, asserted."""
    c = TestClient(create_app())
    r = c.post("/auth/users", json={"username": "x", "password": "password123", "role": "admin"})
    assert r.status_code == 401


def test_user_list_never_leaks_password_hashes():
    c = TestClient(create_app())
    r = c.get("/auth/users", headers=_auth())
    assert r.status_code == 200
    for u in r.json():
        assert "password_hash" not in u
        assert set(u) == {"user_id", "username", "role", "created_at"}


def test_create_then_login_then_delete():
    name = f"pytest_{uuid.uuid4().hex[:8]}"
    c = TestClient(create_app())
    try:
        r = c.post("/auth/users",
                   json={"username": name, "password": "correct horse battery", "role": "analyst"},
                   headers=_auth())
        assert r.status_code == 201, r.text
        assert r.json()["username"] == name
        assert r.json()["role"] == "analyst"

        login = c.post("/auth/login", json={"username": name, "password": "correct horse battery"})
        assert login.status_code == 200
        assert login.json()["role"] == "analyst"

        uid = r.json()["user_id"]
        assert c.delete(f"/auth/users/{uid}", headers=_auth()).status_code == 204
        assert c.post("/auth/login",
                      json={"username": name, "password": "correct horse battery"}).status_code == 401
    finally:
        _cleanup(name)


def test_duplicate_username_is_409_not_500():
    name = f"pytest_{uuid.uuid4().hex[:8]}"
    c = TestClient(create_app())
    try:
        body = {"username": name, "password": "password123", "role": "analyst"}
        assert c.post("/auth/users", json=body, headers=_auth()).status_code == 201
        assert c.post("/auth/users", json=body, headers=_auth()).status_code == 409
    finally:
        _cleanup(name)


def test_rejects_a_role_outside_the_check_constraint():
    c = TestClient(create_app())
    r = c.post("/auth/users", json={"username": "x", "password": "password123", "role": "viewer"},
               headers=_auth())
    assert r.status_code == 422


def test_rejects_a_password_over_bcrypt_72_byte_limit():
    """bcrypt silently truncates at 72 bytes — a 100-char password would
    authenticate against its own first 72, which is not what the user typed."""
    c = TestClient(create_app())
    r = c.post("/auth/users", json={"username": "x", "password": "a" * 100, "role": "analyst"},
               headers=_auth())
    assert r.status_code == 422


def test_rejects_a_short_password():
    c = TestClient(create_app())
    r = c.post("/auth/users", json={"username": "x", "password": "abc", "role": "analyst"},
               headers=_auth())
    assert r.status_code == 422


def test_cannot_delete_yourself():
    c = TestClient(create_app())
    users = c.get("/auth/users", headers=_auth()).json()
    me = next((u for u in users if u["username"] == "admin"), None)
    if me is None:
        pytest.skip("default admin not seeded")
    r = c.delete(f"/auth/users/{me['user_id']}", headers=_auth(username="admin"))
    assert r.status_code == 400


def test_cannot_delete_the_last_admin():
    """Deleting the only admin would lock everyone out of this very screen."""
    name = f"pytest_{uuid.uuid4().hex[:8]}"
    c = TestClient(create_app())
    try:
        created = c.post("/auth/users",
                         json={"username": name, "password": "password123", "role": "admin"},
                         headers=_auth()).json()
        users = c.get("/auth/users", headers=_auth()).json()
        admins = [u for u in users if u["role"] == "admin"]
        # Delete every admin except the newly created one, acting as that one.
        for u in admins:
            if u["user_id"] == created["user_id"]:
                continue
            c.delete(f"/auth/users/{u['user_id']}", headers=_auth(username=name))
        remaining = [u for u in c.get("/auth/users", headers=_auth(username=name)).json()
                     if u["role"] == "admin"]
        if len(remaining) != 1:
            pytest.skip("could not reduce to a single admin in this environment")
        r = c.delete(f"/auth/users/{created['user_id']}", headers=_auth(username=name))
        assert r.status_code == 400
    finally:
        _cleanup(name)
