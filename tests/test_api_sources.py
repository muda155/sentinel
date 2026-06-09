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
