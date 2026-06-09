import os
import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(
    not os.getenv("SENTINEL_TEST_DB"),
    reason="needs live PostGIS via SENTINEL_TEST_DB",
)

from api.app import create_app


def test_grid_cells_shape():
    r = TestClient(create_app()).get("/grid_cells?min_convergence=0")
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
