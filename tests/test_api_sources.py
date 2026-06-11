import os

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.auth import create_token

pytestmark = pytest.mark.skipif(
    not os.getenv("SENTINEL_TEST_DB"), reason="needs live DB"
)


def test_analyst_cannot_patch_trust_tier():
    c = TestClient(create_app())
    tok = create_token(username="analyst", role="analyst")
    r = c.patch("/sources/1", json={"trust_tier": 1}, headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 403


def test_unauth_hotspots_rejected():
    assert TestClient(create_app()).get("/hotspots").status_code == 401


def _auth(role="analyst"):
    return {"Authorization": f"Bearer {create_token(username='t', role=role)}"}


def test_sources_endpoint_returns_int_tiers():
    """Spec 6.2: trust_tier is int 1-4 (1=wire ... 4=unknown), not text."""
    r = TestClient(create_app()).get("/sources", headers=_auth())
    assert r.status_code == 200
    for s in r.json():
        assert s["trust_tier"] is None or (
            isinstance(s["trust_tier"], int) and 1 <= s["trust_tier"] <= 4
        )


def test_patch_trust_tier_roundtrip_updates_generated_score():
    """Spec 6.2: trust_score is GENERATED from trust_tier (2 -> 0.8)."""
    from pipeline.db import get_pooled_connection

    c = TestClient(create_app())
    sources = c.get("/sources", headers=_auth()).json()
    if not sources:
        pytest.skip("no sources seeded")
    sid = sources[0]["source_id"]

    r = c.patch(f"/sources/{sid}", json={"trust_tier": 2}, headers=_auth("admin"))
    assert r.status_code == 200
    assert r.json() == {"source_id": sid, "trust_tier": 2}

    conn, pool = get_pooled_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT trust_tier, trust_score FROM sources WHERE source_id = %s",
                (sid,),
            )
            tier, score = cur.fetchone()
    finally:
        pool.return_connection(conn)
    assert tier == 2
    assert score == pytest.approx(0.8)
