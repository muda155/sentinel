import os

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.auth import create_token

pytestmark = pytest.mark.skipif(
    not os.getenv("SENTINEL_TEST_DB"), reason="needs live PostGIS via SENTINEL_TEST_DB"
)

_AUTH = {"Authorization": f"Bearer {create_token(username='test', role='analyst')}"}


def test_events_returns_geojson():
    client = TestClient(create_app())
    r = client.get("/events", params={
        "sw_lat": -90, "sw_lon": -180, "ne_lat": 90, "ne_lon": 180,
        "start": "2000-01-01T00:00:00Z", "end": "2100-01-01T00:00:00Z",
        "page_size": 10,
    }, headers=_AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "FeatureCollection"
    assert isinstance(body["features"], list)
    if body["features"]:
        assert body["features"][0]["geometry"]["type"] == "Point"
