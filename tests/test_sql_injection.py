import os

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.auth import create_token


def _client():
    return TestClient(create_app())


@pytest.mark.skipif(not os.getenv("SENTINEL_TEST_DB"), reason="needs live DB")
def test_injection_in_alert_level_is_parameterized():
    tok = create_token(username="a", role="analyst")
    r = _client().get("/hotspots?alert_level=High';DROP TABLE hotspots;--",
                      headers={"Authorization": f"Bearer {tok}"})
    # Parameterized query => no 500, table intact (next call still works).
    assert r.status_code in (200, 422)
    r2 = _client().get("/hotspots", headers={"Authorization": f"Bearer {tok}"})
    assert r2.status_code == 200


def test_auth_bypass_attempts_rejected():
    c = _client()
    assert c.get("/hotspots").status_code == 401
    assert c.get("/hotspots", headers={"Authorization": "Bearer not.a.jwt"}).status_code == 401
    assert c.patch("/sources/1", json={"trust_tier": 1}).status_code == 401
