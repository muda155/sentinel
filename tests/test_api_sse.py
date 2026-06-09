import asyncio
import json

import fakeredis

from api.sse import SSE_GROUP, STREAMS, hotspot_event_source
from pipeline.streams import StreamBus


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
