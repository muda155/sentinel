from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from api import queries
from api.auth import get_current_user
from api.ratelimit import limit_hotspots
from pipeline.db import get_pooled_connection

router = APIRouter()


@router.get("/grid_cells")
def list_grid_cells(min_convergence: float = 1.0,
                    max_age_hours: int = Query(720, ge=1),
                    _rate_limit: None = Depends(limit_hotspots),
                    _user: dict = Depends(get_current_user)):
    conn, pool = get_pooled_connection()
    try:
        return queries.fetch_grid_cells(conn, min_convergence=min_convergence,
                                        max_age_hours=max_age_hours)
    finally:
        pool.return_connection(conn)
