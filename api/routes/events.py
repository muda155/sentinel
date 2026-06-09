from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query

from api import queries
from api.ratelimit import limit_events
from pipeline.db import get_pooled_connection

router = APIRouter()


@router.get("/events")
def get_events(sw_lat: float, sw_lon: float, ne_lat: float, ne_lon: float,
               start: datetime, end: datetime,
               cursor: int = 0, page_size: int = Query(100, le=1000),
               _rate_limit: None = Depends(limit_events)):
    conn, pool = get_pooled_connection()
    try:
        rows = queries.fetch_events_bbox(conn, sw_lat=sw_lat, sw_lon=sw_lon,
                                         ne_lat=ne_lat, ne_lon=ne_lon, start=start,
                                         end=end, cursor=cursor, page_size=page_size)
    finally:
        pool.return_connection(conn)
    features = [{
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
        "properties": {k: (v.isoformat() if isinstance(v, datetime) else v)
                       for k, v in r.items() if k not in ("lat", "lon")},
    } for r in rows]
    next_cursor = rows[-1]["event_id"] if rows else None
    return {"type": "FeatureCollection", "features": features, "next_cursor": next_cursor}
