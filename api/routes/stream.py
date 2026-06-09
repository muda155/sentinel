from __future__ import annotations

import socket

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from api.sse import hotspot_event_source
from pipeline.streams import StreamBus

router = APIRouter()


@router.get("/hotspots/stream")
async def hotspots_stream(request: Request):
    bus = StreamBus()
    consumer = f"sse-{socket.gethostname()}-{id(request)}"
    return EventSourceResponse(hotspot_event_source(bus, consumer))
