"""Country-centroid GDELT events (geo_precision=1) must not enter DBSCAN:
they pile hundreds of unrelated 'mentions Vietnam'-style articles onto the
country centroid and mint fake hotspots with unrelated sources. NULL
precision (legacy rows, ACLED) stays clusterable — fail-open."""
from __future__ import annotations

import os

import psycopg2
import pytest

from pipeline.clustering import cluster_single_cell

pytestmark = pytest.mark.destructive

CELL = "1x1_LAT16_LON107"   # Vietnam-centroid cell
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


def _seed(conn, ext_id: str, lat: float, lon: float, geo_precision):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO events (source_system, gdelt_global_event_id, external_event_id,
                event_date, cameo_code, country_code, url, title, point_geom,
                grid_cell_id, geo_precision)
            VALUES ('GDELT', %s, %s, NOW(), '19', 'VM', %s, 'seed',
                    ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s, %s)
            """,
            (int(ext_id), ext_id, f"https://seed/{ext_id}", lon, lat, CELL, geo_precision),
        )
    conn.commit()


def test_centroid_only_cell_produces_no_hotspot(conn):
    for i in range(3):
        _seed(conn, str(9200 + i), 16.166667, 107.833333, geo_precision=1)
    assert cluster_single_cell(conn, CELL) == []


def test_precise_events_still_cluster_next_to_centroid_pile(conn):
    for i in range(3):
        _seed(conn, str(9200 + i), 16.166667, 107.833333, geo_precision=1)
    precise = []
    for i in range(3):
        ext = str(9300 + i)
        _seed(conn, ext, 16.05 + i * 0.01, 107.05, geo_precision=4)
        precise.append(ext)
    ids = cluster_single_cell(conn, CELL)
    assert len(ids) == 1
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT e.external_event_id FROM event_hotspot eh
            JOIN events e ON e.event_id = eh.event_id
            WHERE eh.hotspot_id = %s AND NOT COALESCE(eh.is_noise, false)
            ORDER BY 1
            """,
            (ids[0],),
        )
        members = [r[0] for r in cur.fetchall()]
    assert members == sorted(precise)


def test_null_precision_fails_open(conn):
    for i in range(3):
        _seed(conn, str(9400 + i), 16.50 + i * 0.01, 107.50, geo_precision=None)
    assert len(cluster_single_cell(conn, CELL)) == 1
