import os

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.auth import create_token

pytestmark = pytest.mark.skipif(
    not os.getenv("SENTINEL_TEST_DB"), reason="needs live PostGIS via SENTINEL_TEST_DB"
)

_AUTH = {"Authorization": f"Bearer {create_token(username='test', role='analyst')}"}


def test_hotspots_endpoint_shape():
    client = TestClient(create_app())
    r = client.get("/hotspots?limit=5", headers=_AUTH)
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    if body:
        h = body[0]
        assert set(h) >= {"hotspot_id", "lat", "lon", "conf_score",
                          "convergence_score", "alert_level", "event_count"}


def test_hotspots_include_name_field():
    client = TestClient(create_app())
    r = client.get("/hotspots?limit=5", headers=_AUTH)
    assert r.status_code == 200
    for h in r.json():
        assert "name" in h  # may be None for unbackfilled rows


def test_health():
    client = TestClient(create_app())
    assert client.get("/health").json() == {"status": "ok"}
