"""FR-24: claims endpoint + consistency_score in hotspot payloads."""
import pytest
from fastapi.testclient import TestClient

from api.app import app

client = TestClient(app)


def _auth_headers():
    r = client.post("/auth/login", json={"username": "analyst", "password": "analyst"})
    if r.status_code != 200:
        pytest.skip("default analyst credentials unavailable")
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_claims_404_on_unknown_hotspot():
    r = client.get("/hotspots/999999999/claims", headers=_auth_headers())
    assert r.status_code == 404


def test_claims_requires_auth():
    assert client.get("/hotspots/1/claims").status_code in (401, 403)


def test_fetch_hotspot_claims_shape(live_conn):
    from api.queries import fetch_hotspot_claims

    with live_conn.cursor() as cur:
        cur.execute(
            """INSERT INTO hotspots (centroid_geom, radius_km, start_window,
                   end_window, event_count, unique_sources, consistency_score)
               VALUES (ST_SetSRID(ST_MakePoint(34.45, 31.5), 4326), 5.0,
                       now(), now(), 1, 1, 62.5)
               RETURNING hotspot_id"""
        )
        hid = cur.fetchone()[0]
        cur.execute("SELECT register_source(%s, %s)", ("https://m6api.example/a", None))
        source_id = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO events (source_system, external_event_id, event_date,
                   cameo_code, url, title, source_id, point_geom)
               VALUES ('ACLED', 'M6-API-1', now(), 'armed_conflict',
                       'https://m6api.example/a', 'seed', %s,
                       ST_SetSRID(ST_MakePoint(34.45, 31.5), 4326))
               RETURNING event_id""",
            (source_id,),
        )
        event_id = cur.fetchone()[0]
        cur.execute("INSERT INTO event_hotspot (event_id, hotspot_id) VALUES (%s, %s)",
                    (event_id, hid))
        cur.execute(
            """INSERT INTO claims (hotspot_id, claim_text, status, consensus_weight)
               VALUES (%s, 'Test claim.', 'uncorroborated', 0.4) RETURNING claim_id""",
            (hid,),
        )
        claim_id = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO claim_evidence (claim_id, event_id, relation, probability)
               VALUES (%s, %s, 'supports', 0.9)""",
            (claim_id, event_id),
        )

    payload = fetch_hotspot_claims(live_conn, hid)
    assert payload is not None
    assert payload["insufficient_sources"] is True  # single domain
    assert len(payload["claims"]) == 1
    claim = payload["claims"][0]
    assert claim["claim_text"] == "Test claim."
    assert claim["status"] == "uncorroborated"
    assert claim["evidence"][0]["citation_index"] == 1
    assert claim["evidence"][0]["relation"] == "supports"


def test_fetch_hotspot_claims_none_for_unknown(live_conn):
    from api.queries import fetch_hotspot_claims
    assert fetch_hotspot_claims(live_conn, 999999999) is None
