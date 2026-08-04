import os

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.auth import create_token

pytestmark = pytest.mark.skipif(
    not os.getenv("SENTINEL_TEST_DB"), reason="needs live DB"
)


def _auth(role="analyst"):
    return {"Authorization": f"Bearer {create_token(username='t', role=role)}"}


def test_hotspots_carry_conf_score_inputs():
    """FR-7/FR-8: the panel must be able to show WHY conf_score is what it is."""
    r = TestClient(create_app()).get("/hotspots", headers=_auth())
    assert r.status_code == 200
    rows = r.json()
    if not rows:
        pytest.skip("no hotspots seeded")
    for h in rows:
        assert "source_density" in h
        assert "geopolitical_diversity" in h
        for key in ("source_density", "geopolitical_diversity"):
            assert h[key] is None or 0.0 <= h[key] <= 1.0


def test_hotspots_carry_convergence_inputs():
    r = TestClient(create_app()).get("/hotspots", headers=_auth())
    rows = r.json()
    if not rows:
        pytest.skip("no hotspots seeded")
    for h in rows:
        assert isinstance(h["convergence_types"], int)
        assert isinstance(h["convergence_events"], int)
        assert h["convergence_types"] >= 0
        assert h["convergence_events"] >= 0


def test_convergence_inputs_reconstruct_the_published_score():
    """The two inputs must come from the SAME row the score came from.

    convergence_score COALESCEs grid_cells -> hotspots. If the inputs did not
    follow the same chain, the panel would draw a bar that does not add up to
    the number printed above it.
    """
    r = TestClient(create_app()).get("/hotspots", headers=_auth())
    rows = r.json()
    checked = 0
    for h in rows:
        expected = min(100, h["convergence_types"] * 25
                       + min(25, h["convergence_events"] * 2))
        if h["convergence_score"] == 0 and expected == 0:
            continue
        assert expected == pytest.approx(h["convergence_score"], abs=0.51), h
        checked += 1
    if checked == 0:
        pytest.skip("no scored hotspots to reconstruct")


def test_hotspot_events_carry_source_country():
    """geopolitical_diversity reads sources.country_code; the panel shows the mix."""
    c = TestClient(create_app())
    hotspots = c.get("/hotspots", headers=_auth()).json()
    if not hotspots:
        pytest.skip("no hotspots seeded")
    hid = hotspots[0]["hotspot_id"]
    r = c.get(f"/hotspots/{hid}/events", headers=_auth())
    assert r.status_code == 200
    for e in r.json():
        assert "country_code" in e
        assert e["country_code"] is None or isinstance(e["country_code"], str)


def test_citation_indices_unchanged_by_the_new_column():
    """api/AGENTS.md:23 — additive SELECT only. Order must not move."""
    c = TestClient(create_app())
    hotspots = c.get("/hotspots", headers=_auth()).json()
    if not hotspots:
        pytest.skip("no hotspots seeded")
    events = c.get(f"/hotspots/{hotspots[0]['hotspot_id']}/events", headers=_auth()).json()
    cited = [e["citation_index"] for e in events if e["citation_index"] is not None]
    assert cited == list(range(1, len(cited) + 1))
