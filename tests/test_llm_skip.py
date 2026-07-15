"""Already-summarised hotspots are skipped: candidate_hotspots excludes them
(monolith path) and LLMWorker acks without calling the LLM (worker path).
With stable hotspot identity (test_hotspot_identity), a summary exists exactly
when nothing changed — so skipping is always safe."""
from __future__ import annotations

import os

import fakeredis
import psycopg2
import pytest

from pipeline.clustering import cluster_single_cell
from pipeline.llm_verifier import LLMRepository
from pipeline.streams import StreamBus
from pipeline.workers.llm_worker import LLMWorker
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


def _seed_hotspot_with_summary(conn) -> int:
    seed_demo_events(conn)
    hid = cluster_single_cell(conn, CELL)[0]
    with conn.cursor() as cur:
        cur.execute("UPDATE hotspots SET conf_score = 90 WHERE hotspot_id = %s", (hid,))
        cur.execute(
            "INSERT INTO llm_summaries (hotspot_id, summary_text, conflict_detected)"
            " VALUES (%s, 'Seed summary [1].', false)",
            (hid,),
        )
    conn.commit()
    return hid


def test_candidate_hotspots_excludes_summarised(conn):
    hid = _seed_hotspot_with_summary(conn)
    repo = LLMRepository(conn)
    assert hid not in repo.candidate_hotspots(threshold=40)


def test_summary_exists(conn):
    hid = _seed_hotspot_with_summary(conn)
    repo = LLMRepository(conn)
    assert repo.summary_exists(hid) is True
    assert repo.summary_exists(hid + 999999) is False


def test_llm_worker_acks_summarised_hotspot_without_llm_call(conn, monkeypatch):
    hid = _seed_hotspot_with_summary(conn)

    def _boom(*args, **kwargs):
        raise AssertionError("call_nim_api must not be called for summarised hotspot")

    monkeypatch.setattr("pipeline.workers.llm_worker.call_nim_api", _boom)
    bus = StreamBus(client=fakeredis.FakeStrictRedis(), block_ms=10, batch=100)
    worker = LLMWorker(bus=bus, consumer="c")
    worker.setup()
    bus.publish("sentinel:llm_needed", {"hotspot_id": hid, "conf_score": 90.0})
    assert worker.run_once() == 1
    assert bus.pending_count("sentinel:llm_needed", "cg:llm") == 0
