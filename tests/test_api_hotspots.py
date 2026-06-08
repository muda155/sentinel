import os
import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(
    not os.getenv("SENTINEL_TEST_DB"), reason="needs live PostGIS via SENTINEL_TEST_DB"
)
from api.app import create_app


def test_hotspots_endpoint_shape():
    client = TestClient(create_app())
    r = client.get("/hotspots?limit=5")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    if body:
        h = body[0]
        assert set(h) >= {"hotspot_id", "lat", "lon", "conf_score",
                          "convergence_score", "alert_level", "event_count"}


def test_health():
    client = TestClient(create_app())
    assert client.get("/health").json() == {"status": "ok"}
