from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from api import queries
from api.auth import get_current_user
from api.ratelimit import limit_events
from api.schemas import SearchResults
from pipeline.db import get_pooled_connection

router = APIRouter()


@router.get("/search", response_model=SearchResults)
def search(q: str = Query("", max_length=200),
           _rate_limit: None = Depends(limit_events),
           _user: dict = Depends(get_current_user)):
    conn, pool = get_pooled_connection()
    try:
        return queries.fetch_search(conn, q)
    finally:
        pool.return_connection(conn)
