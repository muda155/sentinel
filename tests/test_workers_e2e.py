"""End-to-end: drive the worker chain over fakeredis and a live DB,
assert the hotspots match expected signatures. Requires SENTINEL_TEST_DB
(live PostGIS); skips otherwise."""
import os
import psycopg2
import fakeredis
import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("SENTINEL_TEST_DB"), reason="needs live PostGIS via SENTINEL_TEST_DB"
)

from pipeline.streams import StreamBus
from pipeline.workers.gridcell_worker import GridCellWorker
from pipeline.workers.clustering_worker import ClusteringWorker
from pipeline.workers.consensus_worker import ConsensusWorker
from tests.helpers_seed import seed_demo_events, monolith_hotspot_signature


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
        grid = GridCellWorker(bus=bus, consumer="c"); grid.bus = bus
        clus = ClusteringWorker(bus=bus, consumer="c")
        cons = ConsensusWorker(bus=bus, consumer="c")
        assert _drain(grid) >= 1
        assert _drain(clus) >= 1
        _drain(cons)

        # Compare to documented expected signature for this fixed seed.
        # 5 events (4 distinct CAMEO root codes) in one cell should produce:
        #   - convergence_score >= 50 (4 types -> type_score=100, 5 events -> count_boost=10)
        #   - exactly 1 hotspot (from DBSCAN on events in same 50km/1h window)
        #   - conf_score ~ 11.8 (same country IL, unknown source trust_tier=4)
        sig = monolith_hotspot_signature(conn)
        assert sig[0] == 1, f"expected 1 hotspot, got {sig[0]} with scores {sig[1]}"
        max_conf = sig[1][-1] if sig[1] else 0
        assert 10 <= max_conf <= 15, f"expected conf_score ~11.8, got {max_conf}"
    finally:
        # Clean up
        with conn.cursor() as cur:
            cur.execute("DELETE FROM event_hotspot")
            cur.execute("DELETE FROM hotspots")
            cur.execute("DELETE FROM grid_cells")
            cur.execute("DELETE FROM events")
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
