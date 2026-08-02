import os
from datetime import datetime, timedelta, timezone

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


def test_hotspots_include_timestamps():
    client = TestClient(create_app())
    r = client.get("/hotspots?limit=5", headers=_AUTH)
    assert r.status_code == 200
    for h in r.json():
        assert "end_window" in h
        assert "created_at" in h


def test_hotspots_excludes_rows_older_than_max_age():
    client = TestClient(create_app())
    r = client.get("/hotspots?limit=200&min_conf=0&max_age_hours=24", headers=_AUTH)
    assert r.status_code == 200
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    for h in r.json():
        assert datetime.fromisoformat(h["end_window"]) >= cutoff


def test_hotspot_payload_includes_start_window(live_conn):
    """start_window is in the hotspots table but was never selected, so the
    UI could not show how long a hotspot has been active."""
    from api import queries

    with live_conn.cursor() as cur:
        cur.execute(
            """INSERT INTO hotspots (centroid_geom, radius_km, start_window,
                   end_window, event_count, unique_sources)
               VALUES (ST_SetSRID(ST_MakePoint(34.45, 31.5), 4326), 5.0,
                       now(), now(), 1, 1)
               RETURNING hotspot_id"""
        )
        hid = cur.fetchone()[0]

    listed = [h for h in queries.fetch_hotspots(live_conn, limit=200, max_age_hours=None)
              if h["hotspot_id"] == hid]
    assert listed, "inserted hotspot not returned by fetch_hotspots"
    assert "start_window" in listed[0]

    single = queries.fetch_hotspot_by_id(live_conn, hid)
    assert single is not None
    assert "start_window" in single
