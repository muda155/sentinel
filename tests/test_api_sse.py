import asyncio
import json
import time
from datetime import datetime, timezone

import fakeredis

import api.sse as sse_module
from api.sse import SSE_GROUP, STREAMS, hotspot_event_source
from pipeline.streams import StreamBus


class _BlockingBus:
    """Stand-in for StreamBus whose read() blocks synchronously the way
    redis-py xreadgroup(block=...) does when no messages are pending."""

    def __init__(self, block_s: float) -> None:
        self._block_s = block_s

    def ensure_group(self, stream, group):
        pass

    def read(self, stream, group, consumer):
        time.sleep(self._block_s)
        return []

    def ack(self, stream, group, msg_id):
        pass


def test_sse_emits_summary_ready_frame():
    bus = StreamBus(client=fakeredis.FakeStrictRedis(), block_ms=10, batch=10)
    for s in STREAMS:
        bus.ensure_group(s, SSE_GROUP)
    bus.publish("sentinel:summary_ready", {"hotspot_id": 4, "summary_id": 12})

    async def first_frame():
        gen = hotspot_event_source(bus, "c1")
        return await gen.__anext__()

    frame = asyncio.run(first_frame())
    assert frame["event"] == "summary_ready"
    assert json.loads(frame["data"]) == {"hotspot_id": 4, "summary_id": 12}


def test_sse_hotspot_created_frame_is_json_serializable(monkeypatch):
    """fetch_hotspot_by_id returns end_window/created_at as datetime objects.
    Raw json.dumps on that row raises TypeError mid-yield, which kills the
    generator and terminates the chunked response without its final chunk
    (browser: ERR_INCOMPLETE_CHUNKED_ENCODING). The message never reaches the
    ack, and reads use `>`, so it strands pending while the next event crashes
    the next connection (observed: 218 crashes in 40 min, 18k pending, no
    hotspot_created frame ever delivered). Frames must carry ISO-8601 strings,
    matching what the Hotspot response_model emits on GET /hotspots."""
    enriched = {
        "hotspot_id": 7, "lat": 31.5, "lon": 34.45, "conf_score": 48.2,
        "convergence_score": 35.0, "alert_level": "Medium", "event_count": 5,
        "consistency_score": None, "name": "Odesa, Ukraine",
        "end_window": datetime(2026, 8, 2, 13, 7, 35, tzinfo=timezone.utc),
        "created_at": datetime(2026, 8, 1, 9, 0, 0, tzinfo=timezone.utc),
    }
    monkeypatch.setattr(sse_module, "_enrich", lambda payload: enriched)

    bus = StreamBus(client=fakeredis.FakeStrictRedis(), block_ms=10, batch=10)
    for s in STREAMS:
        bus.ensure_group(s, SSE_GROUP)
    bus.publish("sentinel:hotspot_created", {"hotspot_id": 7})

    async def first_frame():
        gen = hotspot_event_source(bus, "c1")
        return await gen.__anext__()

    frame = asyncio.run(first_frame())
    assert frame["event"] == "hotspot_created"
    data = json.loads(frame["data"])
    assert data["hotspot_id"] == 7
    assert data["created_at"].startswith("2026-08-01T09:00:00")
    assert data["end_window"].startswith("2026-08-02T13:07:35")


def test_sse_read_does_not_block_event_loop():
    """A live SSE stream must not starve the shared asyncio event loop. The
    blocking Redis read has to run off-loop so concurrent REST requests stay
    responsive (regression: /hotspots hung for minutes while a stream was open)."""
    bus = _BlockingBus(block_s=0.5)

    async def scenario():
        gen = hotspot_event_source(bus, "c1")
        gen_task = asyncio.create_task(gen.__anext__())
        # Start timing before yielding to the loop: the generator's first
        # read() must land inside this window. ~0.1s of ideal loop time.
        t0 = time.perf_counter()
        for _ in range(10):
            await asyncio.sleep(0.01)
        elapsed = time.perf_counter() - t0
        gen_task.cancel()
        try:
            await gen_task
        except (asyncio.CancelledError, StopAsyncIteration):
            pass
        return elapsed

    elapsed = asyncio.run(scenario())
    assert elapsed < 0.3, f"event loop blocked for {elapsed:.3f}s during SSE read"
