from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from api import queries
from api.schemas import Hotspot, HotspotSummary
from pipeline.db import get_pooled_connection

router = APIRouter()


@router.get("/hotspots", response_model=list[Hotspot])
def list_hotspots(limit: int = Query(50, le=200), min_conf: float = 0.0,
                  min_convergence: float = 0.0, alert_level: str | None = None):
    conn, pool = get_pooled_connection()
    try:
        rows = queries.fetch_hotspots(conn, limit=limit, min_conf=min_conf,
                                      min_convergence=min_convergence, alert_level=alert_level)
    finally:
        pool.return_connection(conn)
    return rows


@router.get("/hotspots/{hotspot_id}/summary", response_model=HotspotSummary)
def hotspot_summary(hotspot_id: int):
    conn, pool = get_pooled_connection()
    try:
        row = queries.fetch_hotspot_summary(conn, hotspot_id)
    finally:
        pool.return_connection(conn)
    if row is None:
        raise HTTPException(status_code=404, detail="hotspot not found")
    sc = row["sources_cited"]
    row["sources_cited"] = sc if isinstance(sc, list) else list(sc)
    return row
