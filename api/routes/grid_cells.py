from __future__ import annotations

from fastapi import APIRouter, Depends

from api import queries
from api.ratelimit import limit_hotspots
from pipeline.db import get_pooled_connection

router = APIRouter()


@router.get("/grid_cells")
def list_grid_cells(min_convergence: float = 1.0,
                    _rate_limit: None = Depends(limit_hotspots)):
    conn, pool = get_pooled_connection()
    try:
        return queries.fetch_grid_cells(conn, min_convergence=min_convergence)
    finally:
        pool.return_connection(conn)
