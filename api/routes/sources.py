from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api import queries
from api.auth import get_current_user, require_role
from api.schemas import Source
from pipeline.db import get_pooled_connection

router = APIRouter()


@router.get("/sources", response_model=list[Source])
def list_sources(_user: dict = Depends(get_current_user)):
    conn, pool = get_pooled_connection()
    try:
        return queries.fetch_sources(conn)
    finally:
        pool.return_connection(conn)


class TrustTierUpdate(BaseModel):
    trust_tier: int = Field(ge=1, le=4)


@router.patch("/sources/{source_id}")
def update_trust_tier(source_id: int, body: TrustTierUpdate, _admin: dict = Depends(require_role("admin"))):
    conn, pool = get_pooled_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE sources SET trust_tier=%s WHERE source_id=%s RETURNING source_id, trust_tier",
                (body.trust_tier, source_id),
            )
            row = cur.fetchone()
        conn.commit()
    finally:
        pool.return_connection(conn)
    if not row:
        raise HTTPException(status_code=404, detail="source not found")
    return {"source_id": row[0], "trust_tier": row[1]}
