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
    for s in STREAMS:
        bus.ensure_group(s, SSE_GROUP)
    while True:
        got = False
        for s in STREAMS:
            for mid, data in bus.read(s, SSE_GROUP, consumer):
                got = True
                frame = _enrich(data) if s.endswith("hotspot_created") else data
                yield {"event": s.split(":")[-1], "data": json.dumps(frame)}
                bus.ack(s, SSE_GROUP, mid)
        if not got:
            await asyncio.sleep(0.5)
