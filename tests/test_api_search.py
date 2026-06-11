import os

import pytest

from api.queries import fetch_search


class _NeverCursor:
    def execute(self, *a, **k):
        raise AssertionError("short queries must not hit the DB")
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


class _NeverConn:
    def cursor(self):
        return _NeverCursor()


@pytest.mark.parametrize("q", ["", "a", " x "])
def test_short_query_returns_empty_groups_without_db(q):
    assert fetch_search(_NeverConn(), q) == {"hotspots": [], "events": [], "sources": []}


pytest_live = pytest.mark.skipif(
    not os.getenv("SENTINEL_TEST_DB"), reason="needs live PostGIS via SENTINEL_TEST_DB"
)


@pytest_live
def test_search_endpoint_groups_and_auth():
    from fastapi.testclient import TestClient
    from api.app import create_app
    from api.auth import create_token

    client = TestClient(create_app())
    assert client.get("/search?q=ukraine").status_code in (401, 403)
    auth = {"Authorization": f"Bearer {create_token(username='test', role='analyst')}"}
    r = client.get("/search?q=ukraine", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"hotspots", "events", "sources"}
    for h in body["hotspots"]:
        assert set(h) >= {"hotspot_id", "name", "lat", "lon", "conf_score",
                          "convergence_score", "alert_level", "event_count"}
    for e in body["events"]:
        assert set(e) >= {"event_id", "title", "url", "domain", "event_date", "hotspot"}
    for s in body["sources"]:
        assert set(s) >= {"source_id", "domain", "trust_tier", "hotspots"}


@pytest_live
def test_search_common_domain_returns_200():
    """Regression: q=com must not 500 — trust_tier is text 'A','B','C', not int."""
    from fastapi.testclient import TestClient
    from api.app import create_app
    from api.auth import create_token

    auth = {"Authorization": f"Bearer {create_token(username='test', role='analyst')}"}
    client = TestClient(create_app())
    r = client.get("/search?q=com", headers=auth)
    assert r.status_code == 200
    for s in r.json()["sources"]:
        assert isinstance(s["trust_tier"], (str, type(None)))
