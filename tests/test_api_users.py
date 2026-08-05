import os
import threading
import uuid

import psycopg2
import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.auth import create_token, hash_password
from pipeline.db import get_pooled_connection

pytestmark = pytest.mark.skipif(
    not os.getenv("SENTINEL_TEST_DB"), reason="needs live DB"
)


def _auth(role="admin", username="admin"):
    return {"Authorization": f"Bearer {create_token(username=username, role=role)}"}


def _cleanup(username):
    conn, pool = get_pooled_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE username = %s", (username,))
        conn.commit()
    finally:
        pool.return_connection(conn)


def _count_admins() -> int:
    conn, pool = get_pooled_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM users WHERE role = 'admin'")
            return int(cur.fetchone()[0])
    finally:
        pool.return_connection(conn)


def _snapshot_admins() -> list[tuple]:
    """(username, role, password_hash) for every admin — used to restore rows a
    last-admin test deletes, so the seeded `admin` login survives the run."""
    conn, pool = get_pooled_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT username, role, password_hash FROM users WHERE role = 'admin'")
            return cur.fetchall()
    finally:
        pool.return_connection(conn)


def _restore_admins(snapshot) -> None:
    """Re-insert any snapshot admins missing from the current table, with their
    original password_hash so credentials keep working."""
    conn, pool = get_pooled_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT username FROM users WHERE role = 'admin'")
            existing = {r[0] for r in cur.fetchall()}
            for username, role, pw_hash in snapshot:
                if username not in existing:
                    cur.execute(
                        "INSERT INTO users (username, role, password_hash) VALUES (%s, %s, %s) "
                        "ON CONFLICT (username) DO NOTHING",
                        (username, role, pw_hash),
                    )
        conn.commit()
    finally:
        pool.return_connection(conn)


def _raw_dsn() -> str:
    """A libpq DSN from SENTINEL_TEST_DB when it is a DSN, else the pool env."""
    dsn = os.getenv("SENTINEL_TEST_DB", "")
    if "=" in dsn:
        return dsn
    return (
        f"host={os.getenv('PGHOST', '127.0.0.1')} "
        f"port={os.getenv('PGPORT', '6432')} "
        f"dbname={os.getenv('PGDATABASE', 'sentinel')} "
        f"user={os.getenv('PGUSER', 'sentinel_user')} "
        f"password={os.getenv('PGPASSWORD', 'sentinel_pass')}"
    )


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
    """Deleting the only admin would lock everyone out of this very screen.

    Restores every admin the test deletes (this test removes all but one),
    so the seeded `admin` login survives the run."""
    name = f"pytest_{uuid.uuid4().hex[:8]}"
    c = TestClient(create_app())
    snapshot = _snapshot_admins()
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
        _restore_admins(snapshot)


def test_last_admin_guard_holds_under_concurrent_deletes():
    """The last-admin guard must hold under true write skew.

    Two deletes of *different* admin rows whose count subqueries both evaluate
    before either commits. Starlette's TestClient serializes every request
    through one portal, so the old ThreadPoolExecutor test could never fail:
    each DELETE committed before the next began. This drives two raw psycopg2
    connections synchronized on a barrier so the statements genuinely overlap.
    """
    from api import queries

    name_a = f"pytest_{uuid.uuid4().hex[:8]}"
    name_b = f"pytest_{uuid.uuid4().hex[:8]}"
    snapshot = _snapshot_admins()
    conn, pool = get_pooled_connection()
    id_a = id_b = None
    try:
        with conn.cursor() as cur:
            for nm in (name_a, name_b):
                cur.execute(
                    "INSERT INTO users (username, role, password_hash) VALUES (%s, 'admin', %s)",
                    (nm, hash_password("pytest-race")),
                )
            # Reduce the admin set to exactly {a, b} so the race is about the
            # last admin; _restore_admins re-adds everything deleted here.
            cur.execute(
                "DELETE FROM users WHERE role = 'admin' AND username NOT IN (%s, %s)",
                (name_a, name_b),
            )
            cur.execute("SELECT user_id FROM users WHERE username IN (%s, %s) ORDER BY 1",
                        (name_a, name_b))
            id_a, id_b = [r[0] for r in cur.fetchall()]
        conn.commit()
    finally:
        pool.return_connection(conn)

    try:
        barrier = threading.Barrier(2)
        rowcounts: dict[str, int] = {}

        def run(label: str, target_id: int) -> None:
            c2 = psycopg2.connect(_raw_dsn())
            try:
                with c2.cursor() as cur:
                    barrier.wait(timeout=15)  # both threads issue together
                    cur.execute(queries.DELETE_USER_SQL, (target_id,))
                    rowcounts[label] = cur.rowcount
                    # Hold the transaction open so the other thread's count
                    # subquery evaluates against the same 2-admin snapshot —
                    # this is what makes the write skew reproducible.
                    cur.execute("SELECT pg_sleep(0.2)")
                    c2.commit()
            finally:
                c2.close()

        t_a = threading.Thread(target=run, args=("a", id_b))
        t_b = threading.Thread(target=run, args=("b", id_a))
        t_a.start()
        t_b.start()
        t_a.join()
        t_b.join()

        assert 0 in rowcounts.values(), (
            f"write skew: both deletes succeeded {rowcounts} — guard did not hold"
        )
        assert _count_admins() == 1, f"expected 1 admin to remain, got {_count_admins()}"
    finally:
        _cleanup(name_a)
        _cleanup(name_b)
        _restore_admins(snapshot)


def test_delete_vanished_user_is_404(monkeypatch):
    """The route returns 404, not a misleading last-admin 400, when the target
    vanishes *between* its fetch and its delete.

    TestClient serializes requests, so a real concurrent delete cannot land in
    that window. Instead the test intercepts `queries.delete_user`: the wrapper
    deletes the row on a second connection and then delegates to the real
    delete (which now sees rowcount 0). The `calls` counter asserts the wrapper
    actually ran — a test credited with covering this branch must prove the
    branch executed, not just that the end state looks right.
    """
    from api import queries

    name = f"pytest_{uuid.uuid4().hex[:8]}"
    c = TestClient(create_app())
    try:
        created = c.post("/auth/users",
                         json={"username": name, "password": "password123", "role": "analyst"},
                         headers=_auth()).json()
        uid = created["user_id"]
        real_delete = queries.delete_user
        calls = {"delete_user": 0}

        def vanish_before_delete(conn, user_id):
            calls["delete_user"] += 1
            c2 = psycopg2.connect(_raw_dsn())
            try:
                with c2.cursor() as cur:
                    cur.execute("DELETE FROM users WHERE user_id = %s", (user_id,))
                c2.commit()
            finally:
                c2.close()
            return real_delete(conn, user_id)

        monkeypatch.setattr(queries, "delete_user", vanish_before_delete)

        r = c.delete(f"/auth/users/{uid}", headers=_auth())
        assert calls["delete_user"] == 1, (
            "route never reached delete_user — the vanished-row branch did not execute"
        )
        assert r.status_code == 404
    finally:
        _cleanup(name)


def test_delete_user_returns_false_for_a_row_that_vanished_concurrently():
    """delete_user returns False for a target deleted between the route's fetch
    and its delete; the route re-fetches to map that to 404, not 400."""
    from api import queries

    name = f"pytest_{uuid.uuid4().hex[:8]}"
    c = TestClient(create_app())
    try:
        created = c.post("/auth/users",
                         json={"username": name, "password": "password123", "role": "analyst"},
                         headers=_auth()).json()
        uid = created["user_id"]
        conn, pool = get_pooled_connection()
        try:
            # the route has already fetched the row...
            assert queries.fetch_user_by_id(conn, uid) is not None
            # ...a concurrent actor deletes it on another connection...
            c2 = psycopg2.connect(_raw_dsn())
            try:
                with c2.cursor() as cur:
                    cur.execute("DELETE FROM users WHERE user_id = %s", (uid,))
                c2.commit()
            finally:
                c2.close()
            # ...so delete_user returns False and the re-fetch finds nothing,
            # which is how the route decides 404 vs 400.
            assert queries.delete_user(conn, uid) is False
            assert queries.fetch_user_by_id(conn, uid) is None
        finally:
            pool.return_connection(conn)
    finally:
        _cleanup(name)
