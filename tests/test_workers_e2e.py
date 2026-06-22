"""End-to-end: drive the worker chain over fakeredis and a live DB,
assert the hotspots match expected signatures. Requires SENTINEL_TEST_DB
(live PostGIS); skips otherwise."""
import os

import fakeredis
import psycopg2
import pytest

from pipeline.streams import StreamBus
from pipeline.workers.clustering_worker import ClusteringWorker
from pipeline.workers.consensus_worker import ConsensusWorker
from pipeline.workers.gridcell_worker import GridCellWorker
from tests.helpers_seed import monolith_hotspot_signature, seed_demo_events

pytestmark = pytest.mark.skipif(
    not os.getenv("SENTINEL_TEST_DB"), reason="needs live PostGIS via SENTINEL_TEST_DB"
)


def _drain(worker):
    """Process every currently-pending message for a worker, return count."""
    worker.setup()
    total = 0
    while True:
        n = worker.run_once()
        total += n
        if n == 0:
            break
    return total


def test_batch_flows_to_hotspots_matching_monolith():
    """Seed events, drive workers, compare hotspot signature to expected values."""
    dsn = os.getenv("SENTINEL_TEST_DB")
    conn = psycopg2.connect(dsn)
    try:
        # Clean any leftover data that might interfere with this test
        with conn.cursor() as cur:
            cur.execute("DELETE FROM event_hotspot")
            cur.execute("DELETE FROM hotspots")
            cur.execute("DELETE FROM grid_cells")
            cur.execute("DELETE FROM events")
        conn.commit()

        # Seed deterministic demo events
        event_ids = seed_demo_events(conn)
        assert len(event_ids) > 0, "expected seeded event ids"

        bus = StreamBus(client=fakeredis.FakeStrictRedis(), block_ms=10, batch=100)
        for w in (GridCellWorker, ClusteringWorker, ConsensusWorker):
            bus.ensure_group(w.in_stream, w.group)

        # Kick off the chain: publish the ingested batch.
        bus.publish("sentinel:ingested_events", {"batch_id": "t1", "event_ids": event_ids})

        # Drive workers in dependency order until quiescent.
        grid = GridCellWorker(bus=bus, consumer="c")
        clus = ClusteringWorker(bus=bus, consumer="c")
        cons = ConsensusWorker(bus=bus, consumer="c")
        assert _drain(grid) >= 1
        assert _drain(clus) >= 1
        _drain(cons)

        # Compare to documented expected signature for this fixed seed.
        # 5 events spanning 3 distinct event types (GDELT military_conflict +
        # ACLED armed_conflict + civilian_violence) in one cell should produce:
        #   - convergence fires (>= 2 distinct types, FR-WM-CONVERGENCE)
        #   - exactly 1 hotspot (from DBSCAN on events in same 50km/1h window)
        #   - conf_score ~9.3: one unknown source domain (trust 0.4), single
        #     country -> tanh(0.4/3)*0.7*100. Matches the FR-7/8/9 calibration
        #     target "thin / 1 unknown source -> grey".
        sig = monolith_hotspot_signature(conn)
        assert sig[0] == 1, f"expected 1 hotspot, got {sig[0]} with scores {sig[1]}"
        max_conf = sig[1][-1] if sig[1] else 0
        assert 8 <= max_conf <= 11, f"expected conf_score ~9.3, got {max_conf}"
    finally:
        # Clean up
        with conn.cursor() as cur:
            cur.execute("DELETE FROM event_hotspot")
            cur.execute("DELETE FROM hotspots")
            cur.execute("DELETE FROM grid_cells")
            cur.execute("DELETE FROM events")
        conn.commit()
        conn.close()


def _seed_single_type_gdelt(conn) -> list[int]:
    """4 GDELT-only military events (3-4 digit CAMEO codes), co-located in one
    1x1 cell with NOW() timestamps. All classify as the single 'military_conflict'
    type, so this cell only fires convergence once single-type zones are allowed."""
    rows = [
        ("9101", "190", 31.50, 34.45),
        ("9102", "180", 31.51, 34.46),
        ("9103", "173", 31.49, 34.44),
        ("9104", "1411", 31.52, 34.47),
    ]
    ids: list[int] = []
    with conn.cursor() as cur:
        for ext, cameo, lat, lon in rows:
            url = f"https://seed/{ext}"
            cur.execute("SELECT register_source(%s, %s)", (url, None))
            source_id = cur.fetchone()[0]
            cur.execute(
                """
                INSERT INTO events (source_system, gdelt_global_event_id,
                    external_event_id, event_date, cameo_code, country_code, url,
                    title, source_id, point_geom, grid_cell_id)
                VALUES ('GDELT', %s, %s, NOW(), %s, 'IL', %s, 'seed', %s,
                        ST_SetSRID(ST_MakePoint(%s,%s),4326), '1x1_LAT31_LON34')
                ON CONFLICT (source_system, external_event_id, event_date) DO NOTHING
                RETURNING event_id
                """,
                (int(ext), ext, cameo, url, source_id, lon, lat),
            )
            r = cur.fetchone()
            if r:
                ids.append(r[0])
    conn.commit()
    return ids


def test_single_type_gdelt_cell_produces_hotspot():
    """A GDELT-only cell (one event type) must still produce a hotspot: real
    feeds have no ACLED, so the worker chain has to fire on convergence_score>=1,
    not only on 2+ distinct types."""
    dsn = os.getenv("SENTINEL_TEST_DB")
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            for t in ("event_hotspot", "hotspots", "grid_cells", "events"):
                cur.execute(f"DELETE FROM {t}")
        conn.commit()

        event_ids = _seed_single_type_gdelt(conn)
        assert len(event_ids) >= 3, event_ids

        bus = StreamBus(client=fakeredis.FakeStrictRedis(), block_ms=10, batch=100)
        for w in (GridCellWorker, ClusteringWorker, ConsensusWorker):
            bus.ensure_group(w.in_stream, w.group)
        bus.publish("sentinel:ingested_events", {"batch_id": "s1", "event_ids": event_ids})

        assert _drain(GridCellWorker(bus=bus, consumer="c")) >= 1
        assert _drain(ClusteringWorker(bus=bus, consumer="c")) >= 1
        _drain(ConsensusWorker(bus=bus, consumer="c"))

        count, _ = monolith_hotspot_signature(conn)
        assert count == 1, f"expected 1 hotspot from single-type GDELT cell, got {count}"
    finally:
        with conn.cursor() as cur:
            for t in ("event_hotspot", "hotspots", "grid_cells", "events"):
                cur.execute(f"DELETE FROM {t}")
        conn.commit()
        conn.close()


def test_recluster_same_cell_is_idempotent():
    """Re-running clustering for a cell must REFRESH its hotspots, not accumulate
    duplicates. Each 15-min pipeline tick re-clusters the same events; without
    per-cell cleanup the hotspots table (and the map) grows unboundedly."""
    from pipeline.clustering import cluster_single_cell

    dsn = os.getenv("SENTINEL_TEST_DB")
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            for t in ("event_hotspot", "hotspots", "grid_cells", "events"):
                cur.execute(f"DELETE FROM {t}")
        conn.commit()
        _seed_single_type_gdelt(conn)

        cluster_single_cell(conn, "1x1_LAT31_LON34")
        ids2 = cluster_single_cell(conn, "1x1_LAT31_LON34")

        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM hotspots WHERE cell_id = %s", ("1x1_LAT31_LON34",)
            )
            total = cur.fetchone()[0]
        assert total == len(ids2), (
            f"recluster duplicated hotspots: {total} rows for cell, "
            f"second run produced {len(ids2)}"
        )
        assert total >= 1
    finally:
        with conn.cursor() as cur:
            for t in ("event_hotspot", "hotspots", "grid_cells", "events"):
                cur.execute(f"DELETE FROM {t}")
        conn.commit()
        conn.close()


def test_unacked_message_is_replayed_via_claim():
    bus = StreamBus(client=fakeredis.FakeStrictRedis(), block_ms=10, batch=100)
    bus.ensure_group("sentinel:convergence_zone_detected", "cg:clustering")
    bus.publish("sentinel:convergence_zone_detected",
                {"cell_id": "1x1_LAT31_LON34", "convergence_score": 88.0})
    # Simulate a crashed consumer: deliver but never ack.
    bus.read("sentinel:convergence_zone_detected", "cg:clustering", "dead")
    assert bus.pending_count("sentinel:convergence_zone_detected", "cg:clustering") == 1
    # A fresh consumer reclaims the stale message (min_idle 0 in test).
    claimed = bus.claim_stale("sentinel:convergence_zone_detected", "cg:clustering",
                              "c2", min_idle_ms=0)
    assert len(claimed) == 1
