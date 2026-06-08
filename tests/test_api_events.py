import os
import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(
    not os.getenv("SENTINEL_TEST_DB"), reason="needs live PostGIS via SENTINEL_TEST_DB"
)
from api.app import create_app


def test_events_returns_geojson():
    client = TestClient(create_app())
    r = client.get("/events", params={
        "sw_lat": -90, "sw_lon": -180, "ne_lat": 90, "ne_lon": 180,
        "start": "2000-01-01T00:00:00Z", "end": "2100-01-01T00:00:00Z",
        "page_size": 10,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "FeatureCollection"
    assert isinstance(body["features"], list)
    if body["features"]:
        assert body["features"][0]["geometry"]["type"] == "Point"
