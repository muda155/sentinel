import os

import pytest
from fastapi.testclient import TestClient

from api import queries
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
        if h["convergence_score"] is None:
            continue  # never scored — nothing to reconstruct
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


def test_convergence_inputs_follow_the_score_row():
    """A grid_cells row whose convergence_score is NULL must not leak its
    event_type_count/total_events into the inputs while the score comes from the
    hotspots row — that draws a bar that does not add up."""
    from pipeline.db import get_pooled_connection

    conn, pool = get_pooled_connection()
    hotspot_id = None
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO hotspots (centroid_geom, radius_km, name, cell_id, unique_event_types,
                                      unique_sources, event_count, convergence_score, conf_score,
                                      alert_level, llm_verified, start_window, end_window)
                VALUES (ST_SetSRID(ST_MakePoint(100,0),4326), 10, 'pytest_rowlock',
                        '1x1_LAT0_LON100', 3, 1, 9, 50, 100, 'High', false, NOW(), NOW())
                RETURNING hotspot_id
                """
            )
            hotspot_id = cur.fetchone()[0]
            # grid_cells row with inputs set but the score NULL — the old
            # per-column COALESCE resolved types/events here while the score fell
            # through to hotspots.convergence_score, publishing 9/3/50 mixed rows.
            cur.execute(
                """
                INSERT INTO grid_cells (cell_id, event_type_count, total_events,
                                        convergence_score, cell_geom, updated_at)
                VALUES ('1x1_LAT0_LON100', 1, 1, NULL,
                        ST_SetSRID(ST_MakePolygon(ST_GeomFromText('LINESTRING(100 0,101 0,101 1,100 1,100 0)',4326)),4326),
                        NOW())
                """
            )
        conn.commit()
    finally:
        pool.return_connection(conn)

    if hotspot_id is None:
        pytest.fail("could not seed fixture hotspot")

    def assert_row(h):
        # All three come from the SAME row (hotspots here, since the grid_cells
        # score is NULL) — 3 types / 9 events / 50, not 1 / 1 / 50.
        assert h["convergence_types"] == 3, h
        assert h["convergence_events"] == 9, h
        assert h["convergence_score"] == 50, h

    c = TestClient(create_app())
    try:
        # 1) fetch_hotspots
        r = c.get("/hotspots?limit=200", headers=_auth())
        assert r.status_code == 200
        h = next((x for x in r.json() if x["hotspot_id"] == hotspot_id), None)
        assert h is not None, "fixture hotspot not in /hotspots"
        assert_row(h)
        # 2) _HOTSPOT_SELECT via search
        s = c.get("/search?q=pytest_rowlock", headers=_auth()).json()
        h = next((x for x in s["hotspots"] if x["hotspot_id"] == hotspot_id), None)
        assert h is not None, "fixture hotspot not in /search hotspots"
        assert_row(h)
        # 3) fetch_hotspot_by_id
        conn, pool = get_pooled_connection()
        try:
            assert_row(queries.fetch_hotspot_by_id(conn, hotspot_id))
        finally:
            pool.return_connection(conn)
    finally:
        conn, pool = get_pooled_connection()
        try:
            with conn.cursor() as cur:
                if hotspot_id is not None:
                    cur.execute("DELETE FROM hotspots WHERE hotspot_id = %s", (hotspot_id,))
                cur.execute("DELETE FROM grid_cells WHERE cell_id = '1x1_LAT0_LON100'")
            conn.commit()
        finally:
            pool.return_connection(conn)
