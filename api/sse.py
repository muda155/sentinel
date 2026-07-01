"""SSE generator: tails hotspot_created + summary_ready streams and yields
spec-shaped SSE data frames.  Enriches each hotspot_created with current scores."""
from __future__ import annotations

import asyncio
import json

from api import queries
from pipeline.db import get_pooled_connection
from pipeline.streams import StreamBus

SSE_GROUP = "cg:api-sse"
STREAMS = ["sentinel:hotspot_created", "sentinel:summary_ready"]


def _enrich(payload: dict) -> dict:
    hotspot_id = payload.get("hotspot_id")
    if hotspot_id is None:
        return payload
    conn, pool = get_pooled_connection()
    try:
        row = queries.fetch_hotspot_by_id(conn, int(hotspot_id))
        if row:
            return row
    finally:
        pool.return_connection(conn)
    return payload


async def hotspot_event_source(bus: StreamBus, consumer: str):
    # StreamBus.read/ack and _enrich are synchronous blocking I/O (Redis
    # xreadgroup(block=...), pooled DB). Run them off the event loop via
    # asyncio.to_thread so a live SSE stream never starves concurrent REST
    # requests sharing this event loop.
    for s in STREAMS:
        bus.ensure_group(s, SSE_GROUP)
    while True:
        got = False
        for s in STREAMS:
            messages = await asyncio.to_thread(bus.read, s, SSE_GROUP, consumer)
            for mid, data in messages:
                got = True
                frame = (
                    await asyncio.to_thread(_enrich, data)
                    if s.endswith("hotspot_created")
                    else data
                )
                yield {"event": s.split(":")[-1], "data": json.dumps(frame)}
                await asyncio.to_thread(bus.ack, s, SSE_GROUP, mid)
        if not got:
            await asyncio.sleep(0.5)
