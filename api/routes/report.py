from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from api import queries
from api.auth import get_current_user
from api.ratelimit import limit_report
from pipeline.db import get_pooled_connection
from pipeline.llm_verifier import call_llm_raw, validate_citations
from pipeline.window_report import build_window_report_prompt, report_timeout, window_citations

logger = logging.getLogger("sentinel.api.report")
router = APIRouter()

CACHE_TTL_S = 86400

_redis_client = None


def _redis():
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        import redis as redis_lib
    except ImportError:
        return None
    try:
        # One shared client (and pool), not a fresh pool per request. The short
        # connect timeout stops an unreachable REDIS_URL from pinning a
        # threadpool worker for the OS default (potentially minutes).
        client = redis_lib.from_url(
            os.getenv("REDIS_URL", "redis://localhost:6379"),
            socket_connect_timeout=1, socket_timeout=1,
        )
        client.ping()
    except Exception:
        return None
    _redis_client = client
    return _redis_client


def _cache_key(hotspot_id: int, start: str, end: str, rows: list[dict]) -> str:
    # Key on the exact event set, not just its max id: re-clustering can remove
    # events from a window without changing the largest id, which would serve a
    # narrative citing rows the window no longer holds.
    ids = ",".join(str(r["event_id"]) for r in sorted(rows, key=lambda r: r["event_id"]))
    raw = f"{hotspot_id}:{start}:{end}:{ids}"
    return "sentinel:report:" + hashlib.sha256(raw.encode()).hexdigest()


@router.get("/hotspots/{hotspot_id}/report")
def hotspot_report(hotspot_id: int,
                   start: datetime = Query(alias="from"),
                   end: datetime = Query(alias="to"),
                   _rate_limit: None = Depends(limit_report),
                   _user: dict = Depends(get_current_user)):
    # events.event_date is timestamptz (tz-aware); a naive from/to from a raw
    # client would crash the window comparison with TypeError, not a clean 4xx.
    # Treat a missing offset as UTC, matching what the dashboard always sends.
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    else:
        start = start.astimezone(timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    else:
        end = end.astimezone(timezone.utc)
    if end <= start:
        raise HTTPException(status_code=422, detail="'to' must be after 'from'")

    conn, pool = get_pooled_connection()
    try:
        events = queries.fetch_hotspot_events(conn, hotspot_id)
        name = queries.fetch_hotspot_name(conn, hotspot_id)
    finally:
        pool.return_connection(conn)

    if events is None:
        raise HTTPException(status_code=404, detail="hotspot not found")

    rows = [e for e in events if start <= e["event_date"] < end]
    if not rows:
        raise HTTPException(status_code=404, detail="no events in window")

    citations = window_citations(rows)
    key = _cache_key(hotspot_id, start.isoformat(), end.isoformat(), rows)
    cache = _redis()
    if cache is not None:
        try:
            hit = cache.get(key)
            if hit:
                return {**json.loads(hit), "cached": True}
        except Exception:
            logger.warning("report cache read failed", exc_info=True)

    endpoint = os.getenv("NVIDIA_NIM_ENDPOINT", "")
    ollama = os.getenv("OLLAMA_ENDPOINT", "")
    if not endpoint and not ollama:
        raise HTTPException(status_code=503, detail="report generation unavailable")

    prompt = build_window_report_prompt(name or f"Hotspot #{hotspot_id}", rows,
                                        start.isoformat(), end.isoformat())

    try:
        content, model_used = call_llm_raw(
            prompt,
            endpoint=endpoint,
            api_key=os.getenv("NVIDIA_NIM_API_KEY", ""),
            model=os.getenv("NVIDIA_NIM_MODEL", ""),
            # Fewer retries than the pipeline default (three NIM attempts): this
            # call blocks a request worker while an analyst waits. There is no
            # outer retry loop because temperature is 0 — a re-sent prompt would
            # reproduce the same output, doubling latency without changing the
            # verdict.
            retries=1,
            timeout=report_timeout(),
            ollama_endpoint=ollama or "http://localhost:11434",
        )
    except Exception:
        logger.warning("report LLM call failed", exc_info=True)
        raise HTTPException(status_code=503, detail="report generation unavailable")
    try:
        validate_citations(content)
    except ValueError:
        # FR-11/FR-12: an uncited narrative must never ship. Failing is
        # correct; the CSV and JSON exports are unaffected.
        raise HTTPException(status_code=422, detail="report failed citation validation")
    narrative = content

    payload = {"narrative": narrative, "citations": citations, "model": model_used}
    if cache is not None:
        try:
            cache.setex(key, CACHE_TTL_S, json.dumps(payload))
        except Exception:
            logger.warning("report cache write failed", exc_info=True)
    return {**payload, "cached": False}
