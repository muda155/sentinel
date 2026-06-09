import os

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.auth import create_token

pytestmark = pytest.mark.skipif(
    not os.getenv("SENTINEL_TEST_DB"),
    reason="needs live PostGIS via SENTINEL_TEST_DB",
)

_AUTH = {"Authorization": f"Bearer {create_token(username='test', role='analyst')}"}


def test_grid_cells_shape():
    r = TestClient(create_app()).get("/grid_cells?min_convergence=0", headers=_AUTH)
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    if body:
        assert set(body[0]) >= {
            "cell_id",
            "lat",
            "lon",
            "convergence_score",
            "alert_level",
        }
