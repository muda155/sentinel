"""SSE generator: tails hotspot_created + summary_ready streams and yields
spec-shaped SSE data frames.  Enriches each hotspot_created with current scores."""
from __future__ import annotations

import asyncio
import json
from datetime import date, datetime

from api import queries
from pipeline.db import get_pooled_connection
from pipeline.streams import StreamBus

SSE_GROUP = "cg:api-sse"
STREAMS = ["sentinel:hotspot_created", "sentinel:summary_ready"]


def _json_default(o):
    # hotspots.end_window/created_at are `timestamp with time zone` -> datetime,
    # which json.dumps cannot encode. An exception here escapes mid-yield, so the
    # chunked response ends without its final chunk (browser:
    # ERR_INCOMPLETE_CHUNKED_ENCODING) and the message never reaches the ack
    # below. Reads use `>` (new entries only), so the unacked message is never
    # retried -- it strands in the group's pending list while the next emitted
    # event crashes the next connection the same way. Every hotspot_created
    # frame was lost this way; 18k messages had piled up pending.
    # ISO-8601 matches what the Hotspot response_model emits on GET /hotspots.
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    raise TypeError(f"Object of type {o.__class__.__name__} is not JSON serializable")


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
                yield {"event": s.split(":")[-1], "data": json.dumps(frame, default=_json_default)}
                await asyncio.to_thread(bus.ack, s, SSE_GROUP, mid)
        if not got:
            await asyncio.sleep(0.5)
