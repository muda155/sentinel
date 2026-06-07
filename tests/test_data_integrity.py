"""M1 data-integrity integration tests (require SENTINEL_TEST_DB)."""

from __future__ import annotations


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
    """Filtering hotspots by alert_level should use the b-tree index."""
    cur = live_conn.cursor()
    cur.execute(
        "EXPLAIN SELECT count(*) FROM hotspots WHERE alert_level IN ('High', 'Critical')"
    )
    plan = " ".join(row[0] for row in cur.fetchall())
    assert "Index" in plan or "Bitmap" in plan, plan