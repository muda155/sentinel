"""Hotspot identity is stable across re-clustering: a cluster whose non-noise
event membership is unchanged keeps its hotspot_id, so llm_summaries rows
survive the tick instead of being cascade-deleted and regenerated."""
from __future__ import annotations

import os

import psycopg2
import pytest

from pipeline.clustering import cluster_single_cell
from tests.helpers_seed import seed_demo_events

pytestmark = pytest.mark.destructive

CELL = "1x1_LAT31_LON34"
TABLES = ("llm_summaries", "event_hotspot", "hotspots", "grid_cells", "events")


def _wipe(conn):
    with conn.cursor() as cur:
        for t in TABLES:
            cur.execute(f"DELETE FROM {t}")
    conn.commit()


@pytest.fixture
def conn():
    dsn = os.getenv("SENTINEL_TEST_DB")
    if not dsn:
        pytest.skip("SENTINEL_TEST_DB not set; skipping live-DB integration test")
    conn = psycopg2.connect(dsn)
    _wipe(conn)
    yield conn
    _wipe(conn)
    conn.close()


def test_recluster_unchanged_cell_keeps_hotspot_ids(conn):
    seed_demo_events(conn)
    ids1 = cluster_single_cell(conn, CELL)
    assert ids1, "seed must produce at least one hotspot"
    ids2 = cluster_single_cell(conn, CELL)
    assert sorted(ids1) == sorted(ids2)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM hotspots WHERE cell_id = %s", (CELL,))
        assert cur.fetchone()[0] == len(ids2)


def test_recluster_unchanged_cell_preserves_summary(conn):
    seed_demo_events(conn)
    ids1 = cluster_single_cell(conn, CELL)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO llm_summaries (hotspot_id, summary_text, conflict_detected)"
            " VALUES (%s, 'Seed summary [1].', false)",
            (ids1[0],),
        )
    conn.commit()
    cluster_single_cell(conn, CELL)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM llm_summaries WHERE hotspot_id = %s", (ids1[0],)
        )
        assert cur.fetchone()[0] == 1


def test_recluster_changed_membership_replaces_hotspot(conn):
    seed_demo_events(conn)
    ids1 = cluster_single_cell(conn, CELL)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO events (source_system, gdelt_global_event_id, external_event_id,
                event_date, cameo_code, country_code, url, title, point_geom, grid_cell_id)
            VALUES ('GDELT', 9099, '9099', NOW(), '19', 'IL', 'https://seed/9099', 'seed',
                    ST_SetSRID(ST_MakePoint(34.46, 31.50), 4326), %s)
            """,
            (CELL,),
        )
    conn.commit()
    ids2 = cluster_single_cell(conn, CELL)
    assert set(ids1) != set(ids2)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM hotspots WHERE cell_id = %s", (CELL,))
        assert cur.fetchone()[0] == len(ids2)
