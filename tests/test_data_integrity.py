"""M1 data-integrity integration tests (require SENTINEL_TEST_DB)."""

from __future__ import annotations

import os

import psycopg2

_INSERT = """
    INSERT INTO events (source_system, external_event_id, event_date,
                        gdelt_global_event_id, point_geom, grid_cell_id)
    VALUES ('TEST', %s, '2026-06-15T00:00:00Z', %s,
            ST_SetSRID(ST_MakePoint(2.35, 48.85), 4326), '1x1_LAT48_LON2')
    ON CONFLICT (source_system, external_event_id, event_date) DO NOTHING
"""


def test_duplicate_event_deduplicated_across_connections(live_conn):
    """Two independent committed connections inserting the same key keep one row.

    This is the real consecutive-cycle scenario (NFR-7): the constraint must be
    enforced across transactions/connections, not just within one. Each connection
    commits, so cleanup is explicit (the live_conn rollback cannot undo committed rows).
    """
    dsn = os.environ["SENTINEL_TEST_DB"]  # live_conn fixture guarantees this is set
    conn_a = psycopg2.connect(dsn)
    conn_b = psycopg2.connect(dsn)
    try:
        with conn_a.cursor() as cur:
            cur.execute(_INSERT, ("dup-concurrent", 99998))
        conn_a.commit()
        with conn_b.cursor() as cur:
            cur.execute(_INSERT, ("dup-concurrent", 99998))  # conflicts -> DO NOTHING
        conn_b.commit()

        with live_conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM events "
                "WHERE source_system='TEST' AND external_event_id='dup-concurrent'"
            )
            assert cur.fetchone()[0] == 1
    finally:
        with live_conn.cursor() as cur:
            cur.execute(
                "DELETE FROM events "
                "WHERE source_system='TEST' AND external_event_id='dup-concurrent'"
            )
        live_conn.commit()
        conn_a.close()
        conn_b.close()


def test_duplicate_event_is_deduplicated(live_conn):
    """Inserting the same (source_system, external_event_id, event_date) twice keeps one row."""
    cur = live_conn.cursor()
    insert = """
        INSERT INTO events (source_system, external_event_id, event_date,
                            gdelt_global_event_id, point_geom, grid_cell_id)
        VALUES ('TEST', 'dup-1', '2026-06-15T00:00:00Z', 99999,
                ST_SetSRID(ST_MakePoint(2.35, 48.85), 4326), '1x1_LAT48_LON2')
        ON CONFLICT (source_system, external_event_id, event_date) DO NOTHING
    """
    cur.execute(insert)
    cur.execute(insert)
    cur.execute(
        "SELECT count(*) FROM events WHERE source_system='TEST' AND external_event_id='dup-1'"
    )
    assert cur.fetchone()[0] == 1
    live_conn.rollback()  # fixture also rolls back; keep the DB clean


def test_alert_level_filter_uses_index(live_conn):
    """The b-tree index on alert_level must be usable for severity filtering.

    On a near-empty table the planner rightly prefers a seq scan, so we disable
    seqscan for this EXPLAIN to assert the index *can* serve the query (the
    fixture rolls back, so the setting does not leak).
    """
    cur = live_conn.cursor()
    cur.execute("SET LOCAL enable_seqscan = off")
    cur.execute(
        "EXPLAIN SELECT count(*) FROM hotspots WHERE alert_level IN ('High', 'Critical')"
    )
    plan = " ".join(row[0] for row in cur.fetchall())
    assert "Index" in plan or "Bitmap" in plan, plan